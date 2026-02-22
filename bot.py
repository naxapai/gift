from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import fcntl
from datetime import datetime
from datetime import timezone
from typing import Dict

BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8080").strip()
POLL_INTERVAL_SEC = int(os.getenv("BOT_POLL_INTERVAL", "300"))
MIN_CONFIDENCE = int(os.getenv("BOT_MIN_CONFIDENCE", "60"))
DYNAMICS_PCT = float(os.getenv("BOT_DYNAMICS_PCT", "5"))
CACHE_FILE = os.getenv("BOT_CACHE_FILE", "data/bot_cache.json")
LOCK_FILE = os.getenv("BOT_LOCK_FILE", "data/bot_sender.lock")
MIN_REPEAT_SEC = int(os.getenv("BOT_MIN_REPEAT_SEC", "21600"))
MAX_MESSAGES_PER_CYCLE = int(os.getenv("BOT_MAX_MESSAGES_PER_CYCLE", "8"))


def _http_get(url: str) -> Dict:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_post(url: str, data: Dict[str, str]) -> Dict:
    payload = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def send_message(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Set TG_BOT_TOKEN and TG_CHAT_ID env vars")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    _http_post(url, {"chat_id": CHAT_ID, "text": text})


def _load_cache() -> Dict:
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: Dict) -> None:
    os.makedirs(os.path.dirname(CACHE_FILE) or ".", exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _format_signal(item: Dict) -> str:
    title = item.get("title") or item.get("variant_id")
    reco = item.get("action") or "HOLD"
    score = item.get("reco_score") or 0
    conf = item.get("confidence") or 0
    summary = item.get("summary") or ""
    forecast = item.get("forecast") or {}
    rng = forecast.get("range_pct") if isinstance(forecast, dict) else []
    fc_range = f"{float(rng[0]):.1f}%…{float(rng[1]):.1f}%" if isinstance(rng, list) and len(rng) >= 2 else "-"
    fc_bias = {"up": "рост", "down": "снижение", "flat": "боковик"}.get(str(forecast.get("bias") or "flat"), "боковик")
    reasons = item.get("reasons") or []
    risks = item.get("risks") or []
    lines = [f"Сигнал: {reco} | score {score} | conf {conf}%", title]
    if summary:
        lines.extend(["", summary])
    lines.extend(["", f"Прогноз 24ч: {fc_bias}, диапазон {fc_range}"])
    if reasons:
        lines.append("Причины:")
        for r in reasons[:3]:
            lines.append(f"- {r.get('text')}")
    if risks:
        lines.append("Риск:")
        for r in risks[:2]:
            lines.append(f"- {r.get('text')}")
    return "\n".join(lines)


def _is_dynamic(prev: Dict, curr: Dict) -> bool:
    if not prev:
        return True
    if prev.get("action") != curr.get("action"):
        return True
    if abs(float(curr.get("reco_score", 0) or 0) - float(prev.get("reco_score", 0) or 0)) >= 3.0:
        return True
    if abs(float(curr.get("confidence", 0) or 0) - float(prev.get("confidence", 0) or 0)) >= 5.0:
        return True
    try:
        prev_pct = float(prev.get("floor_change_pct_24h", 0))
        curr_pct = float(curr.get("floor_change_pct_24h", 0))
    except Exception:
        return True
    if abs(curr_pct - prev_pct) >= DYNAMICS_PCT:
        return True
    prev_fc = prev.get("forecast") or {}
    curr_fc = curr.get("forecast") or {}
    if prev_fc.get("bias") != curr_fc.get("bias"):
        return True
    return False


def _signal_fingerprint(item: Dict) -> str:
    fc = item.get("forecast") or {}
    rng = fc.get("range_pct") if isinstance(fc, dict) else []
    lo = float(rng[0]) if isinstance(rng, list) and len(rng) >= 1 else 0.0
    hi = float(rng[1]) if isinstance(rng, list) and len(rng) >= 2 else 0.0
    parts = [
        str(item.get("variant_id") or ""),
        str(item.get("action") or ""),
        str(int(round(float(item.get("reco_score", 0) or 0)))),
        str(int(round(float(item.get("confidence", 0) or 0)))),
        str(fc.get("bias") or "flat"),
        f"{lo:.1f}",
        f"{hi:.1f}",
    ]
    return "|".join(parts)


def cycle(cache: Dict) -> None:
    resp = _http_get(f"{API_BASE_URL}/api/recommendations?scope=all&entity=variant&ai=1")
    items = sorted(resp.get("items") or [], key=lambda x: float(x.get("confidence", 0) or 0), reverse=True)
    now_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_ts = int(time.time())
    sent_count = 0
    for item in items:
        if sent_count >= MAX_MESSAGES_PER_CYCLE:
            break
        if item.get("confidence", 0) < MIN_CONFIDENCE:
            continue
        if str(item.get("action") or "").upper() not in {"BUY", "SELL", "WATCH", "AVOID"}:
            continue
        key = f"{item.get('variant_id')}"
        prev = cache.get(key, {})
        fp = _signal_fingerprint(item)
        last_fp = str(prev.get("last_fp") or "")
        last_sent_ts = int(prev.get("last_sent_ts", 0) or 0)
        # Антидубль: если сигнал по сути не изменился, повтор не отправляем.
        if fp == last_fp and (now_ts - last_sent_ts) < MIN_REPEAT_SEC:
            continue
        if not _is_dynamic(prev, item):
            continue
        send_message(_format_signal(item))
        sent_count += 1
        cache[key] = {**item, "last_sent": now_tag, "last_sent_ts": now_ts, "last_fp": fp}


def main() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise SystemExit("Set TG_BOT_TOKEN and TG_CHAT_ID before running bot.py")

    os.makedirs(os.path.dirname(LOCK_FILE) or ".", exist_ok=True)
    lock_fh = open(LOCK_FILE, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another bot sender process is already running")

    cache = _load_cache()
    while True:
        try:
            cycle(cache)
            _save_cache(cache)
        except urllib.error.URLError as e:
            print(f"Network error: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"Unexpected error: {e}")
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()

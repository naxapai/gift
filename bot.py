from __future__ import annotations

import json
import os
import time
import html
import urllib.error
import urllib.parse
import urllib.request
import fcntl
from datetime import datetime
from datetime import timezone
from datetime import timedelta
from typing import Dict

BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8080").strip()
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "").strip()
HTTP_TIMEOUT_SEC = int(os.getenv("BOT_HTTP_TIMEOUT_SEC", "90"))
HTTP_RETRIES = int(os.getenv("BOT_HTTP_RETRIES", "3"))
HTTP_BACKOFF_SEC = float(os.getenv("BOT_HTTP_BACKOFF_SEC", "1.5"))
API_WARMUP_MAX_SEC = int(os.getenv("BOT_API_WARMUP_MAX_SEC", "120"))
POLL_INTERVAL_SEC = int(os.getenv("BOT_POLL_INTERVAL", "60"))
MIN_CONFIDENCE = int(os.getenv("BOT_MIN_CONFIDENCE", "60"))
DYNAMICS_PCT = float(os.getenv("BOT_DYNAMICS_PCT", "5"))
CACHE_FILE = os.getenv("BOT_CACHE_FILE", "data/bot_cache.json")
LOCK_FILE = os.getenv("BOT_LOCK_FILE", "data/bot_sender.lock")
MIN_REPEAT_SEC = int(os.getenv("BOT_MIN_REPEAT_SEC", "21600"))
MAX_MESSAGES_PER_CYCLE = int(os.getenv("BOT_MAX_MESSAGES_PER_CYCLE", "8"))
DEBUG = os.getenv("BOT_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}
FORCE_SEND_TOP1 = os.getenv("BOT_FORCE_SEND_TOP1", "false").strip().lower() in {"1", "true", "yes", "on"}
COMMANDS_ENABLED = os.getenv("BOT_COMMANDS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
UPDATES_TIMEOUT_SEC = int(os.getenv("BOT_UPDATES_TIMEOUT_SEC", "1"))
MSK_TZ = timezone(timedelta(hours=3))


def _to_msk_text(ts_iso: str | None) -> str:
    if not ts_iso:
        return "-"
    raw = str(ts_iso).strip()
    if not raw:
        return "-"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(MSK_TZ).strftime("%Y-%m-%d %H:%M:%S МСК")
    except Exception:
        return raw


def _now_msk_text() -> str:
    return datetime.now(MSK_TZ).strftime("%Y-%m-%d %H:%M:%S МСК")


def _http_get(url: str) -> Dict:
    last_error = None
    for attempt in range(1, max(1, HTTP_RETRIES) + 1):
        try:
            req = urllib.request.Request(url, method="GET")
            req.add_header("Accept", "application/json")
            if API_AUTH_TOKEN:
                req.add_header("Authorization", f"Bearer {API_AUTH_TOKEN}")
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last_error = e
            if isinstance(e, urllib.error.HTTPError) and e.code in {400, 401, 403, 404}:
                break
            if attempt >= max(1, HTTP_RETRIES):
                break
            time.sleep(HTTP_BACKOFF_SEC * attempt)
    raise last_error


def _http_post(url: str, data: Dict[str, str]) -> Dict:
    last_error = None
    for attempt in range(1, max(1, HTTP_RETRIES) + 1):
        try:
            payload = urllib.parse.urlencode(data).encode("utf-8")
            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last_error = e
            if attempt >= max(1, HTTP_RETRIES):
                break
            time.sleep(HTTP_BACKOFF_SEC * attempt)
    raise last_error


def send_message(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Set TG_BOT_TOKEN and TG_CHAT_ID env vars")
    send_message_to(CHAT_ID, text)


def send_message_to(chat_id: str | int, text: str, parse_mode: str | None = None) -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Set TG_BOT_TOKEN env var")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": str(chat_id), "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    _http_post(url, payload)


def _get_updates(offset: int | None = None, timeout_sec: int = 0) -> Dict:
    if not BOT_TOKEN:
        return {"ok": False, "result": []}
    params = {"timeout": str(max(0, timeout_sec))}
    if offset is not None:
        params["offset"] = str(offset)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?{urllib.parse.urlencode(params)}"
    try:
        return _http_get(url)
    except urllib.error.HTTPError as e:
        # Telegram returns 409 when getUpdates is used while a webhook is active.
        if e.code == 409:
            _http_get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=false")
            return _http_get(url)
        raise


def _format_market_status(overview: Dict) -> str:
    return "\n".join(
        [
            "<b>GiftMarketZone: Статус рынка :</b>",
            f"Состояние: <b>{overview.get('market_state', '-')}</b>",
            f"Подарков: {overview.get('gifts_count', 0)}",
            f"Коллекций: {overview.get('base_count', 0)}",
            f"Моделей: {overview.get('model_count', 0)}",
            f"Мин цена: {overview.get('floor_ton_min', '-')} TON",
            f"Медиана: {overview.get('floor_ton_median', '-')} TON",
            f"Всего в продаже: {overview.get('total_for_sale', overview.get('active_listings', 0))}",
            f"Всего продано: {overview.get('total_sold', 0)}",
            f"Сигналы BUY/SELL: {overview.get('buy_signals', 0)}/{overview.get('sell_signals', 0)}",
            f"Обновлено: {_to_msk_text(overview.get('updated_at'))}",
            f"Время ответа: {_now_msk_text()}",
        ]
    )


def _handle_commands(cache: Dict) -> None:
    if not COMMANDS_ENABLED or not BOT_TOKEN:
        return
    offset = int(cache.get("tg_update_offset", 0) or 0)
    updates = _get_updates(offset=offset, timeout_sec=UPDATES_TIMEOUT_SEC)
    for upd in updates.get("result") or []:
        try:
            update_id = int(upd.get("update_id", 0))
            if update_id >= offset:
                offset = update_id + 1
            msg = upd.get("message") or upd.get("edited_message") or {}
            text = str(msg.get("text") or "").strip()
            chat = msg.get("chat") or {}
            chat_id = chat.get("id")
            if not chat_id or not text.startswith("/"):
                continue
            cmd = text.split()[0].split("@")[0].lower()
            if cmd in {"/status", "/signal"}:
                try:
                    ov = _http_get(f"{API_BASE_URL}/api/market/overview")
                    send_message_to(chat_id, _format_market_status(ov), parse_mode="HTML")
                except Exception as e:  # noqa: BLE001
                    send_message_to(chat_id, f"Ошибка получения статуса: {e}")
        except Exception:
            continue
    cache["tg_update_offset"] = offset


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
    def _pick_trait_name(value) -> str:
        if isinstance(value, dict):
            for key in ("name", "title", "label", "value", "id"):
                text = str(value.get(key) or "").strip()
                if text:
                    return text
            return ""
        return str(value or "").strip()

    action = str(item.get("action") or "HOLD").upper()
    score = float(item.get("reco_score") or 0)
    conf = int(round(float(item.get("confidence") or 0)))
    forecast = item.get("forecast") or {}
    rng = forecast.get("range_pct") if isinstance(forecast, dict) else []
    fc_range = f"{float(rng[0]):.1f}%…{float(rng[1]):.1f}%" if isinstance(rng, list) and len(rng) >= 2 else "-"
    fc_bias = {"up": "рост", "down": "снижение", "flat": "боковик"}.get(str(forecast.get("bias") or "flat"), "боковик")
    action_ru = {"BUY": "Покупка", "SELL": "Продажа", "HOLD": "Держать", "WATCH": "Наблюдение", "AVOID": "Избегать"}.get(action, action)
    title = str(item.get("title") or "").strip()
    title_parts = [x.strip() for x in title.split("•")] if "•" in title else []
    traits = item.get("traits") or {}
    model = (
        _pick_trait_name(traits.get("model"))
        or str(item.get("model_name") or "").strip()
        or (title_parts[0] if len(title_parts) >= 1 else "")
        or "-"
    )
    background = (
        _pick_trait_name(traits.get("background"))
        or str(item.get("background_name") or "").strip()
        or (title_parts[1] if len(title_parts) >= 2 else "")
        or "-"
    )
    pattern = (
        _pick_trait_name(traits.get("pattern"))
        or str(item.get("pattern_name") or "").strip()
        or (title_parts[2] if len(title_parts) >= 3 else "")
        or "-"
    )
    collection = item.get("base_name") or item.get("group") or item.get("base_id") or "-"
    reasons = item.get("reasons") or []
    risks = item.get("risks") or []
    summary = f"ожидается {fc_bias} (24ч: {fc_range}, оценка {score:.1f}, уверенность {conf}%)"

    lines = [
        "<b>GiftMarketZone: Сигналы :</b>",
        f"<b>{html.escape(action)}</b> | score {score:.1f} | conf {conf}%",
        f"Коллекция: <b>{html.escape(str(collection))}</b>",
        f"Модель: <b>{html.escape(str(model))}</b>",
        f"Фон: <b>{html.escape(str(background))}</b>",
        f"Узор: <b>{html.escape(str(pattern))}</b>",
        "",
        f"<b>{html.escape(action_ru)}:</b> {html.escape(summary)}",
        "",
        f"<b>Прогноз 24ч:</b> {html.escape(fc_bias)}, диапазон {html.escape(fc_range)}",
    ]
    lines.append("<b>Причины:</b>")
    if reasons:
        for r in reasons[:3]:
            txt = str((r or {}).get("text") or "-")
            lines.append(f"- {html.escape(txt)}")
    else:
        lines.append("- -")
    lines.append("<b>Риск:</b>")
    if risks:
        for r in risks[:2]:
            txt = str((r or {}).get("text") or "-")
            lines.append(f"- {html.escape(txt)}")
    else:
        lines.append("- -")
    lines.extend(["", f"Время сигнала: {_now_msk_text()}"])
    return "\n".join(lines)


def _send_signal(item: Dict) -> None:
    text = _format_signal(item)
    preview = str(item.get("preview_url") or "").strip()
    if preview.startswith("http://") or preview.startswith("https://"):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        # Telegram caption max 1024 chars.
        caption = text[:1000]
        _http_post(url, {"chat_id": CHAT_ID, "photo": preview, "caption": caption, "parse_mode": "HTML"})
        return
    send_message_to(CHAT_ID, text, parse_mode="HTML")


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


def _wait_api_ready() -> None:
    started = time.time()
    while True:
        try:
            _http_get(f"{API_BASE_URL}/healthz")
            return
        except Exception:
            if time.time() - started >= API_WARMUP_MAX_SEC:
                return
            time.sleep(2)


def cycle(cache: Dict) -> None:
    _wait_api_ready()
    _handle_commands(cache)
    try:
        resp = _http_get(f"{API_BASE_URL}/api/recommendations?scope=all&entity=variant&ai=1")
    except Exception as e:
        # Fallback path for Render cold starts / heavy AI pipeline windows.
        if isinstance(e, TimeoutError) or (
            isinstance(e, urllib.error.HTTPError) and e.code in {502, 503, 504}
        ):
            resp = _http_get(f"{API_BASE_URL}/api/recommendations?scope=all&entity=variant&ai=0")
        else:
            raise
    items = sorted(resp.get("items") or [], key=lambda x: float(x.get("confidence", 0) or 0), reverse=True)
    now_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_ts = int(time.time())
    sent_count = 0
    stat_total = len(items)
    stat_conf = 0
    stat_action = 0
    stat_fp = 0
    stat_dyn = 0

    if FORCE_SEND_TOP1 and items:
        _send_signal(items[0])
        sent_count += 1
        key = f"{items[0].get('variant_id')}"
        fp = _signal_fingerprint(items[0])
        cache[key] = {**items[0], "last_sent": now_tag, "last_sent_ts": now_ts, "last_fp": fp}
        if DEBUG:
            print(f"[bot] force-send top1 variant={key}")
        return

    for item in items:
        if sent_count >= MAX_MESSAGES_PER_CYCLE:
            break
        if item.get("confidence", 0) < MIN_CONFIDENCE:
            continue
        stat_conf += 1
        if str(item.get("action") or "").upper() not in {"BUY", "SELL", "WATCH", "AVOID"}:
            continue
        stat_action += 1
        key = f"{item.get('variant_id')}"
        prev = cache.get(key, {})
        fp = _signal_fingerprint(item)
        last_fp = str(prev.get("last_fp") or "")
        last_sent_ts = int(prev.get("last_sent_ts", 0) or 0)
        # Антидубль: если сигнал по сути не изменился, повтор не отправляем.
        if fp == last_fp and (now_ts - last_sent_ts) < MIN_REPEAT_SEC:
            stat_fp += 1
            continue
        if not _is_dynamic(prev, item):
            stat_dyn += 1
            continue
        _send_signal(item)
        sent_count += 1
        cache[key] = {**item, "last_sent": now_tag, "last_sent_ts": now_ts, "last_fp": fp}
    if DEBUG:
        print(
            f"[bot] total={stat_total} pass_conf={stat_conf} pass_action={stat_action} "
            f"skip_fp={stat_fp} skip_not_dynamic={stat_dyn} sent={sent_count}"
        )


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

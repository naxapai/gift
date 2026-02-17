from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Dict, List, Set

from analytics import get_ranked_signals
from market_data import load_dataset

BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()
POLL_INTERVAL_SEC = int(os.getenv("BOT_POLL_INTERVAL", "300"))
MIN_INTENSITY = float(os.getenv("BOT_MIN_INTENSITY", "10"))


def _http_post(url: str, data: Dict[str, str]) -> Dict:
    payload = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(req, timeout=20) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw)


def send_message(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Set TG_BOT_TOKEN and TG_CHAT_ID env vars")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    _http_post(url, {"chat_id": CHAT_ID, "text": text})


def _score(row: Dict) -> float:
    return abs(row["change_7d"]) + abs(row["zscore_30d"]) * 2 + abs(row["volume_trend_7_vs_30"]) / 2


def _is_alertable(row: Dict) -> bool:
    if row["signal"] in {"BUY", "SELL"}:
        return _score(row) >= MIN_INTENSITY
    if row["signal"] == "ANOMALY":
        return abs(row["zscore_30d"]) >= 2.2
    return False


def _format_alert(row: Dict) -> str:
    return (
        f"[{row['signal']}] {row['name']}\n"
        f"Цена: {row['price']:.2f}\n"
        f"Изм. 1д: {row['change_1d']:+.2f}% | 7д: {row['change_7d']:+.2f}% | 30д: {row['change_30d']:+.2f}%\n"
        f"Спрос/предложение: {row['demand_supply_ratio']:.2f}\n"
        f"Тренд объема (7д/30д): {row['volume_trend_7_vs_30']:+.2f}%\n"
        f"z-score: {row['zscore_30d']:+.2f}\n"
        f"Комментарий: {row['commentary']}"
    )


def cycle(sent_cache: Set[str]) -> None:
    dataset = load_dataset()
    rows = get_ranked_signals(dataset)

    alerts: List[Dict] = [r for r in rows if _is_alertable(r)]

    now_tag = datetime.utcnow().strftime("%Y-%m-%d")
    stale_prefixes = [k for k in sent_cache if not k.startswith(now_tag + ":")]
    for key in stale_prefixes:
        sent_cache.remove(key)
    for row in alerts[:8]:
        key = f"{now_tag}:{row['gift_id']}:{row['signal']}"
        if key in sent_cache:
            continue
        send_message(_format_alert(row))
        sent_cache.add(key)


def main() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise SystemExit("Set TG_BOT_TOKEN and TG_CHAT_ID before running bot.py")

    sent_cache: Set[str] = set()
    send_message("Бот аналитики Telegram Gifts запущен.")

    while True:
        try:
            cycle(sent_cache)
        except urllib.error.URLError as e:
            print(f"Network error: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"Unexpected error: {e}")
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()

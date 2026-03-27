#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backtest_tz_signals import run as backtest_run


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _as_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _send_tg_alert_if_needed(payload: dict) -> None:
    source_ok = bool(payload.get("source_ok"))
    gates_ok = bool(payload.get("gates_ok"))
    if source_ok and gates_ok:
        return
    token = (
        os.getenv("TZ_GATES_ALERT_BOT_TOKEN", "").strip()
        or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        or os.getenv("TG_BOT_TOKEN", "").strip()
    )
    chat_id = (
        os.getenv("TZ_GATES_ALERT_CHAT_ID", "").strip()
        or os.getenv("TG_CHAT_ID", "").strip()
    )
    if not token or not chat_id:
        return
    cooldown_sec = max(60.0, _as_float("TZ_GATES_ALERT_COOLDOWN_SEC", 7200.0))
    state_file = Path(os.getenv("TZ_GATES_ALERT_STATE_FILE", str(ROOT / "data" / "tz_gates_alert_state.json")))
    now_ts = int(datetime.now(timezone.utc).timestamp())
    last_sent = 0
    if state_file.exists():
        try:
            st = json.loads(state_file.read_text(encoding="utf-8"))
            last_sent = int(st.get("last_sent_ts", 0) or 0)
        except Exception:
            last_sent = 0
    if now_ts - last_sent < int(cooldown_sec):
        return
    report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    dist = report.get("distribution") if isinstance(report.get("distribution"), dict) else {}
    text = (
        "GiftMarketZone TZ gates alert\n"
        f"source_ok={source_ok}, gates_ok={gates_ok}, corridor_ok={bool(payload.get('corridor_ok'))}\n"
        f"distribution: BUY={int(dist.get('BUY', 0))}, SELL={int(dist.get('SELL', 0))}, "
        f"WATCH={int(dist.get('WATCH', 0))}, SKIP={int(dist.get('SKIP', 0))}\n"
        f"checked_at={payload.get('checked_at')}"
    )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"last_sent_ts": now_ts, "last_sent_at": _now_iso()}, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    horizon_hours = _as_int("TZ_GATES_HORIZON_HOURS", 24)
    limit = _as_int("TZ_GATES_LIMIT", 1000)
    signals_url = os.getenv("TZ_GATES_SIGNALS_URL", "https://giftmarketzone.com/v1/signals").strip()
    out_file = Path(os.getenv("TZ_GATES_STATUS_FILE", str(ROOT / "data" / "tz_gates_status.json")))

    report = backtest_run(horizon_hours=horizon_hours, mode="tz", limit=limit, signals_url=(signals_url or None))
    dist = report.get("distribution") or {}

    corridor = {
        "buy_min": _as_int("TZ_GATES_BUY_MIN", 1),
        "buy_max": _as_int("TZ_GATES_BUY_MAX", 20),
        "watch_min": _as_int("TZ_GATES_WATCH_MIN", 0),
        "watch_max": _as_int("TZ_GATES_WATCH_MAX", 80),
        "skip_min": _as_int("TZ_GATES_SKIP_MIN", 80),
        "skip_max": _as_int("TZ_GATES_SKIP_MAX", 260),
        "sell_min": _as_int("TZ_GATES_SELL_MIN", 0),
        "sell_max": _as_int("TZ_GATES_SELL_MAX", 20),
    }
    corridor_checks = {
        "buy_ok": corridor["buy_min"] <= int(dist.get("BUY", 0)) <= corridor["buy_max"],
        "watch_ok": corridor["watch_min"] <= int(dist.get("WATCH", 0)) <= corridor["watch_max"],
        "skip_ok": corridor["skip_min"] <= int(dist.get("SKIP", 0)) <= corridor["skip_max"],
        "sell_ok": corridor["sell_min"] <= int(dist.get("SELL", 0)) <= corridor["sell_max"],
    }
    corridor_ok = all(corridor_checks.values())

    source_ok = str(report.get("source") or "") == "remote"
    gates_ok = bool(report.get("gates_passed"))
    # Corridor drift is tracked as warning for calibration and should not fail cron health.
    final_ok = source_ok and gates_ok

    payload = {
        "ok": final_ok,
        "checked_at": _now_iso(),
        "source_ok": source_ok,
        "gates_ok": gates_ok,
        "corridor_ok": corridor_ok,
        "corridor_checks": corridor_checks,
        "corridor": corridor,
        "report": report,
    }

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        _send_tg_alert_if_needed(payload)
    except Exception:
        pass
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if final_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

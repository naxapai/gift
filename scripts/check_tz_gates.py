#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

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


def main() -> int:
    horizon_hours = _as_int("TZ_GATES_HORIZON_HOURS", 24)
    limit = _as_int("TZ_GATES_LIMIT", 1000)
    signals_url = os.getenv("TZ_GATES_SIGNALS_URL", "https://telegram-gifts-market.onrender.com/v1/signals").strip()
    out_file = Path(os.getenv("TZ_GATES_STATUS_FILE", str(ROOT / "data" / "tz_gates_status.json")))

    report = backtest_run(horizon_hours=horizon_hours, mode="tz", limit=limit, signals_url=(signals_url or None))
    dist = report.get("distribution") or {}

    corridor = {
        "buy_min": _as_int("TZ_GATES_BUY_MIN", 3),
        "buy_max": _as_int("TZ_GATES_BUY_MAX", 15),
        "watch_min": _as_int("TZ_GATES_WATCH_MIN", 15),
        "watch_max": _as_int("TZ_GATES_WATCH_MAX", 45),
        "skip_min": _as_int("TZ_GATES_SKIP_MIN", 40),
        "skip_max": _as_int("TZ_GATES_SKIP_MAX", 85),
        "sell_min": _as_int("TZ_GATES_SELL_MIN", 0),
        "sell_max": _as_int("TZ_GATES_SELL_MAX", 12),
    }
    corridor_checks = {
        "buy_ok": corridor["buy_min"] <= int(dist.get("BUY", 0)) <= corridor["buy_max"],
        "watch_ok": corridor["watch_min"] <= int(dist.get("WATCH", 0)) <= corridor["watch_max"],
        "skip_ok": corridor["skip_min"] <= int(dist.get("SKIP", 0)) <= corridor["skip_max"],
        "sell_ok": corridor["sell_min"] <= int(dist.get("SELL", 0)) <= corridor["sell_max"],
    }

    source_ok = str(report.get("source") or "") == "remote"
    gates_ok = bool(report.get("gates_passed"))
    final_ok = source_ok and gates_ok and all(corridor_checks.values())

    payload = {
        "ok": final_ok,
        "checked_at": _now_iso(),
        "source_ok": source_ok,
        "gates_ok": gates_ok,
        "corridor_checks": corridor_checks,
        "corridor": corridor,
        "report": report,
    }

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if final_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())


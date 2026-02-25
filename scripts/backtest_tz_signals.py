#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import GiftAnalyticsService


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


@dataclass
class EvalPoint:
    variant_id: str
    action: str
    score100: float
    conf_pct: float
    realized_pct: float


def _floor_at_or_before(points: list[dict[str, Any]], target: datetime) -> float | None:
    selected: float | None = None
    selected_ts: datetime | None = None
    for row in points:
        ts = _parse_ts(str(row.get("ts") or ""))
        if ts is None or ts > target:
            continue
        floor = row.get("floor_ton")
        if floor is None:
            continue
        try:
            floor_v = float(floor)
        except Exception:
            continue
        if floor_v <= 0:
            continue
        if selected_ts is None or ts > selected_ts:
            selected_ts = ts
            selected = floor_v
    return selected


def _collect_all_signals(svc: GiftAnalyticsService, mode: str, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        chunk = svc.signals_v1(limit=200, cursor=cursor, mode=mode)
        items = chunk.get("items") or []
        out.extend(items)
        cursor = chunk.get("next_cursor")
        if not cursor or len(out) >= limit:
            break
    return out[:limit]


def run(horizon_hours: int, mode: str, limit: int) -> dict[str, Any]:
    svc = GiftAnalyticsService()
    signals = _collect_all_signals(svc, mode=mode, limit=limit)
    history_path = Path("data/variant_history.json")
    history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else {}

    now = datetime.now(timezone.utc)
    horizon_start = now - timedelta(hours=horizon_hours)

    eval_points: list[EvalPoint] = []
    for sig in signals:
        vid = str(sig.get("variant_id") or "")
        if not vid:
            continue
        rows = history.get(vid) or []
        if not isinstance(rows, list) or len(rows) < 2:
            continue
        floor_now = _floor_at_or_before(rows, now)
        floor_then = _floor_at_or_before(rows, horizon_start)
        if not floor_now or not floor_then or floor_then <= 0:
            continue
        realized = ((floor_now - floor_then) / floor_then) * 100.0
        eval_points.append(
            EvalPoint(
                variant_id=vid,
                action=str(sig.get("type") or ""),
                score100=float(sig.get("score100") or 0.0),
                conf_pct=float(sig.get("conf_pct") or 0.0),
                realized_pct=realized,
            )
        )

    def _subset(action: str) -> list[EvalPoint]:
        return [x for x in eval_points if x.action == action]

    buys = _subset("BUY")
    sells = _subset("SELL")
    watches = _subset("WATCH")
    skips = _subset("SKIP")

    buy_hit = sum(1 for x in buys if x.realized_pct > 0)
    sell_hit = sum(1 for x in sells if x.realized_pct < 0)
    watch_neutral = sum(1 for x in watches if -5.0 <= x.realized_pct <= 5.0)

    def _avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    return {
        "mode": mode,
        "horizon_hours": horizon_hours,
        "evaluated": len(eval_points),
        "distribution": {
            "BUY": len(buys),
            "SELL": len(sells),
            "WATCH": len(watches),
            "SKIP": len(skips),
        },
        "quality": {
            "buy_hit_rate": round((buy_hit / len(buys)) * 100.0, 2) if buys else None,
            "sell_hit_rate": round((sell_hit / len(sells)) * 100.0, 2) if sells else None,
            "watch_neutral_rate": round((watch_neutral / len(watches)) * 100.0, 2) if watches else None,
        },
        "avg_realized_pct": {
            "BUY": _avg([x.realized_pct for x in buys]),
            "SELL": _avg([x.realized_pct for x in sells]),
            "WATCH": _avg([x.realized_pct for x in watches]),
            "SKIP": _avg([x.realized_pct for x in skips]),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Quick backtest for TZ signal formulas using local history.")
    parser.add_argument("--horizon-hours", type=int, default=24)
    parser.add_argument("--mode", default="tz")
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    report = run(horizon_hours=args.horizon_hours, mode=args.mode, limit=args.limit)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

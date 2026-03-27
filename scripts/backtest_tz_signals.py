#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import sys
import urllib.parse
import urllib.request
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


def _extract_floor_points(points: list[dict[str, Any]]) -> list[tuple[datetime, float]]:
    out: list[tuple[datetime, float]] = []
    for row in points:
        ts = _parse_ts(str(row.get("ts") or ""))
        if ts is None:
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
        out.append((ts, floor_v))
    out.sort(key=lambda x: x[0])
    return out


def _window_start_end(
    floor_points: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
) -> tuple[float | None, float | None]:
    if not floor_points:
        return None, None
    in_window = [(ts, floor) for ts, floor in floor_points if start <= ts <= end]
    if not in_window:
        return None, None
    return in_window[0][1], in_window[-1][1]


def _collect_all_signals_local(svc: GiftAnalyticsService, mode: str, limit: int) -> list[dict[str, Any]]:
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


def _http_get_json(url: str, timeout: int = 25, retries: int = 4) -> dict[str, Any]:
    last_err: Exception | None = None
    for i in range(max(1, retries)):
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as err:  # noqa: BLE001
            last_err = err
            if i + 1 < retries:
                time.sleep(1.2 + (i * 0.8))
    if last_err is not None:
        raise last_err
    raise RuntimeError("http_get_json_failed_without_error")


def _collect_all_signals_remote(signals_base_url: str, mode: str, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        q = {"limit": "200", "mode": mode}
        if cursor:
            q["cursor"] = cursor
        url = f"{signals_base_url}?{urllib.parse.urlencode(q)}"
        payload = _http_get_json(url)
        items = payload.get("items") or []
        out.extend(items)
        cursor = payload.get("next_cursor")
        if not cursor or len(out) >= limit:
            break
    return out[:limit]


def run(
    horizon_hours: int,
    mode: str,
    limit: int,
    signals_url: str | None = None,
    svc: GiftAnalyticsService | None = None,
    history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    svc_obj = svc if isinstance(svc, GiftAnalyticsService) else GiftAnalyticsService()
    source = "local"
    if signals_url:
        try:
            signals = _collect_all_signals_remote(signals_url, mode=mode, limit=limit)
            source = "remote"
        except Exception:  # noqa: BLE001
            signals = _collect_all_signals_local(svc_obj, mode=mode, limit=limit)
            source = "local_fallback"
    else:
        signals = _collect_all_signals_local(svc_obj, mode=mode, limit=limit)
    if not isinstance(history, dict):
        if isinstance(getattr(svc_obj, "variant_history", None), dict):
            history = getattr(svc_obj, "variant_history")
        else:
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
        floor_points = _extract_floor_points(rows)
        floor_then, floor_now = _window_start_end(floor_points, horizon_start, now)
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

    coverage = round((len(eval_points) / max(1, len(signals))) * 100.0, 2)

    adaptive_min_evaluated = max(100, min(200, int(max(1, len(signals)) * 0.7)))
    min_buy_samples = 8
    min_sell_samples = 8
    min_buy_presence = max(1, int(max(1, len(eval_points)) * 0.01))

    gates = {
        "min_evaluated": adaptive_min_evaluated,
        "min_coverage_pct": 20.0,
        "min_buy_hit_rate_pct": 45.0,
        "min_sell_hit_rate_pct": 45.0,
        "min_watch_neutral_rate_pct": 40.0,
        "min_buy_samples": min_buy_samples,
        "min_sell_samples": min_sell_samples,
        "min_buy_presence": min_buy_presence,
    }
    quality = {
        "buy_hit_rate": round((buy_hit / len(buys)) * 100.0, 2) if buys else None,
        "sell_hit_rate": round((sell_hit / len(sells)) * 100.0, 2) if sells else None,
        "watch_neutral_rate": round((watch_neutral / len(watches)) * 100.0, 2) if watches else None,
    }
    gate_checks = {
        "evaluated_ok": len(eval_points) >= gates["min_evaluated"],
        "coverage_ok": coverage >= gates["min_coverage_pct"],
        "buy_presence_ok": len(buys) >= gates["min_buy_presence"],
        "buy_hit_ok": (len(buys) < gates["min_buy_samples"]) or ((quality["buy_hit_rate"] is not None) and (quality["buy_hit_rate"] >= gates["min_buy_hit_rate_pct"])),
        "sell_hit_ok": (len(sells) < gates["min_sell_samples"]) or ((quality["sell_hit_rate"] is not None) and (quality["sell_hit_rate"] >= gates["min_sell_hit_rate_pct"])),
        "watch_neutral_ok": (quality["watch_neutral_rate"] is not None) and (quality["watch_neutral_rate"] >= gates["min_watch_neutral_rate_pct"]),
    }
    all_ok = all(gate_checks.values())

    return {
        "source": source,
        "mode": mode,
        "horizon_hours": horizon_hours,
        "evaluated": len(eval_points),
        "signals_considered": len(signals),
        "coverage_pct": coverage,
        "distribution": {
            "BUY": len(buys),
            "SELL": len(sells),
            "WATCH": len(watches),
            "SKIP": len(skips),
        },
        "quality": quality,
        "gates": gates,
        "gate_checks": gate_checks,
        "gates_passed": all_ok,
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
    parser.add_argument(
        "--signals-url",
        default="https://giftmarketzone.com/v1/signals",
        help="Optional remote /v1/signals endpoint. Set empty string to use local service signals.",
    )
    args = parser.parse_args()
    report = run(
        horizon_hours=args.horizon_hours,
        mode=args.mode,
        limit=args.limit,
        signals_url=(args.signals_url.strip() or None),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

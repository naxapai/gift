from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Dict, List, Tuple


def _pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / previous * 100


def _safe_ratio(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return a / b


def _slice_last(values: List[float], n: int) -> List[float]:
    if not values:
        return []
    return values[-n:] if len(values) >= n else values[:]


def _rolling_zscore(values: List[float]) -> float:
    if len(values) < 7:
        return 0.0
    baseline = values[:-1]
    latest = values[-1]
    sigma = pstdev(baseline)
    if sigma == 0:
        return 0.0
    return (latest - mean(baseline)) / sigma


def _parse_dt(value: str) -> datetime:
    raw = (value or "").strip()
    if not raw:
        return datetime.now(timezone.utc)
    try:
        if len(raw) == 10:
            return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def _point_at_or_before(series: List[Dict], cutoff: datetime) -> Dict:
    for p in reversed(series):
        if _parse_dt(p.get("dt", "")) <= cutoff:
            return p
    return series[0]


def _points_since(series: List[Dict], cutoff: datetime) -> List[Dict]:
    return [p for p in series if _parse_dt(p.get("dt", "")) >= cutoff]


def _signal_tag(change_7d: float, ratio: float, zscore: float) -> str:
    if change_7d > 6 and ratio > 1.05:
        return "BUY"
    if change_7d < -6 and ratio < 0.95:
        return "SELL"
    if abs(zscore) > 2.3:
        return "ANOMALY"
    return "HOLD"


def summarize_gift(gift: Dict) -> Dict:
    series = gift["series"]
    prices = [p["price"] for p in series]
    demands = [p["demand"] for p in series]
    supplies = [p["supply"] for p in series]
    volumes = [p["volume"] for p in series]

    latest = series[-1]
    latest_dt = _parse_dt(latest.get("dt", ""))
    first_dt = _parse_dt(series[0].get("dt", ""))
    history_span_days = max(0.0, (latest_dt - first_dt).total_seconds() / 86400.0)
    prev_1d = _point_at_or_before(series, latest_dt - timedelta(days=1))
    prev_7d = _point_at_or_before(series, latest_dt - timedelta(days=7))
    prev_30d = _point_at_or_before(series, latest_dt - timedelta(days=30))
    prev_6h = _point_at_or_before(series, latest_dt - timedelta(hours=6))

    change_1d = _pct_change(latest["price"], prev_1d["price"])
    change_7d = _pct_change(latest["price"], prev_7d["price"]) if history_span_days >= 7 else None
    change_30d = _pct_change(latest["price"], prev_30d["price"]) if history_span_days >= 30 else None
    change_6h = _pct_change(latest["price"], prev_6h["price"])

    ratio = _safe_ratio(latest["demand"], latest["supply"])
    last_7d = _points_since(series, latest_dt - timedelta(days=7))
    last_30d = _points_since(series, latest_dt - timedelta(days=30))
    last_6h = _points_since(series, latest_dt - timedelta(hours=6))
    last_24h = _points_since(series, latest_dt - timedelta(hours=24))
    vol_7 = mean([p["volume"] for p in last_7d]) if last_7d else None
    vol_30 = mean([p["volume"] for p in last_30d]) if last_30d else None
    vol_6h = mean([p["volume"] for p in last_6h]) if last_6h else None
    vol_24h = mean([p["volume"] for p in last_24h]) if last_24h else None
    if vol_7 is not None and vol_30 is not None and history_span_days >= 7:
        volume_trend = _pct_change(vol_7, vol_30)
    elif vol_6h is not None and vol_24h is not None:
        volume_trend = _pct_change(vol_6h, vol_24h)
    else:
        volume_trend = 0.0

    prices_30d = [p["price"] for p in last_30d] if last_30d else prices
    returns = []
    for i in range(1, len(prices_30d)):
        returns.append(_pct_change(prices_30d[i], prices_30d[i - 1]))
    volatility = pstdev(_slice_last(returns, 90)) if returns else 0.0
    zscore = _rolling_zscore(prices_30d[-90:]) if prices_30d else 0.0

    effective_change = change_7d if change_7d is not None else change_1d if history_span_days >= 1 else change_6h
    signal = _signal_tag(effective_change, ratio, zscore)

    return {
        "gift_id": gift["gift_id"],
        "name": gift["name"],
        "group": gift.get("group", "Other"),
        "collection": gift.get("collection_slug", gift.get("name", gift.get("gift_id", ""))),
        "model": str((gift.get("profile") or {}).get("model") or ""),
        "backdrop": str((gift.get("profile") or {}).get("background") or ""),
        "symbol": str((gift.get("profile") or {}).get("pattern") or ""),
        "market_statuses": dict(gift.get("status_counts") or {}),
        "price": round(latest["price"], 4),
        "date": latest["dt"],
        "change_1d": round(change_1d, 2),
        "change_6h": round(change_6h, 2),
        "change_7d": round(change_7d, 2) if change_7d is not None else None,
        "change_30d": round(change_30d, 2) if change_30d is not None else None,
        "demand": round(latest["demand"], 3),
        "supply": round(latest["supply"], 3),
        "demand_supply_ratio": round(ratio, 3),
        "volume": int(latest["volume"]),
        "volume_trend_7_vs_30": round(volume_trend, 2),
        "volatility_30d": round(volatility, 2),
        "zscore_30d": round(zscore, 2),
        "signal": signal,
        "commentary": make_commentary(effective_change, change_30d or 0.0, ratio, volume_trend, signal),
        "history_span_days": round(history_span_days, 2),
    }


def make_commentary(
    change_7d: float,
    change_30d: float,
    ratio: float,
    volume_trend: float,
    signal: str,
) -> str:
    momentum = "ускоряется" if change_7d > change_30d / 4 else "замедляется"
    ds = "дефицит предложения" if ratio > 1.1 else "избыток предложения" if ratio < 0.9 else "баланс спроса и предложения"
    activity = "объемы растут" if volume_trend > 5 else "объемы снижаются" if volume_trend < -5 else "объемы стабильны"

    if signal == "BUY":
        action = "сценарий накопления"
    elif signal == "SELL":
        action = "сценарий распределения"
    elif signal == "ANOMALY":
        action = "аномальная фаза, нужен риск-контроль"
    else:
        action = "нейтральная фаза"

    return f"Тренд {momentum}, {ds}, {activity}; {action}."


def build_market_summary(dataset: Dict) -> Dict:
    rows = [summarize_gift(g) for g in dataset["gifts"]]
    avg_7d_vals = [r["change_7d"] for r in rows if isinstance(r.get("change_7d"), (int, float))]
    avg_30d_vals = [r["change_30d"] for r in rows if isinstance(r.get("change_30d"), (int, float))]
    avg_7d = mean(avg_7d_vals) if avg_7d_vals else None
    avg_30d = mean(avg_30d_vals) if avg_30d_vals else None
    buy_count = sum(1 for r in rows if r["signal"] == "BUY")
    sell_count = sum(1 for r in rows if r["signal"] == "SELL")
    anomaly_count = sum(1 for r in rows if r["signal"] == "ANOMALY")

    market_state = "Рост" if avg_7d > 2 else "Падение" if avg_7d < -2 else "Боковик"

    return {
        "generated_at": dataset.get("generated_at"),
        "market_state": market_state,
        "avg_change_7d": round(avg_7d, 2) if avg_7d is not None else None,
        "avg_change_30d": round(avg_30d, 2) if avg_30d is not None else None,
        "buy_signals": buy_count,
        "sell_signals": sell_count,
        "anomalies": anomaly_count,
        "rows": rows,
    }


def build_chart_series(gift: Dict) -> Dict:
    points = gift["series"]
    return {
        "gift_id": gift["gift_id"],
        "name": gift["name"],
        "group": gift.get("group", "Other"),
        "dates": [x["dt"] for x in points],
        "prices": [x["price"] for x in points],
        "demand": [x["demand"] for x in points],
        "supply": [x["supply"] for x in points],
        "volume": [x["volume"] for x in points],
    }


def get_ranked_signals(dataset: Dict) -> List[Dict]:
    summary = build_market_summary(dataset)
    rows = summary["rows"]

    def score(row: Dict) -> Tuple[int, float]:
        label_rank = {"BUY": 0, "SELL": 1, "ANOMALY": 2, "HOLD": 3}
        intensity = abs(row["change_7d"]) + abs(row["zscore_30d"]) * 2 + abs(row["volume_trend_7_vs_30"]) / 2
        return (label_rank[row["signal"]], -intensity)

    return sorted(rows, key=score)

from __future__ import annotations

import math
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
    prev_1d = series[-2] if len(series) > 1 else series[-1]
    prev_7d = series[-8] if len(series) > 8 else series[0]
    prev_30d = series[-31] if len(series) > 31 else series[0]

    change_1d = _pct_change(latest["price"], prev_1d["price"])
    change_7d = _pct_change(latest["price"], prev_7d["price"])
    change_30d = _pct_change(latest["price"], prev_30d["price"])

    ratio = _safe_ratio(latest["demand"], latest["supply"])
    volume_trend = _pct_change(mean(_slice_last(volumes, 7)), mean(_slice_last(volumes, 30)))

    returns = []
    for i in range(1, len(prices)):
        returns.append(_pct_change(prices[i], prices[i - 1]))
    volatility = pstdev(_slice_last(returns, 30)) if returns else 0.0
    zscore = _rolling_zscore(_slice_last(prices, 31))

    signal = _signal_tag(change_7d, ratio, zscore)

    return {
        "gift_id": gift["gift_id"],
        "name": gift["name"],
        "group": gift.get("group", "Other"),
        "price": round(latest["price"], 4),
        "date": latest["dt"],
        "change_1d": round(change_1d, 2),
        "change_7d": round(change_7d, 2),
        "change_30d": round(change_30d, 2),
        "demand": round(latest["demand"], 3),
        "supply": round(latest["supply"], 3),
        "demand_supply_ratio": round(ratio, 3),
        "volume": int(latest["volume"]),
        "volume_trend_7_vs_30": round(volume_trend, 2),
        "volatility_30d": round(volatility, 2),
        "zscore_30d": round(zscore, 2),
        "signal": signal,
        "commentary": make_commentary(change_7d, change_30d, ratio, volume_trend, signal),
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
    avg_7d = mean([r["change_7d"] for r in rows]) if rows else 0.0
    avg_30d = mean([r["change_30d"] for r in rows]) if rows else 0.0
    buy_count = sum(1 for r in rows if r["signal"] == "BUY")
    sell_count = sum(1 for r in rows if r["signal"] == "SELL")
    anomaly_count = sum(1 for r in rows if r["signal"] == "ANOMALY")

    market_state = "Рост" if avg_7d > 2 else "Падение" if avg_7d < -2 else "Боковик"

    return {
        "generated_at": dataset.get("generated_at"),
        "market_state": market_state,
        "avg_change_7d": round(avg_7d, 2),
        "avg_change_30d": round(avg_30d, 2),
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

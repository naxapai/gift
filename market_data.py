from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

DATA_FILE = Path(__file__).parent / "data" / "gifts_history.json"
MIN_GIFTS_COUNT = 200


@dataclass
class GiftPoint:
    dt: str
    price: float
    demand: float
    supply: float
    volume: int


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _gift_templates() -> List[Dict]:
    bases = [
        ("Rose", "Flowers", 38.0, 0.031),
        ("Tulip", "Flowers", 28.0, 0.029),
        ("Gift Box", "Boxes", 60.0, 0.039),
        ("Diamond Heart", "Premium", 110.0, 0.052),
        ("Golden Star", "Premium", 82.0, 0.043),
        ("Lucky Balloon", "Fun", 21.0, 0.03),
        ("Sakura", "Flowers", 49.0, 0.037),
        ("Ocean Pearl", "Luxury", 72.0, 0.041),
        ("Neon Comet", "Digital", 90.0, 0.048),
        ("Royal Crown", "Luxury", 130.0, 0.05),
    ]
    tiers = [
        "Classic", "Prime", "Luxe", "Ultra", "Rare", "Elite", "Nova", "Pulse", "Spark", "Zen",
        "Core", "Pro", "Plus", "Max", "Aura", "Flash", "Orbit", "Crystal", "Legend", "Infinity",
    ]

    templates: List[Dict] = []
    for base_name, group, base_price, base_vol in bases:
        for idx, tier in enumerate(tiers):
            full_name = f"{base_name} {tier}"
            gift_id = (
                full_name.lower()
                .replace(" ", "_")
                .replace("-", "_")
                .replace("__", "_")
            )
            price_mult = 0.74 + idx * 0.055
            vol_add = idx * 0.0015
            templates.append(
                {
                    "gift_id": gift_id,
                    "name": full_name,
                    "group": group,
                    "base_price": round(base_price * price_mult, 2),
                    "volatility": round(base_vol + vol_add, 4),
                }
            )
    return templates


def generate_dataset(days: int = 180, seed: int = 42) -> Dict:
    random.seed(seed)
    start = date.today() - timedelta(days=days - 1)
    gifts = []

    for template in _gift_templates():
        series: List[GiftPoint] = []
        price = template["base_price"] * random.uniform(0.85, 1.15)
        demand = random.uniform(0.9, 1.4)
        supply = random.uniform(0.8, 1.5)
        drift = random.uniform(-0.0004, 0.0014)

        for idx in range(days):
            current_date = start + timedelta(days=idx)
            month_cycle = (idx % 30) / 30.0
            season_component = 0.012 if 0.12 <= month_cycle <= 0.33 else -0.004
            noise = random.gauss(0, template["volatility"])
            price_change = drift + season_component + noise
            price_change = _clamp(price_change, -0.18, 0.2)
            price = max(1.0, price * (1 + price_change))

            demand = _clamp(demand * (1 + random.gauss(0.0, 0.05)), 0.5, 2.8)
            supply = _clamp(supply * (1 + random.gauss(0.0, 0.05)), 0.45, 3.0)

            if random.random() < 0.03:
                demand = _clamp(demand * random.uniform(1.08, 1.28), 0.6, 3.1)
            if random.random() < 0.03:
                supply = _clamp(supply * random.uniform(1.1, 1.32), 0.5, 3.2)

            volume = int(300 + 430 * demand / max(supply, 0.35) + random.randint(-60, 90))
            volume = max(50, volume)

            series.append(
                GiftPoint(
                    dt=current_date.isoformat(),
                    price=round(price, 4),
                    demand=round(demand, 4),
                    supply=round(supply, 4),
                    volume=volume,
                )
            )

        gifts.append(
            {
                "gift_id": template["gift_id"],
                "name": template["name"],
                "group": template["group"],
                "series": [point.__dict__ for point in series],
            }
        )

    return {"generated_at": date.today().isoformat(), "gifts": gifts}


def load_dataset() -> Dict:
    if not DATA_FILE.exists():
        dataset = generate_dataset()
        save_dataset(dataset)
        return dataset

    with DATA_FILE.open("r", encoding="utf-8") as f:
        dataset = json.load(f)

    gifts = dataset.get("gifts", [])
    if len(gifts) < MIN_GIFTS_COUNT:
        dataset = generate_dataset()
        save_dataset(dataset)
    return dataset


def save_dataset(dataset: Dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=2)


def refresh_dataset(days: int = 180) -> Dict:
    dataset = generate_dataset(days=days)
    save_dataset(dataset)
    return dataset


def tick_realtime(dataset: Dict, max_points: int = 360) -> None:
    for gift in dataset.get("gifts", []):
        series = gift.get("series", [])
        if not series:
            continue

        last = series[-1]
        price = float(last["price"])
        demand = float(last["demand"])
        supply = float(last["supply"])

        micro_trend = random.uniform(-0.006, 0.008)
        spike = random.uniform(-0.02, 0.02) if random.random() < 0.1 else 0.0
        price_change = _clamp(micro_trend + spike + random.gauss(0.0, 0.008), -0.04, 0.05)
        price = max(1.0, price * (1 + price_change))

        demand = _clamp(demand * (1 + random.gauss(0.0, 0.018)), 0.4, 3.3)
        supply = _clamp(supply * (1 + random.gauss(0.0, 0.018)), 0.35, 3.4)
        volume = int(180 + 320 * demand / max(supply, 0.35) + random.randint(-30, 45))
        volume = max(30, volume)

        series.append(
            {
                "dt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "price": round(price, 4),
                "demand": round(demand, 4),
                "supply": round(supply, 4),
                "volume": volume,
            }
        )
        if len(series) > max_points:
            del series[: len(series) - max_points]

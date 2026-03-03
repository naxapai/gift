import unittest
import math
from datetime import datetime, timedelta, timezone

from core import GiftAnalyticsService


class TestMetricWindowsRegression(unittest.TestCase):
    def test_liquidity_heatmap_market_includes_6h_bucket(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime.now(timezone.utc)
        variant_id = "liq|m|b|p"
        svc.variants = {
            variant_id: {
                "variant_id": variant_id,
                "base_id": "liq",
                "metrics": {
                    "floor_ton": 10.0,
                    "median_ton": 11.0,
                    "trades_count_24h": 12,
                    "active_listings": 5,
                },
                "traits": {},
            }
        }
        svc.trade_events = [
            {
                "ts": (now - timedelta(minutes=20)).isoformat().replace("+00:00", "Z"),
                "variant_id": variant_id,
                "base_id": "liq",
                "price_ton": 10.2,
            },
            {
                "ts": (now - timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
                "variant_id": variant_id,
                "base_id": "liq",
                "price_ton": 10.4,
            },
            {
                "ts": (now - timedelta(hours=10)).isoformat().replace("+00:00", "Z"),
                "variant_id": variant_id,
                "base_id": "liq",
                "price_ton": 10.8,
            },
        ]

        payload = svc.metrics_v1(metric="LIQUIDITY_HEATMAP", scope="MARKET")
        points = payload.get("points") or []
        self.assertTrue(points)
        first = points[0] if isinstance(points[0], dict) else {}
        extra = first.get("extra") if isinstance(first, dict) else {}
        heat = extra.get("heat") if isinstance(extra, dict) else []
        buckets = {str(row.get("bucket")) for row in heat if isinstance(row, dict)}

        self.assertIn("1h", buckets)
        self.assertIn("6h", buckets)
        self.assertIn("24h", buckets)

    def test_volatility_uses_log_returns_scaled_by_sqrt_n(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime.now(timezone.utc)
        history = [
            {"ts": (now - timedelta(minutes=4)).isoformat().replace("+00:00", "Z"), "floor_ton": 10.0},
            {"ts": (now - timedelta(minutes=3)).isoformat().replace("+00:00", "Z"), "floor_ton": 11.0},
            {"ts": (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"), "floor_ton": 10.5},
            {"ts": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"), "floor_ton": 11.5},
        ]

        got = float(svc._volatility(history, now, 600))  # noqa: SLF001
        lrs = [
            math.log(11.0 / 10.0),
            math.log(10.5 / 11.0),
            math.log(11.5 / 10.5),
        ]
        mean_lr = sum(lrs) / len(lrs)
        variance = sum((x - mean_lr) ** 2 for x in lrs) / len(lrs)
        expected = math.sqrt(variance) * math.sqrt(len(lrs))
        self.assertAlmostEqual(got, expected, places=10)


if __name__ == "__main__":
    unittest.main()

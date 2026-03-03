import unittest
import math
from datetime import datetime, timedelta, timezone

from core import GiftAnalyticsService, METRIC_ALLOWED_SCOPES


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

    def test_metrics_definitions_cover_all_allowed_scopes(self) -> None:
        svc = GiftAnalyticsService()
        defs = svc.metrics_definitions_v1()
        pairs = {
            (str(row.get("metric") or "").upper(), str(row.get("scope") or "").upper())
            for row in defs
            if isinstance(row, dict)
        }
        for metric, scopes in METRIC_ALLOWED_SCOPES.items():
            for scope in scopes:
                self.assertIn((metric, scope), pairs)

    def test_market_floor_realtime_uses_median_of_collection_floors(self) -> None:
        svc = GiftAnalyticsService()
        svc.variants = {
            "c1|m1|b|p": {"variant_id": "c1|m1|b|p", "base_id": "c1", "metrics": {"floor_ton": 1.0, "active_listings": 1, "trades_count_24h": 1, "median_ton": 1.0}, "traits": {}},
            "c1|m2|b|p": {"variant_id": "c1|m2|b|p", "base_id": "c1", "metrics": {"floor_ton": 100.0, "active_listings": 1, "trades_count_24h": 1, "median_ton": 100.0}, "traits": {}},
            "c2|m1|b|p": {"variant_id": "c2|m1|b|p", "base_id": "c2", "metrics": {"floor_ton": 2.0, "active_listings": 1, "trades_count_24h": 1, "median_ton": 2.0}, "traits": {}},
            "c2|m2|b|p": {"variant_id": "c2|m2|b|p", "base_id": "c2", "metrics": {"floor_ton": 100.0, "active_listings": 1, "trades_count_24h": 1, "median_ton": 100.0}, "traits": {}},
            "c3|m1|b|p": {"variant_id": "c3|m1|b|p", "base_id": "c3", "metrics": {"floor_ton": 3.0, "active_listings": 1, "trades_count_24h": 1, "median_ton": 3.0}, "traits": {}},
            "c3|m2|b|p": {"variant_id": "c3|m2|b|p", "base_id": "c3", "metrics": {"floor_ton": 100.0, "active_listings": 1, "trades_count_24h": 1, "median_ton": 100.0}, "traits": {}},
        }

        payload = svc.metrics_v1(metric="FLOOR_REALTIME", scope="MARKET")
        points = payload.get("points") or []
        self.assertTrue(points)
        value = float(points[0].get("value") or 0.0)
        self.assertEqual(value, 2.0)

    def test_strict_edge_score_matches_tz_example_corridor(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime.now(timezone.utc)
        variant_id = "edge|m|b|p"
        svc.variants[variant_id] = {
            "variant_id": variant_id,
            "base_id": "edge",
            "metrics": {
                "floor_ton": 8.0,
                "median_ton": 10.0,
                "trades_count_24h": 700,
                "active_listings": 840,
            },
            "traits": {"model": {"name": "M"}, "background": {"name": "B"}, "pattern": {"name": "P"}},
        }
        # volume_10m = 160, volume_30m = 300 => VV=1.6 => norm=0.8
        # sales_30m = 18, new_30m = 10 => AR=1.8 => norm=0.9
        trade_events = []
        for idx in range(10):
            trade_events.append(
                {
                    "ts": (now - timedelta(minutes=5, seconds=idx)).isoformat().replace("+00:00", "Z"),
                    "variant_id": variant_id,
                    "base_id": "edge",
                    "price_ton": 16.0,
                }
            )
        for idx in range(8):
            trade_events.append(
                {
                    "ts": (now - timedelta(minutes=20, seconds=idx)).isoformat().replace("+00:00", "Z"),
                    "variant_id": variant_id,
                    "base_id": "edge",
                    "price_ton": 17.5,
                }
            )
        svc.trade_events = trade_events
        svc.variant_history[variant_id] = [
            {"ts": (now - timedelta(minutes=3)).isoformat().replace("+00:00", "Z"), "new_listings": 10, "floor_ton": 8.0}
        ]

        mm = svc._strict_formula_inputs(svc.variants[variant_id])  # noqa: SLF001
        # Example in TZ gives ~41.75 due rounded undervalue=0.15;
        # exact pipeline value with fair=9.4 and floor=8.0 is near 41.7.
        self.assertAlmostEqual(float(mm["score100"]), 41.7, places=1)
        self.assertAlmostEqual(float(mm["listing_pressure_norm"]), 0.4, places=6)
        self.assertAlmostEqual(float(mm["volume_velocity_norm"]), 0.8, places=6)
        self.assertAlmostEqual(float(mm["absorption_rate_norm"]), 0.9, places=6)

    def test_metric_definitions_include_min_max_ranges(self) -> None:
        svc = GiftAnalyticsService()
        defs = svc.metrics_definitions_v1()
        by_pair = {
            (str(d.get("metric") or "").upper(), str(d.get("scope") or "").upper()): d
            for d in defs
            if isinstance(d, dict)
        }
        edge = by_pair.get(("EDGE_SCORE", "VARIANT")) or {}
        market_index = by_pair.get(("MARKET_INDEX", "MARKET")) or {}
        trend_market = by_pair.get(("TREND_SCORE", "MARKET")) or {}
        trend_variant = by_pair.get(("TREND_SCORE", "VARIANT")) or {}
        self.assertEqual(edge.get("min_value"), 0.0)
        self.assertEqual(edge.get("max_value"), 1.0)
        self.assertEqual(market_index.get("min_value"), 0.0)
        self.assertEqual(market_index.get("max_value"), 100.0)
        self.assertEqual(trend_market.get("min_value"), 0.0)
        self.assertEqual(trend_market.get("max_value"), 1.0)
        self.assertEqual(trend_variant.get("min_value"), 0.0)
        self.assertEqual(trend_variant.get("max_value"), 1.0)


if __name__ == "__main__":
    unittest.main()

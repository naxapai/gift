import unittest
from datetime import timedelta, timezone, datetime

from core import GiftAnalyticsService


class TestV1MetricsContract(unittest.TestCase):
    def test_metrics_definitions_contract(self) -> None:
        svc = GiftAnalyticsService()
        defs = svc.metrics_definitions_v1()
        self.assertTrue(isinstance(defs, list))
        self.assertTrue(any(d.get("metric") == "MARKET_INDEX" for d in defs))
        self.assertTrue(any(d.get("metric") == "EDGE_SCORE" for d in defs))

    def test_metrics_v1_rejects_unknown_metric(self) -> None:
        svc = GiftAnalyticsService()
        with self.assertRaises(ValueError):
            svc.metrics_v1(metric="NOT_A_METRIC")

    def test_tz_strict_formula_core_values(self) -> None:
        svc = GiftAnalyticsService()
        variant = {
            "variant_id": "test|m|b|p",
            "base_id": "test",
            "metrics": {
                "floor_ton": 8.0,
                "median_ton": 10.0,
                "trades_count_24h": 20,
                "active_listings": 60,
            },
            "traits": {"model": {"name": "M"}, "background": {"name": "B"}, "pattern": {"name": "P"}},
        }
        mm = svc._strict_formula_inputs(variant)  # noqa: SLF001
        # Fair = 0.7*M24 + 0.3*F
        self.assertAlmostEqual(float(mm["fair_ton"]), 9.4, places=6)
        # ListingPressure = active_lots / max(sales24h,1)
        self.assertAlmostEqual(float(mm["listing_pressure"]), 3.0, places=6)
        # target_sell = min(Fair, F*1.02) => min(9.4, 8.16) = 8.16
        expected_profit = ((8.16 - 8.0) / 8.0) - 0.03
        self.assertAlmostEqual(float(mm["expected_profit_pct"]), expected_profit, places=6)

    def test_metrics_v1_variant_scope_payload(self) -> None:
        svc = GiftAnalyticsService()
        svc.variants["x|m|b|p"] = {
            "variant_id": "x|m|b|p",
            "base_id": "x",
            "metrics": {
                "floor_ton": 5.0,
                "median_ton": 7.0,
                "trades_count_24h": 10,
                "active_listings": 15,
            },
            "traits": {"model": {"name": "M"}, "background": {"name": "B"}, "pattern": {"name": "P"}},
            "updated_at": "2026-02-26T00:00:00Z",
        }
        payload = svc.metrics_v1(metric="FAIR_PRICE", variant_id="x|m|b|p", scope="VARIANT", mode="tz_strict")
        self.assertEqual(payload["metric"], "FAIR_PRICE")
        self.assertEqual(payload["scope"], "VARIANT")
        self.assertEqual(payload["unit"], "TON")
        self.assertTrue(len(payload.get("points", [])) >= 1)

    def test_metrics_v1_errors_for_missing_ids(self) -> None:
        svc = GiftAnalyticsService()
        with self.assertRaises(ValueError):
            svc.metrics_v1(metric="FLOOR_REALTIME", scope="VARIANT")
        with self.assertRaises(ValueError):
            svc.metrics_v1(metric="FLOOR_REALTIME", scope="COLLECTION")

    def test_metrics_v1_scope_mismatch_and_range_validation(self) -> None:
        svc = GiftAnalyticsService()
        with self.assertRaises(ValueError):
            svc.metrics_v1(metric="MARKET_INDEX", scope="VARIANT", variant_id="x|m|b|p")
        with self.assertRaises(ValueError):
            svc.metrics_v1(
                metric="FLOOR_HISTORY",
                scope="VARIANT",
                variant_id="x|m|b|p",
                from_ts="2026-02-27T00:00:00Z",
                to_ts="2026-02-26T00:00:00Z",
            )

    def test_metrics_v1_variant_whale_and_buy_wall(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime.now(timezone.utc)
        variant_id = "c|m|b|p"
        svc.variants[variant_id] = {
            "variant_id": variant_id,
            "base_id": "c",
            "metrics": {
                "floor_ton": 10.0,
                "median_ton": 12.0,
                "trades_count_24h": 20,
                "active_listings": 10,
            },
            "traits": {"model": {"name": "M"}, "background": {"name": "B"}, "pattern": {"name": "P"}},
            "updated_at": "2026-02-26T00:00:00Z",
        }
        svc.listing_state = {
            "l1": {"listing_id": "l1", "base_id": "c", "variant_id": variant_id, "status": "ACTIVE", "price_ton": 10.0},
            "l2": {"listing_id": "l2", "base_id": "c", "variant_id": variant_id, "status": "ACTIVE", "price_ton": 10.1},
        }
        svc.trade_events = [
            {"ts": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"), "variant_id": variant_id, "base_id": "c", "price_ton": 10.05},
            {"ts": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"), "variant_id": variant_id, "base_id": "c", "price_ton": 35.0},
            {"ts": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"), "variant_id": variant_id, "base_id": "c", "price_ton": 9.8},
            {"ts": (now - timedelta(hours=30)).isoformat().replace("+00:00", "Z"), "variant_id": variant_id, "base_id": "c", "price_ton": 8.0},
        ]

        whale = svc.metrics_v1(metric="WHALE_RATIO", scope="VARIANT", variant_id=variant_id)
        self.assertGreater(float((whale.get("points") or [{}])[0].get("value") or 0.0), 0.0)
        wall = svc.metrics_v1(metric="BUY_WALL_SCORE", scope="VARIANT", variant_id=variant_id)
        self.assertGreater(float((wall.get("points") or [{}])[0].get("value") or 0.0), 0.0)

    def test_metrics_v1_market_floor_history_and_depth(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime.now(timezone.utc)
        svc.variants = {
            "c1|m|b|p": {
                "variant_id": "c1|m|b|p",
                "base_id": "c1",
                "metrics": {"floor_ton": 10.0, "median_ton": 11.0, "trades_count_24h": 7, "active_listings": 3},
                "traits": {},
            },
            "c2|m|b|p": {
                "variant_id": "c2|m|b|p",
                "base_id": "c2",
                "metrics": {"floor_ton": 20.0, "median_ton": 21.0, "trades_count_24h": 5, "active_listings": 2},
                "traits": {},
            },
        }
        svc.variant_history = {
            "c1|m|b|p": [
                {"ts": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"), "floor_ton": 10.0, "active_listings": 3},
                {"ts": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"), "floor_ton": 11.0, "active_listings": 2},
            ],
            "c2|m|b|p": [
                {"ts": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"), "floor_ton": 20.0, "active_listings": 2},
                {"ts": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"), "floor_ton": 21.0, "active_listings": 1},
            ],
        }
        svc.listing_state = {
            "a": {"listing_id": "a", "base_id": "c1", "variant_id": "c1|m|b|p", "status": "ACTIVE", "price_ton": 15.6},
            "b": {"listing_id": "b", "base_id": "c2", "variant_id": "c2|m|b|p", "status": "ACTIVE", "price_ton": 16.4},
        }

        floor_history = svc.metrics_v1(metric="FLOOR_HISTORY", scope="MARKET")
        self.assertTrue(len(floor_history.get("points") or []) >= 1)
        depth = svc.metrics_v1(metric="MARKET_DEPTH", scope="MARKET")
        self.assertGreaterEqual(float((depth.get("points") or [{}])[0].get("value") or 0.0), 1.0)

    def test_metrics_v1_market_listing_velocity_uses_new_listings_window(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime.now(timezone.utc)
        variant_id = "z|m|b|p"
        svc.variants = {}
        svc.variant_history = {}
        svc.variants[variant_id] = {
            "variant_id": variant_id,
            "base_id": "z",
            "metrics": {"floor_ton": 5.0, "median_ton": 5.5, "trades_count_24h": 1, "active_listings": 999},
            "traits": {},
        }
        svc.variant_history[variant_id] = [
            {"ts": (now - timedelta(minutes=9)).isoformat().replace("+00:00", "Z"), "new_listings": 4},
            {"ts": (now - timedelta(minutes=6)).isoformat().replace("+00:00", "Z"), "new_listings": 3},
            {"ts": (now - timedelta(minutes=40)).isoformat().replace("+00:00", "Z"), "new_listings": 500},
        ]

        payload = svc.metrics_v1(metric="LISTING_VELOCITY", scope="MARKET")
        value = float((payload.get("points") or [{}])[0].get("value") or 0.0)
        self.assertEqual(value, 7.0)


if __name__ == "__main__":
    unittest.main()

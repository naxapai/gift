import unittest

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


if __name__ == "__main__":
    unittest.main()

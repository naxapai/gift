import os
import unittest
from unittest.mock import patch

from core import GiftAnalyticsService


class TestV1FormulaContract(unittest.TestCase):
    def test_default_engine_mode_is_tz(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            svc = GiftAnalyticsService()
            self.assertEqual(svc.v1_signal_engine_mode, "tz")

    def test_signals_v1_contract(self) -> None:
        svc = GiftAnalyticsService()
        payload = svc.signals_v1(limit=25, mode="tz")
        self.assertIn("engine_mode", payload)
        self.assertEqual(payload["engine_mode"], "tz")
        self.assertIn("items", payload)
        for row in payload["items"]:
            self.assertIn(row.get("type"), {"BUY", "SELL", "WATCH", "SKIP"})
            self.assertEqual(row.get("engine_mode"), "tz")
            self.assertIsNotNone(row.get("score100"))
            self.assertIsNotNone(row.get("conf_pct"))

    def test_v1_signal_type_matches_tz_action_hint(self) -> None:
        svc = GiftAnalyticsService()
        if not svc.variants:
            self.skipTest("No variants loaded")
        v = next(iter(svc.variants.values()))
        summary = svc._v1_variant_summary(v, mode="tz")  # noqa: SLF001
        sig = svc._v1_signal(v, mode="tz")  # noqa: SLF001
        self.assertEqual(sig.get("type"), summary.get("action_hint"))

    def test_tz_math_invariants(self) -> None:
        svc = GiftAnalyticsService()
        if not svc.variants:
            self.skipTest("No variants loaded")
        v = next(iter(svc.variants.values()))
        mm = svc._tz_signal_math(v)  # noqa: SLF001
        self.assertGreaterEqual(mm["score"], 0.0)
        self.assertLessEqual(mm["score"], 1.0)
        self.assertGreaterEqual(mm["confidence"], 0.0)
        self.assertLessEqual(mm["confidence"], 1.0)
        self.assertLessEqual(mm["forecast24h_pct_min"], mm["forecast24h_pct_max"])
        self.assertIn(mm["action_hint"], {"BUY", "SELL", "WATCH", "SKIP"})

    def test_variant_details_v1_uses_tz_strict_breakdown(self) -> None:
        svc = GiftAnalyticsService()
        if not svc.variants:
            self.skipTest("No variants loaded")
        variant_id = next(iter(svc.variants.keys()))
        payload = svc.variant_details_v1(variant_id, mode="tz_strict")
        self.assertIsNotNone(payload)
        breakdown = (payload or {}).get("breakdown") or {}
        self.assertEqual(str(breakdown.get("engine_mode") or ""), "tz_strict")
        self.assertIn(str(breakdown.get("action_hint") or ""), {"BUY", "SELL", "WATCH", "SKIP"})

    def test_variant_details_v1_normalizes_listing_statuses(self) -> None:
        svc = GiftAnalyticsService()
        if not svc.variants:
            self.skipTest("No variants loaded")
        variant_id = next(iter(svc.variants.keys()))
        svc.listing_state = {
            "lid-1": {
                "listing_id": "lid-1",
                "variant_id": variant_id,
                "price_ton": 1.23,
                "status": "LISTED",
                "last_seen": "2026-03-03T00:00:00Z",
            }
        }
        payload = svc.variant_details_v1(variant_id, mode="tz")
        self.assertIsNotNone(payload)
        listings = (payload or {}).get("listings") or []
        self.assertTrue(listings)
        self.assertIn(str(listings[0].get("status") or ""), {"ACTIVE", "SOLD", "CANCELED"})
        self.assertEqual(str(listings[0].get("status") or ""), "ACTIVE")


if __name__ == "__main__":
    unittest.main()

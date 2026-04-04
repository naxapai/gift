import os
import unittest
from unittest.mock import patch

from core import GiftAnalyticsService


class TestSignalsRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._old_ingest_auto_loop = os.environ.get("INGEST_AUTO_LOOP")
        os.environ["INGEST_AUTO_LOOP"] = "false"

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._old_ingest_auto_loop is None:
            os.environ.pop("INGEST_AUTO_LOOP", None)
        else:
            os.environ["INGEST_AUTO_LOOP"] = cls._old_ingest_auto_loop

    def test_signals_feed_prefers_actionable_listing_signal_over_skip_variant_signal(self) -> None:
        svc = GiftAnalyticsService()
        variant_id = str(next(iter((svc.variants or {}).keys()), ""))
        self.assertTrue(variant_id)
        variant = svc.variants.get(variant_id) or {}
        with patch.object(svc, "_v1_signal", return_value={
            "signal_id": "sig-skip",
            "variant_id": variant_id,
            "variant_label": "Variant Skip",
            "type": "SKIP",
            "action": "SKIP",
            "edgeRank100": 1.0,
            "score100": 2.0,
            "conf_pct": 3.0,
            "expected_profit_pct": 0.0,
            "market_regime": "RISK_OFF",
            "ts": "2026-04-04T08:00:00Z",
            "reasons": [],
            "risk_flags": [],
        }), patch.object(svc, "_listing_source_rows_v1", return_value=([
            {"variant_id": variant_id, "listing_key": "lk1", "unique_id": "u1", "source": "mtproto_api", "resell_amount_ton": 8.0, "attributes": {"model": variant.get("model") or "M", "background": variant.get("background") or "B", "pattern": variant.get("pattern") or "P"}, "collection": variant.get("collection") or "C", "title": variant.get("collection") or "C", "ts_detected": "2026-04-04T08:05:00Z", "first_seen_at": "2026-04-04T08:05:00Z", "last_seen_at": "2026-04-04T08:05:00Z", "preview_url": "https://example.com/gift.png"}
        ], {"source": "mtproto_api", "error": "", "updated_at": "2026-04-04T08:05:00Z"})), patch.object(svc, "_listing_pro_item_from_row", return_value={
            "variant_id": variant_id,
            "variant_label": "Variant Sell",
            "collection": variant.get("collection") or "C",
            "model": variant.get("model") or "M",
            "background": variant.get("background") or "B",
            "pattern": variant.get("pattern") or "P",
            "action": "SELL",
            "strength_tag": "NONE",
            "market_regime": "RISK_OFF",
            "market_regime_badge": "🔴",
            "edgeRank_profile": "RISK_OFF",
            "edgeRank_raw": 0.2,
            "edgeRank100": 22.0,
            "score100": 10.0,
            "conf_pct": 12.0,
            "price_ton": 8.0,
            "floor_ton": 8.0,
            "fair_ton": 7.5,
            "undervalue_pct": -6.0,
            "expected_profit_pct": 0.0,
            "target_ton": 7.5,
            "stop_ton": 8.5,
            "liquidity_score": 0.0,
            "absorption_30m": 0.0,
            "listing_pressure": 100.0,
            "volume_velocity": 0.0,
            "depth_5pct_count": 10,
            "depth_5pct_ton": 80.0,
            "decision_trace": {"resolved_action": "SELL"},
            "reasons": ["HIGH_PRESSURE"],
            "risk_flags": ["HIGH_PRESSURE"],
            "ts_detected": "2026-04-04T08:05:00Z",
            "ts_source": "2026-04-04T08:05:00Z",
            "preview_url": "https://example.com/gift.png",
            "source": "mtproto_api",
        }):
            payload = svc.signals_v1(limit=50, mode="tz")
        items = payload.get("items") or []
        row = next((x for x in items if str((x or {}).get("variant_id") or "") == variant_id), None)
        self.assertTrue(isinstance(row, dict))
        self.assertEqual(str((row or {}).get("type") or ""), "SELL")


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from unittest.mock import patch

from core import GiftAnalyticsService, RealtimeStore


class TestRealtimeStoreFallback(unittest.TestCase):
    def test_disabled_without_redis_url(self) -> None:
        with patch.dict(os.environ, {"REDIS_URL": ""}, clear=False):
            store = RealtimeStore()
            self.assertFalse(store.enabled)
            self.assertFalse(store.xadd_event("stream:signals", "signal.created", "v1", {"x": 1}))
            self.assertFalse(store.set_json("market:overview", {"ok": True}, 5))
            self.assertTrue(store.dedupe_signal("v1", "BUY", "sig1"))
            self.assertTrue(store.seen_listing("v1", "listing-1"))

    def test_signal_signature_is_stable(self) -> None:
        svc = GiftAnalyticsService()
        signal = {
            "type": "BUY",
            "variant_id": "collection|model|bg|pattern",
            "score100": 81.04,
            "price_ton": 7.123456,
            "fair_ton": 9.99999,
        }
        sig1 = svc._signal_signature(signal)
        sig2 = svc._signal_signature(dict(signal))
        self.assertEqual(sig1, sig2)
        self.assertEqual(len(sig1), 40)

    def test_publish_snapshot_noop_when_redis_disabled(self) -> None:
        with patch.dict(os.environ, {"REDIS_URL": ""}, clear=False):
            svc = GiftAnalyticsService()
            svc._publish_realtime_snapshot(mode="tz")
            self.assertFalse(svc.realtime_store.enabled)


if __name__ == "__main__":
    unittest.main()

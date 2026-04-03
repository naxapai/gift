import os
import unittest
from unittest.mock import patch

from core import GiftAnalyticsService


class TestTelegramRuntimeDelivery(unittest.TestCase):
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

    def test_publish_realtime_snapshot_enqueues_telegram_without_realtime_store(self) -> None:
        svc = GiftAnalyticsService()
        svc.realtime_store.enabled = False
        market_calls = []
        signal_calls = []
        with patch.object(svc.telegram_notifier, "enqueue_market_status", side_effect=lambda payload: market_calls.append(payload) or True), patch.object(svc.telegram_notifier, "enqueue_gift_signal", side_effect=lambda payload: signal_calls.append(payload) or True):
            svc._publish_realtime_snapshot(mode="tz")
        self.assertTrue(market_calls)
        self.assertTrue(signal_calls)


if __name__ == "__main__":
    unittest.main()

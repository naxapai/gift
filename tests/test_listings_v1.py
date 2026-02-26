import unittest
from datetime import datetime, timedelta, timezone

from core import GiftAnalyticsService


class TestListingsV1(unittest.TestCase):
    def test_listings_v1_contract(self) -> None:
        svc = GiftAnalyticsService()
        payload = svc.listings_v1(limit=10, only_new=False, new_window_sec=3600)
        self.assertIn("items", payload)
        self.assertIn("window_sec", payload)
        self.assertGreaterEqual(int(payload["window_sec"]), 30)
        for row in payload["items"]:
            self.assertIn("listing_key", row)
            self.assertIn("gift_id", row)
            self.assertIn("unique_id", row)
            self.assertIn("attributes", row)
            self.assertIn("model", row["attributes"])
            self.assertIn("background", row["attributes"])
            self.assertIn("pattern", row["attributes"])
            self.assertIn("first_seen_at", row)
            self.assertIn("last_seen_at", row)
            self.assertIn("is_new", row)

    def test_listings_summary_v1_contract(self) -> None:
        svc = GiftAnalyticsService()
        summary = svc.listings_summary_v1(new_window_sec=3600)
        self.assertIn("active_total", summary)
        self.assertIn("new_total", summary)
        self.assertIn("relisted_total", summary)
        self.assertIn("top_collections", summary)
        self.assertGreaterEqual(int(summary["active_total"]), 0)
        self.assertGreaterEqual(int(summary["new_total"]), 0)
        self.assertGreaterEqual(int(summary["relisted_total"]), 0)

    def test_listing_tracker_relist_detection(self) -> None:
        svc = GiftAnalyticsService()
        svc.listing_state = {
            "foo-1": {
                "listing_id": "foo-1",
                "variant_id": "foo|model_a|bg_a|pattern_a",
                "base_id": "foo",
                "price_ton": 10.0,
                "status": "ACTIVE",
                "sale_type": "FIXED",
                "preview_url": "",
                "last_seen": "2026-02-26T00:00:00Z",
            }
        }
        svc.listing_tracker_state = {}
        t1 = datetime(2026, 2, 26, 0, 0, 0, tzinfo=timezone.utc)
        svc._sync_listing_tracker_state(t1, persist=False)  # noqa: SLF001
        self.assertIn("foo:foo-1", svc.listing_tracker_state)
        self.assertEqual(int(svc.listing_tracker_state["foo:foo-1"].get("relist_count") or 0), 0)

        svc.listing_state = {}
        t2 = t1 + timedelta(seconds=20)
        svc._sync_listing_tracker_state(t2, persist=False)  # noqa: SLF001
        self.assertFalse(bool(svc.listing_tracker_state["foo:foo-1"].get("active")))

        svc.listing_state = {
            "foo-1": {
                "listing_id": "foo-1",
                "variant_id": "foo|model_a|bg_a|pattern_a",
                "base_id": "foo",
                "price_ton": 10.0,
                "status": "ACTIVE",
                "sale_type": "FIXED",
                "preview_url": "",
                "last_seen": "2026-02-26T00:01:00Z",
            }
        }
        t3 = t1 + timedelta(seconds=60)
        svc._sync_listing_tracker_state(t3, persist=False)  # noqa: SLF001
        self.assertTrue(bool(svc.listing_tracker_state["foo:foo-1"].get("active")))
        self.assertEqual(int(svc.listing_tracker_state["foo:foo-1"].get("relist_count") or 0), 1)
        self.assertIsNotNone(svc.listing_tracker_state["foo:foo-1"].get("last_relisted_at"))


if __name__ == "__main__":
    unittest.main()


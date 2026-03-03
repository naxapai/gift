import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

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
            self.assertIn("preview_url", row)
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

    def test_listing_source_status_contract(self) -> None:
        svc = GiftAnalyticsService()
        payload = svc.listing_source_status_v1()
        self.assertIn("primary_mode", payload)
        self.assertIn("url_configured", payload)
        self.assertIn("source", payload)
        self.assertIn("error", payload)
        self.assertIn("cache_ttl_sec", payload)
        self.assertIn("rows_count", payload)
        self.assertIn("degraded", payload)

    def test_listing_source_status_marks_empty_mtproto_as_degraded(self) -> None:
        svc = GiftAnalyticsService()
        with patch.object(
            svc,
            "_refresh_mt_listing_source",
            return_value=([], {"source": "mtproto_api", "error": "", "updated_at": "2026-02-26T00:00:00Z", "rows_count": 0}),
        ):
            status = svc.listing_source_status_v1()
        self.assertTrue(bool(status.get("degraded")))
        self.assertEqual(str(status.get("error") or ""), "mtproto_empty_payload")

    def test_listings_v1_fallback_when_mtproto_unavailable(self) -> None:
        with patch.dict("os.environ", {"LISTING_PRIMARY_SOURCE": "mtproto", "LISTING_MT_API_URL": "http://127.0.0.1:9/never"}, clear=False):
            svc = GiftAnalyticsService()
            payload = svc.listings_v1(limit=10, only_new=False, new_window_sec=3600)
            self.assertIn("items", payload)
            self.assertIn("source", payload)
            # Even in mtproto mode system must remain available via runtime fallback.
            self.assertTrue(str(payload.get("source") or "").strip() != "")

    def test_normalize_mt_listing_item_builds_variant_from_attrs(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime(2026, 2, 26, 0, 0, 0, tzinfo=timezone.utc)
        row = svc._normalize_mt_listing_item(  # noqa: SLF001
            {
                "gift_id": "5868595669182186720",
                "unique_id": "6001201753654035500",
                "variant_id": "5868595669182186720|unknown|unknown|unknown",
                "slug": "ValentineBox-11249",
                "title": "Valentine Box",
                "attributes": {"model": "Outline", "background": "French Blue", "pattern": "Dragonfly"},
                "resell_amount_stars_est": 1750,
            },
            now=now,
            window_sec=120,
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["gift_id"], "valentinebox")
        self.assertEqual(row["variant_id"], "valentinebox|outline|french_blue|dragonfly")
        self.assertEqual(row["collection_id"], "valentinebox")

    def test_normalize_mt_listing_item_resolves_noncanonical_variant_id(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime(2026, 2, 26, 0, 0, 0, tzinfo=timezone.utc)
        canonical_variant_id = "berryboxes|clarity|black|baphomet"
        svc.variants = {
            canonical_variant_id: {
                "variant_id": canonical_variant_id,
                "base_id": "berryboxes",
                "metrics": {},
                "traits": {},
            }
        }
        row = svc._normalize_mt_listing_item(  # noqa: SLF001
            {
                "gift_id": "5868595669182186720",
                "unique_id": "6001201753654035501",
                "variant_id": "5868595669182186720|Clarity|Black|Baphomet",
                "slug": "BerryBoxes-456",
                "title": "Berry Boxes",
                "attributes": {"model": "Clarity", "background": "Black", "pattern": "Baphomet"},
                "resell_amount_ton": 12.3,
            },
            now=now,
            window_sec=120,
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["gift_id"], "berryboxes")
        self.assertEqual(row["variant_id"], canonical_variant_id)

    def test_get_variant_fallback_from_listing_sources(self) -> None:
        svc = GiftAnalyticsService()
        svc.variants = {}
        variant_id = "berryboxes|clarity|black|baphomet"
        svc._listing_mt_runtime_cache = {
            "rows": [
                {
                    "variant_id": variant_id,
                    "gift_id": "berryboxes",
                    "collection_id": "berryboxes",
                    "unique_id": "7890",
                    "listing_id": "7890",
                    "listing_key": "berryboxes:7890",
                    "resell_amount_ton": 11.5,
                    "status": "ACTIVE",
                    "attributes": {"model": "Clarity", "background": "Black", "pattern": "Baphomet"},
                    "preview_url": "https://example.com/gift.png",
                    "last_seen_at": "2026-02-26T12:00:00Z",
                }
            ]
        }

        payload = svc.get_variant(variant_id)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload.get("variant_id"), variant_id)
        self.assertEqual(payload.get("base_id"), "berryboxes")
        self.assertEqual(float(payload.get("metrics", {}).get("floor_ton") or 0.0), 11.5)

    def test_listings_events_v1_contract(self) -> None:
        svc = GiftAnalyticsService()
        payload = svc.listings_events_v1(limit=5, new_window_sec=3600)
        self.assertIn("items", payload)
        self.assertIn("source", payload)
        self.assertIn("window_sec", payload)
        for ev in payload["items"]:
            self.assertIn("topic", ev)
            self.assertIn("ts", ev)
            self.assertIn("gift_id", ev)
            self.assertIn("unique_id", ev)
            self.assertIn("attributes", ev)

    def test_listings_signals_v1_contract(self) -> None:
        svc = GiftAnalyticsService()
        payload = svc.listings_signals_v1(limit=5, new_window_sec=3600, mode="tz")
        self.assertIn("items", payload)
        self.assertIn("engine_mode", payload)
        self.assertIn("source", payload)
        for row in payload["items"]:
            self.assertIn("signal_id", row)
            self.assertIn("type", row)
            self.assertIn("score100", row)
            self.assertIn("conf_pct", row)
            self.assertIn("preview_url", row)

    def test_listings_signals_v1_pagination_and_sort(self) -> None:
        svc = GiftAnalyticsService()
        payload = svc.listings_signals_v1(
            new_window_sec=3600,
            mode="tz",
            page=1,
            page_size=25,
            sort_by="score100",
            sort_dir="asc",
        )
        self.assertIn("total", payload)
        self.assertIn("page", payload)
        self.assertIn("page_size", payload)
        self.assertIn("total_pages", payload)
        self.assertIn("sort_by", payload)
        self.assertIn("sort_dir", payload)
        self.assertEqual(int(payload["page"]), 1)
        self.assertEqual(int(payload["page_size"]), 25)
        self.assertEqual(str(payload["sort_by"]), "score100")
        self.assertEqual(str(payload["sort_dir"]), "asc")
        self.assertLessEqual(len(payload.get("items", [])), 25)


if __name__ == "__main__":
    unittest.main()

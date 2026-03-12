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

    def test_listing_source_status_cached_mode_starts_async_warmup_on_cold_cache(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "LISTING_PRIMARY_SOURCE": "mtproto",
                "LISTING_MT_API_URL": "https://gift-listing-mtproto-bridge.onrender.com/api/listings/new",
            },
            clear=False,
        ):
            svc = GiftAnalyticsService()
        svc._listing_mt_runtime_cache = {
            "fetched_mono": 0.0,
            "rows": [],
            "source": "disabled",
            "error": "",
            "updated_at": None,
            "rows_count": 0,
            "url_used": "",
        }
        with patch.object(svc, "_start_listing_mt_warmup_async", return_value=True) as warmup_mock:
            status = svc.listing_source_status_v1(allow_remote=False)
        warmup_mock.assert_called_once()
        self.assertEqual(str(status.get("source") or ""), "mtproto_warmup")
        self.assertEqual(str(status.get("error") or ""), "mtproto_cache_cold_warmup_started")
        self.assertTrue(bool(status.get("warmup_started")))

    def test_listings_v1_fallback_when_mtproto_unavailable(self) -> None:
        with patch.dict("os.environ", {"LISTING_PRIMARY_SOURCE": "mtproto", "LISTING_MT_API_URL": "http://127.0.0.1:9/never"}, clear=False):
            svc = GiftAnalyticsService()
            payload = svc.listings_v1(limit=10, only_new=False, new_window_sec=3600)
            self.assertIn("items", payload)
            self.assertIn("source", payload)
            # Even in mtproto mode system must remain available via runtime fallback.
            self.assertTrue(str(payload.get("source") or "").strip() != "")

    def test_listings_summary_prefers_mtproto_snapshot_without_surface_error(self) -> None:
        with patch.dict("os.environ", {"LISTING_PRIMARY_SOURCE": "mtproto", "LISTING_MT_API_URL": "http://127.0.0.1:9/never"}, clear=False):
            svc = GiftAnalyticsService()
            now_iso = "2026-02-26T00:00:00Z"
            svc.mt_listings_snapshot = {
                "updated_at": now_iso,
                "items": [
                    {
                        "listing_key": "berryboxes:1",
                        "gift_id": "berryboxes",
                        "gift_type_id": "123",
                        "unique_id": "1",
                        "variant_id": "berryboxes|clarity|black|baphomet",
                        "num": 1,
                        "slug": "BerryBoxes-1",
                        "title": "Berry Boxes",
                        "collection": "Berry Boxes",
                        "collection_id": "berryboxes",
                        "resell_currency": "TON",
                        "currency_mode": "TON_ONLY",
                        "resell_amount_ton": 10.0,
                        "resell_amount_stars_est": 5000,
                        "attributes": {"model": "Clarity", "background": "Black", "pattern": "Baphomet"},
                        "status": "ACTIVE",
                        "sale_type": "FIXED",
                        "preview_url": "",
                        "ts_detected": now_iso,
                        "first_seen_at": now_iso,
                        "last_seen_at": now_iso,
                        "relist_count": 0,
                        "last_relisted_at": None,
                        "is_new": True,
                        "source": "mtproto_api",
                    }
                ],
            }
            summary = svc.listings_summary_v1(new_window_sec=3600)
            self.assertEqual(str(summary.get("source") or ""), "mtproto_snapshot")
            self.assertEqual(str(summary.get("source_error") or ""), "")
            self.assertGreaterEqual(int(summary.get("active_total") or 0), 1)

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

    def test_listings_new_v1_requires_mtproto_api_source(self) -> None:
        svc = GiftAnalyticsService()
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        rows = [
            {
                "listing_key": "x:1",
                "is_new": True,
                "ts_detected": now_iso,
                "collection": "X",
                "collection_id": "x",
                "attributes": {"model": "M", "background": "B", "pattern": "P"},
            }
        ]
        with patch.object(
            svc,
            "_listing_source_rows_v1",
            return_value=(rows, {"source": "mtproto_snapshot", "updated_at": now_iso, "error": ""}),
        ):
            payload = svc.listings_new_v1(
                limit=10,
                window="30m",
                edgeRank_min=0,
                conf_min=0,
                profit_min=0,
                liq_min=0,
                lp_max=999,
                ar_min=0,
                vv_min=0,
                only_pro_alerts=False,
            )
        self.assertEqual(payload.get("items"), [])
        self.assertIn("source_not_mtproto_api", str(payload.get("source_error") or ""))

    def test_listings_new_v1_filters_old_ts_detected_outside_strict_window(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime.now(timezone.utc)
        fresh_ts = (now - timedelta(seconds=20)).isoformat().replace("+00:00", "Z")
        old_ts = (now - timedelta(minutes=12)).isoformat().replace("+00:00", "Z")
        rows = [
            {
                "listing_key": "x:old",
                "is_new": True,
                "ts_detected": old_ts,
                "collection": "X",
                "collection_id": "x",
                "attributes": {"model": "M", "background": "B", "pattern": "P"},
            },
            {
                "listing_key": "x:fresh",
                "is_new": True,
                "ts_detected": fresh_ts,
                "collection": "X",
                "collection_id": "x",
                "attributes": {"model": "M", "background": "B", "pattern": "P"},
            },
        ]

        def _fake_item_from_row(*, row, **_kwargs):
            return {
                "listing_key": str(row.get("listing_key") or ""),
                "variant_id": "x|m|b|p",
                "variant_label": "X • M • B • P",
                "collection": "X",
                "model": "M",
                "background": "B",
                "pattern": "P",
                "edgeRank100": 70.0,
                "conf_pct": 60.0,
                "expected_profit_pct": 12.0,
                "undervalue_pct": 8.0,
                "liquidity_score": 45.0,
                "listing_pressure": 1.5,
                "absorption_30m": 1.2,
                "volume_velocity": 1.1,
                "market_regime": "MEAN_REVERT",
                "action": "BUY",
                "ts_detected": str(row.get("ts_detected") or ""),
            }

        with patch.object(
            svc,
            "_listing_source_rows_v1",
            return_value=(rows, {"source": "mtproto_api", "updated_at": now.isoformat().replace("+00:00", "Z"), "error": ""}),
        ), patch.object(svc, "_listing_pro_item_from_row", side_effect=_fake_item_from_row):
            payload = svc.listings_new_v1(
                limit=10,
                window="30m",
                edgeRank_min=0,
                conf_min=0,
                profit_min=0,
                liq_min=0,
                lp_max=999,
                ar_min=0,
                vv_min=0,
                only_pro_alerts=False,
            )
        keys = [str(x.get("listing_key") or "") for x in (payload.get("items") or [])]
        self.assertIn("x:fresh", keys)
        self.assertNotIn("x:old", keys)

    def test_listings_signals_variant_row_contains_action_and_edge_rank(self) -> None:
        svc = GiftAnalyticsService()
        variant_id = "artisanbrick|domino|marine_blue|bone"
        svc.variants = {
            variant_id: {
                "variant_id": variant_id,
                "base_id": "artisanbrick",
                "metrics": {
                    "floor_ton": 188.0,
                    "median_ton": 194.0,
                    "trades_count_24h": 160,
                    "trades_count_1h": 12,
                    "volume_ton_24h": 28000.0,
                    "active_listings": 34,
                    "liquidity_score_24h": 0.62,
                },
                "traits": {
                    "model": {"name": "Domino"},
                    "background": {"name": "Marine Blue"},
                    "pattern": {"name": "Bone"},
                },
            }
        }
        mocked_events = {
            "items": [
                {
                    "topic": "market.listing.new",
                    "ts": "2026-03-06T18:00:00Z",
                    "source": "fragment.verified_snapshot",
                    "gift_id": "artisanbrick",
                    "title": "Artisan Bricks",
                    "listing_key": "artisanbrick:1",
                    "variant_id": variant_id,
                    "preview_url": "",
                    "resell_currency": "TON",
                    "resell_amount": 188.0,
                    "attributes": {"model": "Domino", "background": "Marine Blue", "pattern": "Bone"},
                }
            ],
            "source": "fragment.verified_snapshot",
            "source_error": "",
        }
        with patch.object(svc, "listings_events_v1", return_value=mocked_events):
            payload = svc.listings_signals_v1(limit=10, mode="tz")
        rows = payload.get("items") or []
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIn(str(row.get("action") or ""), {"BUY", "SELL", "WATCH", "SKIP"})
        self.assertIsNotNone(row.get("edgeRank100"))
        self.assertIn("score_pct", row)
        self.assertIn("confidence_pct", row)
        self.assertEqual(row.get("score_pct"), row.get("score100"))
        self.assertEqual(row.get("confidence_pct"), row.get("conf_pct"))

    def test_listings_signals_v1_warmup_scores_are_dynamic(self) -> None:
        svc = GiftAnalyticsService()
        mocked_events = {
            "items": [
                {
                    "topic": "market.listing.new",
                    "ts": "2026-03-05T10:00:00Z",
                    "source": "mtproto_api",
                    "gift_id": "artisanbrick",
                    "title": "Artisan Bricks",
                    "listing_key": "artisanbrick:1",
                    "variant_id": "unknown|model|bg|pattern",
                    "preview_url": "",
                    "resell_currency": "TON",
                    "resell_amount": 150.0,
                    "attributes": {"model": "Unknown M", "background": "Unknown B", "pattern": "Unknown P"},
                },
                {
                    "topic": "market.listing.relisted",
                    "ts": "2026-03-05T10:01:00Z",
                    "source": "mtproto_api",
                    "gift_id": "artisanbrick",
                    "title": "Artisan Bricks",
                    "listing_key": "artisanbrick:2",
                    "variant_id": "unknown|model|bg|pattern",
                    "preview_url": "",
                    "resell_currency": "TON",
                    "resell_amount": 260.0,
                    "attributes": {"model": "Unknown M", "background": "Unknown B", "pattern": "Unknown P"},
                },
            ],
            "source": "mtproto_api",
            "source_error": "",
        }
        with patch.object(svc, "listings_events_v1", return_value=mocked_events):
            payload = svc.listings_signals_v1(limit=10, mode="tz")
        items = payload.get("items") or []
        self.assertEqual(len(items), 2)
        prices = [float((row or {}).get("price_ton") or 0.0) for row in items]
        self.assertTrue(all(p > 0 for p in prices))
        scores = {round(float((row or {}).get("score100") or 0.0), 3) for row in items}
        confs = {round(float((row or {}).get("conf_pct") or 0.0), 3) for row in items}
        self.assertGreater(len(scores), 1)
        self.assertGreater(len(confs), 1)

    def test_listings_signals_v1_deduplicates_same_event(self) -> None:
        svc = GiftAnalyticsService()
        event = {
            "topic": "market.listing.new",
            "ts": "2026-03-05T10:00:00Z",
            "source": "mtproto_api",
            "gift_id": "artisanbrick",
            "title": "Artisan Bricks",
            "listing_key": "artisanbrick:1",
            "variant_id": "unknown|model|bg|pattern",
            "preview_url": "",
            "resell_currency": "TON",
            "resell_amount": 150.0,
            "attributes": {"model": "Unknown M", "background": "Unknown B", "pattern": "Unknown P"},
        }
        with patch.object(
            svc,
            "listings_events_v1",
            return_value={"items": [event, dict(event)], "source": "mtproto_api", "source_error": ""},
        ):
            payload = svc.listings_signals_v1(limit=10, mode="tz")
        items = payload.get("items") or []
        self.assertEqual(len(items), 1)

    def test_market_status_v1_contract(self) -> None:
        svc = GiftAnalyticsService()
        payload = svc.market_status_v1(window="30m")
        self.assertIn("market_regime", payload)
        self.assertIn("market_regime_badge", payload)
        self.assertIn("flow", payload)
        self.assertIn("liquidity", payload)
        self.assertIn("supply", payload)
        self.assertIn("signals_1h", payload)

    def test_market_status_v1_uses_cache_without_remote_mt_refresh(self) -> None:
        svc = GiftAnalyticsService()
        with patch.object(svc, "_refresh_mt_listing_source", side_effect=RuntimeError("must_not_call")):
            payload = svc.market_status_v1(window="30m")
        self.assertIn("market_regime", payload)
        self.assertIn("flow", payload)

    def test_whale_ratio_fallback_uses_listing_prices_when_no_trades(self) -> None:
        svc = GiftAnalyticsService()
        svc.trade_events = []
        svc.listing_state = {
            "k1": {
                "listing_id": "k1",
                "variant_id": "demo|m1|b1|p1",
                "price_ton": 12.0,
                "status": "ACTIVE",
                "last_seen": "2026-03-05T10:00:00Z",
            },
            "k2": {
                "listing_id": "k2",
                "variant_id": "demo|m2|b2|p2",
                "price_ton": 420.0,
                "status": "ACTIVE",
                "last_seen": "2026-03-05T10:01:00Z",
            },
        }
        now = datetime(2026, 3, 5, 10, 2, 0, tzinfo=timezone.utc)
        ratio, impulse, threshold = svc._whale_ratio_and_impulse(now)  # noqa: SLF001
        self.assertGreater(threshold, 0.0)
        self.assertGreater(ratio, 0.0)
        self.assertLessEqual(ratio, 1.0)
        self.assertGreaterEqual(impulse, -1.0)
        self.assertLessEqual(impulse, 1.0)

    def test_listings_new_v1_contract(self) -> None:
        svc = GiftAnalyticsService()
        payload = svc.listings_new_v1(limit=10, window="30m", only_pro_alerts=False)
        self.assertIn("items", payload)
        self.assertIn("next_cursor", payload)
        self.assertIn("server_ts", payload)
        self.assertIn("source", payload)
        for row in payload["items"]:
            self.assertIn("listing_key", row)
            self.assertIn("variant_label", row)
            self.assertIn("edgeRank100", row)
            self.assertIn("score100", row)
            self.assertIn("conf_pct", row)
            self.assertIn("action", row)
            self.assertIn("ts_detected", row)

    def test_listings_race_v1_contract(self) -> None:
        svc = GiftAnalyticsService()
        payload = svc.listings_race_v1(limit=10, window="30m", direction="ANY", delta_pct_min=0.0, only_pro_alerts=False)
        self.assertIn("items", payload)
        self.assertIn("next_cursor", payload)
        self.assertIn("server_ts", payload)
        for row in payload["items"]:
            self.assertIn("listing_key", row)
            self.assertIn("collection", row)
            self.assertIn("model", row)
            self.assertIn("background", row)
            self.assertIn("pattern", row)
            self.assertIn("preview_url", row)
            self.assertTrue(str(row.get("variant_label") or ""))
            self.assertIn("price_ton", row)
            self.assertIn("delta_pct", row)
            self.assertIn("direction", row)
            self.assertIn("ts_detected", row)

    def test_listings_history_v1_requires_variant(self) -> None:
        svc = GiftAnalyticsService()
        with self.assertRaises(ValueError):
            svc.listings_history_v1(variant_id="", resolution="1m")

    def test_listings_history_v1_unknown_variant_returns_empty_series(self) -> None:
        svc = GiftAnalyticsService()
        payload = svc.listings_history_v1(variant_id="unknown|model|bg|pattern", resolution="1m")
        self.assertEqual(str(payload.get("variant_id") or ""), "unknown|model|bg|pattern")
        series = payload.get("series") or {}
        self.assertIn("floor", series)
        self.assertIn("active_lots", series)
        self.assertIn("sales_count", series)
        self.assertIn("volume_ton", series)
        self.assertTrue(isinstance(payload.get("events"), list))

    def test_variant_resolve_v1_falls_back_to_relaxed_optional_traits(self) -> None:
        svc = GiftAnalyticsService()
        variant_id = "demo|model_a|bg_a|pattern_a"
        svc.variants = {
            variant_id: {
                "variant_id": variant_id,
                "base_id": "demo",
                "metrics": {"active_listings": 3, "floor_ton": 12.5},
                "traits": {
                    "model": {"name": "Model A"},
                    "background": {"name": "BG A"},
                    "pattern": {"name": "Pattern A"},
                },
            }
        }
        resolved = svc.variant_resolve_v1(
            collection_id="demo",
            model="Model A",
            background="Different BG",
            pattern="Different Pattern",
            active_only=False,
        )
        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertEqual(str(resolved.get("variant_id") or ""), variant_id)
        self.assertEqual(str(resolved.get("matched_by") or ""), "traits_relaxed")

    def test_listings_new_v1_keyset_cursor(self) -> None:
        svc = GiftAnalyticsService()
        page1 = svc.listings_new_v1(limit=5, window="30m", only_pro_alerts=False)
        self.assertIn("next_cursor", page1)
        cursor = page1.get("next_cursor")
        if not cursor:
            self.skipTest("not enough rows for pagination")
        page2 = svc.listings_new_v1(limit=5, window="30m", only_pro_alerts=False, cursor=str(cursor))
        ids1 = {str(x.get("listing_key") or "") for x in (page1.get("items") or [])}
        ids2 = {str(x.get("listing_key") or "") for x in (page2.get("items") or [])}
        self.assertTrue(ids2.isdisjoint(ids1))

    def test_listings_race_v1_keyset_cursor(self) -> None:
        svc = GiftAnalyticsService()
        page1 = svc.listings_race_v1(limit=5, window="24h", direction="ANY", delta_pct_min=0.0, only_pro_alerts=False)
        self.assertIn("next_cursor", page1)
        cursor = page1.get("next_cursor")
        if not cursor:
            self.skipTest("not enough race rows for pagination")
        page2 = svc.listings_race_v1(
            limit=5,
            window="24h",
            direction="ANY",
            delta_pct_min=0.0,
            only_pro_alerts=False,
            cursor=str(cursor),
        )
        ids1 = {f"{x.get('listing_key')}|{x.get('ts_detected')}" for x in (page1.get("items") or [])}
        ids2 = {f"{x.get('listing_key')}|{x.get('ts_detected')}" for x in (page2.get("items") or [])}
        self.assertTrue(ids2.isdisjoint(ids1))

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

    def test_listing_decision_engine_strict_tz(self) -> None:
        svc = GiftAnalyticsService()
        svc.listing_decision_mode = "tz_strict"
        buy = svc._listing_action_from_profiles_v1(  # noqa: SLF001
            regime="RISK_ON",
            ctx={
                "edgeRank100": 62,
                "conf": 40,
                "expected_profit_pct": 11,
                "liquidity_norm": 0.42,
                "absorption": 1.1,
                "listing_pressure": 2.2,
            },
            fallback_action="WATCH",
        )
        self.assertEqual(buy, "BUY")
        sell = svc._listing_action_from_profiles_v1(  # noqa: SLF001
            regime="MEAN_REVERT",
            ctx={
                "edgeRank100": 40,
                "conf": 28,
                "expected_profit_pct": 2,
                "liquidity_norm": 0.2,
                "absorption": 0.7,
                "listing_pressure": 5.1,
            },
            fallback_action="WATCH",
        )
        self.assertEqual(sell, "SELL")
        watch = svc._listing_action_from_profiles_v1(  # noqa: SLF001
            regime="RISK_OFF",
            ctx={
                "edgeRank100": 57,
                "conf": 33,
                "expected_profit_pct": 7,
                "liquidity_norm": 0.33,
                "absorption": 0.88,
                "listing_pressure": 3.0,
            },
            fallback_action="SKIP",
        )
        self.assertEqual(watch, "WATCH")
        skip = svc._listing_action_from_profiles_v1(  # noqa: SLF001
            regime="PANIC",
            ctx={
                "edgeRank100": 47,
                "conf": 30,
                "expected_profit_pct": 4,
                "liquidity_norm": 0.2,
                "absorption": 0.9,
                "listing_pressure": 3.0,
            },
            fallback_action="BUY",
        )
        self.assertEqual(skip, "SKIP")

    def test_listings_race_v1_hides_low_priority_by_default(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        svc._listing_mt_runtime_cache["race_events"] = [  # noqa: SLF001
            {
                "listing_key": "a:1",
                "variant_id": "a|m|b|p",
                "variant_label": "A",
                "prev_price_ton": 10.0,
                "price_ton": 10.03,
                "delta_ton": 0.03,
                "delta_pct": 0.3,
                "direction": "UP",
                "low_priority": True,
                "ts_detected": now,
                "source": "mtproto_api",
            },
            {
                "listing_key": "a:2",
                "variant_id": "a|m|b|p",
                "variant_label": "A",
                "prev_price_ton": 10.0,
                "price_ton": 9.7,
                "delta_ton": -0.3,
                "delta_pct": -3.0,
                "direction": "DOWN",
                "low_priority": False,
                "ts_detected": now,
                "source": "mtproto_api",
            },
        ]
        payload_default = svc.listings_race_v1(limit=10, window="30m", direction="ANY", delta_pct_min=0.0, only_pro_alerts=False)
        keys_default = {str(x.get("listing_key") or "") for x in (payload_default.get("items") or [])}
        self.assertIn("a:2", keys_default)
        self.assertNotIn("a:1", keys_default)
        payload_full = svc.listings_race_v1(
            limit=10,
            window="30m",
            direction="ANY",
            delta_pct_min=0.0,
            only_pro_alerts=False,
            include_low_priority=True,
        )
        keys_full = {str(x.get("listing_key") or "") for x in (payload_full.get("items") or [])}
        self.assertIn("a:1", keys_full)
        self.assertIn("a:2", keys_full)

    def test_variant_resolve_v1_by_traits(self) -> None:
        svc = GiftAnalyticsService()
        rows = svc.variants_v1(limit=1).get("items") or []
        if not rows:
            self.skipTest("no variants")
        row = rows[0]
        resolved = svc.variant_resolve_v1(
            collection_id=str(row.get("collection_id") or ""),
            model=str(row.get("model") or ""),
            background=str(row.get("background") or ""),
            pattern=str(row.get("pattern") or ""),
            active_only=False,
        )
        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertTrue(str(resolved.get("variant_id") or ""))

    def test_mt_api_candidate_urls_autonormalize_status_to_listings(self) -> None:
        with patch.dict(
            "os.environ",
            {"LISTING_MT_API_URL": "https://gift-listing-mtproto-bridge.onrender.com/api/listing-bridge/status"},
            clear=False,
        ):
            svc = GiftAnalyticsService()
            urls = svc._mt_api_candidate_urls()  # noqa: SLF001
        self.assertIn("https://gift-listing-mtproto-bridge.onrender.com/api/listing-bridge/status", urls)
        self.assertIn("https://gift-listing-mtproto-bridge.onrender.com/api/listings/new", urls)

    def test_listing_source_status_includes_url_candidates(self) -> None:
        with patch.dict(
            "os.environ",
            {"LISTING_MT_API_URL": "https://gift-listing-mtproto-bridge.onrender.com"},
            clear=False,
        ):
            svc = GiftAnalyticsService()
            status = svc.listing_source_status_v1(allow_remote=False)
        self.assertIn("url_candidates", status)
        self.assertIsInstance(status.get("url_candidates"), list)
        self.assertTrue(any(str(x).endswith("/api/listings/new") for x in (status.get("url_candidates") or [])))

    def test_listings_new_v1_records_row_processing_errors(self) -> None:
        svc = GiftAnalyticsService()
        bad_row = {
            "listing_key": "bad:new:1",
            "variant_id": "bad|model|background|pattern",
            "collection_id": "bad",
            "collection": "Bad Collection",
            "attributes": {"model": "Model", "background": "Background", "pattern": "Pattern"},
            "source": "mtproto_api",
            "ts_detected": "2026-03-01T00:00:00Z",
        }
        with patch.object(
            svc,
            "_listing_source_rows_v1",
            return_value=([bad_row], {"source": "mtproto_api", "error": "", "updated_at": "2026-03-01T00:00:00Z"}),
        ), patch.object(
            svc,
            "_listing_new_realtime_source_ok",
            return_value=(True, ""),
        ), patch.object(
            svc,
            "_apply_listing_filters",
            return_value=[bad_row],
        ), patch.object(
            svc,
            "_listing_new_row_is_fresh",
            return_value=True,
        ), patch.object(
            svc,
            "_listing_pro_item_from_row",
            side_effect=RuntimeError("simulated_row_failure"),
        ):
            payload = svc.listings_new_v1(limit=10, window="30m", only_pro_alerts=False)
        self.assertEqual(int(payload.get("row_processing_errors") or 0), 1)
        self.assertTrue(bool(payload.get("row_processing_error_samples")))
        errors = svc.listing_runtime_errors_v1(limit=5, block="listings_new")
        self.assertGreaterEqual(int(errors.get("total") or 0), 1)
        top = (errors.get("items") or [])[0]
        self.assertEqual(str(top.get("block") or ""), "listings_new")
        self.assertEqual(str(top.get("stage") or ""), "row_processing")

    def test_listings_race_v1_records_mtproto_row_processing_errors(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        svc.listing_tracker_state = {}
        svc._listing_mt_runtime_cache["race_events"] = [  # noqa: SLF001
            {
                "listing_key": "bad:race:1",
                "variant_id": "bad|model|background|pattern",
                "direction": "UP",
                "delta_pct": "broken-number",
                "ts_detected": now,
                "source": "mtproto_api",
            }
        ]
        payload = svc.listings_race_v1(
            limit=10,
            window="30m",
            direction="ANY",
            delta_pct_min=0.0,
            only_pro_alerts=False,
            include_low_priority=True,
        )
        self.assertEqual(int(payload.get("row_processing_errors") or 0), 1)
        self.assertTrue(bool(payload.get("row_processing_error_samples")))
        errors = svc.listing_runtime_errors_v1(limit=5, block="listings_race")
        self.assertGreaterEqual(int(errors.get("total") or 0), 1)
        top = (errors.get("items") or [])[0]
        self.assertEqual(str(top.get("block") or ""), "listings_race")
        self.assertEqual(str(top.get("stage") or ""), "mtproto_row_processing")


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from core import GiftAnalyticsService


class TestV1StreamSchema(unittest.TestCase):
    def test_signal_created_event_schema_required_fields(self) -> None:
        svc = GiftAnalyticsService()
        signal = {
            "signal_id": "11111111-1111-1111-1111-111111111111",
            "ts": "2026-02-26T00:00:00Z",
            "type": "BUY",
            "variant_id": "c|m|b|p",
            "collection_id": "c",
            "collection": "Collection",
            "score100": 82.0,
            "conf_pct": 71.0,
            "reasons": ["r1"],
            "risk_flags": ["x1"],
        }
        ev = svc.build_signal_created_event_v1(signal)
        self.assertEqual(ev["type"], "signal.created")
        self.assertIn("ts", ev)
        self.assertIn("key", ev)
        self.assertIn("version", ev)
        self.assertIn("payload", ev)
        payload = ev["payload"]
        for key in [
            "signal_id",
            "ts",
            "type",
            "variant_id",
            "collection_id",
            "collection",
            "score100",
            "conf_pct",
            "reasons",
            "risk_flags",
        ]:
            self.assertIn(key, payload)

    def test_metric_updated_event_schema_required_fields(self) -> None:
        svc = GiftAnalyticsService()
        ev = svc.build_metric_updated_event_v1(
            metric="MARKET_INDEX",
            scope="MARKET",
            value=64.3,
            unit="SCORE_0_100",
            market=True,
        )
        self.assertEqual(ev["type"], "metric.updated")
        payload = ev["payload"]
        for key in ["metric", "scope", "market", "unit", "point", "stale"]:
            self.assertIn(key, payload)
        self.assertIn("ts", payload["point"])
        self.assertIn("value", payload["point"])

    def test_signal_created_event_schema_has_no_unexpected_fields(self) -> None:
        svc = GiftAnalyticsService()
        signal = {
            "signal_id": "11111111-1111-1111-1111-111111111111",
            "ts": "2026-02-26T00:00:00Z",
            "type": "BUY",
            "variant_id": "c|m|b|p",
            "collection_id": "c",
            "collection": "Collection",
            "model": "M",
            "background": "B",
            "pattern": "P",
            "score100": 82.0,
            "conf_pct": 71.0,
            "price_ton": 9.0,
            "floor_ton": 9.0,
            "fair_ton": 10.0,
            "undervalue": 0.1,
            "expected_profit_pct": 0.12,
            "forecast24h_pct_min": -5.0,
            "forecast24h_pct_max": 7.0,
            "active_lots": 22,
            "liquidity24h": 0.55,
            "reasons": ["r1"],
            "risk_flags": ["x1"],
        }
        ev = svc.build_signal_created_event_v1(signal)
        allowed_top = {"type", "ts", "key", "version", "trace_id", "payload"}
        self.assertEqual(set(ev.keys()), allowed_top)
        allowed_payload = {
            "signal_id",
            "ts",
            "type",
            "variant_id",
            "collection_id",
            "collection",
            "model",
            "background",
            "pattern",
            "score100",
            "conf_pct",
            "price_ton",
            "floor_ton",
            "fair_ton",
            "undervalue",
            "expected_profit_pct",
            "forecast24h_pct_min",
            "forecast24h_pct_max",
            "active_lots",
            "liquidity24h",
            "reasons",
            "risk_flags",
        }
        self.assertEqual(set(ev["payload"].keys()), allowed_payload)

    def test_metric_updated_event_schema_has_no_unexpected_fields(self) -> None:
        svc = GiftAnalyticsService()
        ev = svc.build_metric_updated_event_v1(
            metric="FLOOR_REALTIME",
            scope="VARIANT",
            value=10.5,
            unit="TON",
            market=False,
            collection_id="c",
            variant_id="c|m|b|p",
            extra={"source": "test"},
        )
        allowed_top = {"type", "ts", "key", "version", "trace_id", "payload"}
        self.assertEqual(set(ev.keys()), allowed_top)
        payload = ev["payload"]
        allowed_payload = {"metric", "scope", "market", "collection_id", "variant_id", "unit", "point", "stale"}
        self.assertEqual(set(payload.keys()), allowed_payload)
        self.assertEqual(set(payload["point"].keys()), {"ts", "value", "extra"})

    def test_stream_events_filtering(self) -> None:
        svc = GiftAnalyticsService()
        events = svc.stream_events_v1(types={"metric.updated"})
        self.assertTrue(len(events) > 0)
        self.assertTrue(all(str(e.get("type")) == "metric.updated" for e in events))

    def test_stream_events_rejects_unsupported_type(self) -> None:
        svc = GiftAnalyticsService()
        with self.assertRaises(ValueError):
            svc.stream_events_v1(types={"metric.updated", "nope.event"})

    def test_stream_events_v1_runtime_cache_reuses_payload(self) -> None:
        svc = GiftAnalyticsService()
        overview_calls = 0
        market_calls = 0

        def _overview(mode=None):
            nonlocal overview_calls
            overview_calls += 1
            return {
                "market_index": 50.0,
                "market_state": "флет",
                "stale": False,
                "top_signals": [],
                "provider_health": [{"provider": "telegram_api", "degraded": False, "err_pct": 0.0, "ts": "2026-02-26T00:00:00Z"}],
                "key_metrics": {"avg_liquidity24h": 0.4},
            }

        def _market():
            nonlocal market_calls
            market_calls += 1
            return {"floor_ton_median": 10.0, "floor_ton_min": 9.0, "active_listings": 100}

        svc.overview_v1 = _overview  # type: ignore[assignment]
        svc.market_overview = _market  # type: ignore[assignment]
        svc.collections_v1 = lambda limit=1: {"items": []}  # type: ignore[assignment]
        svc.variants_v1 = lambda limit=1, mode=None: {"items": []}  # type: ignore[assignment]
        svc.listings_events_v1 = lambda limit=1, include_relisted=True: {"items": []}  # type: ignore[assignment]
        svc.build_market_status_event_v1 = lambda **kwargs: {  # type: ignore[assignment]
            "type": "market.status",
            "ts": "2026-02-26T00:00:00Z",
            "key": "MARKET",
            "version": 1,
            "trace_id": "trace-market",
            "payload": {"window": "30m"},
        }

        first = svc.stream_events_v1(types={"metric.updated", "market.status", "listing.event"}, mode="tz")
        first_overview_calls = overview_calls
        first_market_calls = market_calls
        second = svc.stream_events_v1(types={"metric.updated", "market.status", "listing.event"}, mode="tz")
        self.assertGreaterEqual(first_overview_calls, 1)
        self.assertEqual(overview_calls, first_overview_calls)
        self.assertEqual(market_calls, first_market_calls)
        self.assertEqual(first, second)

    def test_stream_events_filtering_by_variant_id(self) -> None:
        svc = GiftAnalyticsService()
        variant_id = "c|m|b|p"
        collection_id = "c"

        def _overview(mode=None):
            return {
                "market_index": 50.0,
                "market_state": "флет",
                "stale": False,
                "top_signals": [
                    {
                        "signal_id": "s1",
                        "ts": "2026-02-26T00:00:00Z",
                        "type": "BUY",
                        "variant_id": variant_id,
                        "collection_id": collection_id,
                        "collection": "Collection",
                        "score100": 70.0,
                        "conf_pct": 60.0,
                        "reasons": [],
                        "risk_flags": [],
                    }
                ],
                "provider_health": [{"provider": "telegram_api", "degraded": False, "err_pct": 0.0, "ts": "2026-02-26T00:00:00Z"}],
                "key_metrics": {"avg_liquidity24h": 0.4},
            }

        svc.overview_v1 = _overview  # type: ignore[assignment]
        svc.market_overview = lambda: {"floor_ton_median": 10.0, "active_listings": 100}  # type: ignore[assignment]
        svc.collections_v1 = lambda limit=1: {"items": [{"collection_id": collection_id, "floor_ton": 8.0}]}  # type: ignore[assignment]
        svc.variants_v1 = lambda limit=1, mode=None: {"items": [{"variant_id": variant_id, "collection_id": collection_id, "score": 0.8}]}  # type: ignore[assignment]
        svc.listings_events_v1 = lambda limit=1, include_relisted=True: {"items": []}  # type: ignore[assignment]

        events = svc.stream_events_v1(variant_id=variant_id)
        self.assertTrue(len(events) > 0)
        for ev in events:
            payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
            self.assertEqual(str(payload.get("variant_id") or ev.get("key") or ""), variant_id)

    def test_stream_events_filtering_by_collection_id(self) -> None:
        svc = GiftAnalyticsService()
        variant_id = "c|m|b|p"
        collection_id = "c"

        def _overview(mode=None):
            return {
                "market_index": 50.0,
                "market_state": "флет",
                "stale": False,
                "top_signals": [
                    {
                        "signal_id": "s1",
                        "ts": "2026-02-26T00:00:00Z",
                        "type": "BUY",
                        "variant_id": variant_id,
                        "collection_id": collection_id,
                        "collection": "Collection",
                        "score100": 70.0,
                        "conf_pct": 60.0,
                        "reasons": [],
                        "risk_flags": [],
                    }
                ],
                "provider_health": [{"provider": "telegram_api", "degraded": False, "err_pct": 0.0, "ts": "2026-02-26T00:00:00Z"}],
                "key_metrics": {"avg_liquidity24h": 0.4},
            }

        svc.overview_v1 = _overview  # type: ignore[assignment]
        svc.market_overview = lambda: {"floor_ton_median": 10.0, "active_listings": 100}  # type: ignore[assignment]
        svc.collections_v1 = lambda limit=1: {"items": [{"collection_id": collection_id, "floor_ton": 8.0}]}  # type: ignore[assignment]
        svc.variants_v1 = lambda limit=1, mode=None: {"items": [{"variant_id": variant_id, "collection_id": collection_id, "score": 0.8}]}  # type: ignore[assignment]
        svc.listings_events_v1 = lambda limit=1, include_relisted=True: {"items": []}  # type: ignore[assignment]

        events = svc.stream_events_v1(collection_id=collection_id)
        self.assertTrue(len(events) > 0)
        for ev in events:
            payload = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
            self.assertEqual(str(payload.get("collection_id") or ev.get("key") or ""), collection_id)

    def test_listing_event_schema_required_fields(self) -> None:
        svc = GiftAnalyticsService()
        listing = {
            "topic": "market.listing.new",
            "ts": "2026-02-26T00:00:00Z",
            "listing_key": "k1",
            "variant_id": "c|m|b|p",
            "gift_id": "c",
            "title": "Collection",
            "resell_currency": "TON",
            "resell_amount": 10.0,
            "attributes": {"model": "M", "background": "B", "pattern": "P"},
        }
        ev = svc.build_listing_event_v1(listing)
        self.assertEqual(ev["type"], "listing.event")
        self.assertIn("payload", ev)
        payload = ev["payload"]
        for key in ["topic", "ts", "listing_key", "variant_id", "collection_id", "collection", "attributes"]:
            self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()

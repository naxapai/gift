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

    def test_metrics_v1_variant_trend_score_is_not_stub_zero(self) -> None:
        svc = GiftAnalyticsService()
        variant_id = "x|m|b|p"
        variant = {
            "variant_id": variant_id,
            "base_id": "x",
            "metrics": {
                "floor_ton": 5.0,
                "median_ton": 7.0,
                "trades_count_24h": 10,
                "active_listings": 15,
                "floor_change_pct_1h": 8.0,
            },
            "traits": {"model": {"name": "M"}, "background": {"name": "B"}, "pattern": {"name": "P"}},
            "updated_at": "2026-02-26T00:00:00Z",
        }
        svc.variants[variant_id] = variant
        payload = svc.metrics_v1(metric="TREND_SCORE", variant_id=variant_id, scope="VARIANT", mode="tz")
        value = float((payload.get("points") or [{}])[0].get("value") or 0.0)
        expected = float(svc._tz_signal_math(variant).get("trend_t") or 0.0)  # noqa: SLF001
        self.assertAlmostEqual(value, expected, places=6)
        self.assertGreater(value, 0.0)
        self.assertLessEqual(value, 1.0)

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
        with self.assertRaises(ValueError):
            svc.metrics_v1(metric="FLOOR_HISTORY", scope="MARKET", interval="30m")
        with self.assertRaises(ValueError):
            svc.metrics_v1(metric="FLOOR_HISTORY", scope="WORLD")

    def test_signals_and_variants_reject_invalid_enums(self) -> None:
        svc = GiftAnalyticsService()
        with self.assertRaises(ValueError):
            svc.signals_v1(signal_type="LONG")
        with self.assertRaises(ValueError):
            svc.signals_v1(min_score=1.5)
        with self.assertRaises(ValueError):
            svc.variants_v1(action="LONG")
        with self.assertRaises(ValueError):
            svc.variants_v1(sort="floor_asc")
        with self.assertRaises(ValueError):
            svc.variants_v1(min_score=-0.1)

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

    def test_metrics_v1_rarity_score_uses_trait_frequency_and_serial_bonus(self) -> None:
        svc = GiftAnalyticsService()
        target_variant_id = "c|m1|b1|p1"
        svc.variants = {
            target_variant_id: {
                "variant_id": target_variant_id,
                "base_id": "c",
                "metrics": {"floor_ton": 5.0, "median_ton": 6.0, "trades_count_24h": 4, "active_listings": 10, "serial_no": 1},
                "traits": {"model": {"id": "m1"}, "background": {"id": "b1"}, "pattern": {"id": "p1"}},
            },
            "c|m1|b2|p2": {
                "variant_id": "c|m1|b2|p2",
                "base_id": "c",
                "metrics": {"floor_ton": 5.1, "median_ton": 5.5, "trades_count_24h": 3, "active_listings": 5},
                "traits": {"model": {"id": "m1"}, "background": {"id": "b2"}, "pattern": {"id": "p2"}},
            },
            "c|m2|b1|p3": {
                "variant_id": "c|m2|b1|p3",
                "base_id": "c",
                "metrics": {"floor_ton": 5.2, "median_ton": 5.4, "trades_count_24h": 2, "active_listings": 4},
                "traits": {"model": {"id": "m2"}, "background": {"id": "b1"}, "pattern": {"id": "p3"}},
            },
            "c|m3|b3|p3": {
                "variant_id": "c|m3|b3|p3",
                "base_id": "c",
                "metrics": {"floor_ton": 5.3, "median_ton": 5.6, "trades_count_24h": 1, "active_listings": 3},
                "traits": {"model": {"id": "m3"}, "background": {"id": "b3"}, "pattern": {"id": "p3"}},
            },
        }
        payload = svc.metrics_v1(metric="RARITY_SCORE", scope="VARIANT", variant_id=target_variant_id)
        rarity = float((payload.get("points") or [{}])[0].get("value") or 0.0)
        # trait_score = mean([2/3, 2/3, 1]) = 0.777...
        # TZ-aligned rarity in SCORE_0_1 contract: serial_bonus(1)=0.8 + 0.2*trait_score
        self.assertAlmostEqual(rarity, 0.8 + (0.2 * 0.7777777778), places=4)

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

    def test_metrics_v1_floor_realtime_matches_tz_collection_and_market_formula(self) -> None:
        svc = GiftAnalyticsService()
        svc.variants = {
            "c1|m1|b|p": {
                "variant_id": "c1|m1|b|p",
                "base_id": "c1",
                "metrics": {"floor_ton": 1.0, "median_ton": 2.0, "trades_count_24h": 1, "active_listings": 1},
                "traits": {},
            },
            "c1|m2|b|p": {
                "variant_id": "c1|m2|b|p",
                "base_id": "c1",
                "metrics": {"floor_ton": 100.0, "median_ton": 100.0, "trades_count_24h": 1, "active_listings": 1},
                "traits": {},
            },
            "c2|m1|b|p": {
                "variant_id": "c2|m1|b|p",
                "base_id": "c2",
                "metrics": {"floor_ton": 50.0, "median_ton": 55.0, "trades_count_24h": 1, "active_listings": 1},
                "traits": {},
            },
        }

        c1_floor = svc.metrics_v1(metric="FLOOR_REALTIME", scope="COLLECTION", collection_id="c1")
        c1_value = float((c1_floor.get("points") or [{}])[0].get("value") or 0.0)
        self.assertEqual(c1_value, 1.0)

        market_floor = svc.metrics_v1(metric="FLOOR_REALTIME", scope="MARKET")
        market_value = float((market_floor.get("points") or [{}])[0].get("value") or 0.0)
        # Collection floors: c1=1.0, c2=50.0 => median = (1+50)/2 = 25.5
        self.assertAlmostEqual(market_value, 25.5, places=6)

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

    def test_metrics_v1_market_overview_metric_set_contract(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime.now(timezone.utc)
        variant_id = "mkt|m|b|p"
        svc.variants = {
            variant_id: {
                "variant_id": variant_id,
                "base_id": "mkt",
                "metrics": {"floor_ton": 10.0, "median_ton": 11.0, "trades_count_24h": 12, "active_listings": 8},
                "traits": {},
            }
        }
        svc.variant_history = {
            variant_id: [
                {"ts": (now - timedelta(minutes=8)).isoformat().replace("+00:00", "Z"), "floor_ton": 10.0, "active_listings": 8, "new_listings": 2},
                {"ts": (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"), "floor_ton": 10.5, "active_listings": 7, "new_listings": 1},
            ]
        }
        svc.trade_events = [
            {"ts": (now - timedelta(minutes=6)).isoformat().replace("+00:00", "Z"), "variant_id": variant_id, "base_id": "mkt", "price_ton": 10.1},
            {"ts": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"), "variant_id": variant_id, "base_id": "mkt", "price_ton": 11.0},
        ]
        svc.listing_state = {
            "mx1": {"listing_id": "mx1", "base_id": "mkt", "variant_id": variant_id, "status": "ACTIVE", "price_ton": 10.3}
        }
        metrics = [
            "FLOOR_REALTIME",
            "NEW_LISTINGS_REALTIME",
            "LISTING_VELOCITY",
            "LISTING_FEED",
            "VOLUME_VELOCITY",
            "VOLUME_CHART",
            "LIQUIDITY_SCORE",
            "LIQUIDITY_CHART",
            "LIQUIDITY_HEATMAP",
            "VELOCITY_SCORE",
            "ABSORPTION_RATE",
            "MARKET_DEPTH",
            "WHALE_RATIO",
            "WHALE_IMPULSE",
            "SUPPLY_CHART",
            "FLOOR_HISTORY",
            "VOLATILITY",
            "MARKET_INDEX",
            "TREND_SCORE",
        ]
        for metric in metrics:
            payload = svc.metrics_v1(metric=metric, scope="MARKET", limit=10)
            self.assertEqual(payload["metric"], metric)
            self.assertEqual(payload["scope"], "MARKET")
            self.assertTrue(isinstance(payload.get("points"), list))
            self.assertTrue(len(payload.get("points") or []) >= 1)

    def test_metrics_v1_variant_metric_set_contract(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime.now(timezone.utc)
        variant_id = "var|m|b|p"
        svc.variants = {
            variant_id: {
                "variant_id": variant_id,
                "base_id": "var",
                "metrics": {
                    "floor_ton": 8.0,
                    "median_ton": 9.0,
                    "trades_count_24h": 20,
                    "active_listings": 12,
                    "serial_no": 7,
                },
                "traits": {
                    "model": {"id": "m", "name": "M"},
                    "background": {"id": "b", "name": "B"},
                    "pattern": {"id": "p", "name": "P"},
                },
            }
        }
        svc.variant_history = {
            variant_id: [
                {"ts": (now - timedelta(minutes=25)).isoformat().replace("+00:00", "Z"), "floor_ton": 7.9, "active_listings": 13, "new_listings": 2},
                {"ts": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"), "floor_ton": 8.0, "active_listings": 12, "new_listings": 1},
            ]
        }
        svc.trade_events = [
            {"ts": (now - timedelta(minutes=20)).isoformat().replace("+00:00", "Z"), "variant_id": variant_id, "base_id": "var", "price_ton": 8.1},
            {"ts": (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"), "variant_id": variant_id, "base_id": "var", "price_ton": 8.2},
            {"ts": (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"), "variant_id": variant_id, "base_id": "var", "price_ton": 8.3},
        ]
        svc.listing_state = {
            "v1": {"listing_id": "v1", "base_id": "var", "variant_id": variant_id, "status": "ACTIVE", "price_ton": 8.0},
            "v2": {"listing_id": "v2", "base_id": "var", "variant_id": variant_id, "status": "ACTIVE", "price_ton": 8.1},
        }
        svc.listing_tracker_state = {
            "var:v1": {
                "listing_key": "var:v1",
                "variant_id": variant_id,
                "base_id": "var",
                "listing_id": "v1",
                "first_seen_at": (now - timedelta(minutes=4)).isoformat().replace("+00:00", "Z"),
                "last_seen_at": now.isoformat().replace("+00:00", "Z"),
                "last_relisted_at": "",
                "relist_count": 0,
                "last_price_ton": 8.0,
            }
        }
        variant_metrics = [
            "FLOOR_REALTIME",
            "NEW_LISTINGS_REALTIME",
            "LISTING_VELOCITY",
            "LISTING_PRESSURE",
            "LISTING_FEED",
            "FAIR_PRICE",
            "UNDERVALUE",
            "EXPECTED_PROFIT",
            "LIQUIDITY_SCORE",
            "LIQUIDITY_HEATMAP",
            "LIQUIDITY_CHART",
            "VOLUME_VELOCITY",
            "VOLUME_CHART",
            "ABSORPTION_RATE",
            "MARKET_DEPTH",
            "WHALE_RATIO",
            "WHALE_IMPULSE",
            "BUY_WALL_SCORE",
            "FLOOR_HISTORY",
            "VOLATILITY",
            "RARITY_SCORE",
            "SUPPLY_CHART",
            "EDGE_SCORE",
            "BUY_SCORE",
            "SELL_SCORE",
        ]
        for metric in variant_metrics:
            payload = svc.metrics_v1(metric=metric, scope="VARIANT", variant_id=variant_id, limit=10)
            self.assertEqual(payload["metric"], metric)
            self.assertEqual(payload["scope"], "VARIANT")
            self.assertEqual(payload["variant_id"], variant_id)
            self.assertTrue(isinstance(payload.get("points"), list))
            self.assertTrue(len(payload.get("points") or []) >= 1)

    def test_metrics_v1_market_liquidity_heatmap_contains_6h_bucket(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime.now(timezone.utc)
        variant_id = "liq|m|b|p"
        svc.variants = {
            variant_id: {
                "variant_id": variant_id,
                "base_id": "liq",
                "metrics": {"floor_ton": 10.0, "median_ton": 11.0, "trades_count_24h": 12, "active_listings": 5},
                "traits": {},
            }
        }
        svc.trade_events = [
            {"ts": (now - timedelta(minutes=20)).isoformat().replace("+00:00", "Z"), "variant_id": variant_id, "base_id": "liq", "price_ton": 10.2},
            {"ts": (now - timedelta(hours=3)).isoformat().replace("+00:00", "Z"), "variant_id": variant_id, "base_id": "liq", "price_ton": 10.4},
            {"ts": (now - timedelta(hours=10)).isoformat().replace("+00:00", "Z"), "variant_id": variant_id, "base_id": "liq", "price_ton": 10.8},
        ]
        payload = svc.metrics_v1(metric="LIQUIDITY_HEATMAP", scope="MARKET")
        points = payload.get("points") or []
        first = points[0] if points and isinstance(points[0], dict) else {}
        heat = ((first.get("extra") or {}).get("heat") or []) if isinstance(first.get("extra"), dict) else []
        buckets = {str(p.get("bucket")) for p in heat if isinstance(p, dict)}
        self.assertIn("1h", buckets)
        self.assertIn("6h", buckets)
        self.assertIn("24h", buckets)

    def test_metrics_v1_collection_feed_filter_and_variant_id_resolution(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime.now(timezone.utc)
        real_variant_id = "colx|m|b|p"
        listing_id = "12345"
        svc.variants = {
            real_variant_id: {
                "variant_id": real_variant_id,
                "base_id": "COLX",
                "metrics": {"floor_ton": 9.0, "median_ton": 10.0, "trades_count_24h": 5, "active_listings": 4},
                "traits": {},
            }
        }
        svc.listing_state = {
            listing_id: {"listing_id": listing_id, "base_id": "COLX", "variant_id": real_variant_id, "status": "ACTIVE", "price_ton": 9.2}
        }
        svc.listing_tracker_state = {
            "colx:12345": {
                "listing_key": "colx:12345",
                "variant_id": real_variant_id,
                "base_id": "COLX",
                "listing_id": listing_id,
                "first_seen_at": (now - timedelta(minutes=3)).isoformat().replace("+00:00", "Z"),
                "last_seen_at": now.isoformat().replace("+00:00", "Z"),
                "last_relisted_at": "",
                "relist_count": 0,
                "last_price_ton": 9.2,
            }
        }
        svc.bases = {"colx": type("B", (), {"name": "Col X"})()}
        feed = svc.metrics_v1(metric="LISTING_FEED", scope="COLLECTION", collection_id="COLX")
        self.assertEqual(feed["scope"], "COLLECTION")
        self.assertEqual(feed["collection_id"], "COLX")
        self.assertGreaterEqual(float((feed.get("points") or [{}])[0].get("value") or 0.0), 1.0)

        variant_metric = svc.metrics_v1(metric="FLOOR_REALTIME", scope="VARIANT", variant_id=listing_id)
        self.assertEqual(variant_metric["variant_id"], real_variant_id)


if __name__ == "__main__":
    unittest.main()

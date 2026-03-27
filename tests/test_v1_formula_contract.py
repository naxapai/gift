import os
import unittest
from datetime import datetime, timedelta, timezone
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
        self.assertIn("total_count", payload)
        self.assertTrue(isinstance(payload.get("total_count"), int))
        self.assertIn("items", payload)
        for row in payload["items"]:
            self.assertIn(row.get("type"), {"BUY", "SELL", "WATCH", "SKIP"})
            self.assertEqual(row.get("engine_mode"), "tz")
            self.assertIsNotNone(row.get("score100"))
            self.assertIsNotNone(row.get("conf_pct"))

    def test_v1_runtime_endpoints_do_not_crash_on_default_query(self) -> None:
        svc = GiftAnalyticsService()
        signals = svc.signals_v1(limit=8, mode="tz")
        self.assertTrue(isinstance(signals, dict))
        self.assertIn("items", signals)
        overview = svc.overview_v1(mode="tz")
        self.assertTrue(isinstance(overview, dict))
        self.assertIn("market_state", overview)
        metric = svc.metrics_v1(metric="MARKET_INDEX", scope="MARKET", mode="tz")
        self.assertTrue(isinstance(metric, dict))
        self.assertEqual(str(metric.get("metric") or ""), "MARKET_INDEX")

    def test_overview_v1_view_cache_reuses_payload(self) -> None:
        svc = GiftAnalyticsService()
        with patch.object(svc, "signals_v1", wraps=svc.signals_v1) as signals_fn:
            first = svc.overview_v1(mode="tz")
            first_call_count = signals_fn.call_count
            second = svc.overview_v1(mode="tz")
        self.assertGreaterEqual(first_call_count, 1)
        self.assertEqual(signals_fn.call_count, first_call_count)
        self.assertEqual(first, second)

    def test_signal_by_id_v1_runtime_cache_reuses_payload(self) -> None:
        svc = GiftAnalyticsService()
        signals = svc.signals_v1(limit=8, mode="tz").get("items") or []
        if not signals:
            self.skipTest("No signals rows")
        signal_id = str(signals[0].get("signal_id") or "")
        self.assertTrue(signal_id)
        with patch.object(svc, "signals_v1", wraps=svc.signals_v1) as signals_fn:
            first = svc.signal_by_id_v1(signal_id, mode="tz")
            first_call_count = signals_fn.call_count
            second = svc.signal_by_id_v1(signal_id, mode="tz")
        self.assertGreaterEqual(first_call_count, 1)
        self.assertEqual(signals_fn.call_count, first_call_count)
        self.assertEqual(first, second)

    def test_signals_v1_view_cache_reuses_payload(self) -> None:
        svc = GiftAnalyticsService()
        with patch.object(svc, "_v1_signal", wraps=svc._v1_signal) as signal_fn:  # noqa: SLF001
            first = svc.signals_v1(limit=12, mode="tz")
            first_call_count = signal_fn.call_count
            second = svc.signals_v1(limit=12, mode="tz")
        self.assertGreaterEqual(first_call_count, 1)
        self.assertEqual(signal_fn.call_count, first_call_count)
        self.assertEqual(first, second)

    def test_collections_v1_view_cache_reuses_payload(self) -> None:
        svc = GiftAnalyticsService()
        with patch.object(svc, "list_bases", wraps=svc.list_bases) as list_bases_fn:
            first = svc.collections_v1(limit=25)
            first_calls = list_bases_fn.call_count
            second = svc.collections_v1(limit=25)
        self.assertGreaterEqual(first_calls, 1)
        self.assertEqual(list_bases_fn.call_count, first_calls)
        self.assertEqual(first, second)

    def test_collection_details_v1_view_cache_reuses_payload(self) -> None:
        svc = GiftAnalyticsService()
        rows = svc.collections_v1(limit=1).get("items") or []
        if not rows:
            self.skipTest("No collections rows")
        collection_id = str(rows[0].get("collection_id") or "")
        self.assertTrue(collection_id)
        with patch.object(svc, "variants_v1", wraps=svc.variants_v1) as variants_fn:
            first = svc.collection_details_v1(collection_id)
            first_calls = variants_fn.call_count
            second = svc.collection_details_v1(collection_id)
        self.assertGreaterEqual(first_calls, 1)
        self.assertEqual(variants_fn.call_count, first_calls)
        self.assertEqual(first, second)

    def test_variants_v1_view_cache_reuses_payload(self) -> None:
        svc = GiftAnalyticsService()
        if not svc.variants:
            self.skipTest("No variants loaded")
        with patch.object(svc, "_v1_variant_summary", wraps=svc._v1_variant_summary) as summary_fn:  # noqa: SLF001
            first = svc.variants_v1(limit=25, mode="tz")
            first_calls = summary_fn.call_count
            second = svc.variants_v1(limit=25, mode="tz")
        self.assertGreaterEqual(first_calls, 1)
        self.assertEqual(summary_fn.call_count, first_calls)
        self.assertEqual(first, second)

    def test_variant_details_v1_view_cache_reuses_payload(self) -> None:
        svc = GiftAnalyticsService()
        if not svc.variants:
            self.skipTest("No variants loaded")
        variant_id = next(iter(svc.variants.keys()))
        with patch.object(svc, "_v1_variant_summary", wraps=svc._v1_variant_summary) as summary_fn:  # noqa: SLF001
            first = svc.variant_details_v1(variant_id, mode="tz")
            first_calls = summary_fn.call_count
            second = svc.variant_details_v1(variant_id, mode="tz")
        self.assertGreaterEqual(first_calls, 1)
        self.assertEqual(summary_fn.call_count, first_calls)
        self.assertEqual(first, second)

    def test_variant_resolve_v1_view_cache_reuses_payload(self) -> None:
        svc = GiftAnalyticsService()
        rows = svc.variants_v1(limit=1, mode="tz").get("items") or []
        if not rows:
            self.skipTest("No variants rows")
        row = rows[0]
        with patch.object(svc, "_v1_variant_summary", wraps=svc._v1_variant_summary) as summary_fn:  # noqa: SLF001
            first = svc.variant_resolve_v1(
                collection_id=str(row.get("collection_id") or ""),
                model=str(row.get("model") or ""),
                background=str(row.get("background") or ""),
                pattern=str(row.get("pattern") or ""),
                active_only=False,
                mode="tz",
            )
            first_calls = summary_fn.call_count
            second = svc.variant_resolve_v1(
                collection_id=str(row.get("collection_id") or ""),
                model=str(row.get("model") or ""),
                background=str(row.get("background") or ""),
                pattern=str(row.get("pattern") or ""),
                active_only=False,
                mode="tz",
            )
        self.assertGreaterEqual(first_calls, 1)
        self.assertEqual(summary_fn.call_count, first_calls)
        self.assertEqual(first, second)

    def test_market_regime_snapshot_v1_runtime_cache_reuses_payload(self) -> None:
        svc = GiftAnalyticsService()
        with patch.object(svc, "market_overview", wraps=svc.market_overview) as overview_fn:
            first = svc._market_regime_snapshot_v1()  # noqa: SLF001
            first_calls = overview_fn.call_count
            second = svc._market_regime_snapshot_v1()  # noqa: SLF001
        self.assertGreaterEqual(first_calls, 1)
        self.assertEqual(overview_fn.call_count, first_calls)
        self.assertEqual(first, second)

    def test_edge_rank_raw_v1_runtime_cache_reuses_payload(self) -> None:
        svc = GiftAnalyticsService()
        with patch.object(svc, "_rt_cache_get", wraps=svc._rt_cache_get) as cache_get:
            first = svc._edge_rank_raw_v1(  # noqa: SLF001
                regime="MEAN_REVERT",
                score100=67.2,
                conf_pct=42.5,
                expected_profit_ratio=0.089,
                liquidity_score_pct=55.0,
                absorption_30m=1.1,
                listing_pressure=2.5,
                depth_score=0.4,
                volume_velocity=1.0,
            )
            second = svc._edge_rank_raw_v1(  # noqa: SLF001
                regime="MEAN_REVERT",
                score100=67.2,
                conf_pct=42.5,
                expected_profit_ratio=0.089,
                liquidity_score_pct=55.0,
                absorption_30m=1.1,
                listing_pressure=2.5,
                depth_score=0.4,
                volume_velocity=1.0,
            )
        self.assertGreaterEqual(cache_get.call_count, 2)
        self.assertEqual(first, second)

    def test_signals_v1_extended_contract_fields_present(self) -> None:
        svc = GiftAnalyticsService()
        payload = svc.signals_v1(
            limit=25,
            mode="tz",
            edgeRank_min=0,
            conf_min=0,
            profit_min=0,
            liq_min=0,
            lp_max=999,
            ar_min=0,
            vv_min=0,
            only_pro_alerts=False,
        )
        rows = payload.get("items") or []
        self.assertTrue(isinstance(rows, list))
        if not rows:
            self.skipTest("No signals rows")
        row = rows[0]
        for key in [
            "action",
            "market_regime",
            "market_regime_badge",
            "edgeRank100",
            "edgeRank_raw",
            "edgeRank_profile",
            "expected_profit_pct",
            "undervalue_pct",
            "target_ton",
            "stop_ton",
            "liquidity_score",
            "absorption_30m",
            "listing_pressure",
            "volume_velocity",
            "depth_5pct_count",
            "depth_5pct_ton",
            "variant_label",
        ]:
            self.assertIn(key, row)

    def test_signals_v1_default_sort_edge_conf_ts_desc(self) -> None:
        svc = GiftAnalyticsService()
        rows = (svc.signals_v1(limit=50, mode="tz").get("items") or [])
        if len(rows) < 2:
            self.skipTest("Not enough rows to validate sorting")
        for prev, cur in zip(rows, rows[1:]):
            prev_edge = float(prev.get("edgeRank100") or 0.0)
            cur_edge = float(cur.get("edgeRank100") or 0.0)
            if abs(prev_edge - cur_edge) > 1e-9:
                self.assertGreaterEqual(prev_edge, cur_edge)
                continue
            prev_conf = float(prev.get("conf_pct") or 0.0)
            cur_conf = float(cur.get("conf_pct") or 0.0)
            if abs(prev_conf - cur_conf) > 1e-9:
                self.assertGreaterEqual(prev_conf, cur_conf)
                continue
            self.assertGreaterEqual(str(prev.get("ts") or ""), str(cur.get("ts") or ""))

    def test_v1_signal_type_matches_tz_action_hint(self) -> None:
        svc = GiftAnalyticsService()
        if not svc.variants:
            self.skipTest("No variants loaded")
        v = next(iter(svc.variants.values()))
        summary = svc._v1_variant_summary(v, mode="tz")  # noqa: SLF001
        sig = svc._v1_signal(v, mode="tz")  # noqa: SLF001
        self.assertEqual(sig.get("type"), summary.get("action_hint"))

    def test_v1_variant_summary_runtime_cache_reuses_payload(self) -> None:
        svc = GiftAnalyticsService()
        if not svc.variants:
            self.skipTest("No variants loaded")
        v = next(iter(svc.variants.values()))
        with patch.object(svc, "_rt_cache_get", wraps=svc._rt_cache_get) as cache_get:
            summary1 = svc._v1_variant_summary(v, mode="tz")  # noqa: SLF001
            summary2 = svc._v1_variant_summary(v, mode="tz")  # noqa: SLF001
        self.assertGreaterEqual(cache_get.call_count, 2)
        self.assertEqual(summary1, summary2)

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

    def test_tz_math_prefers_variant_floor_over_collection_floor(self) -> None:
        svc = GiftAnalyticsService()
        high_variant_id = "base_x|high|bg|p"
        low_variant_id = "base_x|low|bg|p"
        svc.variants = {
            low_variant_id: {
                "variant_id": low_variant_id,
                "base_id": "base_x",
                "metrics": {"floor_ton": 5.0, "median_ton": 5.0, "trades_count_24h": 10, "active_listings": 10},
                "traits": {"model": {"name": "Low"}, "background": {"name": "Bg"}, "pattern": {"name": "P"}},
            },
            high_variant_id: {
                "variant_id": high_variant_id,
                "base_id": "base_x",
                "metrics": {"floor_ton": 50.0, "median_ton": 50.0, "trades_count_24h": 10, "active_listings": 10},
                "traits": {"model": {"name": "High"}, "background": {"name": "Bg"}, "pattern": {"name": "P"}},
            },
        }
        mm = svc._tz_signal_math(svc.variants[high_variant_id])  # noqa: SLF001
        self.assertAlmostEqual(float(mm.get("floor_ton") or 0.0), 50.0, places=6)

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

    def test_signals_v1_server_side_filters_for_new_undervalue_and_risk(self) -> None:
        svc = GiftAnalyticsService()
        now = datetime.now(timezone.utc)
        fresh_ts = now.isoformat().replace("+00:00", "Z")
        old_ts = (now - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
        svc.variants = {
            "v|a|a|a": {"variant_id": "v|a|a|a"},
            "v|b|b|b": {"variant_id": "v|b|b|b"},
            "v|c|c|c": {"variant_id": "v|c|c|c"},
        }
        signals = {
            "v|a|a|a": {
                "signal_id": "11111111-1111-1111-1111-111111111111",
                "variant_id": "v|a|a|a",
                "ts": fresh_ts,
                "type": "BUY",
                "score100": 70,
                "conf_pct": 50,
                "market_regime": "MEAN_REVERT",
                "market_regime_badge": "🟡",
                "edgeRank100": 60,
                "expected_profit_pct": 10,
                "undervalue_pct": 15,
                "liquidity_score": 55,
                "absorption_30m": 1.1,
                "listing_pressure": 2.0,
                "volume_velocity": 1.1,
                "risk_flags": ["r1"],
            },
            "v|b|b|b": {
                "signal_id": "22222222-2222-2222-2222-222222222222",
                "variant_id": "v|b|b|b",
                "ts": old_ts,
                "type": "BUY",
                "score100": 71,
                "conf_pct": 51,
                "market_regime": "MEAN_REVERT",
                "market_regime_badge": "🟡",
                "edgeRank100": 62,
                "expected_profit_pct": 11,
                "undervalue_pct": 20,
                "liquidity_score": 56,
                "absorption_30m": 1.2,
                "listing_pressure": 2.1,
                "volume_velocity": 1.2,
                "risk_flags": [],
            },
            "v|c|c|c": {
                "signal_id": "33333333-3333-3333-3333-333333333333",
                "variant_id": "v|c|c|c",
                "ts": fresh_ts,
                "type": "BUY",
                "score100": 72,
                "conf_pct": 52,
                "market_regime": "MEAN_REVERT",
                "market_regime_badge": "🟡",
                "edgeRank100": 64,
                "expected_profit_pct": 12,
                "undervalue_pct": 30,
                "liquidity_score": 57,
                "absorption_30m": 1.3,
                "listing_pressure": 2.2,
                "volume_velocity": 1.3,
                "risk_flags": ["r1", "r2", "r3", "r4"],
            },
        }

        def _fake_signal(v, **_kwargs):
            return dict(signals[str(v.get("variant_id") or "")])

        with patch.object(svc, "_v1_signal", side_effect=_fake_signal), patch.object(svc, "_market_regime_snapshot_v1", return_value={}):
            out = svc.signals_v1(
                mode="tz",
                limit=50,
                only_new_1h=True,
                min_undervalue_pct=10,
                max_risk=0.5,
            )
        rows = out.get("items") or []
        self.assertEqual(len(rows), 1)
        self.assertEqual(str(rows[0].get("variant_id") or ""), "v|a|a|a")

    def test_signal_id_is_stable_for_same_variant_snapshot(self) -> None:
        svc = GiftAnalyticsService()
        if not svc.variants:
            self.skipTest("No variants loaded")
        variant = next(iter(svc.variants.values()))
        signal1 = svc._v1_signal(variant, mode="tz")  # noqa: SLF001
        signal2 = svc._v1_signal(variant, mode="tz")  # noqa: SLF001
        self.assertEqual(str(signal1.get("signal_id") or ""), str(signal2.get("signal_id") or ""))

    def test_v1_signal_runtime_cache_reuses_payload(self) -> None:
        svc = GiftAnalyticsService()
        if not svc.variants:
            self.skipTest("No variants loaded")
        variant = next(iter(svc.variants.values()))
        with patch.object(svc, "_rt_cache_get", wraps=svc._rt_cache_get) as cache_get:
            signal1 = svc._v1_signal(variant, mode="tz")  # noqa: SLF001
            signal2 = svc._v1_signal(variant, mode="tz")  # noqa: SLF001
        self.assertGreaterEqual(cache_get.call_count, 2)
        self.assertEqual(signal1, signal2)

    def test_signal_id_stable_when_updated_at_missing(self) -> None:
        svc = GiftAnalyticsService()
        if not svc.variants:
            self.skipTest("No variants loaded")
        variant = dict(next(iter(svc.variants.values())) or {})
        variant.pop("updated_at", None)
        state_prev = dict(svc.state or {})
        svc.state = dict(state_prev)
        svc.state.pop("updated_at", None)
        try:
            signal1 = svc._v1_signal(variant, mode="tz")  # noqa: SLF001
            signal2 = svc._v1_signal(variant, mode="tz")  # noqa: SLF001
            self.assertEqual(str(signal1.get("signal_id") or ""), str(signal2.get("signal_id") or ""))
            self.assertEqual(str(signal1.get("ts") or ""), str(signal2.get("ts") or ""))
        finally:
            svc.state = state_prev

    def test_tz_signal_keeps_sparse_estimates_with_sparse_quality_flag(self) -> None:
        svc = GiftAnalyticsService()
        variant = {
            "variant_id": "sparse_keep|m|b|p",
            "base_id": "sparse_keep",
            "metrics": {
                "floor_ton": 9.0,
                "active_listings": 2,
                "trades_count_24h": 0,
                "trades_count_1h": 0,
                "volume_ton_24h": 0.0,
            },
            "traits": {"model": {"name": "M"}, "background": {"name": "B"}, "pattern": {"name": "P"}},
        }
        with patch.object(svc, "get_base", return_value={"metrics": {"floor_ton": 9.0, "active_listings": 200}}):
            sig = svc._v1_signal(variant, mode="tz")  # noqa: SLF001
        self.assertEqual(str(sig.get("data_quality") or ""), "sparse")
        self.assertIsNotNone(sig.get("fair_ton"))
        self.assertIsNotNone(sig.get("undervalue_pct"))
        self.assertIsNotNone(sig.get("expected_profit_pct"))

    def test_sparse_no_flow_fair_is_anchored_to_floor_range(self) -> None:
        svc = GiftAnalyticsService()
        variant = {
            "variant_id": "sparse_anchor|m|b|p",
            "base_id": "sparse_anchor",
            "metrics": {
                "floor_ton": 100.0,
                "active_listings": 1,
                "trades_count_24h": 0,
                "trades_count_1h": 0,
                "volume_ton_24h": 0.0,
            },
            "traits": {"model": {"name": "M"}, "background": {"name": "B"}, "pattern": {"name": "P"}},
        }
        with patch.object(svc, "get_base", return_value={"metrics": {"floor_ton": 100.0, "active_listings": 500}}):
            mm = svc._tz_signal_math(variant)  # noqa: SLF001
        fair = float(mm.get("fair_ton") or 0.0)
        self.assertGreaterEqual(fair, 90.0)
        self.assertLessEqual(fair, 120.0)

    def test_signal_contains_score_and_confidence_aliases(self) -> None:
        svc = GiftAnalyticsService()
        if not svc.variants:
            self.skipTest("No variants loaded")
        variant = next(iter(svc.variants.values()))
        signal = svc._v1_signal(variant, mode="tz")  # noqa: SLF001
        self.assertIn("score_pct", signal)
        self.assertIn("confidence_pct", signal)
        self.assertEqual(signal.get("score_pct"), signal.get("score100"))
        self.assertEqual(signal.get("confidence_pct"), signal.get("conf_pct"))

    def test_sparse_no_flow_structural_case_produces_nonzero_undervalue(self) -> None:
        svc = GiftAnalyticsService()
        variant = {
            "variant_id": "sparse_buy|m|b|p",
            "base_id": "sparse_buy",
            "metrics": {
                "floor_ton": 10.0,
                "active_listings": 1,
                "trades_count_24h": 0,
                "trades_count_1h": 0,
                "volume_ton_24h": 0.0,
                "floor_change_pct_1h": 30.0,
                "floor_change_pct_12h": 20.0,
                "floor_change_pct_24h": 15.0,
            },
            "traits": {"model": {"name": "M"}, "background": {"name": "B"}, "pattern": {"name": "P"}},
        }
        with patch.object(svc, "get_base", return_value={"metrics": {"floor_ton": 10.0, "active_listings": 120}}):
            mm = svc._tz_signal_math(variant)  # noqa: SLF001
        self.assertGreater(abs(float(mm.get("undervalue") or 0.0)), 0.01)
        self.assertIn(str(mm.get("action_hint") or ""), {"BUY", "SELL", "WATCH", "SKIP"})

    def test_sparse_no_flow_can_emit_sell_for_heavy_supply_pressure(self) -> None:
        svc = GiftAnalyticsService()
        variant = {
            "variant_id": "sparse_sell|m|b|p",
            "base_id": "sparse_sell",
            "metrics": {
                "floor_ton": 10.0,
                "active_listings": 900,
                "trades_count_24h": 0,
                "trades_count_1h": 0,
                "volume_ton_24h": 0.0,
            },
            "traits": {"model": {"name": "M"}, "background": {"name": "B"}, "pattern": {"name": "P"}},
        }
        with patch.object(svc, "get_base", return_value={"metrics": {"floor_ton": 10.0, "active_listings": 900}}):
            mm = svc._tz_signal_math(variant)  # noqa: SLF001
        self.assertLess(float(mm.get("undervalue") or 0.0), -0.06)
        self.assertEqual(str(mm.get("action_hint") or ""), "SELL")

    def test_sparse_signal_fallback_metrics_are_variant_aware(self) -> None:
        svc = GiftAnalyticsService()
        variant_low = {
            "variant_id": "sparse_low|m|b|p",
            "base_id": "sparse_low",
            "metrics": {
                "floor_ton": 10.0,
                "active_listings": 1,
                "trades_count_24h": 0,
                "trades_count_1h": 0,
                "volume_ton_24h": 0.0,
            },
            "traits": {"model": {"name": "M"}, "background": {"name": "B"}, "pattern": {"name": "P"}},
        }
        variant_high = {
            "variant_id": "sparse_high|m|b|p",
            "base_id": "sparse_high",
            "metrics": {
                "floor_ton": 200.0,
                "active_listings": 220,
                "trades_count_24h": 0,
                "trades_count_1h": 0,
                "volume_ton_24h": 0.0,
            },
            "traits": {"model": {"name": "M"}, "background": {"name": "B"}, "pattern": {"name": "P"}},
        }
        with patch.object(svc, "get_base", return_value={"metrics": {"floor_ton": 25.0, "active_listings": 400}}):
            sig_low = svc._v1_signal(variant_low, mode="tz")  # noqa: SLF001
            sig_high = svc._v1_signal(variant_high, mode="tz")  # noqa: SLF001

        self.assertEqual(str(sig_low.get("data_quality") or ""), "sparse")
        self.assertEqual(str(sig_high.get("data_quality") or ""), "sparse")
        self.assertNotEqual(float(sig_low.get("liquidity_score") or 0.0), float(sig_high.get("liquidity_score") or 0.0))
        self.assertNotEqual(float(sig_low.get("listing_pressure") or 0.0), float(sig_high.get("listing_pressure") or 0.0))
        self.assertGreater(float(sig_low.get("absorption_30m") or 0.0), 0.0)
        self.assertGreater(float(sig_high.get("absorption_30m") or 0.0), 0.0)
        self.assertGreaterEqual(float(sig_low.get("volume_velocity") or 0.0), 0.0)
        self.assertGreaterEqual(float(sig_high.get("volume_velocity") or 0.0), 0.0)

    def test_sparse_no_flow_listing_pressure_is_not_flat_one(self) -> None:
        svc = GiftAnalyticsService()
        variant_a = {
            "variant_id": "sparse_lp_a|m|b|p",
            "base_id": "sparse_lp",
            "metrics": {
                "floor_ton": 15.0,
                "active_listings": 1,
                "trades_count_24h": 0,
                "trades_count_1h": 0,
                "volume_ton_24h": 0.0,
            },
            "traits": {"model": {"name": "M"}, "background": {"name": "B"}, "pattern": {"name": "P"}},
        }
        variant_b = {
            "variant_id": "sparse_lp_b|m|b|p",
            "base_id": "sparse_lp",
            "metrics": {
                "floor_ton": 1500.0,
                "active_listings": 1,
                "trades_count_24h": 0,
                "trades_count_1h": 0,
                "volume_ton_24h": 0.0,
            },
            "traits": {"model": {"name": "M"}, "background": {"name": "B"}, "pattern": {"name": "P"}},
        }
        with patch.object(svc, "get_base", return_value={"metrics": {"floor_ton": 120.0, "active_listings": 1200}}):
            sig_a = svc._v1_signal(variant_a, mode="tz")  # noqa: SLF001
            sig_b = svc._v1_signal(variant_b, mode="tz")  # noqa: SLF001
        lp_a = float(sig_a.get("listing_pressure") or 0.0)
        lp_b = float(sig_b.get("listing_pressure") or 0.0)
        self.assertNotAlmostEqual(lp_a, 1.0, places=6)
        self.assertNotAlmostEqual(lp_b, 1.0, places=6)
        self.assertNotAlmostEqual(lp_a, lp_b, places=6)

    def test_v1_signal_blocks_buy_when_expected_profit_non_positive(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            svc = GiftAnalyticsService()
        summary = {
            "variant_id": "x|m|b|p",
            "collection_id": "x",
            "collection_name": "X",
            "preview_url": "",
            "model": "M",
            "background": "B",
            "pattern": "P",
            "active_lots": 296,
            "price_ton": 46.0,
            "floor_ton": 46.0,
            "floor_type": "real",
            "median_ton": 30.0,
            "fair_ton": 24.3,
            "undervalue": -0.893,
            "trend_t": 0.1,
            "liq_score": 0.2,
            "risk_pen": 0.1,
            "score": 0.0,
            "score100": 0.0,
            "confidence": 0.63,
            "conf_pct": 63.0,
            "expected_profit_pct": -50.2,
            "action_hint": "BUY",
            "reasons": [],
            "risk_flags": [],
            "stale": False,
            "updated_at": "2026-03-12T00:00:00Z",
        }
        math_payload = {
            "forecast24h_pct_min": -43.0,
            "forecast24h_pct_max": -7.0,
            "liquidity24h": 0.55,
            "absorption_rate": 0.6,
            "listing_pressure": 3.0,
            "volume_velocity": 0.4,
            "active_lots": 296,
            "sales24h": 304,
            "sales30m": 6,
            "new_listings_30m": 12,
            "reasons": [],
            "risk_flags": [],
            "inputs_sparse": False,
            "action_hint": "BUY",
        }
        with (
            patch.object(svc, "_v1_variant_summary", return_value=summary),
            patch.object(svc, "_tz_signal_math", return_value=math_payload),
            patch.object(
                svc,
                "_market_regime_snapshot_v1",
                return_value={"market_regime": "MEAN_REVERT", "market_regime_badge": "🟡"},
            ),
        ):
            sig = svc._v1_signal({"variant_id": "x|m|b|p", "metrics": {}}, mode="tz")  # noqa: SLF001
        self.assertIn(str(sig.get("type") or ""), {"WATCH", "SELL", "SKIP"})
        self.assertNotEqual(str(sig.get("type") or ""), "BUY")


if __name__ == "__main__":
    unittest.main()

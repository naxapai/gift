import filecmp
import math
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from core import GiftAnalyticsService

ROOT = Path(__file__).resolve().parents[1]
CANON = ROOT / "config" / "contracts" / "catalog_v1"
RUNTIME = ROOT / "config" / "catalog"


class TestCatalogV1Contracts(unittest.TestCase):
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

    def test_canonical_files_present(self) -> None:
        required = [
            "bento_ui_catalog_blocks_v1.json",
            "catalog_page_TZ_PRO_RU_v1.txt",
            "catalog_page_pro_ui_mapping_v1.json",
            "event_schemas_catalog_v1.json",
            "openapi_patch_v1.8_catalog_v1.yaml",
            "redis_topics_structure_catalog_v1.json",
        ]
        for name in required:
            self.assertTrue((CANON / name).exists(), f"missing canonical catalog file: {name}")

    def test_runtime_configs_match_canonical(self) -> None:
        pairs = [
            ("catalog_page_pro_ui_mapping_v1.json", "catalog_page_pro_ui_mapping_v1.json"),
            ("bento_ui_catalog_blocks_v1.json", "bento_ui_catalog_blocks_v1.json"),
            ("event_schemas_catalog_v1.json", "event_schemas_catalog_v1.json"),
            ("redis_topics_structure_catalog_v1.json", "redis_topics_structure_catalog_v1.json"),
        ]
        for src_name, dst_name in pairs:
            src = CANON / src_name
            dst = RUNTIME / dst_name
            self.assertTrue(dst.exists(), f"runtime config is missing: {dst}")
            self.assertTrue(filecmp.cmp(src, dst, shallow=False), f"runtime config drift: {dst}")

    def test_catalog_feed_contract_smoke(self) -> None:
        svc = GiftAnalyticsService()
        payload = svc.catalog_feed_v1(limit=5)
        self.assertIn("items", payload)
        self.assertTrue(isinstance(payload.get("items"), list))
        if payload["items"]:
            row = payload["items"][0]
            for key in ["variant_id", "variant_label", "edgeRank100", "conf_pct", "market_regime", "action", "updated_at", "age_sec"]:
                self.assertIn(key, row)

    def test_catalog_variant_does_not_depend_on_feed_scan(self) -> None:
        svc = GiftAnalyticsService()
        variant_ids = list((svc.variants or {}).keys())
        self.assertTrue(len(variant_ids) > 0, "expected at least one variant in fixtures")
        target = str(variant_ids[0])
        with patch.object(svc, "catalog_feed_v1", side_effect=AssertionError("must not call catalog_feed_v1")):
            row = svc.catalog_variant_v1(target)
        self.assertEqual(str(row.get("variant_id") or ""), target)
        self.assertIn("floor_history", row)

    def test_catalog_fixed_edge_formula_matches_tz(self) -> None:
        svc = GiftAnalyticsService()
        signal = {
            "expected_profit_pct": 12.0,
            "score100": 80.0,
            "liquidity_score": 40.0,
            "absorption_30m": 1.2,
            "depth_score": 0.5,
            "listing_pressure": 2.0,
            "conf_pct": 50.0,
        }
        edge_raw, edge100, norms = svc._screeners_fixed_edge(signal)  # noqa: SLF001
        expected_raw = (0.35 * (0.12 / 0.30)) + (0.25 * 0.80) + (0.15 * 0.40) + (0.10 * (1.2 / 2.0)) + (0.10 * 0.5) - (0.15 * (2.0 / 8.0))
        expected_edge = max(0.0, min(expected_raw, 1.0)) * 0.5
        self.assertTrue(math.isclose(edge_raw, round(expected_raw, 6), rel_tol=0.0, abs_tol=1e-9))
        self.assertTrue(math.isclose(edge100, round(expected_edge * 100.0, 1), rel_tol=0.0, abs_tol=1e-9))
        self.assertEqual(norms, {
            "C": 0.5,
            "EP": 0.4,
            "S": 0.8,
            "L": 0.4,
            "AR": 0.6,
            "LP": 0.25,
            "D": 0.5,
        })

    def test_catalog_decision_engine_changes_by_regime_thresholds(self) -> None:
        svc = GiftAnalyticsService()
        svc.variants["catalog-threshold-test"] = {"metrics": {"trades_count_24h": 5}}
        signal = {
            "variant_id": "catalog-threshold-test",
            "expected_profit_pct": 7.0,
            "score100": 72.0,
            "liquidity_score": 45.0,
            "absorption_30m": 1.1,
            "depth_score": 0.6,
            "listing_pressure": 2.2,
            "conf_pct": 45.0,
            "undervalue_pct": 8.0,
        }
        action_risk_on, trace_risk_on = svc._screeners_action_v1(signal, 60.0, svc._catalog_thresholds_for_regime("RISK_ON"))  # noqa: SLF001
        action_panic, trace_panic = svc._screeners_action_v1(signal, 60.0, svc._catalog_thresholds_for_regime("PANIC"))  # noqa: SLF001
        self.assertEqual(action_risk_on, "BUY")
        self.assertEqual(trace_risk_on.get("missing_for_buy"), [])
        self.assertEqual(action_panic, "WATCH")
        self.assertEqual(trace_panic.get("missing_for_buy"), ["edgeRank100>=", "expected_profit_pct>="])

    def test_catalog_presets_follow_tz_semantics(self) -> None:
        svc = GiftAnalyticsService()
        row = {
            "action": "BUY",
            "edgeRank100": 61.0,
            "conf_pct": 37.0,
            "expected_profit_pct": 8.5,
            "liquidity_score": 54.0,
            "depth_score": 0.55,
            "listing_pressure": 2.4,
            "market_regime": "RISK_OFF",
            "undervalue_pct": 9.0,
        }
        self.assertTrue(svc._catalog_matches_preset(row, "TOP_BUY"))  # noqa: SLF001
        self.assertTrue(svc._catalog_matches_preset(row, "RISK_OFF_SAFE"))  # noqa: SLF001
        self.assertTrue(svc._catalog_matches_preset(row, "UNDERVALUED"))  # noqa: SLF001
        self.assertFalse(svc._catalog_matches_preset(row, "SELL_PRESSURE"))  # noqa: SLF001

    def test_catalog_stream_events_emit_rows_after_data_version_change(self) -> None:
        svc = GiftAnalyticsService()
        row = {
            "variant_id": "catalog-stream-1",
            "updated_at": "2026-03-05T12:00:00Z",
            "floor_ton": 10.0,
            "fair_ton": 12.0,
            "edgeRank100": 66.0,
            "conf_pct": 41.0,
            "action": "BUY",
            "market_regime": "MEAN_REVERT",
        }
        svc._data_version = 100  # noqa: SLF001
        with patch.object(svc, "catalog_feed_v1", return_value={"items": [row]}):
            first = svc.catalog_stream_events_v1(limit=5)
        self.assertIn("items", first)
        self.assertTrue(isinstance(first.get("items"), list))
        self.assertTrue(first["items"])
        row_payload = (first["items"][0] or {}).get("payload") or {}
        self.assertEqual(str(row_payload.get("variant_id") or ""), "catalog-stream-1")

        with patch.object(svc, "catalog_feed_v1", return_value={"items": [row]}):
            second = svc.catalog_stream_events_v1(limit=5)
        self.assertEqual(second.get("items"), first.get("items"))

    def test_market_and_base_aggregations_tolerate_missing_floor_ton(self) -> None:
        svc = GiftAnalyticsService()
        sample = next(iter((svc.variants or {}).values()), None)
        self.assertTrue(isinstance(sample, dict), "expected fixture variant")
        broken = dict(sample or {})
        broken_metrics = dict((broken.get("metrics") or {}))
        broken_metrics.pop("floor_ton", None)
        broken["metrics"] = broken_metrics
        broken["variant_id"] = "broken-floor-variant"
        variants = dict(svc.variants or {})
        variants["broken-floor-variant"] = broken
        svc.variants = variants
        market = svc.market_overview()
        bases = svc.list_bases()
        self.assertIn("variant_count", market)
        self.assertTrue(isinstance(bases, list))


if __name__ == "__main__":
    unittest.main()

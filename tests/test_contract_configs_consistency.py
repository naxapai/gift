import json
import unittest
from pathlib import Path

from core import METRIC_ALLOWED_SCOPES, METRIC_UNITS


ROOT_DIR = Path(__file__).resolve().parents[1]
CANONICAL_DIR = ROOT_DIR / "config" / "contracts"
RUNTIME_SCHEMA_DIR = ROOT_DIR / "tests" / "schemas"
LISTING_DIR = ROOT_DIR / "config" / "listing"
DOCS_DIR = ROOT_DIR / "docs"


class TestContractConfigsConsistency(unittest.TestCase):
    def test_spec_map_exists_and_has_core_references(self) -> None:
        spec_map = DOCS_DIR / "spec-map.md"
        self.assertTrue(spec_map.exists(), "docs/spec-map.md must exist")
        text = spec_map.read_text(encoding="utf-8")
        self.assertIn("server.py", text)
        self.assertIn("core.py", text)
        self.assertIn("frontend-react/src/lib/api.ts", text)
        self.assertIn("tests/test_v1_http_contract.py", text)

    def test_canonical_files_exist(self) -> None:
        required = [
            CANONICAL_DIR / "schema_signal.created.json",
            CANONICAL_DIR / "schema_metric.updated.json",
            CANONICAL_DIR / "frontend_metrics_mapping.json",
            CANONICAL_DIR / "bento_ui_blocks.json",
            LISTING_DIR / "signal_profiles_by_regime.json",
        ]
        for path in required:
            self.assertTrue(path.exists(), f"missing canonical contract file: {path}")

    def test_canonical_signal_metric_schemas_match_runtime_schemas(self) -> None:
        canonical_signal = json.loads((CANONICAL_DIR / "schema_signal.created.json").read_text(encoding="utf-8"))
        canonical_metric = json.loads((CANONICAL_DIR / "schema_metric.updated.json").read_text(encoding="utf-8"))
        runtime_signal = json.loads((RUNTIME_SCHEMA_DIR / "signal.created.schema.json").read_text(encoding="utf-8"))
        runtime_metric = json.loads((RUNTIME_SCHEMA_DIR / "metric.updated.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(canonical_signal, runtime_signal)
        self.assertEqual(canonical_metric, runtime_metric)

    def test_frontend_metrics_mapping_matches_backend_catalog(self) -> None:
        mapping = json.loads((CANONICAL_DIR / "frontend_metrics_mapping.json").read_text(encoding="utf-8"))
        overview_metrics = {str(x).strip().upper() for x in (mapping.get("overview_metrics") or []) if str(x).strip()}
        variant_metrics = {str(x).strip().upper() for x in (mapping.get("variant_metrics") or []) if str(x).strip()}
        mapped_metrics = overview_metrics | variant_metrics
        backend_metrics = set(METRIC_UNITS.keys())
        self.assertEqual(mapped_metrics, backend_metrics)

    def test_frontend_metrics_mapping_scope_compatibility(self) -> None:
        mapping = json.loads((CANONICAL_DIR / "frontend_metrics_mapping.json").read_text(encoding="utf-8"))
        overview_metrics = {str(x).strip().upper() for x in (mapping.get("overview_metrics") or []) if str(x).strip()}
        variant_metrics = {str(x).strip().upper() for x in (mapping.get("variant_metrics") or []) if str(x).strip()}
        for metric in sorted(overview_metrics):
            allowed = METRIC_ALLOWED_SCOPES.get(metric, set())
            self.assertIn("MARKET", allowed, f"metric must support MARKET scope: {metric}")
        for metric in sorted(variant_metrics):
            allowed = METRIC_ALLOWED_SCOPES.get(metric, set())
            self.assertIn("VARIANT", allowed, f"metric must support VARIANT scope: {metric}")

    def test_bento_metrics_known_and_scope_compatible(self) -> None:
        mapping = json.loads((CANONICAL_DIR / "frontend_metrics_mapping.json").read_text(encoding="utf-8"))
        known_metrics = {
            str(x).strip().upper()
            for x in (mapping.get("overview_metrics") or []) + (mapping.get("variant_metrics") or [])
            if str(x).strip()
        }
        bento = json.loads((CANONICAL_DIR / "bento_ui_blocks.json").read_text(encoding="utf-8"))
        pages = bento.get("pages") if isinstance(bento, dict) else {}
        for page_name, page_payload in (pages or {}).items():
            if not isinstance(page_payload, dict):
                continue
            page_scope = str(page_payload.get("scope") or "").strip().upper()
            rows = ((page_payload.get("layout") or {}).get("rows") or []) if isinstance(page_payload.get("layout"), dict) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for block in (row.get("blocks") or []):
                    if not isinstance(block, dict):
                        continue
                    for metric_raw in (block.get("metrics") or []):
                        metric = str(metric_raw or "").strip().upper()
                        if not metric:
                            continue
                        self.assertIn(metric, known_metrics, f"bento metric not found in frontend mapping: {metric}")
                        allowed = METRIC_ALLOWED_SCOPES.get(metric, set())
                        self.assertIn(
                            page_scope,
                            allowed,
                            f"bento metric scope mismatch: page={page_name} scope={page_scope} metric={metric} allowed={sorted(allowed)}",
                        )

    def test_listing_ui_presets_contract(self) -> None:
        payload = json.loads((ROOT_DIR / "config" / "signals" / "signals_page_pro_ui_mapping.json").read_text(encoding="utf-8"))
        presets_raw = payload.get("presets") if isinstance(payload, dict) else None
        self.assertTrue(isinstance(presets_raw, list), "signals presets must be list")
        presets = {
            str(item.get("id") or ""): item
            for item in presets_raw
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
        for key in ["pro_alerts", "top_buy", "defense_sell", "panic_hunt"]:
            self.assertIn(key, presets, f"missing signals ui preset: {key}")

        for key, item in presets.items():
            self.assertTrue(isinstance(item, dict), f"preset {key} must be object")
            edge = float(item.get("edgeRankMin", 0))
            conf = float(item.get("confMin", 0))
            profit = float(item.get("profitMin", 0))
            liq = float(item.get("liqMin", 0))
            lp_max = float(item.get("lpMax", 0))
            ar_min = float(item.get("arMin", 0))
            vv_min = float(item.get("vvMin", 0))
            race_delta = float(item.get("raceDeltaMin", 0))
            self.assertGreaterEqual(edge, 0.0)
            self.assertLessEqual(edge, 100.0)
            self.assertGreaterEqual(conf, 0.0)
            self.assertLessEqual(conf, 100.0)
            self.assertGreaterEqual(profit, 0.0)
            self.assertGreaterEqual(liq, 0.0)
            self.assertLessEqual(liq, 100.0)
            self.assertGreaterEqual(lp_max, 0.0)
            self.assertGreaterEqual(ar_min, 0.0)
            self.assertGreaterEqual(vv_min, 0.0)
            self.assertGreaterEqual(race_delta, 0.0)

    def test_listing_bento_has_signals_table_block(self) -> None:
        listing_bento_path = LISTING_DIR / "bento_ui_blocks_new_listings.json"
        self.assertTrue(listing_bento_path.exists(), "missing listing bento config")
        payload = json.loads(listing_bento_path.read_text(encoding="utf-8"))
        blocks = payload.get("blocks") if isinstance(payload, dict) else []
        self.assertTrue(isinstance(blocks, list), "listing bento blocks must be list")
        by_type = {
            str(block.get("type")): block
            for block in blocks
            if isinstance(block, dict) and str(block.get("type") or "").strip()
        }
        self.assertIn("TABLE_LISTING_SIGNALS", by_type)
        signals_block = by_type["TABLE_LISTING_SIGNALS"]
        source = str(signals_block.get("data_source") or "")
        self.assertIn("/v1/listings/signals", source)
        self.assertIn("signal.generated", str(signals_block.get("realtime") or ""))

    def test_bento_timeframes_contract(self) -> None:
        bento = json.loads((CANONICAL_DIR / "bento_ui_blocks.json").read_text(encoding="utf-8"))
        pages = bento.get("pages") if isinstance(bento, dict) else {}
        allowed = {"1h", "6h", "24h", "7d"}
        for page_name, page_payload in (pages or {}).items():
            if not isinstance(page_payload, dict):
                continue
            rows = ((page_payload.get("layout") or {}).get("rows") or []) if isinstance(page_payload.get("layout"), dict) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for block in (row.get("blocks") or []):
                    if not isinstance(block, dict):
                        continue
                    controls = block.get("controls")
                    if not isinstance(controls, dict):
                        continue
                    tf = controls.get("timeframe")
                    if tf is None:
                        continue
                    self.assertTrue(isinstance(tf, list), f"timeframe must be list: page={page_name} block={block.get('id')}")
                    for val in tf:
                        self.assertIn(str(val), allowed, f"unsupported timeframe: page={page_name} block={block.get('id')} value={val}")


if __name__ == "__main__":
    unittest.main()

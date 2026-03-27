import filecmp
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V5 = ROOT / "config" / "contracts" / "v5"


class TestV5CanonicalContracts(unittest.TestCase):
    def test_v5_package_files_present(self) -> None:
        required = [
            "DEV_PACKAGE_README.txt",
            "GiftMarketZone_Telegram_PRO_templates_v3.txt",
            "bento_ui_blocks.json",
            "bento_ui_blocks_TZ_RU.txt",
            "bento_ui_signals_blocks.json",
            "decision_engine_v2_spec_RU.txt",
            "edgerank_weights_by_regime.json",
            "frontend_signals_ui_mapping.json",
            "openapi_full_v1.4.yaml",
            "openapi_full_v1.5.yaml",
            "openapi_full_v1.6.yaml",
            "redis_topics_structure_v1.3.txt",
            "schema_market.status.v1.json",
            "schema_signal.created.v2.json",
            "signal_profiles_by_regime.json",
            "signals_page_pro_ui_mapping.json",
            "signals_page_TZ_PRO_RU.txt",
            "signals_page_TZ_PRO_RU_v2.txt",
        ]
        for name in required:
            self.assertTrue((V5 / name).exists(), f"missing canonical v5 file: {name}")

    def test_runtime_configs_match_canonical_v5(self) -> None:
        pairs = [
            (V5 / "signals_page_pro_ui_mapping.json", ROOT / "config" / "signals" / "signals_page_pro_ui_mapping.json"),
            (V5 / "frontend_signals_ui_mapping.json", ROOT / "config" / "signals" / "frontend_signals_ui_mapping.json"),
            (V5 / "bento_ui_signals_blocks.json", ROOT / "config" / "signals" / "bento_ui_signals_blocks.json"),
            (V5 / "schema_signal.created.v2.json", ROOT / "config" / "signals" / "schema_signal.created.v2.json"),
            (V5 / "schema_market.status.v1.json", ROOT / "config" / "signals" / "schema_market.status.v1.json"),
            (V5 / "edgerank_weights_by_regime.json", ROOT / "config" / "signals" / "edgerank_weights_by_regime.json"),
            (V5 / "signal_profiles_by_regime.json", ROOT / "config" / "signals" / "signal_profiles_by_regime.json"),
            (V5 / "edgerank_weights_by_regime.json", ROOT / "config" / "listing" / "edgerank_weights_by_regime.json"),
            (V5 / "signal_profiles_by_regime.json", ROOT / "config" / "listing" / "signal_profiles_by_regime.json"),
        ]
        for src, dst in pairs:
            self.assertTrue(dst.exists(), f"runtime config is missing: {dst}")
            self.assertTrue(filecmp.cmp(src, dst, shallow=False), f"runtime config drift: {dst}")


if __name__ == "__main__":
    unittest.main()


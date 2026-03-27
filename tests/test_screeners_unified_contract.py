import filecmp
import unittest
from pathlib import Path

from core import GiftAnalyticsService

ROOT = Path(__file__).resolve().parents[1]
CANON = ROOT / 'config' / 'contracts' / 'screeners_unified_v1'
RUNTIME = ROOT / 'config' / 'screeners'


class TestScreenersUnifiedContracts(unittest.TestCase):
    def test_canonical_files_present(self) -> None:
        required = [
            'bento_ui_screeners_blocks_unified_v1.json',
            'event_schemas_screeners_unified_v1.json',
            'openapi_patch_v1.8_screeners_unified_v1.yaml',
            'redis_topics_structure_screeners_unified_v1.json',
            'screeners_page_pro_ui_mapping_unified_v1.json',
            'screeners_page_TZ_PRO_RU_unified_v1.txt',
        ]
        for name in required:
            self.assertTrue((CANON / name).exists(), f'missing canonical screeners file: {name}')

    def test_runtime_configs_match_canonical(self) -> None:
        pairs = [
            ('screeners_page_pro_ui_mapping_unified_v1.json', 'screeners_page_pro_ui_mapping_unified_v1.json'),
            ('bento_ui_screeners_blocks_unified_v1.json', 'bento_ui_screeners_blocks_unified_v1.json'),
            ('event_schemas_screeners_unified_v1.json', 'event_schemas_screeners_unified_v1.json'),
            ('redis_topics_structure_screeners_unified_v1.json', 'redis_topics_structure_screeners_unified_v1.json'),
        ]
        for src_name, dst_name in pairs:
            src = CANON / src_name
            dst = RUNTIME / dst_name
            self.assertTrue(dst.exists(), f'runtime config is missing: {dst}')
            self.assertTrue(filecmp.cmp(src, dst, shallow=False), f'runtime config drift: {dst}')

    def test_screeners_feed_contract_smoke(self) -> None:
        svc = GiftAnalyticsService()
        payload = svc.screeners_feed_v1(limit=5)
        self.assertIn('items', payload)
        self.assertTrue(isinstance(payload.get('items'), list))
        if payload['items']:
            row = payload['items'][0]
            for key in ['ts', 'screener_type', 'variant_id', 'variant_label', 'edgeRank100', 'score100', 'conf_pct', 'market_regime', 'action']:
                self.assertIn(key, row)

    def test_screeners_stream_events_runtime_smoke(self) -> None:
        svc = GiftAnalyticsService()
        first = svc.screeners_stream_events_v1(limit=10)
        self.assertIn('items', first)
        self.assertTrue(isinstance(first.get('items'), list))
        second = svc.screeners_stream_events_v1(limit=10)
        self.assertIn('items', second)
        self.assertTrue(isinstance(second.get('items'), list))
        if first['items']:
            ev = first['items'][0]
            self.assertIn('event_id', ev)
            self.assertIn('payload', ev)
            payload = ev.get('payload') if isinstance(ev.get('payload'), dict) else {}
            self.assertIn('variant_id', payload)
            self.assertIn('screener_type', payload)


if __name__ == '__main__':
    unittest.main()

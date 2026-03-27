import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SIGNALS_CFG = ROOT / 'config' / 'signals'
FRONT = ROOT / 'frontend-react'


class TestSignalsV5Contracts(unittest.TestCase):
    def test_signals_v5_config_files_exist(self):
        required = [
            'signals_page_pro_ui_mapping.json',
            'frontend_signals_ui_mapping.json',
            'bento_ui_signals_blocks.json',
            'schema_signal.created.v2.json',
            'schema_market.status.v1.json',
            'edgerank_weights_by_regime.json',
            'signal_profiles_by_regime.json',
        ]
        for name in required:
            self.assertTrue((SIGNALS_CFG / name).exists(), f'missing signals config: {name}')

    def test_signals_ui_mapping_has_required_filters(self):
        payload = json.loads((SIGNALS_CFG / 'frontend_signals_ui_mapping.json').read_text(encoding='utf-8'))
        rows = payload.get('filters') if isinstance(payload, dict) else []
        ids = {str((x or {}).get('id') or '') for x in (rows or []) if isinstance(x, dict)}
        for required_id in [
            'action',
            'market_regime',
            'edgeRank100_min',
            'conf_min',
            'profit_min',
            'liq_min',
            'lp_max',
            'ar_min',
            'vv_min',
            'only_pro_alerts',
        ]:
            self.assertIn(required_id, ids)

    def test_signals_page_uses_v5_json_configs(self):
        page = (FRONT / 'src' / 'pages' / 'SignalsPage.tsx').read_text(encoding='utf-8')
        self.assertIn("../../../config/signals/frontend_signals_ui_mapping.json", page)
        self.assertIn("../../../config/signals/bento_ui_signals_blocks.json", page)
        self.assertIn("../../../config/signals/signals_page_pro_ui_mapping.json", page)
        self.assertIn("const FEED_ENDPOINT =", page)
        self.assertIn("const REALTIME_ENDPOINT =", page)
        self.assertIn("const REALTIME_EVENT =", page)
        self.assertIn("const DEFAULT_SORT_BY =", page)
        self.assertIn("const DEFAULT_SORT_DIR =", page)
        self.assertIn("const DEFAULT_WINDOW =", page)

    def test_signals_api_uses_dedicated_stream_endpoint(self):
        openapi = (FRONT / 'src' / 'lib' / 'openapi.ts').read_text(encoding='utf-8')
        api = (FRONT / 'src' / 'lib' / 'api.ts').read_text(encoding='utf-8')
        server = (ROOT / 'server.py').read_text(encoding='utf-8')
        self.assertIn("signalsStream: '/v1/stream/signals'", openapi)
        self.assertIn('subscribeSignalsStream', api)
        self.assertIn("eventName", api)
        self.assertIn("endpoint", api)
        self.assertIn('if path == "/v1/stream/signals"', server)


if __name__ == '__main__':
    unittest.main()

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'config' / 'screeners' / 'redis_topics_structure_screeners_unified_v1.json'


class TestScreenersRedisTopics(unittest.TestCase):
    def test_required_streams_and_events_present(self) -> None:
        payload = json.loads(RUNTIME.read_text(encoding='utf-8'))
        streams = payload.get('streams') if isinstance(payload.get('streams'), dict) else {}
        self.assertIn('stream:screeners', streams)
        self.assertIn('stream:listings', streams)
        self.assertIn('stream:signals', streams)
        self.assertIn('stream:market', streams)
        screeners_events = streams.get('stream:screeners', {}).get('events')
        self.assertTrue(isinstance(screeners_events, list))
        self.assertIn('screener.row', screeners_events)

    def test_required_consumer_groups_present(self) -> None:
        payload = json.loads(RUNTIME.read_text(encoding='utf-8'))
        groups = payload.get('consumer_groups') if isinstance(payload.get('consumer_groups'), dict) else {}
        for name in ['cg:screeners', 'cg:api_sse']:
            self.assertIn(name, groups)


if __name__ == '__main__':
    unittest.main()

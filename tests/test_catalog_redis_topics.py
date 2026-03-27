import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "config" / "catalog" / "redis_topics_structure_catalog_v1.json"


class TestCatalogRedisTopics(unittest.TestCase):
    def test_required_streams_and_events_present(self) -> None:
        payload = json.loads(RUNTIME.read_text(encoding="utf-8"))
        streams = payload.get("streams") if isinstance(payload.get("streams"), dict) else {}
        self.assertIn("stream:listings", streams)
        self.assertIn("stream:market", streams)
        self.assertIn("stream:catalog", streams)
        catalog_events = streams.get("stream:catalog", {}).get("events")
        self.assertTrue(isinstance(catalog_events, list))
        self.assertIn("catalog.row", catalog_events)

    def test_required_consumer_groups_present(self) -> None:
        payload = json.loads(RUNTIME.read_text(encoding="utf-8"))
        groups = payload.get("consumer_groups") if isinstance(payload.get("consumer_groups"), dict) else {}
        for name in ["cg:catalog_builder", "cg:api_sse_catalog"]:
            self.assertIn(name, groups)


if __name__ == "__main__":
    unittest.main()


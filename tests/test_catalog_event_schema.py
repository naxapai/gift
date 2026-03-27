import json
import unittest
from pathlib import Path

from core import GiftAnalyticsService

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = ROOT / "config" / "catalog" / "event_schemas_catalog_v1.json"


class TestCatalogEventSchema(unittest.TestCase):
    def test_catalog_row_envelope_matches_schema(self) -> None:
        schema_payload = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
        envelope = schema_payload.get("envelope") if isinstance(schema_payload, dict) else {}
        required = envelope.get("required") if isinstance(envelope, dict) else []
        props = envelope.get("properties") if isinstance(envelope, dict) else {}
        self.assertTrue(isinstance(required, list))
        self.assertTrue(isinstance(props, dict))

        svc = GiftAnalyticsService()
        feed = svc.catalog_feed_v1(limit=1)
        row = (feed.get("items") or [{}])[0] if isinstance(feed, dict) else {}
        event = svc.build_catalog_row_event_v1(row)
        for key in required:
            self.assertIn(key, event)
        self.assertTrue(isinstance(event.get("event"), str))
        self.assertEqual(str(event.get("event") or ""), "catalog.row")
        self.assertTrue(isinstance(event.get("ts"), str))
        self.assertTrue("T" in str(event.get("ts") or ""))
        self.assertTrue(isinstance(event.get("payload"), dict))

    def test_catalog_stream_payload_has_no_internal_runtime_fields(self) -> None:
        svc = GiftAnalyticsService()
        row = {
            "variant_id": "variant-1",
            "variant_label": "Variant 1",
            "floor_ton": 1.0,
            "fair_ton": 1.2,
            "edgeRank100": 60.0,
            "score100": 70.0,
            "conf_pct": 40.0,
            "market_regime": "MEAN_REVERT",
            "action": "BUY",
            "updated_at": "2026-03-05T12:00:00Z",
        }
        event = svc.build_catalog_row_event_v1(row)
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        self.assertNotIn("_stream_event_id", payload)
        self.assertNotIn("_stream_emitted_at", payload)


if __name__ == "__main__":
    unittest.main()

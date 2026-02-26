import unittest

from core import GiftAnalyticsService


class TestV1StreamSchema(unittest.TestCase):
    def test_signal_created_event_schema_required_fields(self) -> None:
        svc = GiftAnalyticsService()
        signal = {
            "signal_id": "11111111-1111-1111-1111-111111111111",
            "ts": "2026-02-26T00:00:00Z",
            "type": "BUY",
            "variant_id": "c|m|b|p",
            "collection_id": "c",
            "collection": "Collection",
            "score100": 82.0,
            "conf_pct": 71.0,
            "reasons": ["r1"],
            "risk_flags": ["x1"],
        }
        ev = svc.build_signal_created_event_v1(signal)
        self.assertEqual(ev["type"], "signal.created")
        self.assertIn("ts", ev)
        self.assertIn("key", ev)
        self.assertIn("version", ev)
        self.assertIn("payload", ev)
        payload = ev["payload"]
        for key in [
            "signal_id",
            "ts",
            "type",
            "variant_id",
            "collection_id",
            "collection",
            "score100",
            "conf_pct",
            "reasons",
            "risk_flags",
        ]:
            self.assertIn(key, payload)

    def test_metric_updated_event_schema_required_fields(self) -> None:
        svc = GiftAnalyticsService()
        ev = svc.build_metric_updated_event_v1(
            metric="MARKET_INDEX",
            scope="MARKET",
            value=64.3,
            unit="SCORE_0_100",
            market=True,
        )
        self.assertEqual(ev["type"], "metric.updated")
        payload = ev["payload"]
        for key in ["metric", "scope", "market", "unit", "point", "stale"]:
            self.assertIn(key, payload)
        self.assertIn("ts", payload["point"])
        self.assertIn("value", payload["point"])

    def test_stream_events_filtering(self) -> None:
        svc = GiftAnalyticsService()
        events = svc.stream_events_v1(types={"metric.updated"})
        self.assertTrue(len(events) > 0)
        self.assertTrue(all(str(e.get("type")) == "metric.updated" for e in events))


if __name__ == "__main__":
    unittest.main()


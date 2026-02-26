import json
import re
import unittest
from pathlib import Path

from core import GiftAnalyticsService


SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


def _assert_type(value, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


def _validate_schema(schema: dict, value, path: str = "$") -> None:
    if "const" in schema and value != schema["const"]:
        raise AssertionError(f"{path}: const mismatch")
    if "enum" in schema and value not in schema["enum"]:
        raise AssertionError(f"{path}: enum mismatch")
    if "type" in schema:
        expected_type = schema["type"]
        if isinstance(expected_type, list):
            if not any(_assert_type(value, t) for t in expected_type):
                raise AssertionError(f"{path}: type mismatch")
        else:
            if not _assert_type(value, expected_type):
                raise AssertionError(f"{path}: type mismatch")

    fmt = schema.get("format")
    if fmt == "date-time" and isinstance(value, str):
        if "T" not in value:
            raise AssertionError(f"{path}: invalid date-time format")
    if fmt == "uuid" and isinstance(value, str):
        uuid_re = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
        if not uuid_re.match(value):
            raise AssertionError(f"{path}: invalid uuid")

    if isinstance(value, dict):
        required = schema.get("required") or []
        for key in required:
            if key not in value:
                raise AssertionError(f"{path}: missing required key {key}")
        properties = schema.get("properties") or {}
        additional = schema.get("additionalProperties", True)
        for key, val in value.items():
            if key in properties:
                _validate_schema(properties[key], val, f"{path}.{key}")
            elif additional is False:
                raise AssertionError(f"{path}: additional property {key} not allowed")

    if isinstance(value, list):
        item_schema = schema.get("items")
        if item_schema:
            for idx, item in enumerate(value):
                _validate_schema(item_schema, item, f"{path}[{idx}]")


class TestV1EventSchemaValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.signal_schema = json.loads((SCHEMA_DIR / "signal.created.schema.json").read_text(encoding="utf-8"))
        cls.metric_schema = json.loads((SCHEMA_DIR / "metric.updated.schema.json").read_text(encoding="utf-8"))

    def test_signal_created_validates_against_schema(self) -> None:
        svc = GiftAnalyticsService()
        sig = {
            "signal_id": "11111111-1111-1111-1111-111111111111",
            "ts": "2026-02-26T00:00:00Z",
            "type": "BUY",
            "variant_id": "c|m|b|p",
            "collection_id": "c",
            "collection": "Collection",
            "model": "M",
            "background": "B",
            "pattern": "P",
            "score100": 81.0,
            "conf_pct": 70.0,
            "price_ton": 8.0,
            "floor_ton": 8.0,
            "fair_ton": 9.4,
            "undervalue": 0.149,
            "expected_profit_pct": 0.145,
            "forecast24h_pct_min": 4.0,
            "forecast24h_pct_max": 18.0,
            "active_lots": 42,
            "liquidity24h": 0.6,
            "reasons": ["r1"],
            "risk_flags": ["x1"],
        }
        event = svc.build_signal_created_event_v1(sig, trace_id="trace-1")
        _validate_schema(self.signal_schema, event)

    def test_metric_updated_validates_against_schema(self) -> None:
        svc = GiftAnalyticsService()
        event = svc.build_metric_updated_event_v1(
            metric="MARKET_INDEX",
            scope="MARKET",
            value=64.3,
            unit="SCORE_0_100",
            market=True,
            trace_id="trace-2",
            extra={"market_state": "рост"},
        )
        _validate_schema(self.metric_schema, event)


if __name__ == "__main__":
    unittest.main()


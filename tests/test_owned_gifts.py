import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import GiftAnalyticsService


class TestOwnedGifts(unittest.TestCase):
    def test_owned_gifts_token_falls_back_to_bridge_token_env(self) -> None:
        old_bridge = os.environ.get("BRIDGE_API_TOKEN")
        old_owned = os.environ.get("TELEGRAM_OWNED_GIFTS_API_TOKEN")
        old_loop = os.environ.get("INGEST_AUTO_LOOP")
        try:
            os.environ["INGEST_AUTO_LOOP"] = "false"
            os.environ["BRIDGE_API_TOKEN"] = "bridge-secret"
            os.environ.pop("TELEGRAM_OWNED_GIFTS_API_TOKEN", None)
            svc = GiftAnalyticsService()
            self.assertEqual(svc.telegram_owned_gifts_api_token, "bridge-secret")
        finally:
            if old_bridge is None:
                os.environ.pop("BRIDGE_API_TOKEN", None)
            else:
                os.environ["BRIDGE_API_TOKEN"] = old_bridge
            if old_owned is None:
                os.environ.pop("TELEGRAM_OWNED_GIFTS_API_TOKEN", None)
            else:
                os.environ["TELEGRAM_OWNED_GIFTS_API_TOKEN"] = old_owned
            if old_loop is None:
                os.environ.pop("INGEST_AUTO_LOOP", None)
            else:
                os.environ["INGEST_AUTO_LOOP"] = old_loop

    def test_owned_gifts_remote_http_error_falls_back_to_local_snapshot(self) -> None:
        old_loop = os.environ.get("INGEST_AUTO_LOOP")
        try:
            os.environ["INGEST_AUTO_LOOP"] = "false"
            svc = GiftAnalyticsService()
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "owned_gifts.json"
                path.write_text('{"users":{"id:42":[{"gift_id":"g1","collection":"snakebox","model":"Bluebell"}]}}', encoding="utf-8")
                svc.owned_gifts_file = path
                svc.telegram_owned_gifts_api_url = "https://example.com/owned"
                with patch("urllib.request.urlopen", side_effect=__import__("urllib").error.HTTPError(svc.telegram_owned_gifts_api_url, 401, "Unauthorized", None, None)):
                    payload = svc.telegram_owned_gifts_v1({"id": 42, "username": "alice"})
                self.assertTrue(payload.get("ok"))
                self.assertEqual(payload.get("source"), "local_file")
                self.assertTrue(payload.get("items"))
                self.assertIn("локальный snapshot", str(payload.get("message") or ""))
        finally:
            if old_loop is None:
                os.environ.pop("INGEST_AUTO_LOOP", None)
            else:
                os.environ["INGEST_AUTO_LOOP"] = old_loop

    def test_owned_gifts_falls_back_to_wallet_holdings_when_remote_empty(self) -> None:
        old_loop = os.environ.get("INGEST_AUTO_LOOP")
        try:
            os.environ["INGEST_AUTO_LOOP"] = "false"
            svc = GiftAnalyticsService()
            wallet = "EQTESTWALLET_HOLDINGS"
            created = svc.trade_runtime.create_trade_intent({
                "intent_type": "BUY",
                "variant_id": next(iter((svc.variants or {}).keys())),
                "wallet_address": wallet,
                "max_spend_ton": 8.0,
            }, market_regime="MEAN_REVERT", variant_snapshot={"floor_ton": 8.0, "fair_ton": 9.0})
            svc.trade_runtime.confirm_intent_signature(created["intent"]["intent_id"], {"tx_hash": "tx-holdings-1"}, market_regime="MEAN_REVERT", variant_snapshot={"floor_ton": 8.0, "fair_ton": 9.0})
            svc.telegram_owned_gifts_api_url = "https://example.com/owned"
            with patch("urllib.request.urlopen", side_effect=__import__("urllib").error.HTTPError(svc.telegram_owned_gifts_api_url, 401, "Unauthorized", None, None)):
                payload = svc.telegram_owned_gifts_v1({"id": 144832201, "username": "tester"}, {"address": wallet})
            self.assertTrue(payload.get("ok"))
            self.assertEqual(payload.get("source"), "wallet_holdings")
            self.assertTrue(payload.get("items"))
        finally:
            if old_loop is None:
                os.environ.pop("INGEST_AUTO_LOOP", None)
            else:
                os.environ["INGEST_AUTO_LOOP"] = old_loop


if __name__ == "__main__":
    unittest.main()

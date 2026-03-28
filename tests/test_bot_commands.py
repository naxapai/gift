import unittest
from unittest.mock import patch

import bot


class TestBotCommands(unittest.TestCase):
    def test_signal_gift_prompt_matches_tz(self) -> None:
        cache = {}
        updates = {"result": [{"update_id": 1, "message": {"text": "/signal_gift", "chat": {"id": 100}}}]}
        sent: list[tuple] = []
        with patch.object(bot, "BOT_TOKEN", "token"), patch.object(bot, "_get_updates", return_value=updates), patch.object(bot, "send_message_to", side_effect=lambda chat_id, text, parse_mode=None: sent.append((chat_id, text, parse_mode))):
            bot._handle_commands(cache)
        self.assertTrue(sent)
        self.assertIn("коллекция/модель/фон/узор", sent[0][1])
        self.assertEqual(sent[0][2], "HTML")

    def test_signal_command_uses_recent_delivery_fetcher_and_cooldown(self) -> None:
        cache = {}
        updates = {"result": [{"update_id": 1, "message": {"text": "/signal", "chat": {"id": 101}}}]}
        sent: list[str] = []
        delivered: list[dict] = []
        bot.set_recent_signal_fetcher(lambda limit=20: {"sent": [{"kind": "gift_signal", "sent_at": "2999-03-05T12:00:00Z", "payload": {"action": "BUY", "market_regime": "RISK_ON", "score100": 80, "conf_pct": 44, "expected_profit_pct": 11, "collection": "snakebox", "model": "Bluebell", "background": "Cobalt Blue", "pattern": "Hourglass", "price_ton": 8.0, "floor_ton": 8.0, "fair_ton": 9.5, "liquidity_score": 51, "absorption_30m": 1.0, "listing_pressure": 2.1, "depth_score": 0.5, "depth_5pct_count": 5, "depth_5pct_ton": 20, "volume_velocity": 1.2}}]})
        with patch.object(bot, "BOT_TOKEN", "token"), patch.object(bot, "_get_updates", return_value=updates), patch.object(bot, "send_message_to", side_effect=lambda chat_id, text, parse_mode=None: sent.append(text)), patch.object(bot, "_send_gift_signal_payload_to", side_effect=lambda chat_id, payload: delivered.append(payload)):
            bot._handle_commands(cache)
            bot._handle_commands(cache)
        self.assertIn("Сигналы за последний час", sent[0])
        self.assertTrue(delivered)
        self.assertEqual(sent[-1], "Доступные сигналы были отправлены, вернитесь через 1 час")

    def test_status_command_uses_new_market_status_renderer(self) -> None:
        cache = {}
        updates = {"result": [{"update_id": 1, "message": {"text": "/status", "chat": {"id": 102}}}]}
        sent: list[str] = []
        with patch.object(bot, "BOT_TOKEN", "token"), patch.object(bot, "_get_updates", return_value=updates), patch.object(bot, "_http_get", return_value={"market_regime": "RISK_OFF", "data_conf_pct": 70, "trend": "падение", "velocity_score": 41, "vol_level": "HIGH", "flow": {"volume_velocity": 0.91, "absorption": 0.74, "listing_pressure": 4.8}, "liquidity": {"liquidity_score": 38, "depth_5pct": {"lots": 9, "ton": 77.0}}, "supply": {"active_lots": 1220, "delta_lots_1h": 88, "listing_velocity_10m": 17, "listing_velocity_norm": 0.41}, "whales": {"whale_ratio_pct": 14.2, "whale_impulse": 1.3}, "signals_1h": {"buy": 2, "sell": 8, "watch": 5, "skip": 11}, "provider_health": {"p95_ms": 420, "err_pct": 0.8}, "data_health": "OK"}), patch.object(bot, "send_message_to", side_effect=lambda chat_id, text, parse_mode=None: sent.append(text)):
            bot._handle_commands(cache)
        self.assertTrue(sent)
        self.assertIn("GiftMarketZone • РЫНОК", sent[0])


if __name__ == "__main__":
    unittest.main()

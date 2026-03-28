import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from telegram_delivery import GateEngine, MessageRenderer, TelegramNotifier


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "config" / "telegram" / "telegram_message_profile_PRO_v1.json"
RULES_PATH = ROOT / "config" / "telegram" / "telegram_message_templater_rules_PRO_v1.txt"
SIGNAL_PROFILES_PATH = ROOT / "config" / "signals" / "signal_profiles_by_regime.json"
EDGE_WEIGHTS_PATH = ROOT / "config" / "signals" / "edgerank_weights_by_regime.json"


class TestTelegramDelivery(unittest.TestCase):
    def test_gate_engine_applies_profile_thresholds(self) -> None:
        gate = GateEngine({
            "gift_signal_channel": {
                "all": [
                    {"metric": "edgeRank100", "op": ">=", "value": 55},
                    {"metric": "conf_pct", "op": ">=", "value": 35},
                    {"metric": "expected_profit_pct", "op": ">=", "value": 8},
                ]
            }
        })
        passed = gate.evaluate("gift_signal_channel", {"edgeRank100": 61, "conf_pct": 42, "expected_profit_pct": 11})
        failed = gate.evaluate("gift_signal_channel", {"edgeRank100": 54, "conf_pct": 42, "expected_profit_pct": 11})
        self.assertTrue(passed.get("ok"))
        self.assertFalse(failed.get("ok"))

    def test_message_renderer_renders_market_and_signal_templates(self) -> None:
        renderer = MessageRenderer(
            profile=__import__("json").loads(PROFILE_PATH.read_text(encoding="utf-8")),
            rules_text=RULES_PATH.read_text(encoding="utf-8"),
            signal_profiles=__import__("json").loads(SIGNAL_PROFILES_PATH.read_text(encoding="utf-8")),
            edgerank_weights=__import__("json").loads(EDGE_WEIGHTS_PATH.read_text(encoding="utf-8")),
        )
        market = renderer.render_market_status({
            "updated_at": "2026-03-05T12:00:00Z",
            "market_regime": "RISK_OFF",
            "data_conf_pct": 73,
            "trend": "падение",
            "velocity_score": 41,
            "vol_level": "HIGH",
            "flow": {"volume_velocity": 0.91, "absorption": 0.74, "listing_pressure": 4.8},
            "liquidity": {"liquidity_score": 38, "depth_5pct": {"lots": 9, "ton": 77.0}},
            "supply": {"active_lots": 1220, "delta_lots_1h": 88, "listing_velocity_10m": 17, "listing_velocity_norm": 0.41},
            "whales": {"whale_ratio_pct": 14.2, "whale_impulse": 1.3},
            "signals_1h": {"buy": 2, "sell": 8, "watch": 5, "skip": 11},
            "provider_health": {"p95_ms": 420, "err_pct": 0.8},
            "data_health": "OK",
        })
        signal = renderer.render_gift_signal({
            "ts": "2026-03-05T12:00:00Z",
            "action": "WATCH",
            "market_regime": "MEAN_REVERT",
            "edgeRank100": 58,
            "score100": 67,
            "conf_pct": 39,
            "collection": "snakebox",
            "model": "Bluebell",
            "background": "Cobalt Blue",
            "pattern": "Hourglass",
            "price_ton": 8.0,
            "floor_ton": 8.0,
            "fair_ton": 9.2,
            "undervalue_pct": 7.1,
            "expected_profit_pct": 9.4,
            "liquidity_score": 52,
            "absorption_30m": 0.96,
            "listing_pressure": 2.4,
            "volume_velocity": 1.2,
            "depth_5pct_count": 4,
            "depth_5pct_ton": 31,
            "reasons": [],
            "risk_flags": [],
        })
        self.assertIn("GiftMarketZone • РЫНОК", market)
        self.assertIn("🎯 Тактика сейчас:", market)
        self.assertIn("GiftMarketZone • WATCH", signal)
        self.assertIn("🎯 План:", signal)
        self.assertIn("🧠 Почему:", signal)
        self.assertIn("🆕", market)
        self.assertIn("BUY-триггер", signal)

    def test_notifier_settings_are_sanitized_and_test_preview_works(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            notifier = TelegramNotifier(
                profile_path=PROFILE_PATH,
                rules_path=RULES_PATH,
                signal_profiles_path=SIGNAL_PROFILES_PATH,
                edgerank_weights_path=EDGE_WEIGHTS_PATH,
                settings_path=tmp / "telegram_delivery_settings.json",
                journal_path=tmp / "telegram_delivery_journal.json",
                bot_token="token",
                default_chat_id="-100",
            )
            effective = notifier.update_settings({
                "publish_gates": {"gift_signal_channel": {"edgeRank100_gte": 999, "conf_pct_gte": -5, "expected_profit_pct_gte": 12}},
                "transport": {"rate_limit_per_minute": 999, "max_retries": 0, "retry_backoff_sec": 99},
            })
            gate = ((effective.get("publish_gates") or {}).get("gift_signal_channel") or {}) if isinstance(effective, dict) else {}
            self.assertEqual(float(gate.get("edgeRank100_gte") or 0), 100.0)
            self.assertEqual(float(gate.get("conf_pct_gte") or 0), 0.0)
            self.assertEqual(float(gate.get("expected_profit_pct_gte") or 0), 12.0)

            with patch.object(notifier, "_deliver_message", return_value=None):
                payload = notifier.send_test("gift_signal", {
                    "ts": "2026-03-05T12:00:00Z",
                    "action": "BUY",
                    "market_regime": "RISK_ON",
                    "edgeRank100": 66,
                    "score100": 78,
                    "conf_pct": 44,
                    "collection": "snakebox",
                    "model": "Bluebell",
                    "background": "Cobalt Blue",
                    "pattern": "Hourglass",
                    "price_ton": 8.0,
                    "floor_ton": 8.0,
                    "fair_ton": 9.5,
                    "expected_profit_pct": 11,
                    "liquidity_score": 51,
                    "absorption_30m": 1.0,
                    "listing_pressure": 2.1,
                    "depth_5pct_count": 5,
                    "depth_5pct_ton": 45,
                    "preview_url": "https://example.com/gift.png",
                })
            self.assertTrue(payload.get("ok"))
            self.assertTrue(payload.get("sent"))
            self.assertIn("GiftMarketZone • BUY", str(payload.get("preview") or ""))
            notifier.close()

    def test_notifier_queue_journal_end_to_end_success_and_dedupe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            notifier = TelegramNotifier(
                profile_path=PROFILE_PATH,
                rules_path=RULES_PATH,
                signal_profiles_path=SIGNAL_PROFILES_PATH,
                edgerank_weights_path=EDGE_WEIGHTS_PATH,
                settings_path=tmp / "telegram_delivery_settings.json",
                journal_path=tmp / "telegram_delivery_journal.json",
                bot_token="token",
                default_chat_id="-100",
            )
            with patch.object(notifier, "_telegram_post", return_value={"ok": True, "result": {}}) as mocked_post:
                accepted = notifier.enqueue_gift_signal({
                    "payload": {
                        "signal_id": "11111111-1111-1111-1111-111111111111",
                        "ts": "2026-03-05T12:00:00Z",
                        "action": "BUY",
                        "market_regime": "RISK_ON",
                        "edgeRank100": 66,
                        "score100": 78,
                        "conf_pct": 44,
                        "expected_profit_pct": 11,
                        "collection": "snakebox",
                        "model": "Bluebell",
                        "background": "Cobalt Blue",
                        "pattern": "Hourglass",
                        "price_ton": 8.0,
                        "floor_ton": 8.0,
                        "fair_ton": 9.5,
                        "liquidity_score": 51,
                        "absorption_30m": 1.0,
                        "listing_pressure": 2.1,
                        "depth_5pct_count": 5,
                        "depth_5pct_ton": 45,
                        "preview_url": "https://example.com/gift.png",
                    }
                })
                duplicate = notifier.enqueue_gift_signal({
                    "payload": {
                        "signal_id": "11111111-1111-1111-1111-111111111111",
                        "ts": "2026-03-05T12:00:00Z",
                        "action": "BUY",
                        "market_regime": "RISK_ON",
                        "edgeRank100": 66,
                        "conf_pct": 44,
                        "expected_profit_pct": 11,
                    }
                })
                notifier._queue.join()
                journal = notifier.journal_snapshot(limit=10)
            self.assertTrue(accepted)
            self.assertTrue(duplicate)
            self.assertEqual(mocked_post.call_count, 1)
            self.assertTrue(journal.get("sent"))
            self.assertEqual(str((journal.get("sent") or [])[0].get("kind") or ""), "gift_signal")
            self.assertFalse(journal.get("failed"))
            notifier.close()

    def test_notifier_queue_journal_end_to_end_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            notifier = TelegramNotifier(
                profile_path=PROFILE_PATH,
                rules_path=RULES_PATH,
                signal_profiles_path=SIGNAL_PROFILES_PATH,
                edgerank_weights_path=EDGE_WEIGHTS_PATH,
                settings_path=tmp / "telegram_delivery_settings.json",
                journal_path=tmp / "telegram_delivery_journal.json",
                bot_token="token",
                default_chat_id="-100",
            )
            with patch.object(notifier, "_telegram_post", side_effect=RuntimeError("boom")):
                accepted = notifier.enqueue_market_status({
                    "payload": {
                        "updated_at": "2026-03-05T12:00:00Z",
                        "ts": "2026-03-05T12:00:00Z",
                        "market_regime": "RISK_OFF",
                        "data_conf_pct": 70,
                        "trend": "падение",
                        "velocity_score": 41,
                        "vol_level": "HIGH",
                        "flow": {"volume_velocity": 0.91, "absorption": 0.74, "listing_pressure": 4.8},
                        "liquidity": {"liquidity_score": 38, "depth_5pct": {"lots": 9, "ton": 77.0}},
                        "supply": {"active_lots": 1220, "delta_lots_1h": 88, "listing_velocity_10m": 17, "listing_velocity_norm": 0.41},
                        "whales": {"whale_ratio_pct": 14.2, "whale_impulse": 1.3},
                        "signals_1h": {"buy": 2, "sell": 8, "watch": 5, "skip": 11},
                        "provider_health": {"p95_ms": 420, "err_pct": 0.8},
                        "data_health": "OK",
                    }
                })
                notifier._queue.join()
                journal = notifier.journal_snapshot(limit=10)
            self.assertTrue(accepted)
            self.assertTrue(journal.get("failed"))
            self.assertIn("boom", str((journal.get("failed") or [])[0].get("error") or ""))
            notifier.close()

    def test_gate_engine_allows_strong_sell_override_from_tz(self) -> None:
        gate = GateEngine(
            {"gift_signal_channel": {"all": [{"metric": "edgeRank100", "op": ">=", "value": 55}, {"metric": "conf_pct", "op": ">=", "value": 35}, {"metric": "expected_profit_pct", "op": ">=", "value": 8}]}},
            __import__("json").loads(SIGNAL_PROFILES_PATH.read_text(encoding="utf-8")),
        )
        result = gate.evaluate("gift_signal_channel", {
            "action": "SELL",
            "strength_tag": "STRONG_SELL",
            "edgeRank100": 18,
            "conf_pct": 44,
            "expected_profit_pct": 0,
            "listing_pressure": 6.2,
            "absorption_30m": 0.55,
        })
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("exception"), "strong_sell_override")

    def test_renderer_computes_dynamic_edgerank_when_missing(self) -> None:
        renderer = MessageRenderer(
            profile=__import__("json").loads(PROFILE_PATH.read_text(encoding="utf-8")),
            rules_text=RULES_PATH.read_text(encoding="utf-8"),
            signal_profiles=__import__("json").loads(SIGNAL_PROFILES_PATH.read_text(encoding="utf-8")),
            edgerank_weights=__import__("json").loads(EDGE_WEIGHTS_PATH.read_text(encoding="utf-8")),
        )
        text = renderer.render_gift_signal({
            "ts": "2026-03-05T12:00:00Z",
            "action": "BUY",
            "market_regime": "PANIC",
            "score100": 81,
            "conf_pct": 54,
            "expected_profit_pct": 14,
            "collection": "snakebox",
            "model": "Bluebell",
            "background": "Cobalt Blue",
            "pattern": "Hourglass",
            "price_ton": 8.0,
            "floor_ton": 8.0,
            "fair_ton": 9.4,
            "liquidity_score": 52,
            "absorption_30m": 1.2,
            "listing_pressure": 1.8,
            "volume_velocity": 1.6,
            "depth_score": 0.6,
            "depth_5pct_count": 6,
            "depth_5pct_ton": 33,
        })
        self.assertIn("Edge 30", text)


if __name__ == "__main__":
    unittest.main()

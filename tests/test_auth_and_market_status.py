import os
import unittest
from datetime import datetime, timezone

import server
from core import GiftAnalyticsService
from telegram_delivery import MessageRenderer


class TestAuthAndMarketStatus(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._old_ingest_auto_loop = os.environ.get("INGEST_AUTO_LOOP")
        os.environ["INGEST_AUTO_LOOP"] = "false"

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._old_ingest_auto_loop is None:
            os.environ.pop("INGEST_AUTO_LOOP", None)
        else:
            os.environ["INGEST_AUTO_LOOP"] = cls._old_ingest_auto_loop

    def test_auth_store_persists_sessions_to_file(self) -> None:
        store = server.AuthStore()
        session = store.create_session({"id": 1, "username": "alice"})
        reloaded = server.AuthStore()
        restored = reloaded.get_session(session["sid"])
        self.assertTrue(isinstance(restored, dict))
        self.assertEqual(int((restored or {}).get("user", {}).get("id") or 0), 1)

    def test_market_status_not_degraded_for_mtproto_rows_with_error_flag(self) -> None:
        svc = GiftAnalyticsService()
        svc.state["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with unittest.mock.patch.object(svc, "market_overview", return_value={"updated_at": svc.state["updated_at"], "active_listings": 10, "floor_ton_min": 4.0, "provider_health": [{"provider": "mtproto_warmup", "p95_ms": 0, "err_pct": 100.0}]}), unittest.mock.patch.object(svc, "_listing_source_rows_v1", return_value=([{"listing_key": "a", "ts_detected": "2026-04-03T19:38:48.229105Z"}], {"source": "mtproto_api", "error": "mtproto_http_401_unauthorized", "updated_at": svc.state["updated_at"]})), unittest.mock.patch.object(svc, "_trades_in_window_multi", return_value=(0, 0.0)), unittest.mock.patch.object(svc, "signals_v1", return_value={"items": []}), unittest.mock.patch.object(svc, "_market_depth_for_variants", return_value=(1, 4.0)), unittest.mock.patch.object(svc, "_whale_ratio_and_impulse", return_value=(0.0, 0.0, {})):
            payload = svc.market_status_v1(window="30m")
        self.assertEqual(payload.get("data_health"), "OK")
        provider = payload.get("provider_health") or {}
        self.assertEqual(str(provider.get("provider") or ""), "mtproto_api")
        self.assertEqual(float(provider.get("err_pct") or 0.0), 0.0)

    def test_renderer_time_format_matches_required_pattern(self) -> None:
        import json
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        renderer = MessageRenderer(
            profile=json.loads((root / "config" / "telegram" / "telegram_message_profile_PRO_v1.json").read_text(encoding="utf-8")),
            rules_text=(root / "config" / "telegram" / "telegram_message_templater_rules_PRO_v1.txt").read_text(encoding="utf-8"),
            signal_profiles=json.loads((root / "config" / "signals" / "signal_profiles_by_regime.json").read_text(encoding="utf-8")),
            edgerank_weights=json.loads((root / "config" / "signals" / "edgerank_weights_by_regime.json").read_text(encoding="utf-8")),
        )
        text = renderer.render_market_status({"ts": "2026-03-03T19:43:48Z", "market_regime": "RISK_OFF", "data_conf_pct": 70, "trend": "падение", "velocity_score": 41, "vol_level": "HIGH", "flow": {"volume_velocity": 0.91, "absorption": 0.74, "listing_pressure": 4.8}, "liquidity": {"liquidity_score": 38, "depth_5pct": {"lots": 9, "ton": 77.0}}, "supply": {"active_lots": 1220, "delta_lots_1h": 88, "listing_velocity_10m": 17, "listing_velocity_norm": 0.41}, "whales": {"whale_ratio_pct": 14.2, "whale_impulse": 1.3}, "signals_1h": {"buy": 2, "sell": 8, "watch": 5, "skip": 11}, "provider_health": {"p95_ms": 420, "err_pct": 0.8}, "data_health": "OK"})
        self.assertIn("03.03.2026/19:43:48", text)


if __name__ == "__main__":
    unittest.main()

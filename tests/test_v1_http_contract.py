import json
import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib import request as urllib_request
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import server
from core import GiftAnalyticsService
from core import ALERTS_FILE, FAVORITES_FILE


class TestV1HttpContract(unittest.TestCase):
    @staticmethod
    def _seed_variant() -> None:
        svc = server._STATE
        if not isinstance(svc, GiftAnalyticsService):
            return
        svc.variants["x|m|b|p"] = {
            "variant_id": "x|m|b|p",
            "base_id": "x",
            "metrics": {
                "floor_ton": 5.0,
                "median_ton": 7.0,
                "trades_count_24h": 10,
                "active_listings": 15,
            },
            "traits": {"model": {"name": "M"}, "background": {"name": "B"}, "pattern": {"name": "P"}},
            "updated_at": "2026-02-26T00:00:00Z",
        }

    @classmethod
    def setUpClass(cls) -> None:
        cls._old_auth_required = server.AUTH_REQUIRED
        cls._old_state = server._STATE
        cls._old_ingest_auto_loop = os.environ.get("INGEST_AUTO_LOOP")
        cls._old_listing_primary_source = os.environ.get("LISTING_PRIMARY_SOURCE")
        cls._old_listing_mt_api_url = os.environ.get("LISTING_MT_API_URL")
        cls._old_listing_mt_api_token = os.environ.get("LISTING_MT_API_TOKEN")
        os.environ["INGEST_AUTO_LOOP"] = "false"
        # Deterministic test mode: disable external listing API dependency.
        os.environ["LISTING_PRIMARY_SOURCE"] = "fragment"
        os.environ["LISTING_MT_API_URL"] = ""
        os.environ["LISTING_MT_API_TOKEN"] = ""
        server.AUTH_REQUIRED = False

        svc = GiftAnalyticsService()
        svc.state["updated_at"] = "2026-02-26T00:00:00Z"
        server._STATE = svc
        cls._seed_variant()

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.RequestHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.httpd.shutdown()
            cls.httpd.server_close()
        finally:
            if cls._old_ingest_auto_loop is None:
                os.environ.pop("INGEST_AUTO_LOOP", None)
            else:
                os.environ["INGEST_AUTO_LOOP"] = cls._old_ingest_auto_loop
            if cls._old_listing_primary_source is None:
                os.environ.pop("LISTING_PRIMARY_SOURCE", None)
            else:
                os.environ["LISTING_PRIMARY_SOURCE"] = cls._old_listing_primary_source
            if cls._old_listing_mt_api_url is None:
                os.environ.pop("LISTING_MT_API_URL", None)
            else:
                os.environ["LISTING_MT_API_URL"] = cls._old_listing_mt_api_url
            if cls._old_listing_mt_api_token is None:
                os.environ.pop("LISTING_MT_API_TOKEN", None)
            else:
                os.environ["LISTING_MT_API_TOKEN"] = cls._old_listing_mt_api_token
            server.AUTH_REQUIRED = cls._old_auth_required
            server._STATE = cls._old_state

    def setUp(self) -> None:
        self._seed_variant()
        FAVORITES_FILE.write_text("{}", encoding="utf-8")
        ALERTS_FILE.write_text("[]", encoding="utf-8")
        server._ADMIN_RT_CACHE.clear()
        svc = server._STATE
        if isinstance(svc, GiftAnalyticsService):
            svc.alert_rules = []
            svc.alert_events = []

    def _get_json(self, path: str, timeout: float = 20.0):
        with urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)

    def _post_json(self, path: str, payload: dict, timeout: float = 20.0):
        req = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)

    def _put_json(self, path: str, payload: dict, timeout: float = 20.0):
        req = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)

    def _get_json_with_headers(self, path: str, timeout: float = 20.0):
        with urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body), dict(resp.headers.items())

    def _delete_json(self, path: str, timeout: float = 20.0):
        req = Request(f"http://127.0.0.1:{self.port}{path}", method="DELETE")
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)

    def _read_sse_message(self, path: str, timeout: float = 12.0):
        with urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=timeout) as resp:
            lines: list[str] = []
            for _ in range(32):
                raw = resp.readline().decode("utf-8")
                if not raw:
                    break
                line = raw.rstrip("\r\n")
                if not line:
                    if lines:
                        break
                    continue
                if line.startswith(":") and not lines:
                    continue
                lines.append(line)
            return resp.status, str(resp.headers.get("Content-Type") or ""), lines

    def _cookie_opener(self):
        jar = urllib_request.HTTPCookieProcessor()
        return urllib_request.build_opener(jar)

    def test_metrics_endpoint_success(self) -> None:
        status, payload = self._get_json("/v1/metrics?metric=MARKET_INDEX&scope=MARKET")
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("metric"), "MARKET_INDEX")
        self.assertEqual(payload.get("scope"), "MARKET")
        self.assertIn("points", payload)
        self.assertTrue(isinstance(payload.get("points"), list))

    def test_runtime_http_metrics_endpoint_and_trace_header(self) -> None:
        status_h, payload_h, headers_h = self._get_json_with_headers("/healthz")
        self.assertEqual(status_h, 200)
        self.assertTrue(payload_h.get("ok"))
        trace_id = str(headers_h.get("X-Trace-Id") or headers_h.get("x-trace-id") or "").strip()
        self.assertTrue(trace_id)

        # Generate a few requests so metrics have non-zero counters.
        self._get_json("/v1/overview?mode=tz")
        self._get_json("/v1/signals?mode=tz&limit=5")
        status_m, payload_m = self._get_json("/api/admin/runtime/http-metrics")
        self.assertEqual(status_m, 200)
        self.assertTrue(payload_m.get("ok"))
        self.assertIn("total_requests", payload_m)
        self.assertGreaterEqual(int(payload_m.get("total_requests") or 0), 1)
        self.assertIn("latency_ms", payload_m)
        latency = payload_m.get("latency_ms") or {}
        self.assertIn("p95", latency)
        self.assertIn("p99", latency)
        self.assertIn("sse", payload_m)
        self.assertIn("top_routes", payload_m)

    def test_runtime_http_metrics_reset_endpoint(self) -> None:
        self._get_json("/healthz")
        self._get_json("/v1/overview?mode=tz")
        status_before, payload_before = self._get_json("/api/admin/runtime/http-metrics")
        self.assertEqual(status_before, 200)
        self.assertGreaterEqual(int(payload_before.get("total_requests") or 0), 1)

        status_reset, payload_reset = self._post_json("/api/admin/runtime/http-metrics/reset", {})
        self.assertEqual(status_reset, 200)
        self.assertTrue(payload_reset.get("ok"))
        self.assertEqual(int(payload_reset.get("total_requests") or 0), 0)

    def test_signal_engine_preview_runtime_cache_reuses_payload(self) -> None:
        cfg = {"fair_price": {"alpha": 0.7}}
        calls = {"n": 0}
        original = server.GiftAnalyticsService.list_variants

        def wrapped(svc, *args, **kwargs):
            calls["n"] += 1
            return original(svc, *args, **kwargs)

        with patch.object(server.GiftAnalyticsService, "list_variants", new=wrapped):
            first = server._signal_engine_signal_preview(limit=5, cfg=cfg)
            second = server._signal_engine_signal_preview(limit=5, cfg=cfg)
        self.assertTrue(first.get("ok"))
        self.assertEqual(first, second)
        self.assertEqual(calls["n"], 1)

    def test_admin_telegram_delivery_config_roundtrip(self) -> None:
        with patch.object(server, "_auth_user_from_request", return_value={"id": 144832201, "username": "alice"}):
            status_get, payload_get = self._get_json("/api/admin/telegram-delivery/config")
            self.assertEqual(status_get, 200)
            self.assertTrue(payload_get.get("ok"))
            self.assertIn("defaults", payload_get)
            self.assertIn("effective", payload_get)

            status_put, payload_put = self._put_json(
                "/api/admin/telegram-delivery/config",
                {
                    "enabled": True,
                    "market_status": {"enabled": True, "min_interval_sec": 600},
                    "gift_signal": {"enabled": True, "include_image": True},
                    "publish_gates": {"gift_signal_channel": {"edgeRank100_gte": 61, "conf_pct_gte": 42, "expected_profit_pct_gte": 11}},
                    "transport": {"rate_limit_per_minute": 13, "max_retries": 4, "retry_backoff_sec": 2.2},
                },
            )
            self.assertEqual(status_put, 200)
            effective = payload_put.get("effective") or {}
            signal_gate = ((effective.get("publish_gates") or {}).get("gift_signal_channel") or {}) if isinstance(effective, dict) else {}
            self.assertEqual(int(signal_gate.get("edgeRank100_gte") or 0), 61)
            self.assertEqual(int(signal_gate.get("conf_pct_gte") or 0), 42)
            self.assertEqual(int(signal_gate.get("expected_profit_pct_gte") or 0), 11)

            status_reset, payload_reset = self._post_json("/api/admin/telegram-delivery/config/reset", {})
            self.assertEqual(status_reset, 200)
            self.assertTrue(payload_reset.get("ok"))

    def test_admin_telegram_delivery_status_and_test_preview(self) -> None:
        with patch.object(server, "_auth_user_from_request", return_value={"id": 144832201, "username": "alice"}), patch.object(server._STATE.telegram_notifier, "send_test", return_value={"ok": True, "kind": "gift_signal", "preview": "GiftMarketZone • BUY", "sent": True}):
            status_s, payload_s = self._get_json("/api/admin/telegram-delivery/status")
            self.assertEqual(status_s, 200)
            self.assertTrue(payload_s.get("ok"))
            self.assertIn("configured", payload_s)
            self.assertIn("stats", payload_s)

            status_j, payload_j = self._get_json("/api/admin/telegram-delivery/journal?limit=5")
            self.assertEqual(status_j, 200)
            self.assertTrue(payload_j.get("ok"))
            self.assertIn("sent", payload_j)
            self.assertIn("failed", payload_j)

            status_r, payload_r = self._get_json("/api/admin/telegram-delivery/recommendation")
            self.assertEqual(status_r, 200)
            self.assertTrue(payload_r.get("ok"))
            self.assertIn("recommended", payload_r)

            status_t, payload_t = self._post_json("/api/admin/telegram-delivery/test", {"kind": "gift_signal"})
            self.assertEqual(status_t, 200)
            self.assertTrue(payload_t.get("ok"))
            self.assertEqual(str(payload_t.get("kind") or ""), "gift_signal")
            self.assertIn("GiftMarketZone", str(payload_t.get("preview") or ""))

    def test_admin_telegram_delivery_apply_recommendation_updates_gate(self) -> None:
        with patch.object(server, "_auth_user_from_request", return_value={"id": 144832201, "username": "alice"}), patch.object(server._STATE, "telegram_delivery_gate_recommendation_v1", return_value={"ok": True, "recommended": {"edgeRank100_gte": 1.0, "conf_pct_gte": 10.0, "expected_profit_pct_gte": 0.0}, "current_pass_count": 0, "recommended_pass_count": 12}):
            status_apply, payload_apply = self._post_json("/api/admin/telegram-delivery/recommendation/apply", {})
        self.assertEqual(status_apply, 200)
        self.assertTrue(payload_apply.get("ok"))
        self.assertEqual(float(((payload_apply.get("recommended") or {}).get("edgeRank100_gte")) or 0.0), 1.0)

    def test_telegram_delivery_endpoints_require_allowed_telegram_user(self) -> None:
        with patch.object(server, "_auth_user_from_request", return_value=None):
            with self.assertRaises(HTTPError) as cm_anon:
                urlopen(f"http://127.0.0.1:{self.port}/api/admin/telegram-delivery/status", timeout=10)
        self.assertEqual(cm_anon.exception.code, 401)

        with patch.object(server, "_auth_user_from_request", return_value={"id": 77, "username": "operator"}):
            with self.assertRaises(HTTPError) as cm_forbidden:
                urlopen(f"http://127.0.0.1:{self.port}/api/admin/telegram-delivery/status", timeout=10)
        self.assertEqual(cm_forbidden.exception.code, 403)

        with patch.object(server, "_auth_user_from_request", return_value={"id": 144832201, "username": "operator"}):
            status_ok, payload_ok = self._get_json("/api/admin/telegram-delivery/status")
        self.assertEqual(status_ok, 200)
        self.assertTrue(payload_ok.get("ok"))

    def test_telegram_auth_session_is_non_blocking_and_owned_gifts_endpoint_uses_session(self) -> None:
        opener = self._cookie_opener()
        with patch.object(server.AUTH, "verify_telegram_payload", return_value=(True, "ok", {"id": 42, "username": "alice", "first_name": "Alice", "last_name": "Doe", "photo_url": "https://example.com/a.png", "auth_date": 1700000000})):
            req = Request(
                f"http://127.0.0.1:{self.port}/api/auth/telegram/verify",
                data=json.dumps({"id": 42, "hash": "x"}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with opener.open(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(payload.get("ok"))
            self.assertTrue(payload.get("authenticated"))

            with opener.open(f"http://127.0.0.1:{self.port}/api/auth/me", timeout=10) as resp_me:
                payload_me = json.loads(resp_me.read().decode("utf-8"))
            self.assertTrue(payload_me.get("authenticated"))
            self.assertEqual(int((payload_me.get("user") or {}).get("id") or 0), 42)

            with patch.object(server._STATE, "telegram_owned_gifts_v1", return_value={"ok": True, "authenticated": True, "source": "remote", "items": [{"gift_id": "g1", "collection": "snakebox"}]}):
                with opener.open(f"http://127.0.0.1:{self.port}/api/auth/telegram/owned-gifts", timeout=10) as resp_owned:
                    payload_owned = json.loads(resp_owned.read().decode("utf-8"))
            self.assertTrue(payload_owned.get("ok"))
            self.assertTrue(payload_owned.get("authenticated"))
            self.assertEqual(str((payload_owned.get("items") or [])[0].get("gift_id") or ""), "g1")

    def test_owned_gifts_endpoint_passes_wallet_context_to_backend(self) -> None:
        with patch.object(server, "_auth_user_from_request", return_value={"id": 144832201, "username": "alice"}), patch.object(server, "_ton_wallet_from_request", return_value={"address": "EQWALLET"}), patch.object(server._STATE, "telegram_owned_gifts_v1", return_value={"ok": True, "authenticated": True, "items": [], "source": "wallet_holdings_empty"}) as mocked:
            status, payload = self._get_json("/api/auth/telegram/owned-gifts")
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        args = mocked.call_args[0]
        self.assertEqual(args[0].get("id"), 144832201)
        self.assertEqual(args[1].get("address"), "EQWALLET")

    def test_telegram_owned_gifts_endpoint_is_safe_for_anonymous_users(self) -> None:
        status, payload = self._get_json("/api/auth/telegram/owned-gifts")
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertFalse(payload.get("authenticated"))
        self.assertEqual(payload.get("items"), [])

    def test_trades_endpoints_roundtrip_for_allowed_test_user(self) -> None:
        allowed_user = {"id": 144832201, "username": "tester"}
        ton_wallet = {"address": "EQTESTWALLET000000000000000000000000000000000"}
        variant_id = str(next(iter((server._STATE.variants or {}).keys()), ""))
        self.assertTrue(variant_id)
        with patch.object(server, "_auth_user_from_request", return_value=allowed_user), patch.object(server, "_ton_wallet_from_request", return_value=ton_wallet):
            status_access, payload_access = self._get_json("/api/trades/access")
            self.assertEqual(status_access, 200)
            self.assertTrue(payload_access.get("allowed"))

            status_quote, payload_quote = self._get_json(f"/v1/trades/quotes/buy?variant_id={quote(variant_id)}&max_price_ton=8.5&wallet_address={ton_wallet['address']}")
            self.assertEqual(status_quote, 200)
            self.assertTrue(str(payload_quote.get("buy_quote_token") or ""))

            status_create, payload_create = self._post_json("/v1/trades/intents", {
                "intent_type": "BUY",
                "variant_id": variant_id,
                "wallet_address": ton_wallet["address"],
                "max_spend_ton": 8.5,
            })
            self.assertEqual(status_create, 200)
            intent_id = str(((payload_create.get("intent") or {}).get("intent_id")) or "")
            self.assertTrue(intent_id)

            status_confirm, payload_confirm = self._post_json(f"/v1/trades/intents/{intent_id}/confirm_signature", {"tx_hash": "tx_test_1", "wallet_address": ton_wallet["address"]})
            self.assertEqual(status_confirm, 200)
            self.assertEqual(str(payload_confirm.get("status") or ""), "CONFIRMED")

            status_positions, payload_positions = self._get_json(f"/v1/trades/positions?wallet_address={ton_wallet['address']}")
            self.assertEqual(status_positions, 200)
            self.assertTrue(isinstance(payload_positions.get("items"), list))

            status_holdings, payload_holdings = self._get_json(f"/v1/trades/holdings?wallet_address={ton_wallet['address']}")
            self.assertEqual(status_holdings, 200)
            self.assertTrue(isinstance(payload_holdings.get("items"), list))

            status_chain_create, payload_chain_create = self._post_json("/v1/trades/intents", {
                "intent_type": "BUY_AND_LIST",
                "variant_id": variant_id,
                "wallet_address": ton_wallet["address"],
                "max_spend_ton": 9.1,
                "chain_policy": "BUY_THEN_LIST",
                "post_action": {"type": "LIST", "listing_params": {"list_price_ton": 10.2, "duration_sec": 86400, "marketplace": "fragment"}},
            })
            self.assertEqual(status_chain_create, 200)
            chain_intent_id = str(((payload_chain_create.get("intent") or {}).get("intent_id")) or "")
            self.assertTrue(chain_intent_id)

            status_chain_confirm, payload_chain_confirm = self._post_json(f"/v1/trades/intents/{chain_intent_id}/confirm_signature", {"tx_hash": "tx_test_chain", "wallet_address": ton_wallet["address"]})
            self.assertEqual(status_chain_confirm, 200)
            self.assertEqual(str(payload_chain_confirm.get("status") or ""), "CONFIRMED")

            status_history, payload_history = self._get_json(f"/v1/trades/intents?wallet_address={ton_wallet['address']}")
            self.assertEqual(status_history, 200)
            rows = payload_history.get("items") or []
            child = next((x for x in rows if str((x or {}).get("parent_intent_id") or "") == chain_intent_id), None)
            self.assertTrue(isinstance(child, dict))
            self.assertEqual(str((child or {}).get("intent_type") or ""), "LIST")

            status_rules_before, payload_rules_before = self._get_json(f"/v1/trades/autosell/rules?wallet_address={ton_wallet['address']}")
            self.assertEqual(status_rules_before, 200)
            initial_rules = len(payload_rules_before.get("items") or [])

            status_rule_upsert, payload_rule_upsert = self._post_json("/v1/trades/autosell/rules", {
                "rule_id": "rule-test-signal-exit",
                "wallet_address": ton_wallet["address"],
                "enabled": True,
                "scope": "*",
                "trigger_type": "SIGNAL_EXIT",
                "params": {"edgeRank100_min": 55, "conf_pct_min": 35},
                "mode": "NOTIFY_ONLY",
                "cooldown_sec": 120,
                "priority": 5,
            })
            self.assertEqual(status_rule_upsert, 200)
            self.assertEqual(str(payload_rule_upsert.get("rule_id") or ""), "rule-test-signal-exit")

            status_rules_after, payload_rules_after = self._get_json(f"/v1/trades/autosell/rules?wallet_address={ton_wallet['address']}")
            self.assertEqual(status_rules_after, 200)
            self.assertGreaterEqual(len(payload_rules_after.get("items") or []), initial_rules)
            self.assertTrue(any(str((x or {}).get("rule_id") or "") == "rule-test-signal-exit" for x in (payload_rules_after.get("items") or [])))

            status_activity, payload_activity = self._get_json(f"/v1/wallet/activity?address={ton_wallet['address']}")
            self.assertEqual(status_activity, 200)
            self.assertTrue(isinstance(payload_activity.get("items"), list))

    def test_bridge_owned_gifts_endpoint_returns_user_inventory_payload(self) -> None:
        old_token = server.BRIDGE_API_TOKEN
        try:
            server.BRIDGE_API_TOKEN = "bridge-token"
            with patch.object(server._STATE, "owned_gifts_bridge_v1", return_value={"ok": True, "items": [{"gift_id": "g42", "variant_id": "x|m|b|p"}], "source": "local_file"}):
                status, payload = self._get_json("/bridge/gifts/owned?telegram_user_id=42&username=alice&token=bridge-token")
        finally:
            server.BRIDGE_API_TOKEN = old_token
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(str((payload.get("items") or [])[0].get("gift_id") or ""), "g42")

    def test_tz_gates_runtime_cache_reuses_payload(self) -> None:
        calls = {"n": 0}

        def fake_run(*args, **kwargs):
            calls["n"] += 1
            return {
                "source": "local",
                "gates_passed": True,
                "distribution": {"BUY": 1, "WATCH": 10, "SKIP": 90, "SELL": 0},
            }

        with patch("scripts.backtest_tz_signals.run", new=fake_run):
            first = server._build_tz_gates_payload_runtime()
            second = server._build_tz_gates_payload_runtime()
        self.assertTrue(first.get("ok"))
        self.assertEqual(first, second)
        self.assertEqual(calls["n"], 1)

    def test_metrics_endpoint_listing_pressure_market_success(self) -> None:
        status, payload = self._get_json("/v1/metrics?metric=LISTING_PRESSURE&scope=MARKET")
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("metric"), "LISTING_PRESSURE")
        self.assertEqual(payload.get("scope"), "MARKET")
        self.assertIn("points", payload)
        self.assertTrue(isinstance(payload.get("points"), list))

    def test_screeners_feed_filters_and_cursor(self) -> None:
        status1, payload1 = self._get_json("/v1/screeners/feed?limit=2")
        self.assertEqual(status1, 200)
        self.assertIn("items", payload1)
        self.assertTrue(isinstance(payload1.get("items"), list))
        self.assertLessEqual(len(payload1.get("items") or []), 2)
        next_cursor = payload1.get("next_cursor")
        if next_cursor:
            status2, payload2 = self._get_json(f"/v1/screeners/feed?limit=2&cursor={quote(str(next_cursor))}")
            self.assertEqual(status2, 200)
            self.assertIn("items", payload2)
            self.assertTrue(isinstance(payload2.get("items"), list))

        status_buy, payload_buy = self._get_json("/v1/screeners/feed?limit=20&action=BUY")
        self.assertEqual(status_buy, 200)
        self.assertIn("items", payload_buy)
        self.assertTrue(isinstance(payload_buy.get("items"), list))
        for row in payload_buy.get("items") or []:
            self.assertEqual(str((row or {}).get("action") or "").upper(), "BUY")

    def test_catalog_feed_and_variant_endpoint_success(self) -> None:
        status, payload = self._get_json("/v1/catalog/feed?limit=5")
        self.assertEqual(status, 200)
        self.assertIn("items", payload)
        self.assertTrue(isinstance(payload.get("items"), list))
        self.assertLessEqual(len(payload.get("items") or []), 5)
        rows = payload.get("items") or []
        if rows:
            vid = str((rows[0] or {}).get("variant_id") or "")
            if vid:
                status_v, payload_v = self._get_json(f"/v1/catalog/variant/{quote(vid)}")
                self.assertEqual(status_v, 200)
                self.assertEqual(str(payload_v.get("variant_id") or ""), vid)
                self.assertIn("listings_10m", payload_v)
                self.assertIn("volume_24h_ton", payload_v)
                self.assertIn("floor_history", payload_v)

        status_f, payload_f = self._get_json("/v1/catalog/feed?limit=20&preset=TOP_BUY")
        self.assertEqual(status_f, 200)
        self.assertIn("items", payload_f)

    def test_catalog_feed_sort_dir_and_filters(self) -> None:
        status, payload = self._get_json("/v1/catalog/feed?limit=10&sort=updated&dir=desc&action=WATCH")
        self.assertEqual(status, 200)
        self.assertIn("items", payload)
        rows = payload.get("items") or []
        self.assertTrue(isinstance(rows, list))
        for row in rows:
            self.assertEqual(str((row or {}).get("action") or "").upper(), "WATCH")

        with self.assertRaises(HTTPError) as cm_bad_sort:
            urlopen(f"http://127.0.0.1:{self.port}/v1/catalog/feed?sort=unknown", timeout=10)
        self.assertEqual(cm_bad_sort.exception.code, 400)

    def test_catalog_stream_endpoint_success(self) -> None:
        with urlopen(
            f"http://127.0.0.1:{self.port}/v1/stream/catalog?heartbeat=5000&limit=5",
            timeout=12,
        ) as resp:
            self.assertEqual(resp.status, 200)
            content_type = str(resp.headers.get("Content-Type") or "")
            self.assertIn("text/event-stream", content_type)

    def test_static_assets_are_served_from_assets_directory(self) -> None:
        status_index, _, _ = self._get_json_with_headers("/healthz")
        self.assertEqual(status_index, 200)
        with urlopen(f"http://127.0.0.1:{self.port}/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        self.assertIn('/assets/', html)
        marker = 'src="/assets/'
        start = html.find(marker)
        self.assertGreaterEqual(start, 0)
        start += len('src="')
        end = html.find('"', start)
        asset_path = html[start:end]
        with urlopen(f"http://127.0.0.1:{self.port}{asset_path}", timeout=10) as resp_asset:
            body = resp_asset.read().decode("utf-8")
            self.assertEqual(resp_asset.status, 200)
            self.assertTrue(len(body) > 100)

    def test_static_assets_support_head_requests(self) -> None:
        with urlopen(f"http://127.0.0.1:{self.port}/", timeout=10) as resp:
            html = resp.read().decode("utf-8")
        marker = 'src="/assets/'
        start = html.find(marker)
        self.assertGreaterEqual(start, 0)
        start += len('src="')
        end = html.find('"', start)
        asset_path = html[start:end]
        req = Request(f"http://127.0.0.1:{self.port}{asset_path}", method="HEAD")
        with urlopen(req, timeout=10) as resp_head:
            self.assertEqual(resp_head.status, 200)
            self.assertIn('application/javascript', str(resp_head.headers.get('Content-Type') or ''))

    def test_stale_hashed_asset_falls_back_to_latest_matching_chunk(self) -> None:
        stale = '/assets/OverviewPage-OLDHASH.js'
        req = Request(f"http://127.0.0.1:{self.port}{stale}", method='GET')
        with urlopen(req, timeout=10) as resp:
            body = resp.read().decode('utf-8')
        self.assertEqual(resp.status, 200)
        self.assertIn('PageHeader', body)

    def test_legacy_signal_bot_is_not_enabled_by_default(self) -> None:
        self.assertFalse(server.BOT_AUTORUN)

    def test_catalog_stream_endpoint_emits_contract_event(self) -> None:
        svc = server._STATE
        assert isinstance(svc, GiftAnalyticsService)
        row = {
            "variant_id": "stream|catalog|variant",
            "variant_label": "Stream Catalog Variant",
            "floor_ton": 5.0,
            "fair_ton": 7.0,
            "score100": 72.0,
            "conf_pct": 44.0,
            "edgeRank100": 63.0,
            "market_regime": "MEAN_REVERT",
            "action": "BUY",
            "updated_at": "2026-03-05T12:00:00Z",
        }
        item = {"event_id": "cat:test:1:stream|catalog|variant", "ts": "2026-03-05T12:00:01Z", "payload": row}
        with patch.object(svc, "catalog_stream_events_v1", return_value={"items": [item]}):
            status, content_type, lines = self._read_sse_message("/v1/stream/catalog?heartbeat=5000&limit=5")

        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", content_type)
        self.assertGreaterEqual(len(lines), 3)
        self.assertEqual(lines[0], "event: catalog.row")
        self.assertEqual(lines[1], "id: cat:test:1:stream|catalog|variant")
        self.assertTrue(lines[2].startswith("data: "))

        payload = json.loads(lines[2][6:])
        self.assertEqual(payload.get("event"), "catalog.row")
        self.assertEqual(payload.get("ts"), "2026-03-05T12:00:01Z")
        self.assertTrue(isinstance(payload.get("payload"), dict))
        event_payload = payload.get("payload") or {}
        self.assertEqual(event_payload.get("variant_id"), "stream|catalog|variant")
        self.assertEqual(event_payload.get("action"), "BUY")
        self.assertEqual(event_payload.get("market_regime"), "MEAN_REVERT")
        self.assertNotIn("_stream_event_id", event_payload)
        self.assertNotIn("_stream_emitted_at", event_payload)

    def test_collections_variants_signals_endpoints_success_and_404(self) -> None:
        status_col, payload_col = self._get_json("/v1/collections?limit=1")
        self.assertEqual(status_col, 200)
        self.assertIn("items", payload_col)
        self.assertTrue(isinstance(payload_col.get("items"), list))
        self.assertTrue(payload_col.get("items"))
        col_item = payload_col["items"][0]
        self.assertIn("collection_id", col_item)

        collection_id = str(col_item.get("collection_id") or "")
        status_col_d, payload_col_d = self._get_json(f"/v1/collections/{quote(collection_id)}")
        self.assertEqual(status_col_d, 200)
        self.assertIn("collection", payload_col_d)
        self.assertIn("top_variants", payload_col_d)

        self.assertIn("floor_series", payload_col_d)

        status_var, payload_var = self._get_json("/v1/variants?limit=1")
        self.assertEqual(status_var, 200)
        self.assertIn("items", payload_var)
        self.assertTrue(payload_var.get("items"))
        var_item = payload_var["items"][0]
        self.assertIn("variant_id", var_item)

        variant_id = str(var_item.get("variant_id") or "")
        status_var_d, payload_var_d = self._get_json(f"/v1/variants/{quote(variant_id)}")
        self.assertEqual(status_var_d, 200)
        self.assertIn("variant", payload_var_d)
        self.assertIn("listings", payload_var_d)
        self.assertIn("breakdown", payload_var_d)

        resolve_q = (
            f"/v1/variants/resolve?collection_id={quote(str(var_item.get('collection_id') or ''))}"
            f"&model={quote(str(var_item.get('model') or ''))}"
            f"&background={quote(str(var_item.get('background') or ''))}"
            f"&pattern={quote(str(var_item.get('pattern') or ''))}"
            "&active_only=false"
        )
        status_resolve, payload_resolve = self._get_json(resolve_q)
        self.assertEqual(status_resolve, 200)
        self.assertIn("variant_id", payload_resolve)
        self.assertTrue(str(payload_resolve.get("variant_id") or ""))
        with self.assertRaises(HTTPError) as cm_resolve_bad:
            urlopen(f"http://127.0.0.1:{self.port}/v1/variants/resolve?model=domino", timeout=10)
        self.assertEqual(cm_resolve_bad.exception.code, 400)

        status_sig, payload_sig = self._get_json("/v1/signals?limit=20")
        self.assertEqual(status_sig, 200)
        self.assertIn("items", payload_sig)
        self.assertIn("total_count", payload_sig)
        self.assertTrue(isinstance(payload_sig.get("total_count"), int))
        self.assertTrue(isinstance(payload_sig.get("items"), list))
        seeded_signal = next(
            (
                row
                for row in (payload_sig.get("items") or [])
                if str((row or {}).get("variant_id") or "") == "x|m|b|p"
            ),
            None,
        )
        if isinstance(seeded_signal, dict):
            sig_id = str(seeded_signal.get("signal_id") or "")
            status_sig_d, payload_sig_d = self._get_json(f"/v1/signals/{quote(sig_id)}")
            self.assertEqual(status_sig_d, 200)
            self.assertEqual(str(payload_sig_d.get("signal_id") or ""), sig_id)

        with self.assertRaises(HTTPError) as cm_col_404:
            urlopen(f"http://127.0.0.1:{self.port}/v1/collections/does-not-exist", timeout=10)
        self.assertEqual(cm_col_404.exception.code, 404)

        with self.assertRaises(HTTPError) as cm_var_404:
            urlopen(f"http://127.0.0.1:{self.port}/v1/variants/does-not-exist", timeout=10)
        self.assertEqual(cm_var_404.exception.code, 404)

    def test_screeners_feed_endpoint_success(self) -> None:
        status, payload = self._get_json("/v1/screeners/feed?limit=10")
        self.assertEqual(status, 200)
        self.assertIn("items", payload)
        self.assertTrue(isinstance(payload.get("items"), list))
        if payload["items"]:
            row = payload["items"][0]
            for key in ("ts", "screener_type", "variant_id", "variant_label", "edgeRank100", "score100", "conf_pct", "market_regime", "action"):
                self.assertIn(key, row)

    def test_signals_calibration_report_endpoint(self) -> None:
        status, payload = self._get_json("/v1/signals/calibration/report?mode=tz&horizon_hours=24&limit=200")
        self.assertEqual(status, 200)
        self.assertIn("mode", payload)
        self.assertIn("distribution", payload)
        self.assertIn("quality", payload)
        self.assertIn("gate_checks", payload)
        self.assertIn("gates_passed", payload)

    def test_signals_calibration_report_rejects_invalid_params(self) -> None:
        with self.assertRaises(HTTPError) as cm_mode:
            urlopen(f"http://127.0.0.1:{self.port}/v1/signals/calibration/report?mode=foo", timeout=10)
        self.assertEqual(cm_mode.exception.code, 400)
        payload_mode = json.loads(cm_mode.exception.read().decode("utf-8"))
        self.assertIn("unsupported_mode", str(payload_mode.get("error") or ""))

        with self.assertRaises(HTTPError) as cm_horizon:
            urlopen(f"http://127.0.0.1:{self.port}/v1/signals/calibration/report?horizon_hours=999", timeout=10)
        self.assertEqual(cm_horizon.exception.code, 400)
        payload_horizon = json.loads(cm_horizon.exception.read().decode("utf-8"))
        self.assertIn("invalid_horizon_range", str(payload_horizon.get("error") or ""))

    def test_signals_http_layer_applies_action_filter_compat(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        fake_payload = {
            "items": [
                {"signal_id": "s-buy", "type": "BUY", "ts": now_iso, "score100": 90, "conf_pct": 90, "expected_profit_pct": 12, "edgeRank100": 70},
                {"signal_id": "s-sell", "type": "SELL", "ts": now_iso, "score100": 90, "conf_pct": 90, "expected_profit_pct": 12, "edgeRank100": 70},
                {"signal_id": "s-watch", "type": "WATCH", "ts": now_iso, "score100": 60, "conf_pct": 40, "expected_profit_pct": 2, "edgeRank100": 30},
            ],
            "total_count": 3,
            "next_cursor": "opaque",
            "has_more": True,
            "engine_mode": "tz",
        }
        with patch.object(GiftAnalyticsService, "signals_v1", return_value=fake_payload):
            status, payload = self._get_json("/v1/signals?action=SELL&limit=50")
        self.assertEqual(status, 200)
        items = payload.get("items") or []
        self.assertEqual(len(items), 1)
        self.assertEqual(str(items[0].get("type") or ""), "SELL")
        self.assertEqual(int(payload.get("total_count") or 0), 1)
        self.assertIsNone(payload.get("next_cursor"))
        self.assertFalse(bool(payload.get("has_more")))

    def test_signals_http_layer_applies_type_filter_compat(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        fake_payload = {
            "items": [
                {"signal_id": "s-buy", "type": "BUY", "ts": now_iso, "score100": 90, "conf_pct": 90, "expected_profit_pct": 12, "edgeRank100": 70},
                {"signal_id": "s-sell", "type": "SELL", "ts": now_iso, "score100": 90, "conf_pct": 90, "expected_profit_pct": 12, "edgeRank100": 70},
            ],
            "total_count": 2,
            "next_cursor": "opaque",
            "has_more": True,
            "engine_mode": "tz",
        }
        with patch.object(GiftAnalyticsService, "signals_v1", return_value=fake_payload):
            status, payload = self._get_json("/v1/signals?type=SELL&limit=50")
        self.assertEqual(status, 200)
        items = payload.get("items") or []
        self.assertEqual(len(items), 1)
        self.assertEqual(str(items[0].get("type") or ""), "SELL")
        self.assertEqual(int(payload.get("total_count") or 0), 1)
        self.assertIsNone(payload.get("next_cursor"))
        self.assertFalse(bool(payload.get("has_more")))

    def test_signals_http_layer_applies_only_new_1h_filter_compat(self) -> None:
        now = datetime.now(timezone.utc)
        old_iso = (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        new_iso = now.isoformat().replace("+00:00", "Z")
        fake_payload = {
            "items": [
                {"signal_id": "s-old", "type": "BUY", "ts": old_iso, "score100": 80, "conf_pct": 80, "expected_profit_pct": 10, "edgeRank100": 70},
                {"signal_id": "s-new", "type": "BUY", "ts": new_iso, "score100": 80, "conf_pct": 80, "expected_profit_pct": 10, "edgeRank100": 70},
            ],
            "total_count": 2,
            "next_cursor": "opaque",
            "has_more": True,
            "engine_mode": "tz",
        }
        with patch.object(GiftAnalyticsService, "signals_v1", return_value=fake_payload):
            status, payload = self._get_json("/v1/signals?only_new_1h=true&limit=50")
        self.assertEqual(status, 200)
        items = payload.get("items") or []
        self.assertEqual(len(items), 1)
        self.assertEqual(str(items[0].get("signal_id") or ""), "s-new")
        self.assertEqual(int(payload.get("total_count") or 0), 1)

    def test_listing_source_status_endpoint_uses_cached_mode_without_remote_probe(self) -> None:
        svc = server._STATE
        self.assertTrue(isinstance(svc, GiftAnalyticsService))
        with patch.object(
            svc,
            "listing_source_status_v1",
            return_value={"source": "mtproto_api", "rows_count": 10, "degraded": False},
        ) as mocked:
            status, payload = self._get_json("/api/listing/source-status")
        self.assertEqual(status, 200)
        self.assertEqual(str(payload.get("source") or ""), "mtproto_api")
        mocked.assert_called_once()
        _, kwargs = mocked.call_args
        self.assertFalse(bool(kwargs.get("allow_remote", True)))

    def test_listing_source_status_v1_alias_uses_cached_mode_without_remote_probe(self) -> None:
        svc = server._STATE
        self.assertTrue(isinstance(svc, GiftAnalyticsService))
        with patch.object(
            svc,
            "listing_source_status_v1",
            return_value={"source": "mtproto_api", "rows_count": 12, "degraded": False, "status": "ok"},
        ) as mocked:
            status, payload = self._get_json("/v1/listings/source-status")
        self.assertEqual(status, 200)
        self.assertEqual(str(payload.get("source") or ""), "mtproto_api")
        self.assertEqual(str(payload.get("status") or ""), "ok")
        mocked.assert_called_once()
        _, kwargs = mocked.call_args
        self.assertFalse(bool(kwargs.get("allow_remote", True)))

    def test_metrics_endpoint_tz_strict_mode_success(self) -> None:
        status, payload = self._get_json(
            f"/v1/metrics?metric=EDGE_SCORE&scope=VARIANT&variant_id={quote('x|m|b|p')}&mode=tz_strict"
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("metric"), "EDGE_SCORE")
        self.assertEqual(payload.get("scope"), "VARIANT")
        self.assertEqual(payload.get("variant_id"), "x|m|b|p")
        self.assertIn("points", payload)
        self.assertTrue(isinstance(payload.get("points"), list))
        self.assertGreaterEqual(len(payload.get("points") or []), 1)

    def test_metrics_endpoint_bad_request(self) -> None:
        with self.assertRaises(HTTPError) as cm:
            urlopen(f"http://127.0.0.1:{self.port}/v1/metrics?metric=UNKNOWN", timeout=10)
        self.assertEqual(cm.exception.code, 400)
        payload = json.loads(cm.exception.read().decode("utf-8"))
        self.assertFalse(payload.get("ok", True))
        self.assertIn("unsupported_metric", str(payload.get("error") or ""))

    def test_metrics_endpoint_scope_mismatch(self) -> None:
        with self.assertRaises(HTTPError) as cm:
            urlopen(
                f"http://127.0.0.1:{self.port}/v1/metrics?metric=MARKET_INDEX&scope=VARIANT&variant_id="
                f"{quote('x|m|b|p')}",
                timeout=10,
            )
        self.assertEqual(cm.exception.code, 400)
        payload = json.loads(cm.exception.read().decode("utf-8"))
        self.assertIn("metric_scope_mismatch", str(payload.get("error") or ""))

    def test_metrics_endpoint_rejects_unsupported_interval(self) -> None:
        with self.assertRaises(HTTPError) as cm:
            urlopen(
                f"http://127.0.0.1:{self.port}/v1/metrics?metric=FLOOR_HISTORY&scope=MARKET&interval=30m",
                timeout=10,
            )
        self.assertEqual(cm.exception.code, 400)
        payload = json.loads(cm.exception.read().decode("utf-8"))
        self.assertIn("unsupported_interval", str(payload.get("error") or ""))

    def test_variants_endpoint_rejects_invalid_action(self) -> None:
        with self.assertRaises(HTTPError) as cm:
            urlopen(f"http://127.0.0.1:{self.port}/v1/variants?action=HOLD", timeout=10)
        self.assertEqual(cm.exception.code, 400)
        payload = json.loads(cm.exception.read().decode("utf-8"))
        self.assertIn("unsupported_action", str(payload.get("error") or ""))

    def test_variants_endpoint_rejects_invalid_sort_and_min_score(self) -> None:
        with self.assertRaises(HTTPError) as cm_sort:
            urlopen(f"http://127.0.0.1:{self.port}/v1/variants?sort=floor_asc", timeout=10)
        self.assertEqual(cm_sort.exception.code, 400)
        payload_sort = json.loads(cm_sort.exception.read().decode("utf-8"))
        self.assertIn("unsupported_sort", str(payload_sort.get("error") or ""))

        with self.assertRaises(HTTPError) as cm_score:
            urlopen(f"http://127.0.0.1:{self.port}/v1/variants?min_score=1.1", timeout=10)
        self.assertEqual(cm_score.exception.code, 400)
        payload_score = json.loads(cm_score.exception.read().decode("utf-8"))
        self.assertIn("invalid_min_score_range", str(payload_score.get("error") or ""))

    def test_signals_endpoint_rejects_invalid_type(self) -> None:
        with self.assertRaises(HTTPError) as cm:
            urlopen(f"http://127.0.0.1:{self.port}/v1/signals?type=LONG", timeout=10)
        self.assertEqual(cm.exception.code, 400)
        payload = json.loads(cm.exception.read().decode("utf-8"))
        self.assertIn("unsupported_signal_type", str(payload.get("error") or ""))

    def test_signals_endpoint_rejects_invalid_min_score(self) -> None:
        with self.assertRaises(HTTPError) as cm:
            urlopen(f"http://127.0.0.1:{self.port}/v1/signals?min_score=-0.1", timeout=10)
        self.assertEqual(cm.exception.code, 400)
        payload = json.loads(cm.exception.read().decode("utf-8"))
        self.assertIn("invalid_min_score_range", str(payload.get("error") or ""))

    def test_signals_endpoint_rejects_invalid_max_risk(self) -> None:
        with self.assertRaises(HTTPError) as cm:
            urlopen(f"http://127.0.0.1:{self.port}/v1/signals?max_risk=1.5", timeout=10)
        self.assertEqual(cm.exception.code, 400)
        payload = json.loads(cm.exception.read().decode("utf-8"))
        self.assertIn("invalid_max_risk_range", str(payload.get("error") or ""))

    def test_signals_endpoint_rejects_invalid_min_undervalue(self) -> None:
        with self.assertRaises(HTTPError) as cm:
            urlopen(f"http://127.0.0.1:{self.port}/v1/signals?min_undervalue_pct=-1", timeout=10)
        self.assertEqual(cm.exception.code, 400)
        payload = json.loads(cm.exception.read().decode("utf-8"))
        self.assertIn("invalid_min_undervalue_pct_range", str(payload.get("error") or ""))

    def test_metrics_endpoint_rejects_unsupported_scope(self) -> None:
        with self.assertRaises(HTTPError) as cm:
            urlopen(f"http://127.0.0.1:{self.port}/v1/metrics?metric=MARKET_INDEX&scope=WORLD", timeout=10)
        self.assertEqual(cm.exception.code, 400)
        payload = json.loads(cm.exception.read().decode("utf-8"))
        self.assertIn("unsupported_scope", str(payload.get("error") or ""))

    def test_endpoint_limit_validation_ranges(self) -> None:
        with self.assertRaises(HTTPError) as cm_col:
            urlopen(f"http://127.0.0.1:{self.port}/v1/collections?limit=201", timeout=10)
        self.assertEqual(cm_col.exception.code, 400)
        payload_col = json.loads(cm_col.exception.read().decode("utf-8"))
        self.assertIn("invalid_limit_range", str(payload_col.get("error") or ""))

        with self.assertRaises(HTTPError) as cm_var:
            urlopen(f"http://127.0.0.1:{self.port}/v1/variants?limit=0", timeout=10)
        self.assertEqual(cm_var.exception.code, 400)
        payload_var = json.loads(cm_var.exception.read().decode("utf-8"))
        self.assertIn("invalid_limit_range", str(payload_var.get("error") or ""))

        with self.assertRaises(HTTPError) as cm_sig:
            urlopen(f"http://127.0.0.1:{self.port}/v1/signals?limit=999", timeout=10)
        self.assertEqual(cm_sig.exception.code, 400)
        payload_sig = json.loads(cm_sig.exception.read().decode("utf-8"))
        self.assertIn("invalid_limit_range", str(payload_sig.get("error") or ""))

        with self.assertRaises(HTTPError) as cm_met:
            urlopen(f"http://127.0.0.1:{self.port}/v1/metrics?metric=MARKET_INDEX&scope=MARKET&limit=9000", timeout=10)
        self.assertEqual(cm_met.exception.code, 400)
        payload_met = json.loads(cm_met.exception.read().decode("utf-8"))
        self.assertIn("invalid_limit_range", str(payload_met.get("error") or ""))

    def test_alerts_endpoint_requires_name_and_rule_json(self) -> None:
        with self.assertRaises(HTTPError) as cm_name:
            self._post_json("/v1/alerts", {"rule_json": {"foo": "bar"}})
        self.assertEqual(cm_name.exception.code, 400)
        payload_name = json.loads(cm_name.exception.read().decode("utf-8"))
        self.assertIn("name_required", str(payload_name.get("error") or ""))

        with self.assertRaises(HTTPError) as cm_rule:
            self._post_json("/v1/alerts", {"name": "my-alert", "rule_json": "bad"})
        self.assertEqual(cm_rule.exception.code, 400)
        payload_rule = json.loads(cm_rule.exception.read().decode("utf-8"))
        self.assertIn("rule_json_required", str(payload_rule.get("error") or ""))

    def test_favorites_and_alerts_success_contract(self) -> None:
        status_f_get_1, payload_f_get_1 = self._get_json("/v1/favorites")
        self.assertEqual(status_f_get_1, 200)
        self.assertTrue(isinstance(payload_f_get_1.get("items"), list))

        status_f_post, payload_f_post = self._post_json("/v1/favorites", {"variant_id": "x|m|b|p", "note": "watch"})
        self.assertEqual(status_f_post, 200)
        self.assertTrue(bool(payload_f_post.get("ok")))

        status_f_get_2, payload_f_get_2 = self._get_json("/v1/favorites")
        self.assertEqual(status_f_get_2, 200)
        items_f = payload_f_get_2.get("items") or []
        self.assertTrue(items_f)
        self.assertIn("variant_id", items_f[0])
        self.assertIn("created_at", items_f[0])

        status_f_del, payload_f_del = self._delete_json(f"/v1/favorites?variant_id={quote('x|m|b|p')}")
        self.assertEqual(status_f_del, 200)
        self.assertTrue(bool(payload_f_del.get("ok")))

        status_a_post, payload_a_post = self._post_json(
            "/v1/alerts",
            {"name": "my-alert", "rule_json": {"entity": {"type": "VARIANT", "id": "x|m|b|p"}}},
        )
        self.assertEqual(status_a_post, 200)
        self.assertTrue(bool(payload_a_post.get("ok")))

        status_a_get, payload_a_get = self._get_json("/v1/alerts")
        self.assertEqual(status_a_get, 200)
        items_a = payload_a_get.get("items") or []
        self.assertTrue(items_a)
        self.assertIn("rule_id", items_a[0])
        self.assertIn("name", items_a[0])
        self.assertIn("rule_json", items_a[0])
        self.assertIn("enabled", items_a[0])
        self.assertIn("created_at", items_a[0])

        with self.assertRaises(HTTPError) as cm_alert_test_bad:
            self._post_json("/v1/alerts/test", {})
        self.assertEqual(cm_alert_test_bad.exception.code, 400)
        payload_alert_test_bad = json.loads(cm_alert_test_bad.exception.read().decode("utf-8"))
        self.assertIn("rule_id_required", str(payload_alert_test_bad.get("error") or ""))

        any_rule_id = str(items_a[0].get("rule_id") or "")
        status_alert_test_ok, payload_alert_test_ok = self._post_json("/v1/alerts/test", {"rule_id": any_rule_id})
        self.assertEqual(status_alert_test_ok, 200)
        self.assertTrue(bool(payload_alert_test_ok.get("ok")))

    def test_alerts_enabled_roundtrip_and_created_at(self) -> None:
        status_create, payload_create = self._post_json(
            "/v1/alerts",
            {
                "name": "disabled-alert",
                "rule_json": {"entity": {"type": "VARIANT", "id": "x|m|b|p"}},
                "enabled": False,
            },
        )
        self.assertEqual(status_create, 200)
        self.assertTrue(bool(payload_create.get("ok")))

        status_get, payload_get = self._get_json("/v1/alerts")
        self.assertEqual(status_get, 200)
        items = payload_get.get("items") or []
        self.assertTrue(items)
        target = next((x for x in items if str(x.get("name") or "") == "disabled-alert"), None)
        self.assertIsNotNone(target)
        assert target is not None
        self.assertFalse(bool(target.get("enabled")))
        self.assertTrue(bool(str(target.get("created_at") or "").strip()))

    def test_alerts_update_by_rule_id_without_duplicates(self) -> None:
        status_create, payload_create = self._post_json(
            "/v1/alerts",
            {
                "name": "alert-v1",
                "rule_json": {"entity": {"type": "VARIANT", "id": "x|m|b|p"}},
                "enabled": False,
            },
        )
        self.assertEqual(status_create, 200)
        self.assertTrue(bool(payload_create.get("ok")))

        _, before = self._get_json("/v1/alerts")
        before_items = before.get("items") or []
        self.assertEqual(len(before_items), 1)
        rule_id = str(before_items[0].get("rule_id") or "")
        self.assertTrue(rule_id)

        status_update, payload_update = self._post_json(
            "/v1/alerts",
            {
                "rule_id": rule_id,
                "name": "alert-v2",
                "rule_json": {"entity": {"type": "VARIANT", "id": "x|m|b|p"}, "threshold": 10},
                "enabled": True,
            },
        )
        self.assertEqual(status_update, 200)
        self.assertTrue(bool(payload_update.get("ok")))

        _, after = self._get_json("/v1/alerts")
        after_items = after.get("items") or []
        self.assertEqual(len(after_items), 1)
        updated = after_items[0]
        self.assertEqual(str(updated.get("rule_id") or ""), rule_id)
        self.assertEqual(str(updated.get("name") or ""), "alert-v2")
        self.assertTrue(bool(updated.get("enabled")))

    def test_favorites_delete_requires_variant_id(self) -> None:
        with self.assertRaises(HTTPError) as cm:
            self._delete_json("/v1/favorites")
        self.assertEqual(cm.exception.code, 400)
        payload = json.loads(cm.exception.read().decode("utf-8"))
        self.assertIn("variant_id_required", str(payload.get("error") or ""))

    def test_stream_endpoint_rejects_unknown_type(self) -> None:
        with self.assertRaises(HTTPError) as cm:
            urlopen(f"http://127.0.0.1:{self.port}/v1/stream?types=bad.type", timeout=10)
        self.assertEqual(cm.exception.code, 400)
        payload = json.loads(cm.exception.read().decode("utf-8"))
        self.assertEqual(payload.get("error"), "unsupported_stream_type")

    def test_stream_endpoint_rejects_invalid_heartbeat(self) -> None:
        with self.assertRaises(HTTPError) as cm_nonint:
            urlopen(f"http://127.0.0.1:{self.port}/v1/stream?heartbeat=abc", timeout=10)
        self.assertEqual(cm_nonint.exception.code, 400)
        payload_nonint = json.loads(cm_nonint.exception.read().decode("utf-8"))
        self.assertEqual(payload_nonint.get("error"), "invalid_heartbeat")

        with self.assertRaises(HTTPError) as cm_range:
            urlopen(f"http://127.0.0.1:{self.port}/v1/stream?heartbeat=1000", timeout=10)
        self.assertEqual(cm_range.exception.code, 400)
        payload_range = json.loads(cm_range.exception.read().decode("utf-8"))
        self.assertEqual(payload_range.get("error"), "invalid_heartbeat_range")

    def test_listings_stream_rejects_invalid_interval_sec(self) -> None:
        with self.assertRaises(HTTPError) as cm_nonint:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/stream?interval_sec=abc", timeout=10)
        self.assertEqual(cm_nonint.exception.code, 400)
        payload_nonint = json.loads(cm_nonint.exception.read().decode("utf-8"))
        self.assertEqual(payload_nonint.get("error"), "invalid_interval_sec")

        with self.assertRaises(HTTPError) as cm_range:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/stream?interval_sec=0.1", timeout=10)
        self.assertEqual(cm_range.exception.code, 400)
        payload_range = json.loads(cm_range.exception.read().decode("utf-8"))
        self.assertEqual(payload_range.get("error"), "invalid_interval_sec_range")

    def test_listings_stream_rejects_invalid_limit_and_window(self) -> None:
        with self.assertRaises(HTTPError) as cm_limit:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/stream?limit=0", timeout=10)
        self.assertEqual(cm_limit.exception.code, 400)
        payload_limit = json.loads(cm_limit.exception.read().decode("utf-8"))
        self.assertEqual(payload_limit.get("error"), "invalid_limit_range")

        with self.assertRaises(HTTPError) as cm_window_nonint:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/stream?new_window_sec=bad", timeout=10)
        self.assertEqual(cm_window_nonint.exception.code, 400)
        payload_window_nonint = json.loads(cm_window_nonint.exception.read().decode("utf-8"))
        self.assertEqual(payload_window_nonint.get("error"), "invalid_new_window_sec")

        with self.assertRaises(HTTPError) as cm_window_range:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/stream?new_window_sec=1", timeout=10)
        self.assertEqual(cm_window_range.exception.code, 400)
        payload_window_range = json.loads(cm_window_range.exception.read().decode("utf-8"))
        self.assertEqual(payload_window_range.get("error"), "invalid_new_window_sec_range")

    def test_stream_listings_rejects_invalid_params(self) -> None:
        with self.assertRaises(HTTPError) as cm_limit:
            urlopen(f"http://127.0.0.1:{self.port}/v1/stream/listings?limit=abc", timeout=10)
        self.assertEqual(cm_limit.exception.code, 400)
        payload_limit = json.loads(cm_limit.exception.read().decode("utf-8"))
        self.assertEqual(payload_limit.get("error"), "invalid_limit")

        with self.assertRaises(HTTPError) as cm_interval:
            urlopen(f"http://127.0.0.1:{self.port}/v1/stream/listings?interval_sec=0.1", timeout=10)
        self.assertEqual(cm_interval.exception.code, 400)
        payload_interval = json.loads(cm_interval.exception.read().decode("utf-8"))
        self.assertEqual(payload_interval.get("error"), "invalid_interval_sec_range")

        with self.assertRaises(HTTPError) as cm_window:
            urlopen(f"http://127.0.0.1:{self.port}/v1/stream/listings?window=bad", timeout=10)
        self.assertEqual(cm_window.exception.code, 400)
        payload_window = json.loads(cm_window.exception.read().decode("utf-8"))
        self.assertIn("unsupported_window", str(payload_window.get("error") or ""))

    def test_stream_listings_rejects_invalid_include_low_priority(self) -> None:
        with self.assertRaises(HTTPError) as cm:
            urlopen(f"http://127.0.0.1:{self.port}/v1/stream/listings?include_low_priority=maybe", timeout=10)
        self.assertEqual(cm.exception.code, 400)
        payload = json.loads(cm.exception.read().decode("utf-8"))
        self.assertEqual(payload.get("error"), "invalid_include_low_priority")

    def test_listings_stream_rejects_invalid_include_relisted(self) -> None:
        with self.assertRaises(HTTPError) as cm:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/stream?include_relisted=maybe", timeout=10)
        self.assertEqual(cm.exception.code, 400)
        payload = json.loads(cm.exception.read().decode("utf-8"))
        self.assertEqual(payload.get("error"), "invalid_include_relisted")

    def test_stream_endpoint_metric_updated_envelope(self) -> None:
        with urlopen(
            f"http://127.0.0.1:{self.port}/v1/stream?types=metric.updated&heartbeat=5000",
            timeout=12,
        ) as resp:
            self.assertEqual(resp.status, 200)
            content_type = str(resp.headers.get("Content-Type") or "")
            self.assertIn("text/event-stream", content_type)

    def test_stream_endpoint_market_status_envelope(self) -> None:
        with urlopen(
            f"http://127.0.0.1:{self.port}/v1/stream?types=market.status&heartbeat=5000",
            timeout=12,
        ) as resp:
            self.assertEqual(resp.status, 200)
            content_type = str(resp.headers.get("Content-Type") or "")
            self.assertIn("text/event-stream", content_type)

    def test_v1_stream_snapshot_token_changes_with_listing_status(self) -> None:
        svc = server._STATE
        assert svc is not None
        original_data_version = int(getattr(svc, "_data_version", 0))
        try:
            svc._data_version = 123  # noqa: SLF001
            with patch.object(
                svc,
                "listing_source_status_v1",
                return_value={"source": "mtproto_api", "updated_at": "2026-02-26T00:00:00Z", "rows_count": 10, "degraded": False, "error": ""},
            ):
                first = server._v1_stream_snapshot_token(svc)
            with patch.object(
                svc,
                "listing_source_status_v1",
                return_value={"source": "mtproto_api", "updated_at": "2026-02-26T00:01:00Z", "rows_count": 11, "degraded": False, "error": ""},
            ):
                second = server._v1_stream_snapshot_token(svc)
        finally:
            svc._data_version = original_data_version  # noqa: SLF001
        self.assertNotEqual(first, second)

    def test_v1_signals_stream_snapshot_token_changes_with_state(self) -> None:
        svc = server._STATE
        assert svc is not None
        original_data_version = int(getattr(svc, "_data_version", 0))
        original_updated_at = str((svc.state or {}).get("updated_at") or "")
        try:
            svc._data_version = 321  # noqa: SLF001
            if not isinstance(svc.state, dict):
                svc.state = {}
            svc.state["updated_at"] = "2026-02-26T00:00:00Z"
            first = server._v1_signals_stream_snapshot_token(svc, mode="tz")
            svc.state["updated_at"] = "2026-02-26T00:01:00Z"
            second = server._v1_signals_stream_snapshot_token(svc, mode="tz")
        finally:
            svc._data_version = original_data_version  # noqa: SLF001
            if isinstance(svc.state, dict):
                svc.state["updated_at"] = original_updated_at
        self.assertNotEqual(first, second)

    def test_v1_listings_stream_snapshot_token_changes_with_listing_status(self) -> None:
        svc = server._STATE
        assert svc is not None
        with patch.object(
            svc,
            "listing_source_status_v1",
            return_value={"source": "mtproto_api", "updated_at": "2026-02-26T00:00:00Z", "rows_count": 10, "degraded": False, "error": ""},
        ):
            first = server._v1_listings_stream_snapshot_token(svc, window="30m", include_low_priority=False)
        with patch.object(
            svc,
            "listing_source_status_v1",
            return_value={"source": "mtproto_api", "updated_at": "2026-02-26T00:01:00Z", "rows_count": 11, "degraded": False, "error": ""},
        ):
            second = server._v1_listings_stream_snapshot_token(svc, window="30m", include_low_priority=False)
        self.assertNotEqual(first, second)

    def test_v1_listings_events_stream_snapshot_token_changes_with_listing_status(self) -> None:
        svc = server._STATE
        assert svc is not None
        with patch.object(
            svc,
            "listing_source_status_v1",
            return_value={"source": "mtproto_api", "updated_at": "2026-02-26T00:00:00Z", "rows_count": 10, "degraded": False, "error": ""},
        ):
            first = server._v1_listings_events_stream_snapshot_token(svc, new_window_sec=120, include_relisted=True)
        with patch.object(
            svc,
            "listing_source_status_v1",
            return_value={"source": "mtproto_api", "updated_at": "2026-02-26T00:01:00Z", "rows_count": 11, "degraded": False, "error": ""},
        ):
            second = server._v1_listings_events_stream_snapshot_token(svc, new_window_sec=120, include_relisted=True)
        self.assertNotEqual(first, second)

    def test_listings_endpoints_success_contract(self) -> None:
        status_listings, payload_listings = self._get_json("/v1/listings?limit=5")
        self.assertEqual(status_listings, 200)
        self.assertIn("items", payload_listings)
        self.assertIn("source", payload_listings)
        self.assertIn("source_error", payload_listings)

        status_summary, payload_summary = self._get_json("/v1/listings/summary")
        self.assertEqual(status_summary, 200)
        self.assertIn("active_total", payload_summary)
        self.assertIn("new_total", payload_summary)
        self.assertIn("source", payload_summary)
        self.assertIn("source_error", payload_summary)

        status_events, payload_events = self._get_json("/v1/listings/events?limit=5")
        self.assertEqual(status_events, 200)
        self.assertIn("items", payload_events)
        self.assertIn("source", payload_events)
        self.assertIn("source_error", payload_events)

        status_signals, payload_signals = self._get_json("/v1/listings/signals?limit=5")
        self.assertEqual(status_signals, 200)
        self.assertIn("items", payload_signals)
        self.assertIn("source", payload_signals)
        self.assertIn("source_error", payload_signals)
        self.assertIn("engine_mode", payload_signals)

        status_source, payload_source = self._get_json("/api/listing/source-status")
        self.assertEqual(status_source, 200)
        self.assertIn("source", payload_source)
        self.assertIn("degraded", payload_source)

        status_source_v1, payload_source_v1 = self._get_json("/v1/listings/source-status")
        self.assertEqual(status_source_v1, 200)
        self.assertIn("source", payload_source_v1)
        self.assertIn("degraded", payload_source_v1)

    def test_listings_new_and_race_endpoints_success_contract(self) -> None:
        svc = server._STATE
        if isinstance(svc, GiftAnalyticsService):
            now_iso = "2026-02-26T00:00:00Z"
            svc.listing_tracker_state["x:test"] = {
                "listing_key": "x:test",
                "variant_id": "x|m|b|p",
                "base_id": "x",
                "prev_price_ton": 5.0,
                "last_price_ton": 6.0,
                "last_price_changed_at": now_iso,
                "last_seen_at": now_iso,
                "preview_url": "",
            }
            svc.listing_state["test-listing"] = {
                "listing_id": "test-listing",
                "base_id": "x",
                "variant_id": "x|m|b|p",
                "price_ton": 6.0,
                "status": "ACTIVE",
                "sale_type": "FIXED",
                "preview_url": "",
                "last_seen": now_iso,
            }

        status_new, payload_new = self._get_json("/v1/listings/new?limit=5&window=24h&only_pro_alerts=false")
        self.assertEqual(status_new, 200)
        self.assertIn("items", payload_new)
        self.assertIn("source", payload_new)
        self.assertIn("source_error", payload_new)
        # Canonical v1 core route includes row processing diagnostics.
        self.assertIn("row_processing_errors", payload_new)
        self.assertIn("row_processing_error_samples", payload_new)

        status_race, payload_race = self._get_json("/v1/listings/race?limit=5&window=24h&include_low_priority=true")
        self.assertEqual(status_race, 200)
        self.assertIn("items", payload_race)
        self.assertIn("source", payload_race)
        self.assertIn("source_error", payload_race)
        # Canonical v1 core route includes row processing diagnostics.
        self.assertIn("row_processing_errors", payload_race)
        self.assertIn("row_processing_error_samples", payload_race)

    def test_race_warmup_tracker_records_price_changes(self) -> None:
        svc = server._STATE
        self.assertIsInstance(svc, GiftAnalyticsService)
        assert isinstance(svc, GiftAnalyticsService)
        svc.listing_tracker_state = {}
        now_iso = "2026-02-26T00:00:00Z"
        rows_first = [
            {
                "listing_key": "x:abc",
                "collection_id": "x",
                "unique_id": "abc",
                "variant_id": "x|m|b|p",
                "resell_amount_ton": 5.0,
                "last_seen_at": now_iso,
                "preview_url": "",
            }
        ]
        changed_first = server._warmup_race_tracker_from_rows(svc, rows_first, now_iso)
        self.assertGreaterEqual(changed_first, 1)
        entry = svc.listing_tracker_state.get("x:abc") if isinstance(svc.listing_tracker_state, dict) else None
        self.assertIsInstance(entry, dict)
        assert isinstance(entry, dict)
        self.assertEqual(float(entry.get("last_price_ton") or 0.0), 5.0)
        self.assertIsNone(entry.get("last_price_changed_at"))

        rows_second = [
            {
                "listing_key": "x:abc",
                "collection_id": "x",
                "unique_id": "abc",
                "variant_id": "x|m|b|p",
                "resell_amount_ton": 6.25,
                "last_seen_at": "2026-02-26T00:00:40Z",
                "preview_url": "",
            }
        ]
        changed_second = server._warmup_race_tracker_from_rows(svc, rows_second, "2026-02-26T00:00:40Z")
        self.assertGreaterEqual(changed_second, 1)
        entry2 = svc.listing_tracker_state.get("x:abc") if isinstance(svc.listing_tracker_state, dict) else None
        self.assertIsInstance(entry2, dict)
        assert isinstance(entry2, dict)
        self.assertEqual(float(entry2.get("prev_price_ton") or 0.0), 5.0)
        self.assertEqual(float(entry2.get("last_price_ton") or 0.0), 6.25)
        self.assertEqual(str(entry2.get("last_price_changed_at") or ""), "2026-02-26T00:00:40Z")

    def test_race_warmup_supports_stars_to_ton_equivalent(self) -> None:
        svc = server._STATE
        self.assertIsInstance(svc, GiftAnalyticsService)
        assert isinstance(svc, GiftAnalyticsService)
        svc.listing_tracker_state = {}
        with patch.object(
            svc,
            "stars_rate",
            return_value={"stars_per_ton": 1000.0, "ton_per_star": 0.001, "source": "test"},
        ):
            rows_first = [
                {
                    "listing_key": "x:def",
                    "collection_id": "x",
                    "unique_id": "def",
                    "variant_id": "x|m|b|p",
                    "resell_amount_stars_est": 2000,
                    "last_seen_at": "2026-02-26T00:01:00Z",
                }
            ]
            server._warmup_race_tracker_from_rows(svc, rows_first, "2026-02-26T00:01:00Z")
            rows_second = [
                {
                    "listing_key": "x:def",
                    "collection_id": "x",
                    "unique_id": "def",
                    "variant_id": "x|m|b|p",
                    "resell_amount_stars_est": 3000,
                    "last_seen_at": "2026-02-26T00:01:30Z",
                }
            ]
            server._warmup_race_tracker_from_rows(svc, rows_second, "2026-02-26T00:01:30Z")
        entry = svc.listing_tracker_state.get("x:def") if isinstance(svc.listing_tracker_state, dict) else None
        self.assertIsInstance(entry, dict)
        assert isinstance(entry, dict)
        self.assertAlmostEqual(float(entry.get("prev_price_ton") or 0.0), 2.0, places=6)
        self.assertAlmostEqual(float(entry.get("last_price_ton") or 0.0), 3.0, places=6)
        self.assertEqual(str(entry.get("last_price_changed_at") or ""), "2026-02-26T00:01:30Z")

    def test_listings_endpoints_validation(self) -> None:
        with self.assertRaises(HTTPError) as cm_list_limit:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings?limit=0", timeout=10)
        self.assertEqual(cm_list_limit.exception.code, 400)

        with self.assertRaises(HTTPError) as cm_events_limit:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/events?limit=999", timeout=10)
        self.assertEqual(cm_events_limit.exception.code, 400)

        with self.assertRaises(HTTPError) as cm_summary_window:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/summary?new_window_sec=bad", timeout=10)
        self.assertEqual(cm_summary_window.exception.code, 400)

        with self.assertRaises(HTTPError) as cm_signals_type:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/signals?type=LONG", timeout=10)
        self.assertEqual(cm_signals_type.exception.code, 400)
        payload_signals_type = json.loads(cm_signals_type.exception.read().decode("utf-8"))
        self.assertIn("unsupported_signal_type", str(payload_signals_type.get("error") or ""))

        with self.assertRaises(HTTPError) as cm_signals_sort:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/signals?sort_by=price", timeout=10)
        self.assertEqual(cm_signals_sort.exception.code, 400)
        payload_signals_sort = json.loads(cm_signals_sort.exception.read().decode("utf-8"))
        self.assertIn("unsupported_sort_field", str(payload_signals_sort.get("error") or ""))

        with self.assertRaises(HTTPError) as cm_signals_score:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/signals?min_score=abc", timeout=10)
        self.assertEqual(cm_signals_score.exception.code, 400)

        with self.assertRaises(HTTPError) as cm_new_window:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/new?window=2h", timeout=10)
        self.assertEqual(cm_new_window.exception.code, 400)

        with self.assertRaises(HTTPError) as cm_race_direction:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/race?direction=SIDE", timeout=10)
        self.assertEqual(cm_race_direction.exception.code, 400)

    def test_new_listings_v17_endpoints_success_contract(self) -> None:
        status_market, payload_market = self._get_json("/v1/market/status?window=30m")
        self.assertEqual(status_market, 200)
        self.assertIn("market_regime", payload_market)
        self.assertIn("flow", payload_market)
        self.assertIn("liquidity", payload_market)
        self.assertIn("execution_health", payload_market)
        self.assertIn("sse_disconnect_rate", (payload_market.get("execution_health") or {}))

        status_new, payload_new = self._get_json("/v1/listings/new?limit=20&window=30m&only_pro_alerts=false")
        self.assertEqual(status_new, 200)
        self.assertIn("items", payload_new)
        self.assertIn("server_ts", payload_new)

        status_race, payload_race = self._get_json("/v1/listings/race?limit=20&window=30m")
        self.assertEqual(status_race, 200)
        self.assertIn("items", payload_race)
        self.assertIn("server_ts", payload_race)
        if isinstance(payload_race.get("items"), list) and payload_race.get("items"):
            first = payload_race["items"][0]
            self.assertIn("collection", first)
            self.assertIn("model", first)
            self.assertIn("background", first)
            self.assertIn("pattern", first)
            self.assertIn("preview_url", first)
        status_race_low, payload_race_low = self._get_json("/v1/listings/race?limit=20&window=30m&include_low_priority=true")
        self.assertEqual(status_race_low, 200)
        self.assertIn("items", payload_race_low)

        status_history, payload_history = self._get_json(f"/v1/listings/history?variant_id={quote('x|m|b|p')}&resolution=1m")
        self.assertEqual(status_history, 200)
        self.assertIn("series", payload_history)
        self.assertIn("events", payload_history)

    def test_new_listings_v17_validation(self) -> None:
        with self.assertRaises(HTTPError) as cm_window:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/new?window=2h", timeout=10)
        self.assertEqual(cm_window.exception.code, 400)

        with self.assertRaises(HTTPError) as cm_direction:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/race?direction=SIDE", timeout=10)
        self.assertEqual(cm_direction.exception.code, 400)

        with self.assertRaises(HTTPError) as cm_history_missing:
            urlopen(f"http://127.0.0.1:{self.port}/v1/listings/history", timeout=10)
        self.assertEqual(cm_history_missing.exception.code, 400)

    def test_listings_new_survives_row_signal_exceptions(self) -> None:
        svc = server._STATE
        self.assertIsInstance(svc, GiftAnalyticsService)
        assert isinstance(svc, GiftAnalyticsService)
        svc.variants["broken|model|bg|pat"] = {
            "variant_id": "broken|model|bg|pat",
            "base_id": "broken",
            "traits": {"model": {"name": "Model"}, "background": {"name": "BG"}, "pattern": {"name": "Pat"}},
            "metrics": {},
        }
        with patch.object(
            svc,
            "listings_v1",
            return_value={
                "items": [
                    {
                        "listing_key": "broken:1",
                        "variant_id": "broken|model|bg|pat",
                        "collection_id": "broken",
                        "collection": "Broken",
                        "attributes": {"model": "Model", "background": "BG", "pattern": "Pat"},
                        "preview_url": "",
                        "first_seen_at": "2026-03-01T00:00:00Z",
                        "last_seen_at": "2026-03-01T00:00:00Z",
                        "resell_amount_ton": 1.0,
                    }
                ],
                "source": "mtproto_api",
                "source_error": "",
            },
        ), patch.object(svc, "_v1_signal", side_effect=RuntimeError("simulated_signal_error")):
            status, payload = self._get_json("/v1/listings/new?limit=20&window=30m&only_pro_alerts=false")
        self.assertEqual(status, 200)
        self.assertIn("row_processing_errors", payload)
        self.assertGreaterEqual(int(payload.get("row_processing_errors") or 0), 0)
        self.assertIn("row_processing_error_samples", payload)

    def test_listings_race_survives_row_signal_exceptions(self) -> None:
        svc = server._STATE
        self.assertIsInstance(svc, GiftAnalyticsService)
        assert isinstance(svc, GiftAnalyticsService)
        svc.variants["race|model|bg|pat"] = {
            "variant_id": "race|model|bg|pat",
            "base_id": "race",
            "traits": {"model": {"name": "Model"}, "background": {"name": "BG"}, "pattern": {"name": "Pat"}},
            "metrics": {},
        }
        svc.listing_tracker_state["race:1"] = {
            "listing_key": "race:1",
            "variant_id": "race|model|bg|pat",
            "base_id": "race",
            "prev_price_ton": 5.0,
            "last_price_ton": 6.0,
            "last_price_changed_at": "2026-03-01T00:00:00Z",
            "last_seen_at": "2026-03-01T00:00:00Z",
            "preview_url": "",
        }
        with patch.object(svc, "_v1_signal", side_effect=RuntimeError("simulated_signal_error")):
            status, payload = self._get_json("/v1/listings/race?limit=20&window=30m&include_low_priority=true")
        self.assertEqual(status, 200)
        self.assertIn("row_processing_errors", payload)
        self.assertGreaterEqual(int(payload.get("row_processing_errors") or 0), 0)
        self.assertIn("row_processing_error_samples", payload)


if __name__ == "__main__":
    unittest.main()

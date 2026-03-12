import json
import threading
import unittest
from http.server import ThreadingHTTPServer
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
            server.AUTH_REQUIRED = cls._old_auth_required
            server._STATE = cls._old_state

    def setUp(self) -> None:
        self._seed_variant()
        FAVORITES_FILE.write_text("{}", encoding="utf-8")
        ALERTS_FILE.write_text("[]", encoding="utf-8")
        svc = server._STATE
        if isinstance(svc, GiftAnalyticsService):
            svc.alert_rules = []
            svc.alert_events = []

    def _get_json(self, path: str, timeout: float = 10.0):
        with urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)

    def _post_json(self, path: str, payload: dict, timeout: float = 10.0):
        req = Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)

    def _delete_json(self, path: str, timeout: float = 10.0):
        req = Request(f"http://127.0.0.1:{self.port}{path}", method="DELETE")
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)

    def test_metrics_endpoint_success(self) -> None:
        status, payload = self._get_json("/v1/metrics?metric=MARKET_INDEX&scope=MARKET")
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("metric"), "MARKET_INDEX")
        self.assertEqual(payload.get("scope"), "MARKET")
        self.assertIn("points", payload)
        self.assertTrue(isinstance(payload.get("points"), list))

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

        status_sig, payload_sig = self._get_json("/v1/signals?limit=20")
        self.assertEqual(status_sig, 200)
        self.assertIn("items", payload_sig)
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

    def test_stream_endpoint_metric_updated_envelope(self) -> None:
        with urlopen(
            f"http://127.0.0.1:{self.port}/v1/stream?types=metric.updated&heartbeat=5000",
            timeout=12,
        ) as resp:
            self.assertEqual(resp.status, 200)
            content_type = str(resp.headers.get("Content-Type") or "")
            self.assertIn("text/event-stream", content_type)

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

        status_race, payload_race = self._get_json("/v1/listings/race?limit=5&window=24h&include_low_priority=true")
        self.assertEqual(status_race, 200)
        self.assertIn("items", payload_race)
        self.assertIn("source", payload_race)
        self.assertIn("source_error", payload_race)

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
        svc.stars.set_derived_rate(1000.0)  # 1000 stars = 1 TON
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


if __name__ == "__main__":
    unittest.main()

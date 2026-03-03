import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

import server
from core import GiftAnalyticsService


class TestV1HttpContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._old_auth_required = server.AUTH_REQUIRED
        cls._old_state = server._STATE
        server.AUTH_REQUIRED = False

        svc = GiftAnalyticsService()
        svc.state["updated_at"] = "2026-02-26T00:00:00Z"
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
        server._STATE = svc

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

    def _get_json(self, path: str, timeout: float = 10.0):
        with urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)

    def test_metrics_endpoint_success(self) -> None:
        status, payload = self._get_json("/v1/metrics?metric=MARKET_INDEX&scope=MARKET")
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("metric"), "MARKET_INDEX")
        self.assertEqual(payload.get("scope"), "MARKET")
        self.assertIn("points", payload)
        self.assertTrue(isinstance(payload.get("points"), list))

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

    def test_stream_endpoint_rejects_unknown_type(self) -> None:
        with self.assertRaises(HTTPError) as cm:
            urlopen(f"http://127.0.0.1:{self.port}/v1/stream?types=bad.type", timeout=10)
        self.assertEqual(cm.exception.code, 400)
        payload = json.loads(cm.exception.read().decode("utf-8"))
        self.assertEqual(payload.get("error"), "unsupported_stream_type")

    def test_stream_endpoint_metric_updated_envelope(self) -> None:
        with urlopen(
            f"http://127.0.0.1:{self.port}/v1/stream?types=metric.updated&heartbeat=5000",
            timeout=12,
        ) as resp:
            self.assertEqual(resp.status, 200)
            content_type = str(resp.headers.get("Content-Type") or "")
            self.assertIn("text/event-stream", content_type)


if __name__ == "__main__":
    unittest.main()

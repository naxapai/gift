import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.request import Request, urlopen

import server
from core import GiftAnalyticsService


class TestDomainRuntimeConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._old_auth_required = server.AUTH_REQUIRED
        cls._old_state = server._STATE
        cls._old_ingest_auto_loop = os.environ.get("INGEST_AUTO_LOOP")
        os.environ["INGEST_AUTO_LOOP"] = "false"
        server.AUTH_REQUIRED = False
        server._STATE = GiftAnalyticsService()
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
            server.AUTH_REQUIRED = cls._old_auth_required
            server._STATE = cls._old_state

    def test_ton_config_exposes_public_domain_settings(self) -> None:
        with urlopen(f"http://127.0.0.1:{self.port}/api/auth/ton/config", timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(payload.get("public_base_url"), server.PUBLIC_BASE_URL)
        self.assertEqual(payload.get("public_base_host"), server.PUBLIC_BASE_HOST)
        self.assertIn("giftmarketzone.com", payload.get("proof_allowed_domains") or [])

    def test_options_echoes_allowed_origin_for_cors(self) -> None:
        req = Request(f"http://127.0.0.1:{self.port}/api/auth/telegram/verify", method="OPTIONS")
        req.add_header("Origin", "https://giftmarketzone.com")
        req.add_header("Access-Control-Request-Method", "POST")
        with urlopen(req, timeout=10) as resp:
            self.assertEqual(resp.status, 204)
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "https://giftmarketzone.com")
            self.assertEqual(resp.headers.get("Access-Control-Allow-Credentials"), "true")

    def test_cookie_builder_supports_optional_cookie_domain(self) -> None:
        handler = SimpleNamespace(headers={"Host": "giftmarketzone.com"})
        old_auth = server.AUTH_COOKIE_DOMAIN
        old_ton = server.TON_COOKIE_DOMAIN
        try:
            server.AUTH_COOKIE_DOMAIN = "giftmarketzone.com"
            server.TON_COOKIE_DOMAIN = "giftmarketzone.com"
            auth_cookie = server._build_session_cookie(handler, "sid123", 3600)
            ton_cookie = server._build_ton_session_cookie(handler, "tonsid123", 3600)
        finally:
            server.AUTH_COOKIE_DOMAIN = old_auth
            server.TON_COOKIE_DOMAIN = old_ton
        self.assertIn("Domain=giftmarketzone.com", auth_cookie)
        self.assertIn("Domain=giftmarketzone.com", ton_cookie)
        self.assertIn("Secure", auth_cookie)
        self.assertIn("Secure", ton_cookie)


if __name__ == "__main__":
    unittest.main()

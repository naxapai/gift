from __future__ import annotations

import json
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from analytics import build_chart_series, build_market_summary, get_ranked_signals
from market_data import load_dataset, refresh_dataset, tick_realtime

ROOT = Path(__file__).parent
STATIC_DIR = ROOT / "static"


class AppState:
    def __init__(self) -> None:
        self.dataset = load_dataset()
        self.lock = threading.RLock()
        self.realtime_tick_count = 0
        self.last_tick_at = ""
        self.realtime_interval_sec = float(os.getenv("REALTIME_INTERVAL_SEC", "3"))
        self._start_realtime_loop()

    def refresh(self) -> None:
        with self.lock:
            self.dataset = refresh_dataset()
            self.realtime_tick_count = 0
            self.last_tick_at = ""

    def summary(self) -> dict:
        with self.lock:
            return build_market_summary(self.dataset)

    def chart(self, gift_id: str) -> dict | None:
        with self.lock:
            gift = next((g for g in self.dataset["gifts"] if g["gift_id"] == gift_id), None)
            if not gift:
                return None
            return build_chart_series(gift)

    def screener(self) -> list[dict]:
        with self.lock:
            return build_market_summary(self.dataset)["rows"]

    def signals(self) -> list[dict]:
        with self.lock:
            return get_ranked_signals(self.dataset)

    def status(self) -> dict:
        with self.lock:
            return {
                "realtime_interval_sec": self.realtime_interval_sec,
                "realtime_tick_count": self.realtime_tick_count,
                "last_tick_at": self.last_tick_at,
            }

    def _start_realtime_loop(self) -> None:
        def loop() -> None:
            while True:
                time.sleep(self.realtime_interval_sec)
                with self.lock:
                    tick_realtime(self.dataset)
                    self.realtime_tick_count += 1
                    self.last_tick_at = time.strftime("%Y-%m-%d %H:%M:%S")

        thread = threading.Thread(target=loop, daemon=True, name="realtime-ticker")
        thread.start()


STATE = AppState()


def _json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _error(handler: BaseHTTPRequestHandler, message: str, code: int = 400) -> None:
    _json_response(handler, {"ok": False, "error": message}, status=code)


def _serve_file(handler: BaseHTTPRequestHandler, rel_path: str) -> None:
    rel = rel_path.lstrip("/")
    target = (STATIC_DIR / rel).resolve()

    if not str(target).startswith(str(STATIC_DIR.resolve())):
        handler.send_error(HTTPStatus.FORBIDDEN)
        return

    if not target.exists() or not target.is_file():
        handler.send_error(HTTPStatus.NOT_FOUND)
        return

    mime = "text/plain"
    if target.suffix == ".html":
        mime = "text/html; charset=utf-8"
    elif target.suffix == ".css":
        mime = "text/css; charset=utf-8"
    elif target.suffix == ".js":
        mime = "application/javascript; charset=utf-8"
    elif target.suffix == ".json":
        mime = "application/json; charset=utf-8"

    content = target.read_bytes()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(content)))
    handler.end_headers()
    handler.wfile.write(content)


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            _serve_file(self, "index.html")
            return
        if path.startswith("/assets/"):
            _serve_file(self, path.replace("/assets/", ""))
            return

        if path == "/api/market/summary":
            summary = STATE.summary()
            _json_response(self, {"ok": True, "data": summary})
            return

        if path == "/api/market/chart":
            params = parse_qs(parsed.query)
            gift_id = (params.get("gift_id") or [None])[0]
            if not gift_id:
                _error(self, "gift_id is required")
                return

            chart = STATE.chart(gift_id)
            if not chart:
                _error(self, f"gift_id '{gift_id}' not found", code=404)
                return

            _json_response(self, {"ok": True, "data": chart})
            return

        if path == "/api/market/screener":
            params = parse_qs(parsed.query)
            sort_by = (params.get("sort_by") or ["change_7d"])[0]
            order = (params.get("order") or ["desc"])[0]
            signal_filter = (params.get("signal") or [""])[0].upper().strip()
            group_filter = (params.get("group") or [""])[0].strip().lower()
            min_ratio_raw = (params.get("min_ratio") or [""])[0].strip()

            rows = STATE.screener()

            if signal_filter:
                rows = [r for r in rows if r["signal"] == signal_filter]
            if group_filter:
                rows = [r for r in rows if str(r.get("group", "")).lower() == group_filter]

            if min_ratio_raw:
                try:
                    min_ratio = float(min_ratio_raw)
                except ValueError:
                    _error(self, "min_ratio must be a number")
                    return
                rows = [r for r in rows if r["demand_supply_ratio"] >= min_ratio]

            if not rows:
                _json_response(self, {"ok": True, "data": []})
                return

            if sort_by not in rows[0]:
                _error(self, f"invalid sort_by '{sort_by}'")
                return

            reverse = order.lower() != "asc"
            rows = sorted(rows, key=lambda x: x[sort_by], reverse=reverse)
            _json_response(self, {"ok": True, "data": rows})
            return

        if path == "/api/signals/latest":
            top = STATE.signals()[:10]
            _json_response(self, {"ok": True, "data": top})
            return
        if path == "/healthz":
            _json_response(self, {"ok": True, "service": "telegram-gifts-market", "status": "healthy"})
            return
        if path == "/api/market/realtime-status":
            _json_response(self, {"ok": True, "data": STATE.status()})
            return

        _serve_file(self, path.lstrip("/"))

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/admin/refresh":
            STATE.refresh()
            _json_response(self, {"ok": True, "message": "dataset refreshed", "generated_at": STATE.dataset.get("generated_at")})
            return

        _error(self, "not found", code=404)

    def log_message(self, fmt: str, *args) -> None:
        return


def run() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8091"))

    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"Server started on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()

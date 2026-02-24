from __future__ import annotations

import json
import os
import random
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from market_data import (
    _ensure_live_dataset_quality,
    _load_verified_fallback_snapshot,
    fetch_verified_dataset_from_fragment,
    load_verified_dataset,
    save_verified_dataset,
)

ROOT = Path(__file__).parent
UPSTREAM_SNAPSHOT_FILE = Path(os.getenv("UPSTREAM_SNAPSHOT_FILE", str(ROOT / "data" / "upstream_verified_snapshot.json")))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _counts(dataset: dict) -> dict:
    filters = dataset.get("filters") if isinstance(dataset, dict) else {}
    return {
        "gifts": len(dataset.get("gifts") or []) if isinstance(dataset, dict) else 0,
        "collections": len((filters or {}).get("collections") or []) if isinstance(filters, dict) else 0,
        "models": len((filters or {}).get("models") or {}) if isinstance(filters, dict) else 0,
        "backdrops": len((filters or {}).get("backdrops") or {}) if isinstance(filters, dict) else 0,
        "symbols": len((filters or {}).get("symbols") or {}) if isinstance(filters, dict) else 0,
    }


def _token_ok(handler: BaseHTTPRequestHandler, token: str) -> bool:
    if not token:
        return False
    auth = (handler.headers.get("Authorization", "") or "").strip()
    if auth == f"Bearer {token}":
        return True
    x_api_key = (handler.headers.get("X-API-Key", "") or "").strip()
    if x_api_key == token:
        return True
    parsed = urlparse(handler.path)
    token_q = ((parse_qs(parsed.query).get("token") or [""])[0] or "").strip()
    return token_q == token


class UpstreamState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.dataset: dict | None = None
        self.updated_at = ""
        self.last_error = ""
        self.last_source = ""
        self.ingest_running = False
        self.ingest_started_at = ""
        self.refresh_sec = max(30, int(os.getenv("UPSTREAM_REFRESH_SEC", "120")))
        self.fragment_url = os.getenv("FRAGMENT_GIFTS_URL", "https://fragment.com/gifts").strip()
        self.fragment_timeout = max(5, int(os.getenv("UPSTREAM_FRAGMENT_TIMEOUT_SEC", "25")))
        self.fragment_max_collections = int(os.getenv("FRAGMENT_MAX_COLLECTIONS", "0"))
        self.fragment_max_pages = int(os.getenv("FRAGMENT_MAX_PAGES_PER_COLLECTION", "500"))
        self.fragment_collection_start = int(os.getenv("FRAGMENT_COLLECTION_START", "0"))
        self.file_guard_path = os.getenv("VERIFIED_DATA_FILE", str(ROOT / "data" / "verified_gifts.json")).strip()
        self._stop = threading.Event()
        self.schema_version = "upstream.v1"

    def _load_initial(self) -> None:
        try:
            if UPSTREAM_SNAPSHOT_FILE.exists():
                d = load_verified_dataset(str(UPSTREAM_SNAPSHOT_FILE))
                with self.lock:
                    self.dataset = d
                    self.updated_at = str(d.get("generated_at") or _now_iso())
                    self.last_source = "upstream_snapshot"
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()

    def ingest_once(self) -> None:
        with self.lock:
            if self.ingest_running:
                return
            self.ingest_running = True
            self.ingest_started_at = _now_iso()

        err = ""
        selected: dict | None = None
        try:
            selected = fetch_verified_dataset_from_fragment(
                root_url=self.fragment_url,
                timeout_sec=self.fragment_timeout,
                max_collections=self.fragment_max_collections,
                max_pages_per_collection=self.fragment_max_pages,
                collection_start=self.fragment_collection_start,
            )
            fallback = _load_verified_fallback_snapshot(self.file_guard_path)
            _ensure_live_dataset_quality(selected, fallback, "upstream.fragment")
        except Exception as e:
            err = f"fragment_failed:{type(e).__name__}:{str(e)[:220]}"

        with self.lock:
            if selected is not None:
                self.dataset = selected
                self.updated_at = str(selected.get("generated_at") or _now_iso())
                self.last_source = "fragment"
                self.last_error = ""
                try:
                    UPSTREAM_SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
                    save_verified_dataset(selected, str(UPSTREAM_SNAPSHOT_FILE))
                except Exception:
                    pass
            else:
                self.last_error = err or "ingest_failed"
            self.ingest_running = False

    def loop(self) -> None:
        self._load_initial()
        while not self._stop.is_set():
            started = time.time()
            self.ingest_once()
            elapsed = max(0.0, time.time() - started)
            sleep_for = max(1.0, self.refresh_sec - elapsed + random.uniform(0.0, 1.0))
            self._stop.wait(timeout=sleep_for)

    def payload(self) -> dict:
        with self.lock:
            dataset = self.dataset
            if not isinstance(dataset, dict):
                raise RuntimeError("upstream has no verified dataset")
            return {
                "ok": True,
                "source": self.last_source or "unknown",
                "generated_at": dataset.get("generated_at"),
                "counts": _counts(dataset),
                "data": dataset,
            }

    def status(self) -> dict:
        with self.lock:
            return {
                "ok": True,
                "schema": self.schema_version,
                "updated_at": self.updated_at or None,
                "ingest_running": self.ingest_running,
                "ingest_started_at": self.ingest_started_at or None,
                "last_source": self.last_source or None,
                "last_error": self.last_error or "",
                "refresh_sec": self.refresh_sec,
                "counts": _counts(self.dataset or {}),
            }


STATE = UpstreamState()


def _json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except Exception:
        return


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/healthz":
            _json(self, {"ok": True, "service": "gift-upstream"})
            return

        if path == "/api/upstream/status":
            _json(self, STATE.status())
            return

        if path == "/api/gifts/verified":
            token = os.getenv("UPSTREAM_API_TOKEN", "").strip()
            if not token:
                _json(self, {"ok": False, "error": "upstream_token_not_configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                return
            if not _token_ok(self, token):
                _json(self, {"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
                return
            try:
                _json(self, STATE.payload())
            except Exception as e:  # noqa: BLE001
                _json(self, {"ok": False, "error": f"upstream_payload_failed:{type(e).__name__}:{str(e)[:180]}"}, status=HTTPStatus.BAD_GATEWAY)
            return

        _json(self, {"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/upstream/refresh":
            _json(self, {"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return

        token = os.getenv("UPSTREAM_ADMIN_TOKEN", "").strip() or os.getenv("UPSTREAM_API_TOKEN", "").strip()
        if not token:
            _json(self, {"ok": False, "error": "upstream_token_not_configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if not _token_ok(self, token):
            _json(self, {"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return

        threading.Thread(target=STATE.ingest_once, daemon=True, name="upstream-manual-refresh").start()
        _json(self, {"ok": True, "started": True, "at": _now_iso(), "mode": "manual_refresh"})


def run() -> None:
    host = os.getenv("UPSTREAM_HOST", "0.0.0.0").strip()
    port = int(os.getenv("UPSTREAM_PORT", os.getenv("PORT", "8099")))

    t = threading.Thread(target=STATE.loop, daemon=True, name="upstream-ingest-loop")
    t.start()

    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Upstream started on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STATE.stop()


if __name__ == "__main__":
    run()

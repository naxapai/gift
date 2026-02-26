from __future__ import annotations

import asyncio
import json
import os
import random
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import urllib.request

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
SNAPSHOT_FILE = Path(os.getenv("MT_BRIDGE_SNAPSHOT_FILE", str(DATA_DIR / "mt_listings_bridge_snapshot.json")))
STATE_FILE = Path(os.getenv("MT_BRIDGE_STATE_FILE", str(DATA_DIR / "mt_listings_bridge_state.json")))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


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


class MTProtoListingBridgeState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.refresh_sec = max(1.0, float(os.getenv("MT_BRIDGE_REFRESH_SEC", "2.0")))
        self.gift_types_refresh_sec = max(60.0, float(os.getenv("MT_BRIDGE_GIFT_TYPES_REFRESH_SEC", "900")))
        self.max_gift_types = max(1, int(os.getenv("MT_BRIDGE_MAX_GIFT_TYPES", "120")))
        self.per_gift_limit = max(1, min(200, int(os.getenv("MT_BRIDGE_PER_GIFT_LIMIT", "80"))))
        self.per_request_delay_sec = max(0.0, float(os.getenv("MT_BRIDGE_PER_REQUEST_DELAY_SEC", "0.08")))
        self.timeout_sec = max(5.0, float(os.getenv("MT_BRIDGE_TIMEOUT_SEC", "20")))
        self.new_window_sec = max(30, int(os.getenv("MT_BRIDGE_NEW_WINDOW_SEC", "120")))
        self.retention_sec = max(3600, int(os.getenv("MT_BRIDGE_RETENTION_SEC", "1209600")))
        self.api_id = int((os.getenv("MT_BRIDGE_API_ID", "0") or "0").strip() or "0")
        self.api_hash = (os.getenv("MT_BRIDGE_API_HASH", "") or "").strip()
        self.string_session = (os.getenv("MT_BRIDGE_STRING_SESSION", "") or "").strip()
        self.phone = (os.getenv("MT_BRIDGE_PHONE", "") or "").strip()
        self.upstream_url = (os.getenv("MT_BRIDGE_UPSTREAM_LISTINGS_URL", "") or "").strip()
        self.upstream_token = (os.getenv("MT_BRIDGE_UPSTREAM_LISTINGS_TOKEN", "") or "").strip()
        self.upstream_header = (os.getenv("MT_BRIDGE_UPSTREAM_LISTINGS_TOKEN_HEADER", "Authorization") or "Authorization").strip()
        self.upstream_prefix = (os.getenv("MT_BRIDGE_UPSTREAM_LISTINGS_TOKEN_PREFIX", "Bearer ") or "")
        self.upstream_timeout_sec = max(3.0, float(os.getenv("MT_BRIDGE_UPSTREAM_TIMEOUT_SEC", "10")))
        self.schema = "listing.bridge.v1"
        self._stop = threading.Event()
        self.dataset: dict = {"updated_at": None, "items": []}
        self.last_source = "cold_start"
        self.last_error = ""
        self.ingest_running = False
        self.ingest_started_at = None
        self.last_gift_types_sync_at = None
        self.last_gift_types_error = ""
        self.gift_types: list[int] = []
        self.tracker_by_key: dict[str, dict] = _load_json(STATE_FILE, {"tracker_by_key": {}}).get("tracker_by_key") or {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None
        snap = _load_json(SNAPSHOT_FILE, {})
        if isinstance(snap, dict) and isinstance(snap.get("items"), list):
            self.dataset = {"updated_at": snap.get("updated_at"), "items": snap.get("items") or []}

    def stop(self) -> None:
        self._stop.set()

    def _telethon_ready(self) -> bool:
        return bool(self.api_id and self.api_hash and self.string_session)

    async def _ensure_client(self):
        if self._client is not None:
            return self._client
        if not self._telethon_ready():
            raise RuntimeError("mtproto_credentials_missing")
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
        except Exception as exc:
            raise RuntimeError(f"telethon_import_failed:{type(exc).__name__}") from exc
        client = TelegramClient(StringSession(self.string_session), self.api_id, self.api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("mtproto_user_not_authorized")
        self._client = client
        return client

    async def _fetch_gift_types(self) -> list[int]:
        client = await self._ensure_client()
        try:
            from telethon.tl import functions
        except Exception as exc:
            raise RuntimeError(f"telethon_tl_import_failed:{type(exc).__name__}") from exc
        req = functions.payments.GetStarGiftsRequest(hash=0)
        res = await client(req)
        gift_types: list[int] = []
        for g in list(getattr(res, "gifts", []) or []):
            gid = getattr(g, "id", None) or getattr(g, "gift_id", None)
            if gid is None:
                continue
            has_resale = bool(getattr(g, "availability_resale", False))
            if has_resale:
                try:
                    gift_types.append(int(gid))
                except Exception:
                    continue
        return gift_types

    def _attr_name(self, attrs: list, keys: tuple[str, ...]) -> str:
        for a in attrs or []:
            cname = str(getattr(a, "__class__", type("x", (), {})).__name__ or "").lower()
            if any(k in cname for k in keys):
                name = str(getattr(a, "name", "") or "").strip()
                if name:
                    return name
        return "Unknown"

    def _slug_text(self, text: str) -> str:
        return "".join(ch if ("a" <= ch <= "z" or "0" <= ch <= "9") else "_" for ch in str(text or "").strip().lower()).strip("_") or "unknown"

    def _base_id_from(self, gid: int | str, slug: str, title: str) -> str:
        slug_head = str(slug or "").split("-", 1)[0].strip().lower()
        if any(("a" <= ch <= "z") for ch in slug_head):
            return self._slug_text(slug_head)
        title_slug = self._slug_text(title)
        if any(("a" <= ch <= "z") for ch in title_slug):
            return title_slug
        return self._slug_text(str(gid))

    def _to_stars_float(self, val: Any) -> float | None:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        amount = getattr(val, "amount", None)
        nanos = getattr(val, "nanos", None)
        if amount is None and nanos is None:
            return None
        try:
            amount_i = int(amount or 0)
            nanos_i = int(nanos or 0)
            return float(amount_i) + (float(nanos_i) / 1_000_000_000.0)
        except Exception:
            return None

    async def _fetch_resale_for_gift(self, gift_id: int) -> list[dict]:
        client = await self._ensure_client()
        try:
            from telethon.tl import functions
        except Exception as exc:
            raise RuntimeError(f"telethon_tl_import_failed:{type(exc).__name__}") from exc
        req = functions.payments.GetResaleStarGiftsRequest(
            gift_id=int(gift_id),
            offset="",
            limit=int(self.per_gift_limit),
        )
        res = await client(req)
        out = []
        for g in list(getattr(res, "gifts", []) or []):
            unique_id = getattr(g, "id", None)
            gid = getattr(g, "gift_id", None) or gift_id
            if unique_id is None or gid is None:
                continue
            slug = str(getattr(g, "slug", "") or "")
            title = str(getattr(g, "title", "") or "")
            attrs = list(getattr(g, "attributes", []) or [])
            model = self._attr_name(attrs, ("model",))
            background = self._attr_name(attrs, ("backdrop", "background"))
            pattern = self._attr_name(attrs, ("pattern", "symbol"))
            base_id = self._base_id_from(gid, slug, title)
            variant_id = f"{base_id}|{self._slug_text(model)}|{self._slug_text(background)}|{self._slug_text(pattern)}"
            amount_raw = getattr(g, "resell_amount", None)
            stars_val = None
            if isinstance(amount_raw, list):
                for x in amount_raw:
                    stars_val = self._to_stars_float(x)
                    if stars_val is not None:
                        break
            else:
                stars_val = self._to_stars_float(amount_raw)
            out.append(
                {
                    "gift_id": base_id,
                    "gift_type_id": str(gid),
                    "unique_id": str(unique_id),
                    "variant_id": variant_id,
                    "num": getattr(g, "num", None),
                    "slug": slug,
                    "title": title,
                    "collection": title,
                    "collection_id": base_id,
                    "resell_currency": "STARS",
                    "currency_mode": "TON_ONLY" if bool(getattr(g, "resale_ton_only", False)) else "STARS",
                    "resell_amount_ton": None,
                    "resell_amount_stars_est": stars_val,
                    "attributes": {"model": model, "background": background, "pattern": pattern},
                    "status": "ACTIVE",
                    "sale_type": "FIXED",
                    "preview_url": "",
                }
            )
        return out

    async def _ingest_mtproto(self) -> tuple[list[dict], str]:
        now_iso = _now_iso()
        if (
            not self.gift_types
            or not self.last_gift_types_sync_at
            or (datetime.now(timezone.utc) - datetime.fromisoformat(str(self.last_gift_types_sync_at).replace("Z", "+00:00"))).total_seconds() >= self.gift_types_refresh_sec
        ):
            self.gift_types = (await self._fetch_gift_types())[: self.max_gift_types]
            self.last_gift_types_sync_at = now_iso
            self.last_gift_types_error = ""
        items: list[dict] = []
        for gid in self.gift_types[: self.max_gift_types]:
            chunk = await self._fetch_resale_for_gift(gid)
            items.extend(chunk)
            if self.per_request_delay_sec > 0:
                await asyncio.sleep(self.per_request_delay_sec)
        return items, "mtproto_api"

    def _fetch_upstream_reserve(self) -> tuple[list[dict], str]:
        if not self.upstream_url:
            raise RuntimeError("mt_bridge_upstream_url_empty")
        req = urllib.request.Request(self.upstream_url, method="GET")
        if self.upstream_token:
            req.add_header(self.upstream_header, f"{self.upstream_prefix}{self.upstream_token}")
        with urllib.request.urlopen(req, timeout=self.upstream_timeout_sec) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise RuntimeError("mt_bridge_upstream_invalid_payload")
        return items, "upstream_reserve"

    def _apply_tracker(self, items: list[dict]) -> list[dict]:
        now = datetime.now(timezone.utc)
        now_iso = _now_iso()
        active_keys: set[str] = set()
        norm_items: list[dict] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            gift_id = str(it.get("gift_id") or it.get("collection_id") or "").strip().lower()
            unique_id = str(it.get("unique_id") or it.get("id") or "").strip()
            if not gift_id or not unique_id:
                continue
            key = f"{gift_id}:{unique_id}"
            active_keys.add(key)
            entry = self.tracker_by_key.get(key)
            if not isinstance(entry, dict):
                entry = {
                    "first_seen_at": now_iso,
                    "last_seen_at": now_iso,
                    "relist_count": 0,
                    "active": True,
                    "last_relisted_at": None,
                }
                self.tracker_by_key[key] = entry
            else:
                if not bool(entry.get("active")):
                    entry["relist_count"] = int(entry.get("relist_count") or 0) + 1
                    entry["last_relisted_at"] = now_iso
                entry["active"] = True
                entry["last_seen_at"] = now_iso
            first_seen_at = str(entry.get("first_seen_at") or now_iso)
            relisted_at = str(entry.get("last_relisted_at") or "")
            first_dt = datetime.fromisoformat(first_seen_at.replace("Z", "+00:00"))
            rel_dt = datetime.fromisoformat(relisted_at.replace("Z", "+00:00")) if relisted_at else None
            is_new = (now - first_dt).total_seconds() <= self.new_window_sec or (rel_dt is not None and (now - rel_dt).total_seconds() <= self.new_window_sec)
            enriched = dict(it)
            enriched.update(
                {
                    "listing_key": key,
                    "first_seen_at": first_seen_at,
                    "last_seen_at": str(entry.get("last_seen_at") or now_iso),
                    "relist_count": int(entry.get("relist_count") or 0),
                    "last_relisted_at": relisted_at or None,
                    "is_new": bool(is_new),
                    "source": "mtproto_api",
                }
            )
            norm_items.append(enriched)

        cutoff = now.timestamp() - float(self.retention_sec)
        for key, entry in list(self.tracker_by_key.items()):
            if key in active_keys:
                continue
            if bool(entry.get("active")):
                entry["active"] = False
                entry["last_absent_at"] = now_iso
            last_seen = str(entry.get("last_seen_at") or "")
            try:
                last_ts = datetime.fromisoformat(last_seen.replace("Z", "+00:00")).timestamp() if last_seen else 0.0
            except Exception:
                last_ts = 0.0
            if last_ts > 0 and last_ts < cutoff:
                self.tracker_by_key.pop(key, None)

        norm_items.sort(key=lambda x: str(x.get("last_seen_at") or ""), reverse=True)
        return norm_items

    def ingest_once(self) -> None:
        with self.lock:
            if self.ingest_running:
                return
            self.ingest_running = True
            self.ingest_started_at = _now_iso()
        selected: list[dict] = []
        source = "none"
        err = ""
        try:
            if self._telethon_ready():
                if self._loop is None:
                    self._loop = asyncio.new_event_loop()
                selected, source = self._loop.run_until_complete(self._ingest_mtproto())
            else:
                raise RuntimeError("mtproto_credentials_missing")
        except Exception as exc:
            err = f"mtproto_failed:{type(exc).__name__}:{str(exc)[:220]}"
            self.last_gift_types_error = str(exc)[:220]
            try:
                selected, source = self._fetch_upstream_reserve()
            except Exception as exc2:
                err = f"{err}; reserve_failed:{type(exc2).__name__}:{str(exc2)[:220]}"
                selected = []
                source = "error"

        with self.lock:
            if selected:
                items = self._apply_tracker(selected)
                self.dataset = {"updated_at": _now_iso(), "items": items}
                self.last_source = source
                self.last_error = ""
                _save_json(SNAPSHOT_FILE, self.dataset)
                _save_json(STATE_FILE, {"tracker_by_key": self.tracker_by_key})
            else:
                self.last_error = err or "ingest_failed"
            self.ingest_running = False

    def loop(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            self.ingest_once()
            elapsed = max(0.0, time.time() - started)
            wait_s = max(0.5, self.refresh_sec - elapsed + random.uniform(0.0, 0.4))
            self._stop.wait(wait_s)

    def payload(self) -> dict:
        with self.lock:
            return {
                "ok": True,
                "schema": self.schema,
                "updated_at": self.dataset.get("updated_at"),
                "source": self.last_source or "unknown",
                "items": self.dataset.get("items") or [],
            }

    def status(self) -> dict:
        with self.lock:
            return {
                "ok": True,
                "schema": self.schema,
                "updated_at": self.dataset.get("updated_at"),
                "ingest_running": self.ingest_running,
                "ingest_started_at": self.ingest_started_at,
                "last_source": self.last_source,
                "last_error": self.last_error,
                "gift_types_count": len(self.gift_types),
                "last_gift_types_sync_at": self.last_gift_types_sync_at,
                "last_gift_types_error": self.last_gift_types_error,
                "mtproto_ready": self._telethon_ready(),
                "upstream_configured": bool(self.upstream_url),
                "items_count": len(self.dataset.get("items") or []),
            }


STATE = MTProtoListingBridgeState()


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
            _json(self, {"ok": True, "service": "gift-listing-mtproto-bridge"})
            return
        if path == "/api/listing-bridge/status":
            _json(self, STATE.status())
            return
        if path == "/api/listings/new":
            token = (os.getenv("MT_BRIDGE_API_TOKEN", "") or "").strip()
            if not token:
                _json(self, {"ok": False, "error": "mt_bridge_token_not_configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                return
            if not _token_ok(self, token):
                _json(self, {"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
                return
            _json(self, STATE.payload())
            return
        _json(self, {"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/listing-bridge/ingest":
            _json(self, {"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return
        token = (os.getenv("MT_BRIDGE_ADMIN_TOKEN", "") or "").strip() or (os.getenv("MT_BRIDGE_API_TOKEN", "") or "").strip()
        if not token:
            _json(self, {"ok": False, "error": "mt_bridge_token_not_configured"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if not _token_ok(self, token):
            _json(self, {"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return
        threading.Thread(target=STATE.ingest_once, daemon=True, name="listing-bridge-manual-ingest").start()
        _json(self, {"ok": True, "started": True, "at": _now_iso(), "mode": "manual_ingest"})


def run() -> None:
    host = (os.getenv("MT_BRIDGE_HOST", "0.0.0.0") or "0.0.0.0").strip()
    port = int((os.getenv("MT_BRIDGE_PORT", os.getenv("PORT", "8101")) or "8101").strip())
    t = threading.Thread(target=STATE.loop, daemon=True, name="listing-bridge-loop")
    t.start()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Listing bridge started on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STATE.stop()


if __name__ == "__main__":
    run()

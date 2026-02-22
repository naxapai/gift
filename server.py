from __future__ import annotations

import json
import os
import secrets
import threading
import time
import hmac
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from core import GiftAnalyticsService

ROOT = Path(__file__).parent
STATIC_DIR = ROOT / "static"

STATE = GiftAnalyticsService()

AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "true").strip().lower() in {"1", "true", "yes", "on"}
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "").strip()
AUTH_SESSION_TTL_SEC = max(300, int(os.getenv("AUTH_SESSION_TTL_SEC", "86400")))
TELEGRAM_AUTH_MAX_AGE_SEC = max(30, int(os.getenv("TELEGRAM_AUTH_MAX_AGE_SEC", "300")))
SESSION_COOKIE_NAME = os.getenv("AUTH_SESSION_COOKIE", "gmz_session").strip() or "gmz_session"
TON_SESSION_COOKIE_NAME = os.getenv("TON_SESSION_COOKIE", "gmz_ton_session").strip() or "gmz_ton_session"
TON_AUTH_REQUIRED = os.getenv("TON_AUTH_REQUIRED", "false").strip().lower() in {"1", "true", "yes", "on"}
TON_AUTH_SESSION_TTL_SEC = max(300, int(os.getenv("TON_AUTH_SESSION_TTL_SEC", "86400")))
TON_PROOF_MAX_AGE_SEC = max(60, int(os.getenv("TON_PROOF_MAX_AGE_SEC", "300")))
TON_CHALLENGE_TTL_SEC = max(30, int(os.getenv("TON_CHALLENGE_TTL_SEC", "180")))


class AuthStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}

    def _cleanup_locked(self, now: float) -> None:
        expired = [sid for sid, s in self._sessions.items() if float(s.get("expires_at", 0)) <= now]
        for sid in expired:
            self._sessions.pop(sid, None)

    def enabled(self) -> bool:
        return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_USERNAME)

    def verify_telegram_payload(self, payload: dict) -> tuple[bool, str, dict | None]:
        if not self.enabled():
            return False, "telegram_auth_not_configured", None
        recv_hash = str(payload.get("hash", "")).strip()
        if not recv_hash:
            return False, "missing_hash", None
        auth_date_raw = payload.get("auth_date")
        try:
            auth_date = int(str(auth_date_raw))
        except (TypeError, ValueError):
            return False, "invalid_auth_date", None
        now_ts = int(time.time())
        if auth_date > now_ts + 30:
            return False, "auth_date_in_future", None
        if now_ts - auth_date > TELEGRAM_AUTH_MAX_AGE_SEC:
            return False, "auth_date_expired", None

        check_lines: list[str] = []
        for key in sorted(payload.keys()):
            if key == "hash":
                continue
            value = payload.get(key)
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                continue
            check_lines.append(f"{key}={value}")
        data_check_string = "\n".join(check_lines)
        secret_key = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode("utf-8")).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed_hash, recv_hash):
            return False, "signature_mismatch", None

        user_id_raw = payload.get("id")
        try:
            user_id = int(str(user_id_raw))
        except (TypeError, ValueError):
            return False, "invalid_user_id", None

        user = {
            "id": user_id,
            "username": str(payload.get("username", "") or ""),
            "first_name": str(payload.get("first_name", "") or ""),
            "last_name": str(payload.get("last_name", "") or ""),
            "photo_url": str(payload.get("photo_url", "") or ""),
            "auth_date": auth_date,
        }
        return True, "ok", user

    def verify_telegram_webapp_init_data(self, init_data_raw: str) -> tuple[bool, str, dict | None]:
        if not self.enabled():
            return False, "telegram_auth_not_configured", None
        raw = str(init_data_raw or "").strip()
        if not raw:
            return False, "empty_init_data", None
        params = parse_qs(raw, keep_blank_values=True)
        flat: dict[str, str] = {}
        for k, v in params.items():
            flat[k] = v[0] if isinstance(v, list) and v else ""
        recv_hash = str(flat.get("hash", "")).strip()
        if not recv_hash:
            return False, "missing_hash", None
        check_lines: list[str] = []
        for key in sorted(flat.keys()):
            if key == "hash":
                continue
            check_lines.append(f"{key}={flat.get(key, '')}")
        data_check_string = "\n".join(check_lines)
        secret_key = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed_hash, recv_hash):
            return False, "signature_mismatch", None

        auth_date_raw = flat.get("auth_date", "0")
        try:
            auth_date = int(str(auth_date_raw))
        except (TypeError, ValueError):
            return False, "invalid_auth_date", None
        now_ts = int(time.time())
        if auth_date > now_ts + 30:
            return False, "auth_date_in_future", None
        if now_ts - auth_date > TELEGRAM_AUTH_MAX_AGE_SEC:
            return False, "auth_date_expired", None

        user_raw = flat.get("user", "")
        try:
            user_obj = json.loads(user_raw) if user_raw else {}
        except json.JSONDecodeError:
            return False, "invalid_user_json", None
        if not isinstance(user_obj, dict):
            return False, "invalid_user_payload", None
        try:
            user_id = int(str(user_obj.get("id")))
        except (TypeError, ValueError):
            return False, "invalid_user_id", None
        user = {
            "id": user_id,
            "username": str(user_obj.get("username", "") or ""),
            "first_name": str(user_obj.get("first_name", "") or ""),
            "last_name": str(user_obj.get("last_name", "") or ""),
            "photo_url": str(user_obj.get("photo_url", "") or ""),
            "auth_date": auth_date,
        }
        return True, "ok", user

    def create_session(self, user: dict) -> dict:
        sid = secrets.token_urlsafe(32)
        now = time.time()
        session = {
            "sid": sid,
            "user": user,
            "created_at": now,
            "updated_at": now,
            "expires_at": now + AUTH_SESSION_TTL_SEC,
        }
        with self._lock:
            self._cleanup_locked(now)
            self._sessions[sid] = session
        return session

    def get_session(self, sid: str) -> dict | None:
        if not sid:
            return None
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            session = self._sessions.get(sid)
            if not session:
                return None
            session["updated_at"] = now
            session["expires_at"] = now + AUTH_SESSION_TTL_SEC
            return dict(session)

    def destroy_session(self, sid: str) -> None:
        if not sid:
            return
        with self._lock:
            self._sessions.pop(sid, None)


AUTH = AuthStore()


class TonAuthStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self._challenges: dict[str, dict] = {}

    def _cleanup_locked(self, now: float) -> None:
        expired_s = [sid for sid, s in self._sessions.items() if float(s.get("expires_at", 0)) <= now]
        for sid in expired_s:
            self._sessions.pop(sid, None)
        expired_c = [nonce for nonce, c in self._challenges.items() if float(c.get("expires_at", 0)) <= now]
        for nonce in expired_c:
            self._challenges.pop(nonce, None)

    def issue_challenge(self, host: str, ua_hash: str) -> dict:
        now = time.time()
        nonce = secrets.token_urlsafe(24)
        item = {
            "nonce": nonce,
            "host": host,
            "ua_hash": ua_hash,
            "created_at": now,
            "expires_at": now + TON_CHALLENGE_TTL_SEC,
            "used": False,
        }
        with self._lock:
            self._cleanup_locked(now)
            self._challenges[nonce] = item
        return dict(item)

    def consume_challenge(self, nonce: str, host: str, ua_hash: str) -> tuple[bool, str]:
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            ch = self._challenges.get(nonce)
            if not ch:
                return False, "challenge_not_found"
            if ch.get("used"):
                return False, "challenge_used"
            if ch.get("host") != host:
                return False, "challenge_host_mismatch"
            if ch.get("ua_hash") != ua_hash:
                return False, "challenge_ua_mismatch"
            if float(ch.get("expires_at", 0)) <= now:
                return False, "challenge_expired"
            ch["used"] = True
            return True, "ok"

    def create_session(self, wallet: dict) -> dict:
        sid = secrets.token_urlsafe(32)
        now = time.time()
        session = {
            "sid": sid,
            "wallet": wallet,
            "created_at": now,
            "updated_at": now,
            "expires_at": now + TON_AUTH_SESSION_TTL_SEC,
        }
        with self._lock:
            self._cleanup_locked(now)
            self._sessions[sid] = session
        return session

    def get_session(self, sid: str) -> dict | None:
        if not sid:
            return None
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            session = self._sessions.get(sid)
            if not session:
                return None
            session["updated_at"] = now
            session["expires_at"] = now + TON_AUTH_SESSION_TTL_SEC
            return dict(session)

    def destroy_session(self, sid: str) -> None:
        if not sid:
            return
        with self._lock:
            self._sessions.pop(sid, None)


TON_AUTH = TonAuthStore()


def _add_security_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
    handler.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")


def _cookie_secure(handler: BaseHTTPRequestHandler) -> bool:
    host = (handler.headers.get("Host", "") or "").split(":")[0].strip().lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False
    if host.startswith("127."):
        return False
    return True


def _build_session_cookie(handler: BaseHTTPRequestHandler, session_id: str, max_age: int) -> str:
    secure = _cookie_secure(handler)
    parts = [
        f"{SESSION_COOKIE_NAME}={session_id}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={max_age}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def _build_clear_session_cookie(handler: BaseHTTPRequestHandler) -> str:
    secure = _cookie_secure(handler)
    parts = [
        f"{SESSION_COOKIE_NAME}=",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=0",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def _build_ton_session_cookie(handler: BaseHTTPRequestHandler, session_id: str, max_age: int) -> str:
    secure = _cookie_secure(handler)
    parts = [
        f"{TON_SESSION_COOKIE_NAME}={session_id}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={max_age}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def _build_clear_ton_session_cookie(handler: BaseHTTPRequestHandler) -> str:
    secure = _cookie_secure(handler)
    parts = [
        f"{TON_SESSION_COOKIE_NAME}=",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=0",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def _parse_cookies(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    raw = handler.headers.get("Cookie", "") or ""
    out: dict[str, str] = {}
    for chunk in raw.split(";"):
        part = chunk.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    try:
        length = int(handler.headers.get("Content-Length", "0") or 0)
    except ValueError:
        length = 0
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict):
            return data
        return {}
    except json.JSONDecodeError:
        return {}


def _auth_user_from_request(handler: BaseHTTPRequestHandler) -> dict | None:
    if not AUTH_REQUIRED:
        return None
    cookies = _parse_cookies(handler)
    sid = cookies.get(SESSION_COOKIE_NAME, "")
    session = AUTH.get_session(sid)
    if not session:
        return None
    return session.get("user")


def _ton_wallet_from_request(handler: BaseHTTPRequestHandler) -> dict | None:
    cookies = _parse_cookies(handler)
    sid = cookies.get(TON_SESSION_COOKIE_NAME, "")
    session = TON_AUTH.get_session(sid)
    if not session:
        return None
    return session.get("wallet")


def _ua_hash(handler: BaseHTTPRequestHandler) -> str:
    ua = handler.headers.get("User-Agent", "") or ""
    return hashlib.sha256(ua.encode("utf-8")).hexdigest()


def _host_only(handler: BaseHTTPRequestHandler) -> str:
    return (handler.headers.get("Host", "") or "").split(":")[0].strip().lower()


def _validate_ton_verify_payload(handler: BaseHTTPRequestHandler, payload: dict) -> tuple[bool, str, dict | None]:
    account = payload.get("account")
    proof = payload.get("ton_proof")
    if not isinstance(account, dict) or not isinstance(proof, dict):
        return False, "invalid_payload_shape", None
    address = str(account.get("address", "")).strip()
    chain = str(account.get("chain", "")).strip()
    public_key = str(account.get("publicKey", "")).strip()
    proof_payload = str(proof.get("payload", "")).strip()
    proof_timestamp = proof.get("timestamp")
    domain = proof.get("domain") if isinstance(proof.get("domain"), dict) else {}
    domain_value = str(domain.get("value", "")).strip().lower()
    signature = str(proof.get("signature", "")).strip()
    if not address or not signature or not proof_payload:
        return False, "missing_proof_fields", None
    try:
        ts = int(str(proof_timestamp))
    except (TypeError, ValueError):
        return False, "invalid_proof_timestamp", None
    now_ts = int(time.time())
    if ts > now_ts + 30:
        return False, "proof_time_in_future", None
    if now_ts - ts > TON_PROOF_MAX_AGE_SEC:
        return False, "proof_expired", None
    host = _host_only(handler)
    if domain_value and domain_value != host:
        return False, "proof_domain_mismatch", None
    ok, reason = TON_AUTH.consume_challenge(proof_payload, host=host, ua_hash=_ua_hash(handler))
    if not ok:
        return False, reason, None
    wallet = {
        "address": address,
        "chain": chain,
        "public_key": public_key,
        "domain": domain_value or host,
        "verified_at": now_ts,
        "proof_timestamp": ts,
        # В MVP валидируем challenge/domain/time/replay. Криптовалидация сигнатуры добавляется отдельным модулем.
        "verification_level": "challenge+domain+time+anti_replay",
        "verification_status": "mvp_verified",
    }
    return True, "ok", wallet


def _require_auth(handler: BaseHTTPRequestHandler) -> dict | None:
    if not AUTH_REQUIRED:
        return {"id": 0, "username": "", "first_name": "", "last_name": "", "photo_url": ""}
    if API_AUTH_TOKEN:
        auth_header = (handler.headers.get("Authorization", "") or "").strip()
        if auth_header == f"Bearer {API_AUTH_TOKEN}":
            return {"id": -1, "username": "service", "first_name": "Service", "last_name": "", "photo_url": ""}
    user = _auth_user_from_request(handler)
    if user:
        return user
    _json_response(
        handler,
        {"ok": False, "error": "unauthorized", "message": "Требуется вход через Telegram"},
        status=HTTPStatus.UNAUTHORIZED,
    )
    return None


def _json_response(
    handler: BaseHTTPRequestHandler,
    payload: dict,
    status: int = 200,
    *,
    cache_control: str | None = None,
    set_cookies: list[str] | None = None,
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    if cache_control:
        handler.send_header("Cache-Control", cache_control)
    _add_security_headers(handler)
    for cookie in set_cookies or []:
        handler.send_header("Set-Cookie", cookie)
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        return


def _safe_send_error(handler: BaseHTTPRequestHandler, code: int) -> None:
    try:
        handler.send_error(code)
    except (BrokenPipeError, ConnectionResetError):
        return


def _redirect(handler: BaseHTTPRequestHandler, location: str, *, set_cookies: list[str] | None = None) -> None:
    handler.send_response(HTTPStatus.FOUND)
    handler.send_header("Location", location)
    _add_security_headers(handler)
    for cookie in set_cookies or []:
        handler.send_header("Set-Cookie", cookie)
    handler.end_headers()


def _serve_file(handler: BaseHTTPRequestHandler, rel_path: str) -> None:
    rel = rel_path.lstrip("/")
    target = (STATIC_DIR / rel).resolve()
    if not str(target).startswith(str(STATIC_DIR.resolve())):
        _safe_send_error(handler, HTTPStatus.FORBIDDEN)
        return
    if not target.exists() or not target.is_file():
        _safe_send_error(handler, HTTPStatus.NOT_FOUND)
        return
    content = target.read_bytes()
    mime = "text/plain"
    if target.suffix == ".html":
        mime = "text/html; charset=utf-8"
    elif target.suffix == ".css":
        mime = "text/css; charset=utf-8"
    elif target.suffix == ".js":
        mime = "application/javascript; charset=utf-8"
    elif target.suffix == ".json":
        mime = "application/json; charset=utf-8"
    elif target.suffix == ".svg":
        mime = "image/svg+xml"
    elif target.suffix == ".png":
        mime = "image/png"
    elif target.suffix == ".jpg" or target.suffix == ".jpeg":
        mime = "image/jpeg"
    elif target.suffix == ".webp":
        mime = "image/webp"
    elif target.suffix == ".ico":
        mime = "image/x-icon"
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(content)))
    if target.suffix in {".html"}:
        handler.send_header("Cache-Control", "no-store")
    _add_security_headers(handler)
    handler.end_headers()
    try:
        handler.wfile.write(content)
    except (BrokenPipeError, ConnectionResetError):
        return


def _request_origin(handler: BaseHTTPRequestHandler) -> str:
    host = handler.headers.get("Host", "") or "127.0.0.1:8080"
    xf_proto = (handler.headers.get("X-Forwarded-Proto", "") or "").strip().lower()
    proto = xf_proto if xf_proto in {"http", "https"} else "http"
    host_only = host.split(":")[0].strip().lower()
    if host_only not in {"127.0.0.1", "localhost", "::1"} and not host_only.startswith("127."):
        proto = "https"
    return f"{proto}://{host}"


def _tonconnect_manifest(handler: BaseHTTPRequestHandler) -> None:
    origin = _request_origin(handler)
    payload = {
        "url": origin,
        "name": "GiftMarketZone",
        "iconUrl": f"{origin}/assets/logo-mask.svg",
        "termsOfUseUrl": f"{origin}/index.html",
        "privacyPolicyUrl": f"{origin}/index.html",
    }
    _json_response(handler, payload, cache_control="public, max-age=300")


class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/auth/bootstrap":
            user = _auth_user_from_request(self)
            _json_response(
                self,
                {
                    "ok": True,
                    "required": AUTH_REQUIRED,
                    "enabled": AUTH.enabled(),
                    "bot_username": TELEGRAM_BOT_USERNAME,
                    "session_ttl_sec": AUTH_SESSION_TTL_SEC,
                    "max_auth_age_sec": TELEGRAM_AUTH_MAX_AGE_SEC,
                    "authenticated": bool(user),
                    "user": user,
                },
                cache_control="no-store",
            )
            return

        if path == "/tonconnect-manifest.json":
            _tonconnect_manifest(self)
            return

        if path == "/api/auth/config":
            _json_response(
                self,
                {
                    "ok": True,
                    "required": AUTH_REQUIRED,
                    "enabled": AUTH.enabled(),
                    "bot_username": TELEGRAM_BOT_USERNAME,
                    "session_ttl_sec": AUTH_SESSION_TTL_SEC,
                    "max_auth_age_sec": TELEGRAM_AUTH_MAX_AGE_SEC,
                },
                cache_control="no-store",
            )
            return

        if path == "/api/auth/me":
            user = _auth_user_from_request(self)
            _json_response(
                self,
                {
                    "ok": True,
                    "authenticated": bool(user),
                    "required": AUTH_REQUIRED,
                    "enabled": AUTH.enabled(),
                    "user": user,
                },
                cache_control="no-store",
            )
            return

        if path == "/api/auth/telegram/callback":
            params = parse_qs(parsed.query)
            payload = {k: (v[0] if isinstance(v, list) and v else "") for k, v in params.items()}
            ok, reason, user = AUTH.verify_telegram_payload(payload)
            if not ok or not user:
                _redirect(
                    self,
                    f"/index.html?auth=telegram_failed&reason={reason}#overview",
                    set_cookies=[_build_clear_session_cookie(self)],
                )
                return
            session = AUTH.create_session(user)
            _redirect(
                self,
                "/index.html?auth=telegram_ok#overview",
                set_cookies=[_build_session_cookie(self, session["sid"], AUTH_SESSION_TTL_SEC)],
            )
            return

        if path == "/api/auth/ton/config":
            _json_response(
                self,
                {
                    "ok": True,
                    "required": TON_AUTH_REQUIRED,
                    "session_ttl_sec": TON_AUTH_SESSION_TTL_SEC,
                    "proof_max_age_sec": TON_PROOF_MAX_AGE_SEC,
                    "challenge_ttl_sec": TON_CHALLENGE_TTL_SEC,
                },
                cache_control="no-store",
            )
            return

        if path == "/api/auth/ton/me":
            wallet = _ton_wallet_from_request(self)
            _json_response(
                self,
                {
                    "ok": True,
                    "connected": bool(wallet),
                    "required": TON_AUTH_REQUIRED,
                    "wallet": wallet,
                },
                cache_control="no-store",
            )
            return

        if path == "/" or path == "/index.html":
            _serve_file(self, "index.html")
            return
        if path.startswith("/assets/"):
            _serve_file(self, path.replace("/assets/", ""))
            return

        if path == "/healthz":
            _json_response(self, {"ok": True, "service": "telegram-gifts-analytics"})
            return

        if path.startswith("/api/") and not path.startswith("/api/auth/"):
            if not _require_auth(self):
                return

        if path == "/api/rates/stars":
            _json_response(self, STATE.stars_rate())
            return

        if path == "/api/ai/status":
            params = parse_qs(parsed.query)
            probe = ((params.get("probe") or ["0"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            _json_response(self, STATE.ai_status(probe=probe))
            return

        if path == "/api/market/overview":
            _json_response(self, STATE.market_overview())
            return

        if path == "/api/bases":
            _json_response(self, {"items": STATE.list_bases(), "stars_rate": STATE.stars_rate()})
            return

        if path.startswith("/api/bases/") and path.count("/") == 3:
            base_id = unquote(path.split("/")[-1])
            base = STATE.get_base(base_id)
            if not base:
                _safe_send_error(self, HTTPStatus.NOT_FOUND)
                return
            _json_response(self, base)
            return

        if path.startswith("/api/bases/") and path.endswith("/dimensions"):
            base_id = unquote(path.split("/")[3])
            params = parse_qs(parsed.query)
            dim_type = (params.get("type") or ["model"])[0]
            period = (params.get("period") or ["24h"])[0]
            data = STATE.list_dimensions(base_id, dim_type, period)
            data["stars_rate"] = STATE.stars_rate()
            _json_response(self, data)
            return

        if path.startswith("/api/bases/") and path.endswith("/variants"):
            base_id = unquote(path.split("/")[3])
            params = parse_qs(parsed.query)
            sort = (params.get("sort") or ["reco_score_desc"])[0]
            page = int((params.get("page") or ["1"])[0])
            page_size = int((params.get("page_size") or ["20"])[0])
            include_ai = ((params.get("ai") or ["0"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            filters = {
                "model_id": params.get("model_id") or [],
                "background_id": params.get("background_id") or [],
                "pattern_id": params.get("pattern_id") or [],
            }
            data = STATE.list_variants(
                base_id=base_id,
                filters=filters,
                sort=sort,
                page=page,
                page_size=page_size,
                include_ai=include_ai,
            )
            data["stars_rate"] = STATE.stars_rate()
            _json_response(self, data)
            return

        if path.startswith("/api/variants/") and path.count("/") == 3:
            variant_id = unquote(path.split("/")[-1])
            data = STATE.get_variant(variant_id)
            if not data:
                _json_response(
                    self,
                    {
                        "error": "variant_not_found_or_not_active",
                        "variant_id": variant_id,
                        "hint": "Variant may be sold out and excluded from active dataset.",
                    },
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            _json_response(self, data)
            return

        if path.startswith("/api/variants/") and path.endswith("/listings"):
            variant_id = unquote(path.split("/")[3])
            data = STATE.list_variant_listings(variant_id)
            _json_response(self, data)
            return

        if path.startswith("/api/variants/") and path.endswith("/timeseries"):
            variant_id = unquote(path.split("/")[3])
            params = parse_qs(parsed.query)
            metric = (params.get("metric") or ["floor"])[0]
            period = (params.get("period") or ["24h"])[0]
            data = STATE.list_variant_timeseries(variant_id, metric, period)
            _json_response(self, data)
            return

        if path.startswith("/api/screeners/"):
            screener = path.split("/")[-1]
            params = parse_qs(parsed.query)
            entity = (params.get("entity") or ["variant"])[0]
            period = (params.get("period") or ["24h"])[0]
            metric_type = (params.get("type") or ["price"])[0]
            include_ai = ((params.get("ai") or ["0"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            data = STATE.screeners(screener, entity, period, metric_type, include_ai=include_ai)
            _json_response(self, data)
            return

        if path == "/api/recommendations":
            params = parse_qs(parsed.query)
            scope = (params.get("scope") or ["all"])[0]
            entity = (params.get("entity") or ["variant"])[0]
            include_ai = ((params.get("ai") or ["0"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            data = STATE.recommendations(scope, entity, include_ai=include_ai)
            _json_response(self, data)
            return

        if path == "/api/alerts":
            _json_response(self, {"items": STATE.alerts_list()})
            return

        _safe_send_error(self, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/auth/telegram/verify":
            payload = _read_json_body(self)
            ok, reason, user = AUTH.verify_telegram_payload(payload)
            if not ok or not user:
                _json_response(
                    self,
                    {"ok": False, "error": "auth_failed", "reason": reason},
                    status=HTTPStatus.UNAUTHORIZED,
                    cache_control="no-store",
                    set_cookies=[_build_clear_session_cookie(self)],
                )
                return
            session = AUTH.create_session(user)
            _json_response(
                self,
                {"ok": True, "authenticated": True, "user": session.get("user")},
                cache_control="no-store",
                set_cookies=[_build_session_cookie(self, session["sid"], AUTH_SESSION_TTL_SEC)],
            )
            return

        if parsed.path == "/api/auth/telegram/webapp-login":
            payload = _read_json_body(self)
            init_data = payload.get("init_data") if isinstance(payload, dict) else ""
            ok, reason, user = AUTH.verify_telegram_webapp_init_data(str(init_data or ""))
            if not ok or not user:
                _json_response(
                    self,
                    {"ok": False, "error": "auth_failed", "reason": reason},
                    status=HTTPStatus.UNAUTHORIZED,
                    cache_control="no-store",
                    set_cookies=[_build_clear_session_cookie(self)],
                )
                return
            session = AUTH.create_session(user)
            _json_response(
                self,
                {"ok": True, "authenticated": True, "user": session.get("user"), "source": "telegram_webapp"},
                cache_control="no-store",
                set_cookies=[_build_session_cookie(self, session["sid"], AUTH_SESSION_TTL_SEC)],
            )
            return

        if parsed.path == "/api/auth/logout":
            cookies = _parse_cookies(self)
            AUTH.destroy_session(cookies.get(SESSION_COOKIE_NAME, ""))
            _json_response(
                self,
                {"ok": True, "authenticated": False},
                cache_control="no-store",
                set_cookies=[_build_clear_session_cookie(self)],
            )
            return

        if parsed.path == "/api/auth/ton/challenge":
            host = _host_only(self)
            challenge = TON_AUTH.issue_challenge(host=host, ua_hash=_ua_hash(self))
            _json_response(
                self,
                {
                    "ok": True,
                    "challenge": challenge.get("nonce"),
                    "expires_at": int(challenge.get("expires_at", 0)),
                    "ttl_sec": TON_CHALLENGE_TTL_SEC,
                },
                cache_control="no-store",
            )
            return

        if parsed.path == "/api/auth/ton/verify":
            payload = _read_json_body(self)
            ok, reason, wallet = _validate_ton_verify_payload(self, payload)
            if not ok or not wallet:
                _json_response(
                    self,
                    {"ok": False, "error": "ton_auth_failed", "reason": reason},
                    status=HTTPStatus.UNAUTHORIZED,
                    cache_control="no-store",
                    set_cookies=[_build_clear_ton_session_cookie(self)],
                )
                return
            session = TON_AUTH.create_session(wallet)
            _json_response(
                self,
                {"ok": True, "connected": True, "wallet": session.get("wallet")},
                cache_control="no-store",
                set_cookies=[_build_ton_session_cookie(self, session["sid"], TON_AUTH_SESSION_TTL_SEC)],
            )
            return

        if parsed.path == "/api/auth/ton/logout":
            cookies = _parse_cookies(self)
            TON_AUTH.destroy_session(cookies.get(TON_SESSION_COOKIE_NAME, ""))
            _json_response(
                self,
                {"ok": True, "connected": False},
                cache_control="no-store",
                set_cookies=[_build_clear_ton_session_cookie(self)],
            )
            return

        if parsed.path.startswith("/api/") and not parsed.path.startswith("/api/auth/"):
            if not _require_auth(self):
                return

        if parsed.path == "/api/admin/refresh":
            threading.Thread(target=STATE.ingest_safe, daemon=True).start()
            _json_response(self, {"ok": True, "message": "refresh started"})
            return
        if parsed.path == "/api/alerts":
            rule = _read_json_body(self)
            _json_response(self, STATE.alerts_create(rule), status=201)
            return
        _safe_send_error(self, HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") and not parsed.path.startswith("/api/auth/"):
            if not _require_auth(self):
                return
        if parsed.path.startswith("/api/alerts/"):
            alert_id = parsed.path.split("/")[-1]
            rule = _read_json_body(self)
            updated = STATE.alerts_update(alert_id, rule)
            if not updated:
                _safe_send_error(self, HTTPStatus.NOT_FOUND)
                return
            _json_response(self, updated)
            return
        _safe_send_error(self, HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") and not parsed.path.startswith("/api/auth/"):
            if not _require_auth(self):
                return
        if parsed.path.startswith("/api/alerts/"):
            alert_id = parsed.path.split("/")[-1]
            ok = STATE.alerts_delete(alert_id)
            if not ok:
                _safe_send_error(self, HTTPStatus.NOT_FOUND)
                return
            _json_response(self, {"ok": True})
            return
        _safe_send_error(self, HTTPStatus.NOT_FOUND)

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

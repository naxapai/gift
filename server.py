from __future__ import annotations

import json
import os
import math
import secrets
import threading
import time
import subprocess
import hmac
import hashlib
from collections import defaultdict, deque
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse, urlencode
from urllib.request import Request, urlopen

from core import GiftAnalyticsService
import bot as signal_bot

ROOT = Path(__file__).parent
STATIC_DIR = ROOT / "static"
SPA_FRONTEND_ROUTES = {
    "/catalog",
    "/screeners",
    "/signals",
    "/listing",
    "/trades",
    "/favorites",
    "/cabinet",
    "/settings",
    "/admin",
}

_STATE: GiftAnalyticsService | None = None
_STATE_LOCK = threading.Lock()


def _state() -> GiftAnalyticsService:
    global _STATE
    if _STATE is not None:
        return _STATE
    with _STATE_LOCK:
        if _STATE is None:
            _STATE = GiftAnalyticsService()
    return _STATE

AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "false").strip().lower() in {"1", "true", "yes", "on"}
PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL", "https://giftmarketzone.com").strip() or "https://giftmarketzone.com").rstrip("/")
PUBLIC_BASE_HOST = (urlparse(PUBLIC_BASE_URL).netloc or "giftmarketzone.com").split(":")[0].strip().lower() or "giftmarketzone.com"
TELEGRAM_BOT_TOKEN = (
    os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    or os.getenv("TG_BOT_TOKEN", "").strip()
)
TELEGRAM_BOT_USERNAME = (
    os.getenv("TELEGRAM_BOT_USERNAME", "").strip()
    or os.getenv("TG_BOT_USERNAME", "").strip()
).lstrip("@")
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "").strip()
AUTH_SESSION_TTL_SEC = max(300, int(os.getenv("AUTH_SESSION_TTL_SEC", "86400")))
TELEGRAM_AUTH_MAX_AGE_SEC = max(30, int(os.getenv("TELEGRAM_AUTH_MAX_AGE_SEC", "300")))
SESSION_COOKIE_NAME = os.getenv("AUTH_SESSION_COOKIE", "gmz_session").strip() or "gmz_session"
TON_SESSION_COOKIE_NAME = os.getenv("TON_SESSION_COOKIE", "gmz_ton_session").strip() or "gmz_ton_session"
TON_AUTH_REQUIRED = os.getenv("TON_AUTH_REQUIRED", "false").strip().lower() in {"1", "true", "yes", "on"}
TON_AUTH_SESSION_TTL_SEC = max(300, int(os.getenv("TON_AUTH_SESSION_TTL_SEC", "86400")))
TON_PROOF_MAX_AGE_SEC = max(60, int(os.getenv("TON_PROOF_MAX_AGE_SEC", "300")))
TON_CHALLENGE_TTL_SEC = max(30, int(os.getenv("TON_CHALLENGE_TTL_SEC", "180")))
TON_ALLOW_WEAK_VERIFY = os.getenv("TON_ALLOW_WEAK_VERIFY", "true").strip().lower() in {"1", "true", "yes", "on"}
TON_BALANCE_API_URL = (os.getenv("TON_BALANCE_API_URL", "https://toncenter.com/api/v2/getAddressBalance").strip() or "https://toncenter.com/api/v2/getAddressBalance")
TON_BALANCE_TIMEOUT_SEC = max(2.0, float(os.getenv("TON_BALANCE_TIMEOUT_SEC", "8")))
TON_BALANCE_CACHE_TTL_SEC = max(5.0, float(os.getenv("TON_BALANCE_CACHE_TTL_SEC", "30")))
TONCENTER_API_KEY = os.getenv("TONCENTER_API_KEY", "").strip()
BOT_AUTORUN = os.getenv("BOT_AUTORUN", "false").strip().lower() in {"1", "true", "yes", "on"}
BOT_INTERVAL_SEC = max(15, int(os.getenv("BOT_POLL_INTERVAL", "30")))
BOT_API_BASE_URL = os.getenv("BOT_API_BASE_URL", "").strip()
BOT_API_AUTH_TOKEN = os.getenv("BOT_API_AUTH_TOKEN", "").strip() or API_AUTH_TOKEN
BRIDGE_API_TOKEN = os.getenv("BRIDGE_API_TOKEN", "").strip() or os.getenv("TELEGRAM_GIFTS_API_TOKEN", "").strip()
BRIDGE_API_PATH = (os.getenv("BRIDGE_API_PATH", "/bridge/gifts/verified").strip() or "/bridge/gifts/verified")
AUTH_COOKIE_DOMAIN = os.getenv("AUTH_COOKIE_DOMAIN", "").strip().lower()
TON_COOKIE_DOMAIN = os.getenv("TON_COOKIE_DOMAIN", AUTH_COOKIE_DOMAIN).strip().lower()
CORS_ALLOWED_ORIGINS_RAW = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    f"{PUBLIC_BASE_URL},https://telegram-gifts-market.onrender.com,http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
).strip()
TON_PROOF_ALLOWED_DOMAINS_RAW = os.getenv(
    "TON_PROOF_ALLOWED_DOMAINS",
    f"{PUBLIC_BASE_HOST},telegram-gifts-market.onrender.com,localhost,127.0.0.1",
).strip()
ADMIN_TELEGRAM_USER_ID = os.getenv("ADMIN_TELEGRAM_USER_ID", "").strip()
ADMIN_TELEGRAM_USER_IDS_RAW = os.getenv("ADMIN_TELEGRAM_USER_IDS", "").strip()
SIGNAL_ENGINE_OVERRIDES_FILE = ROOT / "data" / "signal_engine_overrides.json"
MANUAL_FULL_SYNC_COOLDOWN_SEC = max(300, int(os.getenv("MANUAL_FULL_SYNC_COOLDOWN_SEC", "3600")))
MANUAL_FULL_SYNC_TIMEOUT_SEC = max(120, int(os.getenv("MANUAL_FULL_SYNC_TIMEOUT_SEC", "1800")))
LAST_FULL_SYNC_TS_FILE = Path(os.getenv("FRAGMENT_LAST_FULL_TS_FILE", "/tmp/fragment_sync_last_full.ts"))
SNAPSHOT_META_FILE = ROOT / "data" / "fragment_snapshot_meta.json"
TZ_GATES_STATUS_FILE = ROOT / "data" / "tz_gates_status.json"

_BOT_STATUS = {
    "enabled": False,
    "running": False,
    "last_run_at": None,
    "last_ok_at": None,
    "last_error": "",
}

_REFRESH_LOCK = threading.Lock()
_REFRESH_STATUS = {
    "running": False,
    "mode": "",
    "started_at": None,
    "last_mode": "",
    "last_started_at": None,
    "last_finished_at": None,
    "last_error": "",
}
_TON_BALANCE_CACHE_LOCK = threading.Lock()
_TON_BALANCE_CACHE: dict[str, dict] = {}

HTTP_METRICS_WINDOW = max(200, int(os.getenv("HTTP_METRICS_WINDOW", "5000")))
HTTP_METRICS_TOP_ROUTES = max(5, min(50, int(os.getenv("HTTP_METRICS_TOP_ROUTES", "20"))))
_HTTP_METRICS_LOCK = threading.Lock()
_HTTP_METRICS_STARTED_AT = time.time()
_HTTP_METRICS_TOTAL = 0
_HTTP_METRICS_BY_METHOD: dict[str, int] = defaultdict(int)
_HTTP_METRICS_BY_STATUS: dict[str, int] = defaultdict(int)
_HTTP_METRICS_BY_ROUTE: dict[str, int] = defaultdict(int)
_HTTP_METRICS_LAT_ALL_MS: deque[float] = deque(maxlen=HTTP_METRICS_WINDOW)
_HTTP_METRICS_LAT_BY_ROUTE: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=HTTP_METRICS_WINDOW))
_SSE_METRICS_ACTIVE: dict[str, int] = defaultdict(int)
_SSE_METRICS_OPENS: dict[str, int] = defaultdict(int)
_SSE_METRICS_ABRUPT_CLOSES: dict[str, int] = defaultdict(int)
_ADMIN_RT_CACHE_LOCK = threading.Lock()
_ADMIN_RT_CACHE: dict[tuple, tuple[float, object]] = {}


def _split_csv(raw: str) -> list[str]:
    return [part.strip() for part in str(raw or "").split(",") if part.strip()]


def _load_json_file(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json_file(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{int(time.time() * 1000)}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


CORS_ALLOWED_ORIGINS = {item.rstrip("/") for item in _split_csv(CORS_ALLOWED_ORIGINS_RAW)}
TON_PROOF_ALLOWED_DOMAINS = {item.strip().lower() for item in _split_csv(TON_PROOF_ALLOWED_DOMAINS_RAW)}
AUTH_SESSIONS_FILE = ROOT / "data" / "auth_sessions.json"
TON_AUTH_SESSIONS_FILE = ROOT / "data" / "ton_auth_sessions.json"


def _admin_rt_cache_get(key: tuple, ttl_sec: float | None = None):
    ttl = 0.0 if ttl_sec is None else max(0.0, float(ttl_sec))
    now = time.time()
    with _ADMIN_RT_CACHE_LOCK:
        item = _ADMIN_RT_CACHE.get(tuple(key))
        if not item:
            return None
        ts, payload = item
        if ttl > 0.0 and (now - float(ts)) > ttl:
            _ADMIN_RT_CACHE.pop(tuple(key), None)
            return None
        return json.loads(json.dumps(payload, ensure_ascii=False))


def _admin_rt_cache_set(key: tuple, payload):
    with _ADMIN_RT_CACHE_LOCK:
        _ADMIN_RT_CACHE[tuple(key)] = (time.time(), json.loads(json.dumps(payload, ensure_ascii=False)))


def _observe_sse_open(stream: str) -> None:
    key = str(stream or "unknown")
    with _HTTP_METRICS_LOCK:
        _SSE_METRICS_OPENS[key] += 1
        _SSE_METRICS_ACTIVE[key] += 1


def _observe_sse_close(stream: str, *, abrupt: bool) -> None:
    key = str(stream or "unknown")
    with _HTTP_METRICS_LOCK:
        _SSE_METRICS_ACTIVE[key] = max(0, int(_SSE_METRICS_ACTIVE.get(key, 0)) - 1)
        if abrupt:
            _SSE_METRICS_ABRUPT_CLOSES[key] += 1


def _v1_stream_snapshot_token(svc: GiftAnalyticsService) -> str:
    state = svc.state if isinstance(getattr(svc, "state", None), dict) else {}
    try:
        listing_status = svc.listing_source_status_v1(allow_remote=False)
    except Exception:
        listing_status = {}
    payload = {
        "data_version": int(getattr(svc, "_data_version", 0)),
        "updated_at": str(state.get("updated_at") or ""),
        "last_error": str(state.get("last_error") or ""),
        "ingest_in_progress": bool(state.get("ingest_in_progress")),
        "listing_source": str((listing_status or {}).get("source") or ""),
        "listing_updated_at": str((listing_status or {}).get("updated_at") or ""),
        "listing_error": str((listing_status or {}).get("error") or (listing_status or {}).get("last_error") or ""),
        "listing_rows_count": int((listing_status or {}).get("rows_count") or 0),
        "listing_degraded": bool((listing_status or {}).get("degraded")),
        "listing_runtime_error_count": int(getattr(svc, "_listing_runtime_error_count", 0)),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _v1_signals_stream_snapshot_token(svc: GiftAnalyticsService, mode: str | None = None) -> str:
    state = svc.state if isinstance(getattr(svc, "state", None), dict) else {}
    payload = {
        "mode": str(mode or ""),
        "engine_mode": str(getattr(svc, "v1_signal_engine_mode", "") or ""),
        "data_version": int(getattr(svc, "_data_version", 0)),
        "updated_at": str(state.get("updated_at") or ""),
        "last_error": str(state.get("last_error") or ""),
        "ingest_in_progress": bool(state.get("ingest_in_progress")),
        "listing_runtime_error_count": int(getattr(svc, "_listing_runtime_error_count", 0)),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _v1_listings_stream_snapshot_token(
    svc: GiftAnalyticsService,
    *,
    window: str | None = None,
    include_low_priority: bool = False,
) -> str:
    try:
        listing_status = svc.listing_source_status_v1(allow_remote=False)
    except Exception:
        listing_status = {}
    listing_state = svc.listing_state if isinstance(getattr(svc, "listing_state", None), dict) else {}
    tracker_state = svc.listing_tracker_state if isinstance(getattr(svc, "listing_tracker_state", None), dict) else {}
    payload = {
        "window": str(window or ""),
        "include_low_priority": bool(include_low_priority),
        "data_version": int(getattr(svc, "_data_version", 0)),
        "listing_runtime_error_count": int(getattr(svc, "_listing_runtime_error_count", 0)),
        "listing_source": str((listing_status or {}).get("source") or ""),
        "listing_updated_at": str((listing_status or {}).get("updated_at") or ""),
        "listing_error": str((listing_status or {}).get("error") or (listing_status or {}).get("last_error") or ""),
        "listing_rows_count": int((listing_status or {}).get("rows_count") or 0),
        "listing_degraded": bool((listing_status or {}).get("degraded")),
        "listing_state_size": len(listing_state),
        "tracker_state_size": len(tracker_state),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _v1_listings_events_stream_snapshot_token(
    svc: GiftAnalyticsService,
    *,
    new_window_sec: int,
    include_relisted: bool,
) -> str:
    try:
        listing_status = svc.listing_source_status_v1(allow_remote=False)
    except Exception:
        listing_status = {}
    listing_state = svc.listing_state if isinstance(getattr(svc, "listing_state", None), dict) else {}
    tracker_state = svc.listing_tracker_state if isinstance(getattr(svc, "listing_tracker_state", None), dict) else {}
    payload = {
        "new_window_sec": int(new_window_sec),
        "include_relisted": bool(include_relisted),
        "data_version": int(getattr(svc, "_data_version", 0)),
        "listing_runtime_error_count": int(getattr(svc, "_listing_runtime_error_count", 0)),
        "listing_source": str((listing_status or {}).get("source") or ""),
        "listing_updated_at": str((listing_status or {}).get("updated_at") or ""),
        "listing_error": str((listing_status or {}).get("error") or (listing_status or {}).get("last_error") or ""),
        "listing_rows_count": int((listing_status or {}).get("rows_count") or 0),
        "listing_degraded": bool((listing_status or {}).get("degraded")),
        "listing_state_size": len(listing_state),
        "tracker_state_size": len(tracker_state),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _sse_disconnect_rate_pct_locked(stream: str | None = None) -> float:
    if stream:
        opens = int(_SSE_METRICS_OPENS.get(stream, 0))
        abrupt = int(_SSE_METRICS_ABRUPT_CLOSES.get(stream, 0))
        return round((float(abrupt) / float(max(1, opens))) * 100.0, 4)
    total_opens = int(sum(_SSE_METRICS_OPENS.values()))
    total_abrupt = int(sum(_SSE_METRICS_ABRUPT_CLOSES.values()))
    return round((float(total_abrupt) / float(max(1, total_opens))) * 100.0, 4)


def _sse_disconnect_rate_pct(stream: str | None = None) -> float:
    with _HTTP_METRICS_LOCK:
        return _sse_disconnect_rate_pct_locked(stream)


def _http_route_key(path: str) -> str:
    p = urlparse(str(path or "")).path or "/"
    if p.startswith("/v1/variants/") and p.count("/") >= 3 and not p.startswith("/v1/variants/resolve"):
        return "/v1/variants/:id"
    if p.startswith("/v1/collections/") and p.count("/") >= 3:
        return "/v1/collections/:id"
    if p.startswith("/v1/signals/") and p.count("/") >= 3 and not p.startswith("/v1/signals/stream"):
        return "/v1/signals/:id"
    if p.startswith("/api/alerts/") and p.count("/") >= 3:
        return "/api/alerts/:id"
    if p.startswith("/assets/"):
        return "/assets/*"
    return p


def _http_percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return 0.0
    arr = sorted(samples)
    idx = int(max(0, min(len(arr) - 1, round((pct / 100.0) * (len(arr) - 1)))))
    return round(float(arr[idx]), 3)


def _observe_http_request(method: str, path: str, status_code: int, duration_ms: float) -> None:
    route = _http_route_key(path)
    status_bucket = f"{int(status_code) // 100}xx" if status_code >= 100 else "unknown"
    duration_ms = max(0.0, float(duration_ms))
    with _HTTP_METRICS_LOCK:
        global _HTTP_METRICS_TOTAL
        _HTTP_METRICS_TOTAL += 1
        _HTTP_METRICS_BY_METHOD[str(method or "UNKNOWN").upper()] += 1
        _HTTP_METRICS_BY_STATUS[status_bucket] += 1
        _HTTP_METRICS_BY_ROUTE[route] += 1
        _HTTP_METRICS_LAT_ALL_MS.append(duration_ms)
        _HTTP_METRICS_LAT_BY_ROUTE[route].append(duration_ms)


def _http_metrics_snapshot() -> dict:
    with _HTTP_METRICS_LOCK:
        all_lat = list(_HTTP_METRICS_LAT_ALL_MS)
        top_routes = sorted(_HTTP_METRICS_BY_ROUTE.items(), key=lambda x: x[1], reverse=True)[:HTTP_METRICS_TOP_ROUTES]
        routes_payload = []
        for route, count in top_routes:
            route_lat = list(_HTTP_METRICS_LAT_BY_ROUTE.get(route) or [])
            routes_payload.append(
                {
                    "route": route,
                    "count": int(count),
                    "p50_ms": _http_percentile(route_lat, 50),
                    "p95_ms": _http_percentile(route_lat, 95),
                    "p99_ms": _http_percentile(route_lat, 99),
                }
            )
        return {
            "ok": True,
            "started_at": datetime.fromtimestamp(_HTTP_METRICS_STARTED_AT, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "uptime_sec": max(0, int(time.time() - _HTTP_METRICS_STARTED_AT)),
            "window_size": HTTP_METRICS_WINDOW,
            "total_requests": int(_HTTP_METRICS_TOTAL),
            "methods": {k: int(v) for k, v in sorted(_HTTP_METRICS_BY_METHOD.items())},
            "statuses": {k: int(v) for k, v in sorted(_HTTP_METRICS_BY_STATUS.items())},
            "latency_ms": {
                "p50": _http_percentile(all_lat, 50),
                "p95": _http_percentile(all_lat, 95),
                "p99": _http_percentile(all_lat, 99),
            },
            "sse": {
                "active": {k: int(v) for k, v in sorted(_SSE_METRICS_ACTIVE.items())},
                "opens": {k: int(v) for k, v in sorted(_SSE_METRICS_OPENS.items())},
                "abrupt_closes": {k: int(v) for k, v in sorted(_SSE_METRICS_ABRUPT_CLOSES.items())},
                "abrupt_disconnect_rate_pct": _sse_disconnect_rate_pct_locked(),
            },
            "top_routes": routes_payload,
        }


def _http_metrics_reset() -> dict:
    with _HTTP_METRICS_LOCK:
        global _HTTP_METRICS_STARTED_AT, _HTTP_METRICS_TOTAL
        _HTTP_METRICS_STARTED_AT = time.time()
        _HTTP_METRICS_TOTAL = 0
        _HTTP_METRICS_BY_METHOD.clear()
        _HTTP_METRICS_BY_STATUS.clear()
        _HTTP_METRICS_BY_ROUTE.clear()
        _HTTP_METRICS_LAT_ALL_MS.clear()
        _HTTP_METRICS_LAT_BY_ROUTE.clear()
        _SSE_METRICS_ACTIVE.clear()
        _SSE_METRICS_OPENS.clear()
        _SSE_METRICS_ABRUPT_CLOSES.clear()
    return _http_metrics_snapshot()


def _tz_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _tz_gates_corridor() -> dict:
    return {
        "buy_min": _as_int_env("TZ_GATES_BUY_MIN", 1),
        "buy_max": _as_int_env("TZ_GATES_BUY_MAX", 20),
        "watch_min": _as_int_env("TZ_GATES_WATCH_MIN", 0),
        "watch_max": _as_int_env("TZ_GATES_WATCH_MAX", 80),
        "skip_min": _as_int_env("TZ_GATES_SKIP_MIN", 80),
        "skip_max": _as_int_env("TZ_GATES_SKIP_MAX", 260),
        "sell_min": _as_int_env("TZ_GATES_SELL_MIN", 0),
        "sell_max": _as_int_env("TZ_GATES_SELL_MAX", 20),
    }


def _tz_gates_corridor_checks(dist: dict, corridor: dict) -> dict:
    return {
        "buy_ok": corridor["buy_min"] <= int(dist.get("BUY", 0)) <= corridor["buy_max"],
        "watch_ok": corridor["watch_min"] <= int(dist.get("WATCH", 0)) <= corridor["watch_max"],
        "skip_ok": corridor["skip_min"] <= int(dist.get("SKIP", 0)) <= corridor["skip_max"],
        "sell_ok": corridor["sell_min"] <= int(dist.get("SELL", 0)) <= corridor["sell_max"],
    }


def _normalize_tz_gates_payload(payload: dict | None, report_source: str = "file", error: str = "") -> dict:
    payload = payload or {}
    report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    dist = report.get("distribution") if isinstance(report.get("distribution"), dict) else {}
    if not dist and isinstance(payload.get("distribution"), dict):
        dist = payload.get("distribution") or {}
    corridor = payload.get("corridor") if isinstance(payload.get("corridor"), dict) else _tz_gates_corridor()
    corridor_checks = payload.get("corridor_checks") if isinstance(payload.get("corridor_checks"), dict) else _tz_gates_corridor_checks(dist, corridor)
    corridor_ok = all(bool(v) for v in corridor_checks.values())
    source_raw = str((report.get("source") if isinstance(report, dict) else "") or payload.get("source") or "")
    source_ok = payload.get("source_ok")
    if source_ok is None:
        source_ok = source_raw in {"remote", "local", "local_fallback"}
    gates_ok = payload.get("gates_ok")
    if gates_ok is None:
        gates_ok = bool(report.get("gates_passed")) if isinstance(report, dict) else bool(payload.get("ok"))
    status_ok = payload.get("status_ok")
    if status_ok is None:
        # Corridor drift is a warning signal for calibration, not service health.
        status_ok = bool(source_ok) and bool(gates_ok)
    return {
        "status_ok": bool(status_ok),
        "checked_at": payload.get("checked_at") or _tz_now_iso(),
        "source_ok": bool(source_ok),
        "gates_ok": bool(gates_ok),
        "corridor_ok": bool(corridor_ok),
        "corridor_checks": corridor_checks,
        "report_source": payload.get("report_source") or report_source,
        "error": str(payload.get("error") or error or ""),
        "corridor": corridor,
        "report": report,
        "ok": bool(status_ok),
    }


def _build_tz_gates_payload_runtime() -> dict:
    try:
        data_version = int(getattr(_state(), "_data_version", 0))
    except Exception:
        data_version = 0
    cache_key = ("tz_gates_runtime", data_version)
    cached = _admin_rt_cache_get(cache_key, ttl_sec=30.0)
    if isinstance(cached, dict):
        return cached
    from scripts.backtest_tz_signals import run as backtest_run

    horizon_hours = _as_int_env("TZ_GATES_HORIZON_HOURS", 24)
    limit = _as_int_env("TZ_GATES_LIMIT", 1000)
    report = backtest_run(horizon_hours=horizon_hours, mode="tz", limit=limit, signals_url=None)
    corridor = _tz_gates_corridor()
    dist = report.get("distribution") if isinstance(report.get("distribution"), dict) else {}
    payload = {
        "checked_at": _tz_now_iso(),
        "source_ok": str(report.get("source") or "") in {"remote", "local", "local_fallback"},
        "gates_ok": bool(report.get("gates_passed")),
        "corridor": corridor,
        "corridor_checks": _tz_gates_corridor_checks(dist, corridor),
        "report_source": "runtime",
        "report": report,
    }
    normalized = _normalize_tz_gates_payload(payload, report_source="runtime")
    _admin_rt_cache_set(cache_key, normalized)
    return normalized


SIGNAL_ENGINE_DEFAULTS: dict = {
    "version": "1.0",
    "windows": {
        "median_sales_primary": {"n": 30, "hours": 24},
        "median_sales_fallback": {"n": 10, "days": 7},
        "floor_delta_window_minutes": 30,
        "liquidity_window_hours": 24,
        "recent_sales_buffer_n": 200,
    },
    "floor": {"spread_guard": 0.12, "type_preference": "real_first"},
    "fair_price": {"alpha": 0.7, "target_liq_sales_per_hour": 0.5, "max_liq_penalty": 0.25},
    "rarity_premiums": {
        "serial": {
            "s1": 0.8,
            "s2_3": 0.5,
            "s4_10": 0.25,
            "s11_50": 0.12,
            "s51_100": 0.07,
            "s101_250": 0.04,
            "last": 0.25,
            "last10": 0.12,
        },
        "nice_numbers": {
            "enabled": True,
            "set": [69, 77, 88, 99, 100, 111, 222, 333, 444, 555, 666, 777, 1000],
            "premium_default": 0.07,
        },
        "patterns": {"palindrome": 0.04, "repeat_digits": 0.03, "lucky_7_bonus": 0.03, "cap": 0.08},
        "cap_total": 0.8,
    },
    "trend": {"vol_ref_30m": 20, "w_floor": 0.6, "w_vol": 0.4},
    "risk_penalties": {
        "synthetic_floor": 0.15,
        "thin_liquidity_sales24h_lt": 5,
        "thin_liquidity_penalty": 0.10,
        "provider_degraded_penalty": 0.10,
        "exec_fail_spike_penalty": 0.25,
    },
    "score_weights": {"undervalue": 0.45, "rarity": 0.25, "trend": 0.20, "liquidity": 0.10},
    "thresholds": {
        "min_undervalue": 0.22,
        "min_score_signal": 0.62,
        "min_score_autobuy": 0.72,
        "min_score_racemode": 0.80,
        "min_expected_profit_pct": 0.18,
    },
    "fees": {"fees_pct_default": 0.03},
    "sell_rules": {
        "quick_flip": {"floor_minus_ton": 0.10, "fair_mult": 0.98},
        "swing": {"trend_threshold": 0.4, "fair_mult": 1.02},
        "trailing_stop": {"trailing_pct": 0.08},
    },
    "drop_pressure": {
        "window_sec": 300,
        "sales_norm": 20,
        "transfers_norm": 200,
        "w_sales": 0.6,
        "w_transfers": 0.4,
        "boost_threshold": 0.7,
        "min_score_relax": 0.04,
    },
}


def _read_last_full_sync_ts() -> int | None:
    try:
        raw = LAST_FULL_SYNC_TS_FILE.read_text(encoding="utf-8").strip()
        value = int(raw)
        if value > 0:
            return value
    except Exception:
        pass
    try:
        if not SNAPSHOT_META_FILE.exists():
            return None
        meta = json.loads(SNAPSHOT_META_FILE.read_text(encoding="utf-8"))
        generated_at = str((meta or {}).get("generated_at") or "").strip()
        if not generated_at:
            return None
        dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


_LISTING_WINDOWS_SEC = {
    "10m": 10 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "6h": 6 * 60 * 60,
    "24h": 24 * 60 * 60,
}

_BOOL_TRUE_VALUES = {"1", "true", "yes", "on"}
_BOOL_FALSE_VALUES = {"0", "false", "no", "off"}


def _listing_window_to_sec(value: str | None, default: str = "30m") -> tuple[str, int]:
    raw = str(value or default).strip().lower()
    if raw not in _LISTING_WINDOWS_SEC:
        raise ValueError(f"unsupported_window:{raw}")
    return raw, int(_LISTING_WINDOWS_SEC[raw])


def _parse_query_bool(value: str | None, *, default: bool, field: str) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return bool(default)
    if raw in _BOOL_TRUE_VALUES:
        return True
    if raw in _BOOL_FALSE_VALUES:
        return False
    raise ValueError(f"invalid_{field}")


def _parse_iso_utc(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _norm_pct(value: float | None) -> float:
    v = _safe_float(value, 0.0)
    if abs(v) <= 1.5:
        return v * 100.0
    return v


def _listing_variant_label(collection: str, model: str, background: str, pattern: str) -> str:
    parts = [str(collection or "").strip(), str(model or "").strip(), str(background or "").strip(), str(pattern or "").strip()]
    return " • ".join([x for x in parts if x]) or "—"


def _signal_action_strength(action: str, score100: float) -> str:
    a = str(action or "WATCH").strip().upper()
    s = float(score100 or 0.0)
    if a == "BUY" and s >= 80.0:
        return "STRONG_BUY"
    if a == "SELL" and s >= 80.0:
        return "STRONG_SELL"
    return "NONE"


def _market_regime_snapshot_compat() -> tuple[str, str]:
    try:
        payload = _state().market_overview()
    except Exception:
        payload = {}
    state_ru = str((payload or {}).get("market_state") or "").strip().lower()
    if state_ru == "рост":
        return "RISK_ON", "🟢"
    if state_ru == "падение":
        return "RISK_OFF", "🔴"
    if state_ru == "panic":
        return "PANIC", "⚠"
    return "MEAN_REVERT", "🟡"


def _warmup_race_tracker_from_rows(state: GiftAnalyticsService, rows: list[dict], now_iso: str) -> int:
    if not isinstance(rows, list) or not rows:
        return 0
    tracker = state.listing_tracker_state if isinstance(state.listing_tracker_state, dict) else {}
    if not isinstance(tracker, dict):
        tracker = {}
        state.listing_tracker_state = tracker
    changed = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        listing_key = str(row.get("listing_key") or "").strip()
        if not listing_key:
            base_id = str(row.get("collection_id") or row.get("gift_id") or "").strip().lower()
            listing_id = str(row.get("listing_id") or row.get("unique_id") or "").strip()
            if not base_id or not listing_id:
                continue
            listing_key = f"{base_id}:{listing_id}"
        price_ton = _listing_row_price_ton_equiv(state, row)
        if price_ton <= 0.0:
            continue
        ts_seen = str(row.get("last_seen_at") or row.get("ts_detected") or now_iso)
        variant_id = str(row.get("variant_id") or "")
        base_id = str(row.get("collection_id") or row.get("gift_id") or "").strip().lower()
        listing_id = str(row.get("listing_id") or row.get("unique_id") or listing_key.split(":", 1)[-1] or "")
        preview_url = str(row.get("preview_url") or "")
        entry = tracker.get(listing_key)
        if not isinstance(entry, dict):
            tracker[listing_key] = {
                "listing_key": listing_key,
                "base_id": base_id,
                "listing_id": listing_id,
                "variant_id": variant_id,
                "first_seen_at": ts_seen,
                "last_seen_at": ts_seen,
                "last_price_ton": price_ton,
                "prev_price_ton": price_ton,
                "last_price_changed_at": None,
                "active": True,
                "relist_count": 0,
                "last_relisted_at": None,
                "last_absent_at": None,
                "preview_url": preview_url,
            }
            changed += 1
            continue
        old_price = _safe_float(entry.get("last_price_ton"), 0.0)
        if old_price > 0.0 and abs(old_price - price_ton) >= 1e-9:
            entry["prev_price_ton"] = old_price
            entry["last_price_ton"] = price_ton
            entry["last_price_changed_at"] = ts_seen
            changed += 1
        elif old_price <= 0.0:
            entry["last_price_ton"] = price_ton
            entry["prev_price_ton"] = price_ton
            changed += 1
        if str(entry.get("last_seen_at") or "") != ts_seen:
            entry["last_seen_at"] = ts_seen
            changed += 1
        if str(entry.get("variant_id") or "") != variant_id:
            entry["variant_id"] = variant_id
            changed += 1
        if preview_url and str(entry.get("preview_url") or "") != preview_url:
            entry["preview_url"] = preview_url
            changed += 1
        if str(entry.get("base_id") or "") != base_id:
            entry["base_id"] = base_id
            changed += 1
        if str(entry.get("listing_id") or "") != listing_id:
            entry["listing_id"] = listing_id
            changed += 1
        if not bool(entry.get("active")):
            entry["active"] = True
            changed += 1
    if changed > 0:
        state._data_version += 1
        try:
            state._invalidate_view_cache()
        except Exception:
            pass
        try:
            state._save_listing_tracker_state()
        except Exception:
            pass
    return changed


def _listing_row_price_ton_equiv(state: GiftAnalyticsService, row: dict) -> float:
    ton = _safe_float((row or {}).get("resell_amount_ton"), 0.0)
    if ton > 0.0:
        return ton
    stars_val = _safe_float((row or {}).get("resell_amount_stars_est"), 0.0)
    if stars_val <= 0.0:
        return 0.0
    rate = state.stars_rate() if hasattr(state, "stars_rate") else {}
    ton_per_star = _safe_float((rate or {}).get("ton_per_star"), 0.0)
    if ton_per_star > 0.0:
        return stars_val * ton_per_star
    stars_per_ton = _safe_float((rate or {}).get("stars_per_ton"), 0.0)
    if stars_per_ton > 0.0:
        return stars_val / stars_per_ton
    return 0.0
def _parse_admin_ids() -> set[int]:
    out: set[int] = set()
    for raw in [ADMIN_TELEGRAM_USER_ID, ADMIN_TELEGRAM_USER_IDS_RAW]:
        for part in str(raw or "").replace(";", ",").split(","):
            token = part.strip()
            if not token:
                continue
            try:
                out.add(int(token))
            except Exception:
                continue
    return out


ADMIN_TELEGRAM_IDS = _parse_admin_ids()


def _is_admin_user(user: dict | None) -> bool:
    if not isinstance(user, dict) or not ADMIN_TELEGRAM_IDS:
        return False
    try:
        uid = int(user.get("id"))
    except Exception:
        return False
    return uid in ADMIN_TELEGRAM_IDS


def _deep_merge(base, patch):
    if isinstance(base, dict) and isinstance(patch, dict):
        out = dict(base)
        for k, v in patch.items():
            out[k] = _deep_merge(out.get(k), v)
        return out
    return patch


def _load_signal_engine_overrides() -> dict:
    try:
        if SIGNAL_ENGINE_OVERRIDES_FILE.exists():
            payload = json.loads(SIGNAL_ENGINE_OVERRIDES_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    except Exception:
        pass
    return {}


def _save_signal_engine_overrides(overrides: dict) -> None:
    SIGNAL_ENGINE_OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SIGNAL_ENGINE_OVERRIDES_FILE.write_text(
        json.dumps(overrides, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _signal_engine_effective_config() -> tuple[dict, dict, dict]:
    defaults = json.loads(json.dumps(SIGNAL_ENGINE_DEFAULTS))
    overrides = _load_signal_engine_overrides()
    if not isinstance(overrides, dict):
        overrides = {}
    effective = _deep_merge(defaults, overrides)
    return defaults, overrides, effective


def _signal_engine_signal_preview(limit: int, cfg: dict) -> dict:
    svc = _state()
    cfg_hash = hashlib.sha256(json.dumps(cfg or {}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    data_version = int(getattr(svc, "_data_version", 0))
    cache_key = ("signal_engine_preview", int(limit or 0), cfg_hash, data_version)
    cached = _admin_rt_cache_get(cache_key, ttl_sec=20.0)
    if isinstance(cached, dict):
        return cached
    rows = (svc.list_variants(sort="reco_score_desc", page=1, page_size=max(50, min(limit * 3, 5000))).get("items") or [])
    out: list[dict] = []
    alpha = _safe_float(((cfg.get("fair_price") or {}).get("alpha")), 0.7)
    liq_target = _safe_float(((cfg.get("fair_price") or {}).get("target_liq_sales_per_hour")), 0.5)
    liq_pen_cap = _safe_float(((cfg.get("fair_price") or {}).get("max_liq_penalty")), 0.25)
    spread_guard = _safe_float(((cfg.get("floor") or {}).get("spread_guard")), 0.12)
    w = (cfg.get("score_weights") or {})
    w_u = _safe_float(w.get("undervalue"), 0.45)
    w_r = _safe_float(w.get("rarity"), 0.25)
    w_t = _safe_float(w.get("trend"), 0.20)
    w_l = _safe_float(w.get("liquidity"), 0.10)
    tr = (cfg.get("thresholds") or {})
    th_und = _safe_float(tr.get("min_undervalue"), 0.22)
    th_signal = _safe_float(tr.get("min_score_signal"), 0.62)
    th_autobuy = _safe_float(tr.get("min_score_autobuy"), 0.72)
    th_profit = _safe_float(tr.get("min_expected_profit_pct"), 0.18)
    fee_default = _safe_float(((cfg.get("fees") or {}).get("fees_pct_default")), 0.03)
    trend_cfg = cfg.get("trend") or {}
    w_floor = _safe_float(trend_cfg.get("w_floor"), 0.6)
    w_vol = _safe_float(trend_cfg.get("w_vol"), 0.4)
    vol_ref = max(1.0, _safe_float(trend_cfg.get("vol_ref_30m"), 20.0))
    risk_cfg = cfg.get("risk_penalties") or {}

    for v in rows:
        metrics = v.get("metrics") or {}
        traits = v.get("traits") or {}
        floor = max(0.0001, _safe_float(metrics.get("floor_ton"), 0.0001))
        median = _safe_float(metrics.get("median_ton"), floor)
        if median <= 0:
            median = floor
        model_name = str(((traits.get("model") or {}).get("name")) or "")
        bg_name = str(((traits.get("background") or {}).get("name")) or "")
        pt_name = str(((traits.get("pattern") or {}).get("name")) or "")
        name = " • ".join([x for x in [model_name, bg_name, pt_name] if x]) or str(v.get("variant_id") or "-")
        price = floor
        sales24h = int(_safe_float(metrics.get("trades_count_24h"), 0))
        liq6h = sales24h / 24.0
        liq_pen = _clamp((max(0.0, liq_target - liq6h) / max(liq_target, 1e-9)), 0.0, liq_pen_cap)
        prem_rarity = 0.0
        fair_base = alpha * median + (1 - alpha) * floor
        fair = max(0.0001, fair_base * (1 + prem_rarity) * (1 - liq_pen))
        undervalue = _clamp((fair - price) / max(fair, 1e-9), -1.0, 1.0)

        floor_change_1h = _safe_float(metrics.get("floor_change_pct_1h"), 0.0) / 100.0
        f_30m = floor / max(1e-6, (1.0 + floor_change_1h * 0.5))
        d_f = (floor - f_30m) / max(f_30m, 1e-9)
        vol30m = _safe_float(metrics.get("volume_ton_24h"), 0.0) / 48.0
        trend_raw = _clamp((w_floor * d_f) + (w_vol * (math.log1p(max(0.0, vol30m)) / math.log1p(vol_ref))), -1.0, 1.0)
        t = (trend_raw + 1.0) / 2.0

        supply_proxy = max(1.0, _safe_float(metrics.get("active_listings"), 1.0))
        liq_score = _clamp((sales24h / max(1e-9, supply_proxy / 1000.0)), 0.0, 1.0)
        spread_proxy = abs(_safe_float(metrics.get("spread_proxy_24h"), 0.0))
        floor_type = "synthetic" if spread_proxy > spread_guard else "real"
        risk_pen = 0.0
        if floor_type == "synthetic":
            risk_pen += _safe_float(risk_cfg.get("synthetic_floor"), 0.15)
        if sales24h < int(_safe_float(risk_cfg.get("thin_liquidity_sales24h_lt"), 5)):
            risk_pen += _safe_float(risk_cfg.get("thin_liquidity_penalty"), 0.10)
        risk_pen = _clamp(risk_pen, 0.0, 1.0)

        u = _clamp(undervalue / 0.6, 0.0, 1.0)
        r = _clamp(prem_rarity / 0.8, 0.0, 1.0)
        score = _clamp((w_u * u) + (w_r * r) + (w_t * t) + (w_l * liq_score) - risk_pen, 0.0, 1.0)
        confidence = _clamp(0.3 + 0.7 * min(1.0, sales24h / 30.0), 0.0, 1.0)
        target_sell = min(
            floor,
            fair * _safe_float((((cfg.get("sell_rules") or {}).get("quick_flip") or {}).get("fair_mult"), 0.98)),
        )
        expected_profit = max(0.0, (target_sell - price) / max(price, 1e-9)) - fee_default

        action_hint = "SKIP"
        if score >= th_autobuy and expected_profit >= th_profit:
            action_hint = "BUY"
        elif undervalue >= th_und and score >= th_signal:
            action_hint = "WATCH"

        if action_hint == "SKIP":
            continue

        risk_flags: list[str] = []
        if floor_type == "synthetic":
            risk_flags.append("SYNTH_FLOOR")
        if sales24h < int(_safe_float(risk_cfg.get("thin_liquidity_sales24h_lt"), 5)):
            risk_flags.append("THIN_LIQUIDITY")

        out.append(
            {
                "signalId": str(v.get("variant_id") or ""),
                "type": "undervalued" if action_hint in {"BUY", "WATCH"} else "trend",
                "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "collectionId": str(v.get("base_id") or ""),
                "collectionName": str(v.get("base_id") or "").replace("_", " ").title(),
                "itemId": str(v.get("variant_id") or ""),
                "serial": None,
                "supply": None,
                "priceTon": round(price, 6),
                "floorTon": round(floor, 6),
                "floorType": floor_type,
                "fairTon": round(fair, 6),
                "undervaluePct": round(_clamp(undervalue, -1.0, 1.0), 6),
                "score": round(score, 6),
                "confidence": round(confidence, 6),
                "expectedProfitPct": round(_clamp(expected_profit, -1.0, 1.0), 6),
                "riskFlags": risk_flags,
                "actionHint": action_hint,
                "explain": {
                    "name": name,
                    "P": round(price, 6),
                    "F": round(floor, 6),
                    "M": round(median, 6),
                    "Fair": round(fair, 6),
                    "undervalue": round(undervalue, 6),
                    "pen_liq": round(liq_pen, 6),
                    "dF": round(d_f, 6),
                    "vol30m": round(vol30m, 6),
                    "t": round(t, 6),
                    "sales24h": sales24h,
                    "liq_score": round(liq_score, 6),
                    "risk_pen": round(risk_pen, 6),
                    "expected_profit_pct": round(expected_profit, 6),
                },
            }
        )
        if len(out) >= limit:
            break
    payload = {
        "ok": True,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total": len(out),
        "items": out,
    }
    _admin_rt_cache_set(cache_key, payload)
    return payload

def _run_full_sync_once() -> tuple[bool, str]:
    env = os.environ.copy()
    env.setdefault("VERIFIED_SOURCE", os.getenv("VERIFIED_SOURCE", "hybrid"))
    env.setdefault("VERIFIED_DATA_FILE", "data/verified_gifts.json")
    env.setdefault("VERIFIED_API_TIMEOUT_SEC", "20")

    def _run_cmd(cmd: list[str], timeout_sec: int) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            return False, f"{cmd[-1]} timeout>{timeout_sec}s"
        except Exception as e:  # noqa: BLE001
            return False, f"{cmd[-1]} start failed: {e}"
        if proc.returncode != 0:
            tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-3:])
            return False, f"{cmd[-1]} failed rc={proc.returncode}: {tail[:280]}"
        return True, ""

    # Primary sync path: verified source (hybrid/telegram/api).
    source = str(env.get("VERIFIED_SOURCE") or "").strip().lower()
    if source in {"hybrid", "telegram_api", "api"}:
        ok_primary, err_primary = _run_cmd(
            ["python3", "-u", "sync_verified.py"],
            timeout_sec=min(MANUAL_FULL_SYNC_TIMEOUT_SEC, max(90, int(MANUAL_FULL_SYNC_TIMEOUT_SEC * 0.35))),
        )
        if ok_primary:
            try:
                LAST_FULL_SYNC_TS_FILE.parent.mkdir(parents=True, exist_ok=True)
                LAST_FULL_SYNC_TS_FILE.write_text(str(int(time.time())), encoding="utf-8")
            except Exception:
                pass
            return True, ""
        # Reserve channel: Fragment full sync.
        reserve_default = "false" if source == "telegram_api" else "true"
        if os.getenv("ALLOW_FRAGMENT_RESERVE_SYNC", reserve_default).strip().lower() not in {"1", "true", "yes", "on"}:
            return False, err_primary

    env.setdefault("FRAGMENT_SSL_NO_VERIFY", "true")
    env.setdefault("FRAGMENT_GIFTS_URL", "https://fragment.com/gifts")
    env.setdefault("FRAGMENT_MAX_PAGES_PER_COLLECTION", os.getenv("FULL_MAX_PAGES_PER_COLLECTION", "120"))
    env.setdefault("FRAGMENT_INCLUDE_SOLD", os.getenv("FULL_INCLUDE_SOLD", "true"))
    env.setdefault("FRAGMENT_ENRICH_LOT_TRAITS", os.getenv("FULL_ENRICH_LOT_TRAITS", "true"))
    env.setdefault("FRAGMENT_LOT_DETAIL_WORKERS", os.getenv("FULL_LOT_DETAIL_WORKERS", "10"))
    env.setdefault("FRAGMENT_FETCH_BUDGET_SEC", os.getenv("FULL_FETCH_BUDGET_SEC", "1400"))
    env.setdefault("FRAGMENT_MIN_REQUEST_INTERVAL_SEC", os.getenv("FULL_MIN_REQUEST_INTERVAL_SEC", "0.18"))
    env.setdefault("FRAGMENT_REQUEST_JITTER_SEC", os.getenv("FULL_REQUEST_JITTER_SEC", "0.06"))
    env.setdefault("FRAGMENT_REQUEST_RETRIES", os.getenv("FRAGMENT_REQUEST_RETRIES", "3"))
    env.setdefault("FRAGMENT_REQUEST_BACKOFF_SEC", os.getenv("FRAGMENT_REQUEST_BACKOFF_SEC", "0.8"))
    env.setdefault("FRAGMENT_BATCH_SIZE", os.getenv("FRAGMENT_BATCH_SIZE", "8"))
    env.setdefault("FRAGMENT_BATCH_RETRIES", os.getenv("FRAGMENT_BATCH_RETRIES", "6"))
    env.setdefault("FRAGMENT_RESUME", "true")
    env.setdefault("FRAGMENT_SYNC_STATE_FILE", "data/fragment_sync_state.json")

    ok_fragment, err_fragment = _run_cmd(["python3", "-u", "sync_fragment_batches.py"], timeout_sec=MANUAL_FULL_SYNC_TIMEOUT_SEC)
    if not ok_fragment:
        return False, err_fragment
    try:
        LAST_FULL_SYNC_TS_FILE.parent.mkdir(parents=True, exist_ok=True)
        LAST_FULL_SYNC_TS_FILE.write_text(str(int(time.time())), encoding="utf-8")
    except Exception:
        pass
    return True, ""


def _manual_refresh_worker(mode: str) -> None:
    err = ""
    try:
        if mode == "full":
            ok, err = _run_full_sync_once()
            if not ok:
                raise RuntimeError(err)
        _state().ingest_safe()
    except Exception as e:  # noqa: BLE001
        err = str(e)
    finally:
        with _REFRESH_LOCK:
            _REFRESH_STATUS["running"] = False
            _REFRESH_STATUS["last_finished_at"] = int(time.time())
            _REFRESH_STATUS["last_error"] = err


def _start_manual_refresh() -> dict:
    now_ts = int(time.time())
    last_full_ts = _read_last_full_sync_ts()
    age_sec = None if not last_full_ts else max(0, now_ts - last_full_ts)
    mode = "analytics" if (age_sec is not None and age_sec < MANUAL_FULL_SYNC_COOLDOWN_SEC) else "full"

    with _REFRESH_LOCK:
        if _REFRESH_STATUS["running"]:
            return {
                "ok": True,
                "started": False,
                "running": True,
                "mode": _REFRESH_STATUS.get("mode") or "analytics",
                "message": "refresh already running",
            }
        _REFRESH_STATUS["running"] = True
        _REFRESH_STATUS["mode"] = mode
        _REFRESH_STATUS["started_at"] = now_ts
        _REFRESH_STATUS["last_mode"] = mode
        _REFRESH_STATUS["last_started_at"] = now_ts
        _REFRESH_STATUS["last_error"] = ""

    threading.Thread(target=_manual_refresh_worker, args=(mode,), daemon=True, name=f"manual-refresh-{mode}").start()
    return {
        "ok": True,
        "started": True,
        "running": True,
        "mode": mode,
        "last_full_sync_age_sec": age_sec,
        "cooldown_sec": MANUAL_FULL_SYNC_COOLDOWN_SEC,
        "message": "full sync started" if mode == "full" else "analytics refresh started",
    }


def _refresh_status_snapshot() -> dict:
    with _REFRESH_LOCK:
        return {
            "ok": True,
            "running": bool(_REFRESH_STATUS.get("running")),
            "mode": _REFRESH_STATUS.get("mode") or "",
            "started_at": _REFRESH_STATUS.get("started_at"),
            "last_mode": _REFRESH_STATUS.get("last_mode") or "",
            "last_started_at": _REFRESH_STATUS.get("last_started_at"),
            "last_finished_at": _REFRESH_STATUS.get("last_finished_at"),
            "last_error": _REFRESH_STATUS.get("last_error") or "",
        }


class AuthStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = _load_json_file(AUTH_SESSIONS_FILE, {}) if isinstance(_load_json_file(AUTH_SESSIONS_FILE, {}), dict) else {}

    def _cleanup_locked(self, now: float) -> None:
        expired = [sid for sid, s in self._sessions.items() if float(s.get("expires_at", 0)) <= now]
        for sid in expired:
            self._sessions.pop(sid, None)
        self._persist_locked()

    def _persist_locked(self) -> None:
        _save_json_file(AUTH_SESSIONS_FILE, self._sessions)

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
            self._persist_locked()
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
            self._persist_locked()
            return dict(session)

    def destroy_session(self, sid: str) -> None:
        if not sid:
            return
        with self._lock:
            self._sessions.pop(sid, None)
            self._persist_locked()


AUTH = AuthStore()


class TonAuthStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = _load_json_file(TON_AUTH_SESSIONS_FILE, {}) if isinstance(_load_json_file(TON_AUTH_SESSIONS_FILE, {}), dict) else {}
        self._challenges: dict[str, dict] = {}

    def _cleanup_locked(self, now: float) -> None:
        expired_s = [sid for sid, s in self._sessions.items() if float(s.get("expires_at", 0)) <= now]
        for sid in expired_s:
            self._sessions.pop(sid, None)
        expired_c = [nonce for nonce, c in self._challenges.items() if float(c.get("expires_at", 0)) <= now]
        for nonce in expired_c:
            self._challenges.pop(nonce, None)
        self._persist_locked()

    def _persist_locked(self) -> None:
        _save_json_file(TON_AUTH_SESSIONS_FILE, self._sessions)

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
            self._persist_locked()
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
            self._persist_locked()
            return dict(session)

    def destroy_session(self, sid: str) -> None:
        if not sid:
            return
        with self._lock:
            self._sessions.pop(sid, None)
            self._persist_locked()


TON_AUTH = TonAuthStore()


def _add_security_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
    handler.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    origin = _cors_origin_for_request(handler)
    if origin:
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Access-Control-Allow-Credentials", "true")
        handler.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        handler.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        handler.send_header("Vary", "Origin")


def _cors_origin_for_request(handler: BaseHTTPRequestHandler) -> str:
    origin = (handler.headers.get("Origin", "") or "").strip().rstrip("/")
    if not origin:
        return ""
    request_origin = _request_origin(handler).rstrip("/")
    if origin == request_origin:
        return origin
    if origin in CORS_ALLOWED_ORIGINS:
        return origin
    return ""


def _cookie_secure(handler: BaseHTTPRequestHandler) -> bool:
    host = (handler.headers.get("Host", "") or "").split(":")[0].strip().lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False
    if host.startswith("127."):
        return False
    return True


def _cookie_domain_attr(value: str) -> str:
    domain = str(value or "").strip().lower().lstrip(".")
    if not domain or domain in {"localhost", "127.0.0.1", "::1"}:
        return ""
    return f"Domain={domain}"


def _build_session_cookie(handler: BaseHTTPRequestHandler, session_id: str, max_age: int) -> str:
    secure = _cookie_secure(handler)
    cookie_domain = _cookie_domain_attr(AUTH_COOKIE_DOMAIN)
    parts = [
        f"{SESSION_COOKIE_NAME}={session_id}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={max_age}",
    ]
    if cookie_domain:
        parts.append(cookie_domain)
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def _build_clear_session_cookie(handler: BaseHTTPRequestHandler) -> str:
    secure = _cookie_secure(handler)
    cookie_domain = _cookie_domain_attr(AUTH_COOKIE_DOMAIN)
    parts = [
        f"{SESSION_COOKIE_NAME}=",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=0",
    ]
    if cookie_domain:
        parts.append(cookie_domain)
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def _build_ton_session_cookie(handler: BaseHTTPRequestHandler, session_id: str, max_age: int) -> str:
    secure = _cookie_secure(handler)
    cookie_domain = _cookie_domain_attr(TON_COOKIE_DOMAIN)
    parts = [
        f"{TON_SESSION_COOKIE_NAME}={session_id}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={max_age}",
    ]
    if cookie_domain:
        parts.append(cookie_domain)
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def _build_clear_ton_session_cookie(handler: BaseHTTPRequestHandler) -> str:
    secure = _cookie_secure(handler)
    cookie_domain = _cookie_domain_attr(TON_COOKIE_DOMAIN)
    parts = [
        f"{TON_SESSION_COOKIE_NAME}=",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=0",
    ]
    if cookie_domain:
        parts.append(cookie_domain)
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
    forwarded_host = (handler.headers.get("X-Forwarded-Host", "") or "").strip()
    host = forwarded_host or (handler.headers.get("Host", "") or PUBLIC_BASE_HOST)
    return host.split(":")[0].strip().lower()


def _fetch_ton_wallet_balance(address: str) -> tuple[float | None, str]:
    wallet = str(address or "").strip()
    if not wallet:
        return None, "wallet_address_missing"
    now = time.time()
    with _TON_BALANCE_CACHE_LOCK:
        cached = _TON_BALANCE_CACHE.get(wallet)
        if cached and float(cached.get("expires_at", 0)) > now:
            return cached.get("balance_ton"), "ok_cached"
    url = f"{TON_BALANCE_API_URL}?{urlencode({'address': wallet})}"
    req = Request(url, headers={"Accept": "application/json"})
    if TONCENTER_API_KEY:
        req.add_header("X-API-Key", TONCENTER_API_KEY)
    try:
        with urlopen(req, timeout=TON_BALANCE_TIMEOUT_SEC) as resp:
            raw = resp.read()
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("ok") is not True:
            return None, "provider_not_ok"
        nano_raw = payload.get("result")
        nano = int(str(nano_raw))
        balance_ton = nano / 1_000_000_000
    except Exception:
        return None, "provider_unavailable"
    with _TON_BALANCE_CACHE_LOCK:
        _TON_BALANCE_CACHE[wallet] = {
            "balance_ton": balance_ton,
            "expires_at": now + TON_BALANCE_CACHE_TTL_SEC,
        }
    return balance_ton, "ok"


def _validate_ton_verify_payload(handler: BaseHTTPRequestHandler, payload: dict) -> tuple[bool, str, dict | None]:
    account = payload.get("account")
    proof = payload.get("ton_proof")
    if not isinstance(account, dict):
        return False, "invalid_payload_shape", None
    address = str(account.get("address", "")).strip()
    chain = str(account.get("chain", "")).strip()
    public_key = str(account.get("publicKey", "")).strip()
    if not address:
        return False, "missing_account_address", None
    # Fallback mode for wallets/sessions that return account without tonProof.
    if not isinstance(proof, dict):
        if TON_ALLOW_WEAK_VERIFY:
            now_ts = int(time.time())
            host = _host_only(handler)
            wallet = {
                "address": address,
                "chain": chain,
                "public_key": public_key,
                "domain": host,
                "verified_at": now_ts,
                "proof_timestamp": None,
                "verification_level": "wallet_address_only",
                "verification_status": "weak_verified_no_proof",
            }
            return True, "ok_weak_no_proof", wallet
        return False, "ton_proof_missing", None
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
    allowed_domains = set(TON_PROOF_ALLOWED_DOMAINS)
    allowed_domains.add(host)
    if domain_value and domain_value not in allowed_domains:
        return False, "proof_domain_mismatch", None
    challenge_host = domain_value or host
    ok, reason = TON_AUTH.consume_challenge(proof_payload, host=challenge_host, ua_hash=_ua_hash(handler))
    if not ok:
        return False, reason, None
    wallet = {
        "address": address,
        "chain": chain,
        "public_key": public_key,
        "domain": challenge_host,
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


def _require_admin(handler: BaseHTTPRequestHandler) -> dict | None:
    user = _require_auth(handler)
    if not user:
        return None
    if _is_admin_user(user):
        return user
    _json_response(
        handler,
        {"ok": False, "error": "forbidden", "message": "Доступ только для администратора"},
        status=HTTPStatus.FORBIDDEN,
    )
    return None


def _require_authenticated_telegram_user(handler: BaseHTTPRequestHandler) -> dict | None:
    user = _auth_user_from_request(handler)
    if user:
        return user
    _json_response(
        handler,
        {"ok": False, "error": "unauthorized", "message": "Требуется вход через Telegram"},
        status=HTTPStatus.UNAUTHORIZED,
    )
    return None


def _require_trading_user(handler: BaseHTTPRequestHandler) -> tuple[dict | None, dict | None]:
    user = _require_authenticated_telegram_user(handler)
    if not user:
        return None, None
    wallet = _ton_wallet_from_request(handler)
    access = _state().trading_feature_access_v1(user, wallet)
    if not bool(access.get("allowed")):
        _json_response(
            handler,
            {"ok": False, "error": "forbidden", "message": "Trading module temporarily enabled only for test account", "details": access},
            status=HTTPStatus.FORBIDDEN,
        )
        return None, None
    return user, wallet


def _validate_wallet_match(expected_wallet: dict | None, wallet_address: str | None) -> tuple[bool, str]:
    expected = str((expected_wallet or {}).get("address") or "").strip()
    current = str(wallet_address or "").strip()
    if not current:
        return False, "wallet_address_required"
    if expected and expected != current:
        return False, "wallet_address_mismatch"
    return True, "ok"


def _user_storage_key(user: dict | None) -> str:
    if not isinstance(user, dict):
        return "default"
    user_id = str(user.get("id", "")).strip()
    return user_id or "default"


def _bridge_token_ok(handler: BaseHTTPRequestHandler) -> bool:
    expected = BRIDGE_API_TOKEN
    if not expected:
        return False
    auth_header = (handler.headers.get("Authorization", "") or "").strip()
    if auth_header == f"Bearer {expected}":
        return True
    x_api_key = (handler.headers.get("X-API-Key", "") or "").strip()
    if x_api_key == expected:
        return True
    parsed = urlparse(handler.path)
    params = parse_qs(parsed.query)
    token_q = (params.get("token") or [""])[0].strip()
    return token_q == expected


def _bridge_verified_payload() -> dict:
    from market_data import load_verified_dataset

    file_path = os.getenv("VERIFIED_DATA_FILE", "").strip() or None
    dataset = load_verified_dataset(file_path)
    gifts = dataset.get("gifts") if isinstance(dataset, dict) else []
    filters = dataset.get("filters") if isinstance(dataset, dict) else {}
    return {
        "ok": True,
        "source": "local_verified_snapshot",
        "generated_at": dataset.get("generated_at"),
        "counts": {
            "gifts": len(gifts) if isinstance(gifts, list) else 0,
            "collections": len((filters or {}).get("collections") or []) if isinstance(filters, dict) else 0,
            "models": len((filters or {}).get("models") or {}) if isinstance(filters, dict) else 0,
            "backdrops": len((filters or {}).get("backdrops") or {}) if isinstance(filters, dict) else 0,
            "symbols": len((filters or {}).get("symbols") or {}) if isinstance(filters, dict) else 0,
        },
        "data": dataset,
    }


def _bridge_owned_gifts_payload(telegram_user_id: str = "", username: str = "") -> dict:
    return _state().owned_gifts_bridge_v1(telegram_user_id=telegram_user_id, username=username)


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


def _serve_file_head(handler: BaseHTTPRequestHandler, rel_path: str) -> None:
    rel = rel_path.lstrip("/")
    target = (STATIC_DIR / rel).resolve()
    if not str(target).startswith(str(STATIC_DIR.resolve())):
        _safe_send_error(handler, HTTPStatus.FORBIDDEN)
        return
    if not target.exists() or not target.is_file():
        _safe_send_error(handler, HTTPStatus.NOT_FOUND)
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
    handler.send_header("Content-Length", str(target.stat().st_size))
    if target.suffix in {".html"}:
        handler.send_header("Cache-Control", "no-store")
    _add_security_headers(handler)
    handler.end_headers()


def _request_origin(handler: BaseHTTPRequestHandler) -> str:
    forwarded_host = (handler.headers.get("X-Forwarded-Host", "") or "").strip()
    host = forwarded_host or (handler.headers.get("Host", "") or PUBLIC_BASE_HOST)
    xf_proto = (handler.headers.get("X-Forwarded-Proto", "") or "").strip().lower()
    proto = xf_proto if xf_proto in {"http", "https"} else "http"
    host_only = host.split(":")[0].strip().lower()
    if host_only not in {"127.0.0.1", "localhost", "::1"} and not host_only.startswith("127."):
        proto = "https"
    return f"{proto}://{host}"


def _public_origin_for_handler(handler: BaseHTTPRequestHandler) -> str:
    request_origin = _request_origin(handler).rstrip("/")
    req_host = urlparse(request_origin).netloc.split(":")[0].strip().lower()
    if req_host in {"localhost", "127.0.0.1", "::1"} or req_host.startswith("127."):
        return request_origin
    return PUBLIC_BASE_URL.rstrip("/")


def _tonconnect_manifest(handler: BaseHTTPRequestHandler) -> None:
    origin = _public_origin_for_handler(handler)
    payload = {
        "url": origin,
        "name": "GiftMarketZone",
        "iconUrl": f"{origin}/assets/favicon.png",
        "termsOfUseUrl": f"{origin}/index.html",
        "privacyPolicyUrl": f"{origin}/index.html",
    }
    _json_response(handler, payload, cache_control="public, max-age=300")


class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @staticmethod
    def _is_benign_disconnect(exc: BaseException) -> bool:
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return True
        if isinstance(exc, OSError):
            return getattr(exc, "errno", None) in {32, 54, 104}
        return False

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        _add_security_headers(self)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/" or path == "/index.html":
            _serve_file_head(self, "index.html")
            return
        if path.startswith("/assets/"):
            _serve_file_head(self, path.lstrip("/"))
            return
        if path in {"/favicon.png", "/logo.png", "/vite.svg"}:
            _serve_file_head(self, path.lstrip("/"))
            return
        if path in SPA_FRONTEND_ROUTES or path.startswith("/variant/"):
            _serve_file_head(self, "index.html")
            return
        if path == "/healthz":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", "0")
            _add_security_headers(self)
            self.end_headers()
            return
        _safe_send_error(self, HTTPStatus.NOT_FOUND)

    def handle(self) -> None:
        try:
            super().handle()
        except BaseException as exc:
            if self._is_benign_disconnect(exc):
                return
            raise

    def send_response(self, code: int, message: str | None = None) -> None:
        self._gmz_status_code = int(code)
        super().send_response(code, message)
        trace_id = str(getattr(self, "_gmz_trace_id", "") or "").strip()
        if trace_id:
            super().send_header("X-Trace-Id", trace_id)

    def handle_one_request(self) -> None:
        self._gmz_trace_id = secrets.token_hex(8)
        self._gmz_status_code = 0
        started = time.perf_counter()
        try:
            super().handle_one_request()
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            method = str(getattr(self, "command", "") or "").upper()
            path = str(getattr(self, "path", "") or "")
            if method and path.startswith("/"):
                status_code = int(getattr(self, "_gmz_status_code", 0) or 500)
                _observe_http_request(method=method, path=path, status_code=status_code, duration_ms=elapsed_ms)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == BRIDGE_API_PATH:
            if not BRIDGE_API_TOKEN:
                _json_response(
                    self,
                    {"ok": False, "error": "bridge_token_not_configured"},
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                    cache_control="no-store",
                )
                return
            if not _bridge_token_ok(self):
                _json_response(
                    self,
                    {"ok": False, "error": "unauthorized"},
                    status=HTTPStatus.UNAUTHORIZED,
                    cache_control="no-store",
                )
                return
            try:
                _json_response(self, _bridge_verified_payload(), cache_control="no-store")
            except Exception as e:  # noqa: BLE001
                _json_response(
                    self,
                    {"ok": False, "error": f"bridge_failed: {type(e).__name__}: {str(e)[:180]}"},
                    status=HTTPStatus.BAD_GATEWAY,
                    cache_control="no-store",
                )
            return

        if path == "/bridge/gifts/owned":
            if not BRIDGE_API_TOKEN:
                _json_response(
                    self,
                    {"ok": False, "error": "bridge_token_not_configured"},
                    status=HTTPStatus.SERVICE_UNAVAILABLE,
                    cache_control="no-store",
                )
                return
            if not _bridge_token_ok(self):
                _json_response(
                    self,
                    {"ok": False, "error": "unauthorized"},
                    status=HTTPStatus.UNAUTHORIZED,
                    cache_control="no-store",
                )
                return
            params = parse_qs(parsed.query)
            telegram_user_id = str((params.get("telegram_user_id") or [""])[0] or "").strip()
            username = str((params.get("username") or [""])[0] or "").strip()
            _json_response(self, _bridge_owned_gifts_payload(telegram_user_id=telegram_user_id, username=username), cache_control="no-store")
            return

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
                    "public_base_url": PUBLIC_BASE_URL,
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

        if path == "/api/trades/access":
            user = _auth_user_from_request(self)
            wallet = _ton_wallet_from_request(self)
            _json_response(self, _state().trading_feature_access_v1(user, wallet), cache_control="no-store")
            return

        if path == "/api/auth/telegram/owned-gifts":
            user = _auth_user_from_request(self)
            _json_response(self, _state().telegram_owned_gifts_v1(user), cache_control="no-store")
            return

        if path == "/api/admin/access":
            user = _auth_user_from_request(self)
            _json_response(
                self,
                {
                    "ok": True,
                    "authenticated": bool(user),
                    "is_admin": bool(_is_admin_user(user)),
                    "user_id": int(user.get("id")) if isinstance(user, dict) and str(user.get("id", "")).strip() else None,
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
                    "public_base_url": PUBLIC_BASE_URL,
                    "public_base_host": PUBLIC_BASE_HOST,
                    "proof_allowed_domains": sorted(TON_PROOF_ALLOWED_DOMAINS),
                    "cookie_domain": TON_COOKIE_DOMAIN or AUTH_COOKIE_DOMAIN or None,
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

        if path == "/api/auth/ton/balance":
            wallet = _ton_wallet_from_request(self) or {}
            address = str(wallet.get("address", "")).strip()
            if not address:
                _json_response(
                    self,
                    {"ok": False, "error": "ton_wallet_not_connected"},
                    status=HTTPStatus.UNAUTHORIZED,
                    cache_control="no-store",
                )
                return
            balance_ton, reason = _fetch_ton_wallet_balance(address)
            _json_response(
                self,
                {
                    "ok": balance_ton is not None,
                    "ton_balance": balance_ton,
                    "reason": reason,
                    "address": address,
                    "fetched_at": int(time.time()),
                },
                cache_control="no-store",
            )
            return

        if path == "/" or path == "/index.html":
            _serve_file(self, "index.html")
            return
        if path.startswith("/assets/"):
            _serve_file(self, path.lstrip("/"))
            return
        if path in {"/favicon.png", "/logo.png", "/vite.svg"}:
            _serve_file(self, path.lstrip("/"))
            return
        if path in SPA_FRONTEND_ROUTES or path.startswith("/variant/"):
            _serve_file(self, "index.html")
            return

        if path == "/healthz":
            _json_response(self, {"ok": True, "service": "telegram-gifts-analytics"})
            return

        if path == "/v1/overview":
            params = parse_qs(parsed.query)
            mode = (params.get("mode") or [None])[0]
            _json_response(self, _state().overview_v1(mode=mode), cache_control="no-store")
            return

        if path == "/v1/collections":
            params = parse_qs(parsed.query)
            q = (params.get("q") or [""])[0]
            try:
                limit = int((params.get("limit") or ["50"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 200:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            cursor = (params.get("cursor") or [None])[0]
            _json_response(self, _state().collections_v1(q=q, limit=limit, cursor=cursor), cache_control="no-store")
            return

        if path.startswith("/v1/collections/") and path.count("/") == 3:
            collection_id = unquote(path.split("/")[-1])
            params = parse_qs(parsed.query)
            mode = (params.get("mode") or [None])[0]
            data = _state().collection_details_v1(collection_id)
            if not data:
                _safe_send_error(self, HTTPStatus.NOT_FOUND)
                return
            _json_response(self, data, cache_control="no-store")
            return

        if path == "/v1/variants":
            params = parse_qs(parsed.query)
            collection_id = (params.get("collection_id") or [None])[0]
            model = (params.get("model") or [None])[0]
            background = (params.get("background") or [None])[0]
            pattern = (params.get("pattern") or [None])[0]
            min_score_raw = (params.get("min_score") or [None])[0]
            if min_score_raw in (None, ""):
                min_score = None
            else:
                try:
                    min_score = float(min_score_raw)
                except Exception:
                    _json_response(self, {"ok": False, "error": "invalid_min_score"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                    return
            action = (params.get("action") or [None])[0]
            sort = (params.get("sort") or ["score_desc"])[0]
            mode = (params.get("mode") or [None])[0]
            try:
                limit = int((params.get("limit") or ["50"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 200:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            cursor = (params.get("cursor") or [None])[0]
            try:
                data = _state().variants_v1(
                    collection_id=collection_id,
                    model=model,
                    background=background,
                    pattern=pattern,
                    min_score=min_score,
                    action=action,
                    sort=sort,
                    limit=limit,
                    cursor=cursor,
                    mode=mode,
                )
                _json_response(self, data, cache_control="no-store")
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            return

        if path == "/v1/variants/resolve":
            params = parse_qs(parsed.query)
            collection_id = (params.get("collection_id") or [None])[0]
            collection = (params.get("collection") or [None])[0]
            model = (params.get("model") or [None])[0]
            background = (params.get("background") or [None])[0]
            pattern = (params.get("pattern") or [None])[0]
            mode = (params.get("mode") or [None])[0]
            active_only = ((params.get("active_only") or ["true"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            if (not str(collection_id or "").strip() and not str(collection or "").strip()) or not str(model or "").strip():
                _json_response(
                    self,
                    {"ok": False, "error": "invalid_resolve_params"},
                    status=HTTPStatus.BAD_REQUEST,
                    cache_control="no-store",
                )
                return
            data = _state().variant_resolve_v1(
                collection_id=collection_id,
                collection=collection,
                model=model,
                background=background,
                pattern=pattern,
                active_only=active_only,
                mode=mode,
            )
            if not data:
                _json_response(
                    self,
                    {"ok": False, "error": "variant_not_found_or_not_active"},
                    status=HTTPStatus.NOT_FOUND,
                    cache_control="no-store",
                )
                return
            _json_response(self, data, cache_control="no-store")
            return

        if path == "/v1/trades/quotes/buy":
            user, wallet = _require_trading_user(self)
            if user is None:
                return
            params = parse_qs(parsed.query)
            variant_id = str((params.get("variant_id") or [""])[0] or "").strip()
            max_price_raw = (params.get("max_price_ton") or [None])[0]
            slippage_raw = (params.get("slippage_bps") or ["100"])[0]
            wallet_address = (params.get("wallet_address") or [None])[0]
            try:
                max_price_ton = float(max_price_raw)
                slippage_bps = int(slippage_raw)
            except Exception:
                _json_response(self, {"code": "bad_request", "message": "invalid quote params"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            ok_wallet, reason = _validate_wallet_match(wallet, wallet_address)
            if not ok_wallet:
                _json_response(self, {"code": reason, "message": reason}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                payload = _state().trades_issue_buy_quote_v1(variant_id=variant_id, max_price_ton=max_price_ton, slippage_bps=slippage_bps, wallet_address=wallet_address)
                _json_response(self, payload, cache_control="no-store")
            except Exception as exc:
                _json_response(self, {"code": "bad_request", "message": f"quote_issue_failed:{exc.__class__.__name__}"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            return

        if path == "/v1/trades/intents":
            user, wallet = _require_trading_user(self)
            if user is None:
                return
            params = parse_qs(parsed.query)
            wallet_address = str((params.get("wallet_address") or [""])[0] or "").strip()
            if not wallet_address:
                _json_response(self, {"code": "bad_request", "message": "wallet_address_required"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            ok_wallet, reason = _validate_wallet_match(wallet, wallet_address)
            if not ok_wallet:
                _json_response(self, {"code": reason, "message": reason}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            status_filter = (params.get("status") or [None])[0]
            limit = int((params.get("limit") or ["100"])[0]) if str((params.get("limit") or ["100"])[0]).isdigit() else 100
            cursor = (params.get("cursor") or [None])[0]
            _json_response(self, _state().trades_list_intents_v1(wallet_address, status=status_filter, limit=limit, cursor=cursor), cache_control="no-store")
            return

        if path == "/v1/trades/positions":
            user, wallet = _require_trading_user(self)
            if user is None:
                return
            params = parse_qs(parsed.query)
            wallet_address = str((params.get("wallet_address") or [""])[0] or "").strip()
            ok_wallet, reason = _validate_wallet_match(wallet, wallet_address)
            if not ok_wallet:
                _json_response(self, {"code": reason, "message": reason}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            _json_response(self, _state().trades_positions_v1(wallet_address), cache_control="no-store")
            return

        if path == "/v1/trades/holdings":
            user, wallet = _require_trading_user(self)
            if user is None:
                return
            params = parse_qs(parsed.query)
            wallet_address = str((params.get("wallet_address") or [""])[0] or "").strip()
            ok_wallet, reason = _validate_wallet_match(wallet, wallet_address)
            if not ok_wallet:
                _json_response(self, {"code": reason, "message": reason}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            _json_response(self, _state().trades_holdings_v1(wallet_address), cache_control="no-store")
            return

        if path == "/v1/trades/pnl":
            user, wallet = _require_trading_user(self)
            if user is None:
                return
            params = parse_qs(parsed.query)
            wallet_address = str((params.get("wallet_address") or [""])[0] or "").strip()
            ok_wallet, reason = _validate_wallet_match(wallet, wallet_address)
            if not ok_wallet:
                _json_response(self, {"code": reason, "message": reason}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            _json_response(self, _state().trades_pnl_v1(wallet_address), cache_control="no-store")
            return

        if path == "/v1/trades/autosell/rules":
            user, wallet = _require_trading_user(self)
            if user is None:
                return
            params = parse_qs(parsed.query)
            wallet_address = str((params.get("wallet_address") or [""])[0] or "").strip()
            ok_wallet, reason = _validate_wallet_match(wallet, wallet_address)
            if not ok_wallet:
                _json_response(self, {"code": reason, "message": reason}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            _json_response(self, _state().trades_autosell_rules_v1(wallet_address), cache_control="no-store")
            return

        if path == "/v1/wallet/activity":
            user, wallet = _require_trading_user(self)
            if user is None:
                return
            params = parse_qs(parsed.query)
            wallet_address = str((params.get("address") or [""])[0] or "").strip()
            ok_wallet, reason = _validate_wallet_match(wallet, wallet_address)
            if not ok_wallet:
                _json_response(self, {"code": reason, "message": reason}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            limit = int((params.get("limit") or ["50"])[0]) if str((params.get("limit") or ["50"])[0]).isdigit() else 50
            cursor = (params.get("cursor") or [None])[0]
            _json_response(self, _state().wallet_activity_v1(wallet_address, limit=limit, cursor=cursor), cache_control="no-store")
            return

        if path.startswith("/v1/trades/intents/") and not path.endswith("/confirm_signature"):
            user, _ = _require_trading_user(self)
            if user is None:
                return
            intent_id = path.split("/")[-1]
            item = _state().trades_get_intent_v1(intent_id)
            if not item:
                _json_response(self, {"code": "not_found", "message": "intent_not_found"}, status=HTTPStatus.NOT_FOUND, cache_control="no-store")
                return
            _json_response(self, item, cache_control="no-store")
            return

        if path.startswith("/v1/variants/") and path.count("/") == 3:
            variant_id = unquote(path.split("/")[-1])
            params = parse_qs(parsed.query)
            mode = (params.get("mode") or [None])[0]
            data = _state().variant_details_v1(variant_id, mode=mode)
            if not data:
                _safe_send_error(self, HTTPStatus.NOT_FOUND)
                return
            _json_response(self, data, cache_control="no-store")
            return

        if path == "/v1/signals/calibration/report":
            params = parse_qs(parsed.query)
            mode = str((params.get("mode") or ["tz"])[0] or "tz").strip().lower()
            if mode not in {"tz", "legacy", "tz_strict"}:
                _json_response(self, {"ok": False, "error": "unsupported_mode"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                horizon_hours = int((params.get("horizon_hours") or ["24"])[0])
                limit = int((params.get("limit") or ["1000"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_numeric_filter"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if horizon_hours < 1 or horizon_hours > 168:
                _json_response(self, {"ok": False, "error": "invalid_horizon_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 5000:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                from scripts.backtest_tz_signals import run as backtest_run

                svc = _state()
                payload = backtest_run(
                    horizon_hours=horizon_hours,
                    mode=mode,
                    limit=limit,
                    signals_url=None,
                    svc=svc,
                    history=(svc.variant_history if isinstance(getattr(svc, "variant_history", None), dict) else None),
                )
                _json_response(self, payload, cache_control="no-store")
            except Exception as exc:
                _json_response(
                    self,
                    {"ok": False, "error": f"calibration_failed:{exc.__class__.__name__}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                    cache_control="no-store",
                )
            return

        if path == "/v1/signals":
            params = parse_qs(parsed.query)
            signal_type = (params.get("type") or [None])[0]
            action = [str(x) for x in (params.get("action") or [])]
            market_regime = [str(x) for x in (params.get("market_regime") or [])]
            min_score_raw = (params.get("min_score") or [None])[0]
            if min_score_raw in (None, ""):
                min_score = None
            else:
                try:
                    min_score = float(min_score_raw)
                except Exception:
                    _json_response(self, {"ok": False, "error": "invalid_min_score"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                    return
            since = (params.get("since") or [None])[0]
            mode = (params.get("mode") or [None])[0]
            edge_rank_raw = (params.get("edgeRank_min") or params.get("edgeRank100_min") or [None])[0]
            conf_min_raw = (params.get("conf_min") or [None])[0]
            profit_min_raw = (params.get("profit_min") or [None])[0]
            liq_min_raw = (params.get("liq_min") or [None])[0]
            lp_max_raw = (params.get("lp_max") or [None])[0]
            ar_min_raw = (params.get("ar_min") or [None])[0]
            vv_min_raw = (params.get("vv_min") or [None])[0]
            min_undervalue_raw = (params.get("min_undervalue_pct") or params.get("min_undervalue") or [None])[0]
            max_risk_raw = (params.get("max_risk") or [None])[0]
            only_new_1h = ((params.get("only_new_1h") or params.get("only_new") or ["false"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            sort_by = (params.get("sort_by") or [None])[0]
            sort_dir = (params.get("sort_dir") or [None])[0]
            q = (params.get("q") or params.get("search") or [""])[0]
            only_pro_alerts = ((params.get("only_pro_alerts") or ["false"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            try:
                edge_rank_min = float(edge_rank_raw) if edge_rank_raw not in (None, "") else None
                conf_min = float(conf_min_raw) if conf_min_raw not in (None, "") else None
                profit_min = float(profit_min_raw) if profit_min_raw not in (None, "") else None
                liq_min = float(liq_min_raw) if liq_min_raw not in (None, "") else None
                lp_max = float(lp_max_raw) if lp_max_raw not in (None, "") else None
                ar_min = float(ar_min_raw) if ar_min_raw not in (None, "") else None
                vv_min = float(vv_min_raw) if vv_min_raw not in (None, "") else None
                min_undervalue_pct = float(min_undervalue_raw) if min_undervalue_raw not in (None, "") else None
                max_risk = float(max_risk_raw) if max_risk_raw not in (None, "") else None
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_numeric_filter"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                limit = int((params.get("limit") or ["50"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 200:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            cursor = (params.get("cursor") or [None])[0]
            try:
                data = _state().signals_v1(
                    signal_type=signal_type,
                    action=action,
                    market_regime=market_regime,
                    min_score=min_score,
                    edgeRank_min=edge_rank_min,
                    conf_min=conf_min,
                    profit_min=profit_min,
                    liq_min=liq_min,
                    lp_max=lp_max,
                    ar_min=ar_min,
                    vv_min=vv_min,
                    min_undervalue_pct=min_undervalue_pct,
                    max_risk=max_risk,
                    only_new_1h=only_new_1h,
                    only_pro_alerts=only_pro_alerts,
                    q=q,
                    sort_by=sort_by,
                    sort_dir=sort_dir,
                    since=since,
                    limit=limit,
                    cursor=cursor,
                    mode=mode,
                )
                # Compatibility safety net: enforce client filters at HTTP layer.
                # Some older runtimes ignore part of query filters in core signals_v1.
                items = data.get("items") if isinstance(data, dict) else None
                if isinstance(items, list):
                    filtered = list(items)
                    signal_type_set = (
                        {str(signal_type or "").strip().upper()}
                        if str(signal_type or "").strip()
                        else set()
                    )
                    action_set = {str(x or "").strip().upper() for x in action if str(x or "").strip()}
                    regime_set = {str(x or "").strip().upper() for x in market_regime if str(x or "").strip()}
                    q_norm = str(q or "").strip().lower()
                    filters_applied = bool(signal_type_set or action_set or regime_set or q_norm)
                    filters_applied = filters_applied or any(
                        v is not None for v in (
                            min_score,
                            edge_rank_min,
                            conf_min,
                            profit_min,
                            liq_min,
                            lp_max,
                            ar_min,
                            vv_min,
                            min_undervalue_pct,
                            max_risk,
                        )
                    ) or bool(only_new_1h or only_pro_alerts)
                    if signal_type_set:
                        filtered = [
                            row for row in filtered
                            if str((row or {}).get("type") or (row or {}).get("action") or "").strip().upper() in signal_type_set
                        ]
                    if action_set:
                        filtered = [
                            row for row in filtered
                            if str((row or {}).get("type") or (row or {}).get("action") or "").strip().upper() in action_set
                        ]
                    if regime_set:
                        filtered = [
                            row for row in filtered
                            if str((row or {}).get("market_regime") or "").strip().upper() in regime_set
                        ]
                    if min_score is not None:
                        ms = float(min_score) * 100.0
                        filtered = [row for row in filtered if _safe_float((row or {}).get("score100"), 0.0) >= ms]
                    if edge_rank_min is not None:
                        filtered = [row for row in filtered if _safe_float((row or {}).get("edgeRank100"), 0.0) >= float(edge_rank_min)]
                    if conf_min is not None:
                        filtered = [row for row in filtered if _safe_float((row or {}).get("conf_pct"), 0.0) >= float(conf_min)]
                    if profit_min is not None:
                        filtered = [row for row in filtered if _safe_float((row or {}).get("expected_profit_pct"), 0.0) >= float(profit_min)]
                    if liq_min is not None:
                        filtered = [row for row in filtered if _safe_float((row or {}).get("liquidity_score"), 0.0) >= float(liq_min)]
                    if lp_max is not None:
                        filtered = [row for row in filtered if _safe_float((row or {}).get("listing_pressure"), 0.0) <= float(lp_max)]
                    if ar_min is not None:
                        filtered = [row for row in filtered if _safe_float((row or {}).get("absorption_30m"), 0.0) >= float(ar_min)]
                    if vv_min is not None:
                        filtered = [row for row in filtered if _safe_float((row or {}).get("volume_velocity"), 0.0) >= float(vv_min)]
                    if min_undervalue_pct is not None:
                        def _undervalue_pct(row: dict) -> float:
                            u = row.get("undervalue_pct")
                            if u not in (None, ""):
                                return _safe_float(u, 0.0)
                            return _safe_float(row.get("undervalue"), 0.0) * 100.0
                        filtered = [row for row in filtered if _undervalue_pct(row if isinstance(row, dict) else {}) >= float(min_undervalue_pct)]
                    if max_risk is not None:
                        def _risk_proxy(row: dict) -> float:
                            flags = (row or {}).get("risk_flags")
                            if isinstance(flags, list):
                                return min(1.0, len(flags) / 4.0)
                            return 0.0
                        filtered = [row for row in filtered if _risk_proxy(row if isinstance(row, dict) else {}) <= float(max_risk)]
                    if only_new_1h:
                        cutoff = datetime.now(timezone.utc).timestamp() - 3600
                        tmp = []
                        for row in filtered:
                            ts_dt = _parse_iso_utc(str((row or {}).get("ts") or ""))
                            if ts_dt is not None and ts_dt.timestamp() >= cutoff:
                                tmp.append(row)
                        filtered = tmp
                    if only_pro_alerts:
                        filtered = [
                            row for row in filtered
                            if _safe_float((row or {}).get("edgeRank100"), 0.0) >= 55.0
                            and _safe_float((row or {}).get("conf_pct"), 0.0) >= 35.0
                            and _safe_float((row or {}).get("expected_profit_pct"), 0.0) >= 8.0
                        ]
                    if q_norm:
                        def _haystack(row: dict) -> str:
                            parts = [
                                str((row or {}).get("variant_id") or ""),
                                str((row or {}).get("variant_label") or ""),
                                str((row or {}).get("collection") or ""),
                                str((row or {}).get("model") or ""),
                                str((row or {}).get("background") or ""),
                                str((row or {}).get("pattern") or ""),
                            ]
                            return " ".join(parts).lower()
                        filtered = [row for row in filtered if q_norm in _haystack(row if isinstance(row, dict) else {})]
                    if filters_applied:
                        data["items"] = filtered
                        data["total_count"] = len(filtered)
                        data["next_cursor"] = None
                        data["has_more"] = False
                _json_response(self, data, cache_control="no-store")
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            return

        if path == "/v1/market/status":
            params = parse_qs(parsed.query)
            window = (params.get("window") or ["30m"])[0]
            try:
                payload = _state().market_status_v1(window=window)
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if isinstance(payload, dict):
                ex = payload.get("execution_health")
                if isinstance(ex, dict):
                    ex["sse_disconnect_rate"] = float(_sse_disconnect_rate_pct())
                    payload["execution_health"] = ex
            _json_response(self, payload, cache_control="no-store")
            return

        if path == "/v1/screeners/feed":
            params = parse_qs(parsed.query)
            screener_type = [str(x) for x in (params.get("screener_type") or [])]
            market_regime = [str(x) for x in (params.get("market_regime") or [])]
            action = [str(x) for x in (params.get("action") or [])]
            edge_rank_raw = (params.get("edgeRank_min") or [None])[0]
            conf_min_raw = (params.get("conf_min") or [None])[0]
            profit_min_raw = (params.get("profit_min_pct") or [None])[0]
            liq_min_raw = (params.get("liq_min") or [None])[0]
            ar_min_raw = (params.get("ar_min") or [None])[0]
            lp_max_raw = (params.get("lp_max") or [None])[0]
            try:
                edge_rank_min = float(edge_rank_raw) if edge_rank_raw not in (None, "") else None
                conf_min = float(conf_min_raw) if conf_min_raw not in (None, "") else None
                profit_min_pct = float(profit_min_raw) if profit_min_raw not in (None, "") else None
                liq_min = float(liq_min_raw) if liq_min_raw not in (None, "") else None
                ar_min = float(ar_min_raw) if ar_min_raw not in (None, "") else None
                lp_max = float(lp_max_raw) if lp_max_raw not in (None, "") else None
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_numeric_filter"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                limit = int((params.get("limit") or ["100"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 500:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            cursor = (params.get("cursor") or [None])[0]
            try:
                payload = _state().screeners_feed_v1(
                    screener_type=screener_type,
                    market_regime=market_regime,
                    action=action,
                    edgeRank_min=edge_rank_min,
                    conf_min=conf_min,
                    profit_min_pct=profit_min_pct,
                    liq_min=liq_min,
                    ar_min=ar_min,
                    lp_max=lp_max,
                    limit=limit,
                    cursor=cursor,
                )
                _json_response(self, payload, cache_control="no-store")
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            return

        if path == "/v1/catalog/feed":
            params = parse_qs(parsed.query)
            q = (params.get("q") or [""])[0]
            action = [str(x) for x in (params.get("action") or [])]
            market_regime = [str(x) for x in (params.get("market_regime") or [])]
            preset = (params.get("preset") or [None])[0]
            sort = (params.get("sort") or [None])[0]
            dir_value = (params.get("dir") or [None])[0]
            edge_raw = (params.get("edgeRank_min") or [None])[0]
            conf_raw = (params.get("conf_min") or [None])[0]
            profit_raw = (params.get("profit_min_pct") or [None])[0]
            liq_raw = (params.get("liq_min") or [None])[0]
            depth_raw = (params.get("depth_min") or [None])[0]
            ar_raw = (params.get("ar_min") or [None])[0]
            lp_raw = (params.get("lp_max") or [None])[0]
            lots_min_raw = (params.get("active_lots_min") or [None])[0]
            lots_max_raw = (params.get("active_lots_max") or [None])[0]
            listed_min_raw = (params.get("listed_share_min") or [None])[0]
            listed_max_raw = (params.get("listed_share_max") or [None])[0]
            try:
                edge_rank_min = float(edge_raw) if edge_raw not in (None, "") else None
                conf_min = float(conf_raw) if conf_raw not in (None, "") else None
                profit_min_pct = float(profit_raw) if profit_raw not in (None, "") else None
                liq_min = float(liq_raw) if liq_raw not in (None, "") else None
                depth_min = float(depth_raw) if depth_raw not in (None, "") else None
                ar_min = float(ar_raw) if ar_raw not in (None, "") else None
                lp_max = float(lp_raw) if lp_raw not in (None, "") else None
                active_lots_min = int(lots_min_raw) if lots_min_raw not in (None, "") else None
                active_lots_max = int(lots_max_raw) if lots_max_raw not in (None, "") else None
                listed_share_min = float(listed_min_raw) if listed_min_raw not in (None, "") else None
                listed_share_max = float(listed_max_raw) if listed_max_raw not in (None, "") else None
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_numeric_filter"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                limit = int((params.get("limit") or ["200"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 1000:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            cursor = (params.get("cursor") or [None])[0]
            try:
                payload = _state().catalog_feed_v1(
                    q=q,
                    action=action,
                    market_regime=market_regime,
                    edgeRank_min=edge_rank_min,
                    conf_min=conf_min,
                    profit_min_pct=profit_min_pct,
                    liq_min=liq_min,
                    depth_min=depth_min,
                    ar_min=ar_min,
                    lp_max=lp_max,
                    active_lots_min=active_lots_min,
                    active_lots_max=active_lots_max,
                    listed_share_min=listed_share_min,
                    listed_share_max=listed_share_max,
                    preset=preset,
                    sort=sort,
                    dir=dir_value,
                    limit=limit,
                    cursor=cursor,
                )
                _json_response(self, payload, cache_control="no-store")
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            return

        if path.startswith("/v1/catalog/variant/") and path.count("/") == 4:
            variant_id = unquote(path.split("/")[-1])
            try:
                payload = _state().catalog_variant_v1(variant_id)
            except KeyError:
                _json_response(self, {"ok": False, "error": "variant_not_found"}, status=HTTPStatus.NOT_FOUND, cache_control="no-store")
                return
            _json_response(self, payload, cache_control="no-store")
            return

        # Canonical v1 listing endpoints: always delegate to core service methods.
        # Keep legacy duplicated handlers below unreachable to avoid divergent logic.
        if path == "/v1/listings/new":
            params = parse_qs(parsed.query)
            try:
                limit = int((params.get("limit") or ["200"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 500:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            cursor = (params.get("cursor") or [None])[0]
            window = (params.get("window") or ["30m"])[0]
            market_regime = [str(x) for x in (params.get("market_regime") or [])]
            action = [str(x) for x in (params.get("action") or [])]
            try:
                edge_rank_min = float((params.get("edgeRank_min") or ["55"])[0])
                conf_min = float((params.get("conf_min") or ["35"])[0])
                profit_min = float((params.get("profit_min") or ["8"])[0])
                undervalue_min = float((params.get("undervalue_min") or ["0"])[0])
                liq_min = float((params.get("liq_min") or ["35"])[0])
                lp_max = float((params.get("lp_max") or ["4"])[0])
                ar_min = float((params.get("ar_min") or ["0.9"])[0])
                vv_min = float((params.get("vv_min") or ["1"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_numeric_filter"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            only_pro_alerts = ((params.get("only_pro_alerts") or ["true"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            collection = (params.get("collection") or [""])[0]
            model = (params.get("model") or [""])[0]
            background = (params.get("background") or [""])[0]
            pattern = (params.get("pattern") or [""])[0]
            variant_id = (params.get("variant_id") or [""])[0]
            q = (params.get("q") or [""])[0]
            try:
                payload = _state().listings_new_v1(
                    limit=limit,
                    cursor=cursor,
                    window=window,
                    market_regime=market_regime,
                    action=action,
                    edgeRank_min=edge_rank_min,
                    conf_min=conf_min,
                    profit_min=profit_min,
                    undervalue_min=undervalue_min,
                    liq_min=liq_min,
                    lp_max=lp_max,
                    ar_min=ar_min,
                    vv_min=vv_min,
                    only_pro_alerts=only_pro_alerts,
                    collection=collection,
                    model=model,
                    background=background,
                    pattern=pattern,
                    variant_id=variant_id,
                    q=q,
                )
                if isinstance(payload, dict):
                    payload.setdefault("row_processing_errors", 0)
                    payload.setdefault("row_processing_error_samples", [])
                _json_response(self, payload, cache_control="no-store")
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            except Exception as exc:
                _json_response(
                    self,
                    {
                        "items": [],
                        "next_cursor": None,
                        "server_ts": _tz_now_iso(),
                        "window": str(window or "30m"),
                        "window_sec": 0,
                        "source": "runtime_error",
                        "source_error": f"listings_new_runtime_error:{exc.__class__.__name__}:{exc}",
                        "row_processing_errors": 1,
                        "row_processing_error_samples": [
                            {
                                "error_class": exc.__class__.__name__,
                                "error": str(exc),
                                "listing_key": "",
                                "variant_id": str(variant_id or ""),
                            }
                        ],
                    },
                    cache_control="no-store",
                )
            return

        if path == "/v1/listings/race":
            params = parse_qs(parsed.query)
            try:
                limit = int((params.get("limit") or ["200"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 500:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            cursor = (params.get("cursor") or [None])[0]
            window = (params.get("window") or ["30m"])[0]
            direction = (params.get("direction") or ["ANY"])[0]
            try:
                delta_pct_min = float((params.get("delta_pct_min") or ["0"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_delta_pct_min"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            only_pro_alerts = ((params.get("only_pro_alerts") or ["false"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            include_low_priority = ((params.get("include_low_priority") or ["false"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            q = (params.get("q") or [""])[0]
            try:
                payload = _state().listings_race_v1(
                    limit=limit,
                    cursor=cursor,
                    window=window,
                    direction=direction,
                    delta_pct_min=delta_pct_min,
                    only_pro_alerts=only_pro_alerts,
                    include_low_priority=include_low_priority,
                    q=q,
                )
                if isinstance(payload, dict):
                    payload.setdefault("row_processing_errors", 0)
                    payload.setdefault("row_processing_error_samples", [])
                _json_response(self, payload, cache_control="no-store")
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            except Exception as exc:
                _json_response(
                    self,
                    {
                        "items": [],
                        "next_cursor": None,
                        "server_ts": _tz_now_iso(),
                        "window": str(window or "30m"),
                        "window_sec": 0,
                        "source": "runtime_error",
                        "source_error": f"listings_race_runtime_error:{exc.__class__.__name__}:{exc}",
                        "row_processing_errors": 1,
                        "row_processing_error_samples": [
                            {
                                "error_class": exc.__class__.__name__,
                                "error": str(exc),
                                "listing_key": "",
                                "variant_id": "",
                            }
                        ],
                    },
                    cache_control="no-store",
                )
            return

        if path == "/v1/listings/new":
            params = parse_qs(parsed.query)
            try:
                limit = int((params.get("limit") or ["200"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 500:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            cursor = (params.get("cursor") or [None])[0]
            window = (params.get("window") or ["30m"])[0]
            market_regime = [str(x) for x in (params.get("market_regime") or [])]
            action = [str(x) for x in (params.get("action") or [])]
            try:
                edge_rank_min = float((params.get("edgeRank_min") or ["55"])[0])
                conf_min = float((params.get("conf_min") or ["35"])[0])
                profit_min = float((params.get("profit_min") or ["8"])[0])
                undervalue_min = float((params.get("undervalue_min") or ["0"])[0])
                liq_min = float((params.get("liq_min") or ["35"])[0])
                lp_max = float((params.get("lp_max") or ["4"])[0])
                ar_min = float((params.get("ar_min") or ["0.9"])[0])
                vv_min = float((params.get("vv_min") or ["1"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_numeric_filter"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            only_pro_alerts = ((params.get("only_pro_alerts") or ["true"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            collection = (params.get("collection") or [""])[0]
            model = (params.get("model") or [""])[0]
            background = (params.get("background") or [""])[0]
            pattern = (params.get("pattern") or [""])[0]
            variant_id = (params.get("variant_id") or [""])[0]
            q = (params.get("q") or [""])[0]
            try:
                window_raw, window_sec = _listing_window_to_sec(window, default="30m")
                state = _state()
                base = state.listings_v1(
                    limit=500,
                    cursor=None,
                    only_new=True,
                    new_window_sec=window_sec,
                    collection_q=collection,
                    model_q=model,
                    background_q=background,
                    pattern_q=pattern,
                )
                source = str((base or {}).get("source") or "mtproto_api")
                source_error = str((base or {}).get("source_error") or "")
                rows = (base or {}).get("items") if isinstance(base, dict) else []
                rows = rows if isinstance(rows, list) else []
                now = datetime.now(timezone.utc)
                market_regime_current, market_badge_current = _market_regime_snapshot_compat()

                regime_filter = {str(x or "").strip().upper() for x in (market_regime or []) if str(x or "").strip()}
                action_filter = {str(x or "").strip().upper() for x in (action or []) if str(x or "").strip()}
                q_norm = str(q or "").strip().lower()
                variant_q = str(variant_id or "").strip()

                out: list[dict] = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    ts_detected = str(row.get("first_seen_at") or row.get("last_seen_at") or "")
                    ts_dt = _parse_iso_utc(ts_detected)
                    if ts_dt is None:
                        continue
                    if (now - ts_dt).total_seconds() > float(window_sec):
                        continue

                    row_variant_id = str(row.get("variant_id") or "").strip()
                    if variant_q and variant_q != row_variant_id:
                        continue
                    attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
                    collection_name = str(row.get("collection") or row.get("title") or row.get("collection_id") or row.get("gift_id") or "")
                    model_name = str(attrs.get("model") or "Unknown")
                    background_name = str(attrs.get("background") or "Unknown")
                    pattern_name = str(attrs.get("pattern") or "Unknown")
                    variant = state.variants.get(row_variant_id) if row_variant_id else None
                    preview_url = str(row.get("preview_url") or "")
                    if isinstance(variant, dict):
                        traits = variant.get("traits") if isinstance(variant.get("traits"), dict) else {}
                        model_name = str(((traits.get("model") or {}).get("name")) or model_name or "Unknown")
                        background_name = str(((traits.get("background") or {}).get("name")) or background_name or "Unknown")
                        pattern_name = str(((traits.get("pattern") or {}).get("name")) or pattern_name or "Unknown")
                        preview_url = str(variant.get("preview_url") or preview_url)
                    variant_label = _listing_variant_label(collection_name, model_name, background_name, pattern_name)
                    signal_payload = state._v1_signal(variant, mode="tz") if isinstance(variant, dict) else {}
                    score100 = float(signal_payload.get("score100") or 0.0) if isinstance(signal_payload, dict) else 0.0
                    conf_pct_val = float(signal_payload.get("conf_pct") or 0.0) if isinstance(signal_payload, dict) else 0.0
                    expected_profit_pct = _norm_pct(float(signal_payload.get("expected_profit_pct") or 0.0)) if isinstance(signal_payload, dict) else 0.0
                    undervalue_pct = _norm_pct(float(signal_payload.get("undervalue") or 0.0)) if isinstance(signal_payload, dict) else 0.0
                    liquidity_score = _clamp(float(signal_payload.get("liquidity24h") or 0.0), 0.0, 1.0) * 100.0 if isinstance(signal_payload, dict) else 0.0
                    absorption_30m = float(signal_payload.get("absorption_rate") or 0.0) if isinstance(signal_payload, dict) else 0.0
                    listing_pressure = float(signal_payload.get("listing_pressure") or 0.0) if isinstance(signal_payload, dict) else 0.0
                    volume_velocity = float(signal_payload.get("volume_velocity") or 0.0) if isinstance(signal_payload, dict) else 0.0
                    action_val = str(signal_payload.get("type") or "WATCH") if isinstance(signal_payload, dict) else "WATCH"
                    edge_rank = _clamp((score100 * conf_pct_val) / 100.0, 0.0, 100.0)

                    if regime_filter and market_regime_current not in regime_filter:
                        continue
                    if action_filter and action_val.upper() not in action_filter:
                        continue
                    if edge_rank < edge_rank_min or conf_pct_val < conf_min:
                        continue
                    if expected_profit_pct < profit_min or undervalue_pct < undervalue_min:
                        continue
                    if liquidity_score < liq_min or listing_pressure > lp_max:
                        continue
                    if absorption_30m < ar_min or volume_velocity < vv_min:
                        continue
                    if only_pro_alerts and action_val.upper() not in {"BUY", "SELL"}:
                        continue
                    if q_norm:
                        hay = " ".join([variant_label, row_variant_id, str(row.get("listing_key") or "")]).lower()
                        if q_norm not in hay:
                            continue

                    out.append(
                        {
                            "listing_key": str(row.get("listing_key") or ""),
                            "variant_id": row_variant_id or None,
                            "collection_id": str(row.get("collection_id") or row.get("gift_id") or "") or None,
                            "collection": collection_name or None,
                            "model": model_name,
                            "background": background_name,
                            "pattern": pattern_name,
                            "variant_label": variant_label,
                            "preview_url": preview_url,
                            "price_ton": round(_listing_row_price_ton_equiv(state, row), 6),
                            "floor_ton": signal_payload.get("floor_ton") if isinstance(signal_payload, dict) else None,
                            "fair_ton": signal_payload.get("fair_ton") if isinstance(signal_payload, dict) else None,
                            "undervalue_pct": round(undervalue_pct, 2),
                            "expected_profit_pct": round(expected_profit_pct, 2),
                            "score100": round(score100, 1),
                            "conf_pct": round(conf_pct_val, 1),
                            "edgeRank100": round(edge_rank, 1),
                            "edgeRank_raw": round(edge_rank / 100.0, 6),
                            "action": action_val.upper(),
                            "strength_tag": _signal_action_strength(action_val, score100),
                            "liquidity_score": round(liquidity_score, 2),
                            "absorption_30m": round(absorption_30m, 4),
                            "listing_pressure": round(listing_pressure, 4),
                            "volume_velocity": round(volume_velocity, 4),
                            "market_regime": market_regime_current,
                            "market_regime_badge": market_badge_current,
                            "ts_detected": ts_detected,
                            "latency_ms": max(0, int((now - ts_dt).total_seconds() * 1000.0)),
                            "source": source,
                        }
                    )
                out.sort(key=lambda x: (float(x.get("edgeRank100") or 0.0), float(x.get("expected_profit_pct") or 0.0), str(x.get("ts_detected") or "")), reverse=True)
                off = 0
                try:
                    off = max(0, int(str(cursor or "0")))
                except Exception:
                    off = 0
                chunk = out[off : off + limit]
                next_cursor = str(off + limit) if (off + limit) < len(out) else None
                _json_response(
                    self,
                    {
                        "items": chunk,
                        "next_cursor": next_cursor,
                        "server_ts": _tz_now_iso(),
                        "window": window_raw,
                        "window_sec": window_sec,
                        "source": source,
                        "source_error": source_error,
                    },
                    cache_control="no-store",
                )
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            except Exception as exc:
                _json_response(
                    self,
                    {
                        "items": [],
                        "next_cursor": None,
                        "server_ts": _tz_now_iso(),
                        "window": str(window or "30m"),
                        "window_sec": 0,
                        "source": "runtime_error",
                        "source_error": f"listings_new_runtime_error:{exc.__class__.__name__}:{exc}",
                    },
                    cache_control="no-store",
                )
            return

        if path == "/v1/listings/race":
            params = parse_qs(parsed.query)
            try:
                limit = int((params.get("limit") or ["200"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 500:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            cursor = (params.get("cursor") or [None])[0]
            window = (params.get("window") or ["30m"])[0]
            direction = (params.get("direction") or ["ANY"])[0]
            try:
                delta_pct_min = float((params.get("delta_pct_min") or ["0"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_delta_pct_min"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            only_pro_alerts = ((params.get("only_pro_alerts") or ["false"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            include_low_priority = ((params.get("include_low_priority") or ["false"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            q = (params.get("q") or [""])[0]
            try:
                window_raw, window_sec = _listing_window_to_sec(window, default="30m")
                direction_norm = str(direction or "ANY").strip().upper()
                if direction_norm not in {"UP", "DOWN", "ANY"}:
                    raise ValueError(f"unsupported_direction:{direction_norm}")
                state = _state()
                base_payload = None
                base_rows: list[dict] = []
                try:
                    mt_rows, mt_status = state._refresh_mt_listing_source(force=False, window_sec=max(window_sec, 120))
                    if isinstance(mt_rows, list):
                        base_rows = [x for x in mt_rows if isinstance(x, dict)]
                    base_payload = {
                        "items": base_rows,
                        "source": str((mt_status or {}).get("source") or "mtproto_api"),
                        "source_error": str((mt_status or {}).get("error") or ""),
                    }
                except Exception:
                    base_payload = state.listings_v1(
                        limit=500,
                        cursor=None,
                        only_new=False,
                        new_window_sec=max(window_sec, 120),
                        collection_q="",
                        model_q="",
                        background_q="",
                        pattern_q="",
                    )
                    rows_raw = (base_payload or {}).get("items") if isinstance(base_payload, dict) else []
                    base_rows = rows_raw if isinstance(rows_raw, list) else []
                if isinstance(base_rows, list) and base_rows:
                    _warmup_race_tracker_from_rows(state, base_rows, _tz_now_iso())
                try:
                    state._sync_listing_tracker_state(datetime.now(timezone.utc), persist=False)
                except Exception:
                    pass
                market_regime_current, market_badge_current = _market_regime_snapshot_compat()
                source = str((base_payload or {}).get("source") or "mtproto_api")
                source_error = str((base_payload or {}).get("source_error") or "")
                q_norm = str(q or "").strip().lower()
                now = datetime.now(timezone.utc)
                out: list[dict] = []
                tracker = state.listing_tracker_state if isinstance(state.listing_tracker_state, dict) else {}
                for entry in tracker.values():
                    if not isinstance(entry, dict):
                        continue
                    ts_detected = str(entry.get("last_price_changed_at") or entry.get("last_seen_at") or "")
                    ts_dt = _parse_iso_utc(ts_detected)
                    if ts_dt is None:
                        continue
                    if (now - ts_dt).total_seconds() > float(window_sec):
                        continue
                    prev_price = _safe_float(entry.get("prev_price_ton"), 0.0)
                    price_ton = _safe_float(entry.get("last_price_ton"), 0.0)
                    if prev_price <= 0.0 or price_ton <= 0.0:
                        continue
                    delta_ton = price_ton - prev_price
                    if abs(delta_ton) < 1e-9:
                        continue
                    delta_pct = (delta_ton / max(prev_price, 1e-9)) * 100.0
                    row_direction = "UP" if delta_ton > 0 else "DOWN"
                    if direction_norm != "ANY" and row_direction != direction_norm:
                        continue
                    if abs(delta_pct) < max(0.0, float(delta_pct_min or 0.0)):
                        continue
                    low_priority = abs(delta_pct) < 0.5
                    if low_priority and not include_low_priority:
                        continue
                    variant_id_row = str(entry.get("variant_id") or "")
                    variant = state.variants.get(variant_id_row) if variant_id_row else None
                    base_id = str(entry.get("base_id") or "")
                    collection_name = base_id.replace("_", " ").title() if base_id else "Unknown"
                    model_name = "Unknown"
                    background_name = "Unknown"
                    pattern_name = "Unknown"
                    preview_url = str(entry.get("preview_url") or "")
                    if isinstance(variant, dict):
                        traits = variant.get("traits") if isinstance(variant.get("traits"), dict) else {}
                        model_name = str(((traits.get("model") or {}).get("name")) or model_name)
                        background_name = str(((traits.get("background") or {}).get("name")) or background_name)
                        pattern_name = str(((traits.get("pattern") or {}).get("name")) or pattern_name)
                        preview_url = str(variant.get("preview_url") or preview_url)
                    label = _listing_variant_label(collection_name, model_name, background_name, pattern_name)
                    signal_payload = state._v1_signal(variant, mode="tz") if isinstance(variant, dict) else {}
                    score100 = float(signal_payload.get("score100") or 0.0) if isinstance(signal_payload, dict) else 0.0
                    conf_pct_val = float(signal_payload.get("conf_pct") or 0.0) if isinstance(signal_payload, dict) else 0.0
                    edge_rank = _clamp((score100 * conf_pct_val) / 100.0, 0.0, 100.0)
                    action_val = str(signal_payload.get("type") or "WATCH") if isinstance(signal_payload, dict) else "WATCH"
                    if only_pro_alerts and action_val.upper() not in {"BUY", "SELL"}:
                        continue
                    if q_norm:
                        hay = " ".join([label, variant_id_row, str(entry.get("listing_key") or "")]).lower()
                        if q_norm not in hay:
                            continue
                    out.append(
                        {
                            "listing_key": str(entry.get("listing_key") or ""),
                            "variant_id": variant_id_row or None,
                            "collection_id": base_id or None,
                            "collection": collection_name,
                            "model": model_name,
                            "background": background_name,
                            "pattern": pattern_name,
                            "variant_label": label,
                            "preview_url": preview_url,
                            "prev_price_ton": round(prev_price, 6),
                            "price_ton": round(price_ton, 6),
                            "delta_ton": round(delta_ton, 6),
                            "delta_pct": round(delta_pct, 6),
                            "direction": row_direction,
                            "low_priority": low_priority,
                            "market_regime": market_regime_current,
                            "market_regime_badge": market_badge_current,
                            "edgeRank100": round(edge_rank, 1),
                            "action": action_val.upper(),
                            "ts_detected": ts_detected,
                            "source": source,
                        }
                    )
                out.sort(key=lambda x: (abs(float(x.get("delta_pct") or 0.0)), str(x.get("ts_detected") or "")), reverse=True)
                off = 0
                try:
                    off = max(0, int(str(cursor or "0")))
                except Exception:
                    off = 0
                chunk = out[off : off + limit]
                next_cursor = str(off + limit) if (off + limit) < len(out) else None
                _json_response(
                    self,
                    {
                        "items": chunk,
                        "next_cursor": next_cursor,
                        "server_ts": _tz_now_iso(),
                        "window": window_raw,
                        "window_sec": window_sec,
                        "source": source,
                        "source_error": source_error,
                    },
                    cache_control="no-store",
                )
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            except Exception as exc:
                _json_response(
                    self,
                    {
                        "items": [],
                        "next_cursor": None,
                        "server_ts": _tz_now_iso(),
                        "window": str(window or "30m"),
                        "window_sec": 0,
                        "source": "runtime_error",
                        "source_error": f"listings_race_runtime_error:{exc.__class__.__name__}:{exc}",
                    },
                    cache_control="no-store",
                )
            return

        if path == "/v1/listings/history":
            params = parse_qs(parsed.query)
            variant_id = (params.get("variant_id") or [""])[0]
            if not variant_id:
                _json_response(self, {"ok": False, "error": "variant_id_required"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            from_ts = (params.get("from") or [None])[0]
            to_ts = (params.get("to") or [None])[0]
            resolution = (params.get("resolution") or ["1m"])[0]
            try:
                _json_response(
                    self,
                    _state().listings_history_v1(
                        variant_id=variant_id,
                        from_ts=from_ts,
                        to_ts=to_ts,
                        resolution=resolution,
                    ),
                    cache_control="no-store",
                )
            except ValueError as exc:
                code = HTTPStatus.BAD_REQUEST
                if str(exc) == "variant_not_found_or_not_active":
                    code = HTTPStatus.NOT_FOUND
                _json_response(self, {"ok": False, "error": str(exc)}, status=code, cache_control="no-store")
            return

        if path == "/v1/stream/listings":
            params = parse_qs(parsed.query)
            since = (params.get("since") or [None])[0]
            window = (params.get("window") or ["30m"])[0]
            include_low_priority_raw = (params.get("include_low_priority") or [None])[0]
            try:
                include_low_priority = _parse_query_bool(
                    include_low_priority_raw,
                    default=False,
                    field="include_low_priority",
                )
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                limit = int((params.get("limit") or ["200"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 500:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                interval_sec = float((params.get("interval_sec") or ["2.0"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_interval_sec"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if interval_sec < 0.8 or interval_sec > 10.0:
                _json_response(self, {"ok": False, "error": "invalid_interval_sec_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                _state()._listing_window_to_seconds(window, default="30m")  # noqa: SLF001
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            stream_key = "v1/stream/listings"
            _observe_sse_open(stream_key)

            abrupt_close = False
            try:
                last_seen_ts = since or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                last_snapshot_token = ""
                sent_ids: set[str] = set()
                sent_listing_keys: dict[str, float] = {}
                dedupe_ttl = float(max(60, int(getattr(_state(), "listing_event_dedupe_ttl_sec", 600))))
                deadline = time.time() + 25
                while time.time() < deadline:
                    out_events: list[tuple[str, str, dict]] = []
                    max_ts = last_seen_ts
                    sent = 0
                    try:
                        svc = _state()
                        snapshot_token = _v1_listings_stream_snapshot_token(
                            svc,
                            window=window,
                            include_low_priority=include_low_priority,
                        )
                    except Exception:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        time.sleep(interval_sec)
                        continue

                    now_mono = time.monotonic()
                    for key, seen_ts in list(sent_listing_keys.items()):
                        if (now_mono - seen_ts) >= dedupe_ttl:
                            sent_listing_keys.pop(key, None)
                    if snapshot_token != last_snapshot_token:
                        last_snapshot_token = snapshot_token
                        try:
                            new_payload = svc.listings_new_v1(limit=limit, window=window, only_pro_alerts=False)
                            race_payload = svc.listings_race_v1(
                                limit=limit,
                                window=window,
                                direction="ANY",
                                delta_pct_min=0.0,
                                only_pro_alerts=False,
                                include_low_priority=include_low_priority,
                            )
                            removed_payload = svc._listing_removed_events_v1()  # noqa: SLF001
                        except Exception:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                            time.sleep(interval_sec)
                            continue

                        for row in (new_payload.get("items") or []):
                            if not isinstance(row, dict):
                                continue
                            ts = str(row.get("ts_detected") or "")
                            if not ts or ts <= last_seen_ts:
                                continue
                            listing_key = str(row.get("listing_key") or "")
                            dedupe_key = f"listing.new|{listing_key}"
                            if listing_key and dedupe_key in sent_listing_keys:
                                continue
                            if listing_key:
                                sent_listing_keys[dedupe_key] = now_mono
                            out_events.append(("listing.new", ts, row))
                        for row in (race_payload.get("items") or []):
                            if not isinstance(row, dict):
                                continue
                            ts = str(row.get("ts_detected") or "")
                            if not ts or ts <= last_seen_ts:
                                continue
                            listing_key = str(row.get("listing_key") or "")
                            dedupe_key = f"listing.price_changed|{listing_key}"
                            if listing_key and dedupe_key in sent_listing_keys:
                                continue
                            if listing_key:
                                sent_listing_keys[dedupe_key] = now_mono
                            out_events.append(("listing.price_changed", ts, row))
                        for row in (removed_payload or []):
                            if not isinstance(row, dict):
                                continue
                            ts = str(row.get("ts") or "")
                            if not ts or ts <= last_seen_ts:
                                continue
                            out_events.append(("listing.removed", ts, row))

                        out_events.sort(key=lambda x: x[1])
                        for ev_name, ts, payload in out_events:
                            event_id = f"{ev_name}|{payload.get('listing_key')}|{ts}"
                            if event_id in sent_ids:
                                continue
                            sent_ids.add(event_id)
                            self.wfile.write(f"event: {ev_name}\n".encode("utf-8"))
                            self.wfile.write(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8"))
                            sent += 1
                            if ts > max_ts:
                                max_ts = ts
                    if len(sent_ids) > 10000:
                        sent_ids.clear()
                    health_payload = {
                        "source": "listing.stream.v1",
                        "count": sent,
                        "ts": max_ts,
                    }
                    self.wfile.write(b"event: listing.feed.health\n")
                    self.wfile.write(f"data: {json.dumps(health_payload, ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last_seen_ts = max_ts
                    time.sleep(interval_sec)
            except (BrokenPipeError, ConnectionResetError, OSError):
                abrupt_close = True
            finally:
                _observe_sse_close(stream_key, abrupt=abrupt_close)
            return

        if path == "/v1/listings":
            params = parse_qs(parsed.query)
            try:
                limit = int((params.get("limit") or ["100"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 500:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            cursor = (params.get("cursor") or [None])[0]
            only_new = ((params.get("only_new") or ["0"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            try:
                new_window_sec = int((params.get("new_window_sec") or ["120"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_new_window_sec"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            collection_q = (params.get("collection_q") or [""])[0]
            model_q = (params.get("model_q") or [""])[0]
            background_q = (params.get("background_q") or [""])[0]
            pattern_q = (params.get("pattern_q") or [""])[0]
            data = _state().listings_v1(
                limit=limit,
                cursor=cursor,
                only_new=only_new,
                new_window_sec=new_window_sec,
                collection_q=collection_q,
                model_q=model_q,
                background_q=background_q,
                pattern_q=pattern_q,
            )
            _json_response(self, data, cache_control="no-store")
            return

        if path == "/v1/listings/new":
            params = parse_qs(parsed.query)
            try:
                limit = int((params.get("limit") or ["200"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 500:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            cursor = (params.get("cursor") or [None])[0]
            try:
                window_raw, window_sec = _listing_window_to_sec((params.get("window") or ["30m"])[0], default="30m")
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return

            market_regime = {str(x or "").strip().upper() for x in (params.get("market_regime") or []) if str(x or "").strip()}
            action_filter = {str(x or "").strip().upper() for x in (params.get("action") or []) if str(x or "").strip()}
            bad_regimes = sorted([x for x in market_regime if x not in {"RISK_ON", "MEAN_REVERT", "RISK_OFF", "PANIC"}])
            if bad_regimes:
                _json_response(self, {"ok": False, "error": f"unsupported_market_regime:{','.join(bad_regimes)}"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            bad_actions = sorted([x for x in action_filter if x not in {"BUY", "SELL", "WATCH", "SKIP"}])
            if bad_actions:
                _json_response(self, {"ok": False, "error": f"unsupported_action:{','.join(bad_actions)}"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return

            try:
                edge_rank_min = _clamp(float((params.get("edgeRank_min") or ["55"])[0]), 0.0, 100.0)
                conf_min = _clamp(float((params.get("conf_min") or ["35"])[0]), 0.0, 100.0)
                profit_min = float((params.get("profit_min") or ["8"])[0])
                undervalue_min = float((params.get("undervalue_min") or ["0"])[0])
                liq_min = _clamp(float((params.get("liq_min") or ["35"])[0]), 0.0, 100.0)
                lp_max = max(0.0, float((params.get("lp_max") or ["4"])[0]))
                ar_min = float((params.get("ar_min") or ["0.9"])[0])
                vv_min = float((params.get("vv_min") or ["1"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_numeric_filter"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return

            only_pro_alerts = ((params.get("only_pro_alerts") or ["true"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            collection_q = (params.get("collection") or [""])[0]
            model_q = (params.get("model") or [""])[0]
            background_q = (params.get("background") or [""])[0]
            pattern_q = (params.get("pattern") or [""])[0]
            variant_q = (params.get("variant_id") or [""])[0].strip()
            free_q = (params.get("q") or [""])[0].strip().lower()

            state = _state()
            base = state.listings_v1(
                limit=500,
                cursor=None,
                only_new=True,
                new_window_sec=window_sec,
                collection_q=collection_q,
                model_q=model_q,
                background_q=background_q,
                pattern_q=pattern_q,
            )
            source = str((base or {}).get("source") or "mtproto_api")
            source_error = str((base or {}).get("source_error") or "")
            rows = (base or {}).get("items") if isinstance(base, dict) else []
            rows = rows if isinstance(rows, list) else []
            market_regime_current, market_badge_current = _market_regime_snapshot_compat()
            now = datetime.now(timezone.utc)

            out: list[dict] = []
            row_processing_errors = 0
            row_processing_error_samples: list[dict] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    ts_detected = str(row.get("first_seen_at") or row.get("last_seen_at") or "")
                    ts_dt = _parse_iso_utc(ts_detected)
                    if ts_dt is None:
                        continue
                    if (now - ts_dt).total_seconds() > float(window_sec):
                        continue

                    variant_id = str(row.get("variant_id") or "").strip()
                    if variant_q and variant_q != variant_id:
                        continue
                    attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
                    collection = str(row.get("collection") or row.get("title") or row.get("collection_id") or row.get("gift_id") or "")
                    model = str(attrs.get("model") or "Unknown")
                    background = str(attrs.get("background") or "Unknown")
                    pattern = str(attrs.get("pattern") or "Unknown")
                    variant = state.variants.get(variant_id) if variant_id else None
                    preview_url = str(row.get("preview_url") or "")
                    if isinstance(variant, dict):
                        traits = variant.get("traits") if isinstance(variant.get("traits"), dict) else {}
                        model = str(((traits.get("model") or {}).get("name")) or model or "Unknown")
                        background = str(((traits.get("background") or {}).get("name")) or background or "Unknown")
                        pattern = str(((traits.get("pattern") or {}).get("name")) or pattern or "Unknown")
                        preview_url = str(variant.get("preview_url") or preview_url)
                    variant_label = _listing_variant_label(collection, model, background, pattern)
                    signal_payload = state._v1_signal(variant, mode="tz") if isinstance(variant, dict) else {}
                    score100 = float(signal_payload.get("score100") or 0.0) if isinstance(signal_payload, dict) else 0.0
                    conf_pct = float(signal_payload.get("conf_pct") or 0.0) if isinstance(signal_payload, dict) else 0.0
                    expected_profit_pct = _norm_pct(float(signal_payload.get("expected_profit_pct") or 0.0)) if isinstance(signal_payload, dict) else 0.0
                    undervalue_pct = _norm_pct(float(signal_payload.get("undervalue") or 0.0)) if isinstance(signal_payload, dict) else 0.0
                    liquidity_score = _clamp(float(signal_payload.get("liquidity24h") or 0.0), 0.0, 1.0) * 100.0 if isinstance(signal_payload, dict) else 0.0
                    absorption_30m = float(signal_payload.get("absorption_rate") or 0.0) if isinstance(signal_payload, dict) else 0.0
                    listing_pressure = float(signal_payload.get("listing_pressure") or 0.0) if isinstance(signal_payload, dict) else 0.0
                    volume_velocity = float(signal_payload.get("volume_velocity") or 0.0) if isinstance(signal_payload, dict) else 0.0
                    action = str(signal_payload.get("type") or "WATCH") if isinstance(signal_payload, dict) else "WATCH"
                    edge_rank = _clamp((score100 * conf_pct) / 100.0, 0.0, 100.0)
                    if market_regime and market_regime_current not in market_regime:
                        continue
                    if action_filter and action.upper() not in action_filter:
                        continue
                    if edge_rank < edge_rank_min or conf_pct < conf_min:
                        continue
                    if expected_profit_pct < profit_min or undervalue_pct < undervalue_min:
                        continue
                    if liquidity_score < liq_min or listing_pressure > lp_max:
                        continue
                    if absorption_30m < ar_min or volume_velocity < vv_min:
                        continue
                    if only_pro_alerts and action.upper() not in {"BUY", "SELL"}:
                        continue
                    if free_q:
                        hay = " ".join([variant_label, variant_id, str(row.get("listing_key") or "")]).lower()
                        if free_q not in hay:
                            continue
                    row_price_ton = _listing_row_price_ton_equiv(state, row)
                    item = {
                        "listing_key": str(row.get("listing_key") or ""),
                        "variant_id": variant_id or None,
                        "collection_id": str(row.get("collection_id") or row.get("gift_id") or "") or None,
                        "collection": collection or None,
                        "model": model,
                        "background": background,
                        "pattern": pattern,
                        "variant_label": variant_label,
                        "preview_url": preview_url,
                        "price_ton": round(row_price_ton, 6),
                        "floor_ton": signal_payload.get("floor_ton") if isinstance(signal_payload, dict) else None,
                        "fair_ton": signal_payload.get("fair_ton") if isinstance(signal_payload, dict) else None,
                        "undervalue_pct": round(undervalue_pct, 2),
                        "expected_profit_pct": round(expected_profit_pct, 2),
                        "score100": round(score100, 1),
                        "conf_pct": round(conf_pct, 1),
                        "edgeRank100": round(edge_rank, 1),
                        "edgeRank_raw": round(edge_rank / 100.0, 6),
                        "action": action.upper(),
                        "strength_tag": _signal_action_strength(action, score100),
                        "liquidity_score": round(liquidity_score, 2),
                        "absorption_30m": round(absorption_30m, 4),
                        "listing_pressure": round(listing_pressure, 4),
                        "volume_velocity": round(volume_velocity, 4),
                        "market_regime": market_regime_current,
                        "market_regime_badge": market_badge_current,
                        "ts_detected": ts_detected,
                        "latency_ms": max(0, int((now - ts_dt).total_seconds() * 1000.0)),
                        "source": source,
                    }
                    out.append(item)
                except Exception as exc:
                    row_processing_errors += 1
                    state._record_listing_runtime_error(  # noqa: SLF001
                        block="listings_new",
                        stage="http_row_processing",
                        exc=exc,
                        row=row if isinstance(row, dict) else None,
                    )
                    if len(row_processing_error_samples) < 3:
                        row_processing_error_samples.append(
                            {
                                "error_class": exc.__class__.__name__,
                                "error": str(exc),
                                "listing_key": str((row or {}).get("listing_key") or ""),
                                "variant_id": str((row or {}).get("variant_id") or ""),
                            }
                        )
            out.sort(key=lambda x: (float(x.get("edgeRank100") or 0.0), float(x.get("expected_profit_pct") or 0.0), str(x.get("ts_detected") or "")), reverse=True)
            off = 0
            try:
                off = max(0, int(str(cursor or "0")))
            except Exception:
                off = 0
            chunk = out[off : off + limit]
            next_cursor = str(off + limit) if (off + limit) < len(out) else None
            _json_response(
                self,
                {
                    "items": chunk,
                    "next_cursor": next_cursor,
                    "server_ts": _tz_now_iso(),
                    "window": window_raw,
                    "window_sec": window_sec,
                    "source": source,
                    "source_error": source_error,
                    "row_processing_errors": row_processing_errors,
                    "row_processing_error_samples": row_processing_error_samples,
                },
                cache_control="no-store",
            )
            return

        if path == "/v1/listings/race":
            params = parse_qs(parsed.query)
            try:
                limit = int((params.get("limit") or ["200"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 500:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            cursor = (params.get("cursor") or [None])[0]
            try:
                window_raw, window_sec = _listing_window_to_sec((params.get("window") or ["30m"])[0], default="30m")
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            direction = str((params.get("direction") or ["ANY"])[0] or "ANY").strip().upper()
            if direction not in {"UP", "DOWN", "ANY"}:
                _json_response(self, {"ok": False, "error": f"unsupported_direction:{direction}"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                delta_pct_min = max(0.0, float((params.get("delta_pct_min") or ["0"])[0]))
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_delta_pct_min"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            only_pro_alerts = ((params.get("only_pro_alerts") or ["false"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            include_low_priority = ((params.get("include_low_priority") or ["false"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            q = (params.get("q") or [""])[0].strip().lower()

            state = _state()
            now = datetime.now(timezone.utc)
            base_payload = None
            base_rows: list[dict] = []
            try:
                mt_rows, mt_status = state._refresh_mt_listing_source(force=False, window_sec=max(window_sec, 120))
                if isinstance(mt_rows, list):
                    base_rows = [x for x in mt_rows if isinstance(x, dict)]
                base_payload = {
                    "items": base_rows,
                    "source": str((mt_status or {}).get("source") or "mtproto_api"),
                    "source_error": str((mt_status or {}).get("error") or ""),
                }
            except Exception:
                base_payload = state.listings_v1(
                    limit=500,
                    cursor=None,
                    only_new=False,
                    new_window_sec=max(window_sec, 120),
                    collection_q="",
                    model_q="",
                    background_q="",
                    pattern_q="",
                )
                rows_raw = (base_payload or {}).get("items") if isinstance(base_payload, dict) else []
                base_rows = rows_raw if isinstance(rows_raw, list) else []
            if isinstance(base_rows, list) and base_rows:
                _warmup_race_tracker_from_rows(state, base_rows, _tz_now_iso())
            try:
                state._sync_listing_tracker_state(now, persist=False)
            except Exception:
                pass
            market_regime_current, market_badge_current = _market_regime_snapshot_compat()
            source = str((base_payload or {}).get("source") or "mtproto_api")
            source_error = str((base_payload or {}).get("source_error") or "")
            if not source:
                source_status = state.listing_source_status_v1()
                source = str((source_status or {}).get("source") or "mtproto_api")
                source_error = str((source_status or {}).get("error") or "")

            out: list[dict] = []
            row_processing_errors = 0
            row_processing_error_samples: list[dict] = []
            tracker = state.listing_tracker_state if isinstance(state.listing_tracker_state, dict) else {}
            for entry in tracker.values():
                if not isinstance(entry, dict):
                    continue
                try:
                    ts_detected = str(entry.get("last_price_changed_at") or entry.get("last_seen_at") or "")
                    ts_dt = _parse_iso_utc(ts_detected)
                    if ts_dt is None:
                        continue
                    if (now - ts_dt).total_seconds() > float(window_sec):
                        continue
                    prev_price = _safe_float(entry.get("prev_price_ton"), 0.0)
                    price_ton = _safe_float(entry.get("last_price_ton"), 0.0)
                    if prev_price <= 0.0 or price_ton <= 0.0:
                        continue
                    delta_ton = price_ton - prev_price
                    if abs(delta_ton) < 1e-9:
                        continue
                    delta_pct = (delta_ton / max(prev_price, 1e-9)) * 100.0
                    row_direction = "UP" if delta_ton > 0 else "DOWN"
                    if direction != "ANY" and row_direction != direction:
                        continue
                    if abs(delta_pct) < delta_pct_min:
                        continue
                    low_priority = abs(delta_pct) < 0.5
                    if low_priority and not include_low_priority:
                        continue
                    variant_id = str(entry.get("variant_id") or "")
                    variant = state.variants.get(variant_id) if variant_id else None
                    base_id = str(entry.get("base_id") or "")
                    collection = base_id.replace("_", " ").title() if base_id else "Unknown"
                    model = "Unknown"
                    background = "Unknown"
                    pattern = "Unknown"
                    preview_url = str(entry.get("preview_url") or "")
                    if isinstance(variant, dict):
                        traits = variant.get("traits") if isinstance(variant.get("traits"), dict) else {}
                        model = str(((traits.get("model") or {}).get("name")) or model)
                        background = str(((traits.get("background") or {}).get("name")) or background)
                        pattern = str(((traits.get("pattern") or {}).get("name")) or pattern)
                        preview_url = str(variant.get("preview_url") or preview_url)
                    label = _listing_variant_label(collection, model, background, pattern)
                    signal_payload = state._v1_signal(variant, mode="tz") if isinstance(variant, dict) else {}
                    score100 = float(signal_payload.get("score100") or 0.0) if isinstance(signal_payload, dict) else 0.0
                    conf_pct = float(signal_payload.get("conf_pct") or 0.0) if isinstance(signal_payload, dict) else 0.0
                    edge_rank = _clamp((score100 * conf_pct) / 100.0, 0.0, 100.0)
                    action = str(signal_payload.get("type") or "WATCH") if isinstance(signal_payload, dict) else "WATCH"
                    if only_pro_alerts and action.upper() not in {"BUY", "SELL"}:
                        continue
                    if q:
                        hay = " ".join([label, variant_id, str(entry.get("listing_key") or "")]).lower()
                        if q not in hay:
                            continue
                    out.append(
                        {
                            "listing_key": str(entry.get("listing_key") or ""),
                            "variant_id": variant_id or None,
                            "collection_id": base_id or None,
                            "collection": collection,
                            "model": model,
                            "background": background,
                            "pattern": pattern,
                            "variant_label": label,
                            "preview_url": preview_url,
                            "prev_price_ton": round(prev_price, 6),
                            "price_ton": round(price_ton, 6),
                            "delta_ton": round(delta_ton, 6),
                            "delta_pct": round(delta_pct, 6),
                            "direction": row_direction,
                            "low_priority": low_priority,
                            "market_regime": market_regime_current,
                            "market_regime_badge": market_badge_current,
                            "edgeRank100": round(edge_rank, 1),
                            "action": action.upper(),
                            "ts_detected": ts_detected,
                            "source": source,
                        }
                    )
                except Exception as exc:
                    row_processing_errors += 1
                    state._record_listing_runtime_error(  # noqa: SLF001
                        block="listings_race",
                        stage="http_row_processing",
                        exc=exc,
                        row=entry if isinstance(entry, dict) else None,
                    )
                    if len(row_processing_error_samples) < 3:
                        row_processing_error_samples.append(
                            {
                                "error_class": exc.__class__.__name__,
                                "error": str(exc),
                                "listing_key": str((entry or {}).get("listing_key") or ""),
                                "variant_id": str((entry or {}).get("variant_id") or ""),
                            }
                        )

            out.sort(key=lambda x: (abs(float(x.get("delta_pct") or 0.0)), str(x.get("ts_detected") or "")), reverse=True)
            off = 0
            try:
                off = max(0, int(str(cursor or "0")))
            except Exception:
                off = 0
            chunk = out[off : off + limit]
            next_cursor = str(off + limit) if (off + limit) < len(out) else None
            _json_response(
                self,
                {
                    "items": chunk,
                    "next_cursor": next_cursor,
                    "server_ts": _tz_now_iso(),
                    "window": window_raw,
                    "window_sec": window_sec,
                    "source": source,
                    "source_error": source_error,
                    "row_processing_errors": row_processing_errors,
                    "row_processing_error_samples": row_processing_error_samples,
                },
                cache_control="no-store",
            )
            return

        if path == "/v1/listings/summary":
            params = parse_qs(parsed.query)
            try:
                new_window_sec = int((params.get("new_window_sec") or ["120"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_new_window_sec"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            _json_response(self, _state().listings_summary_v1(new_window_sec=new_window_sec), cache_control="no-store")
            return

        if path == "/v1/listings/events":
            params = parse_qs(parsed.query)
            try:
                limit = int((params.get("limit") or ["100"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 500:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            cursor = (params.get("cursor") or [None])[0]
            since = (params.get("since") or [None])[0]
            try:
                new_window_sec = int((params.get("new_window_sec") or ["120"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_new_window_sec"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            include_relisted = ((params.get("include_relisted") or ["1"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            _json_response(
                self,
                _state().listings_events_v1(
                    limit=limit,
                    cursor=cursor,
                    since=since,
                    new_window_sec=new_window_sec,
                    include_relisted=include_relisted,
                ),
                cache_control="no-store",
            )
            return

        if path == "/v1/listings/signals":
            params = parse_qs(parsed.query)
            signal_type = (params.get("type") or [None])[0]
            min_score_raw = (params.get("min_score") or [None])[0]
            try:
                min_score = float(min_score_raw) if min_score_raw not in (None, "") else None
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_min_score"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            since = (params.get("since") or [None])[0]
            mode = (params.get("mode") or [None])[0]
            try:
                limit = int((params.get("limit") or ["50"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 500:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            cursor = (params.get("cursor") or [None])[0]
            try:
                new_window_sec = int((params.get("new_window_sec") or ["120"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_new_window_sec"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            include_relisted = ((params.get("include_relisted") or ["1"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            try:
                page = int((params.get("page") or [None])[0]) if (params.get("page") or [None])[0] not in (None, "") else None
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_page"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                page_size = int((params.get("page_size") or [None])[0]) if (params.get("page_size") or [None])[0] not in (None, "") else None
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_page_size"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            sort_by = (params.get("sort_by") or [None])[0]
            sort_dir = (params.get("sort_dir") or [None])[0]
            try:
                _json_response(
                    self,
                    _state().listings_signals_v1(
                        limit=limit,
                        cursor=cursor,
                        since=since,
                        new_window_sec=new_window_sec,
                        include_relisted=include_relisted,
                        signal_type=signal_type,
                        min_score=min_score,
                        mode=mode,
                        page=page,
                        page_size=page_size,
                        sort_by=sort_by,
                        sort_dir=sort_dir,
                    ),
                    cache_control="no-store",
                )
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            return

        if path == "/v1/listings/stream":
            params = parse_qs(parsed.query)
            since = (params.get("since") or [None])[0]
            try:
                limit = int((params.get("limit") or ["200"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 500:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                new_window_sec = int((params.get("new_window_sec") or ["120"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_new_window_sec"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if new_window_sec < 30 or new_window_sec > (7 * 24 * 3600):
                _json_response(self, {"ok": False, "error": "invalid_new_window_sec_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            include_relisted_raw = (params.get("include_relisted") or [None])[0]
            try:
                include_relisted = _parse_query_bool(
                    include_relisted_raw,
                    default=True,
                    field="include_relisted",
                )
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                interval_sec = float((params.get("interval_sec") or ["2.5"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_interval_sec"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if interval_sec < 0.8 or interval_sec > 10.0:
                _json_response(self, {"ok": False, "error": "invalid_interval_sec_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            stream_key = "v1/listings/stream"
            _observe_sse_open(stream_key)

            abrupt_close = False
            try:
                last_seen_ts = since or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                last_snapshot_token = ""
                sent_ids: set[str] = set()
                sent_listing_keys: dict[str, float] = {}
                dedupe_ttl = float(max(60, int(getattr(_state(), "listing_event_dedupe_ttl_sec", 600))))
                deadline = time.time() + 25
                while time.time() < deadline:
                    svc = _state()
                    snapshot_token = _v1_listings_events_stream_snapshot_token(
                        svc,
                        new_window_sec=new_window_sec,
                        include_relisted=include_relisted,
                    )
                    payload = {"items": []}
                    items = []
                    fresh = []
                    max_ts = last_seen_ts
                    fresh = []
                    now_mono = time.monotonic()
                    for key, seen_ts in list(sent_listing_keys.items()):
                        if (now_mono - seen_ts) >= dedupe_ttl:
                            sent_listing_keys.pop(key, None)
                    if snapshot_token != last_snapshot_token:
                        last_snapshot_token = snapshot_token
                        payload = svc.listings_events_v1(
                            limit=limit,
                            cursor=None,
                            since=last_seen_ts,
                            new_window_sec=new_window_sec,
                            include_relisted=include_relisted,
                        )
                        items = payload.get("items") if isinstance(payload, dict) else []
                        for ev in reversed(items if isinstance(items, list) else []):
                            ts = str(ev.get("ts") or "")
                            event_id = f"{ev.get('topic')}|{ev.get('listing_key')}|{ts}"
                            if not ts or event_id in sent_ids:
                                continue
                            topic = str(ev.get("topic") or "")
                            if topic in {"market.listing.new", "listing.new", "listing.price_changed", "market.listing.price_changed"}:
                                listing_key = str(ev.get("listing_key") or "")
                                dedupe_key = f"{topic}|{listing_key}"
                                if listing_key and dedupe_key in sent_listing_keys:
                                    continue
                                if listing_key:
                                    sent_listing_keys[dedupe_key] = now_mono
                            sent_ids.add(event_id)
                            fresh.append(ev)
                            if ts > max_ts:
                                max_ts = ts

                    if len(sent_ids) > 10000:
                        sent_ids.clear()

                    if fresh:
                        for ev in fresh:
                            ev_name = str(ev.get("topic") or "market.listing.new")
                            self.wfile.write(f"event: {ev_name}\n".encode("utf-8"))
                            self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8"))
                        health_payload = {
                            "source": payload.get("source"),
                            "source_error": payload.get("source_error"),
                            "count": len(fresh),
                            "ts": max_ts,
                        }
                        self.wfile.write(b"event: listing.feed.health\n")
                        self.wfile.write(f"data: {json.dumps(health_payload, ensure_ascii=False)}\n\n".encode("utf-8"))
                        last_seen_ts = max_ts
                    else:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    time.sleep(interval_sec)
            except (BrokenPipeError, ConnectionResetError, OSError):
                abrupt_close = True
            finally:
                _observe_sse_close(stream_key, abrupt=abrupt_close)
            return

        if path == "/api/listing/source-status" or path == "/v1/listings/source-status":
            _json_response(self, _state().listing_source_status_v1(allow_remote=False), cache_control="no-store")
            return

        if path.startswith("/v1/signals/") and path.count("/") == 3:
            signal_id = unquote(path.split("/")[-1])
            params = parse_qs(parsed.query)
            mode = (params.get("mode") or [None])[0]
            data = _state().signal_by_id_v1(signal_id, mode=mode)
            if not data:
                _safe_send_error(self, HTTPStatus.NOT_FOUND)
                return
            _json_response(self, data, cache_control="no-store")
            return

        if path == "/v1/metrics/definitions":
            _json_response(self, _state().metrics_definitions_v1(), cache_control="no-store")
            return

        if path == "/v1/metrics":
            params = parse_qs(parsed.query)
            metric = (params.get("metric") or [""])[0]
            scope = (params.get("scope") or [None])[0]
            market = ((params.get("market") or ["0"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            collection_id = (params.get("collection_id") or [None])[0]
            variant_id = (params.get("variant_id") or [None])[0]
            from_ts = (params.get("from") or [None])[0]
            to_ts = (params.get("to") or [None])[0]
            interval = (params.get("interval") or [None])[0]
            mode = (params.get("mode") or [None])[0]
            try:
                limit = int((params.get("limit") or ["500"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 5000:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                payload = _state().metrics_v1(
                    metric=metric,
                    scope=scope,
                    market=market,
                    collection_id=collection_id,
                    variant_id=variant_id,
                    from_ts=from_ts,
                    to_ts=to_ts,
                    interval=interval,
                    limit=limit,
                    mode=mode,
                )
                _json_response(self, payload, cache_control="no-store")
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            return

        if path == "/v1/favorites":
            user = _require_auth(self)
            if not user:
                return
            key = _user_storage_key(user)
            _json_response(self, {"items": _state().favorites_list(key)}, cache_control="no-store")
            return

        if path == "/v1/alerts":
            user = _require_auth(self)
            if not user:
                return
            items = []
            for row in _state().alerts_list():
                rid = str(row.get("id") or "")
                rule_json = row.get("rule_json") or {}
                enabled = bool(row.get("enabled", rule_json.get("enabled", True)))
                created_at = (
                    row.get("created_at")
                    or rule_json.get("created_at")
                    or row.get("last_fired_at")
                    or _state().state.get("updated_at")
                    or datetime.now(timezone.utc).isoformat()
                )
                items.append(
                    {
                        "rule_id": rid,
                        "name": str(rule_json.get("name") or row.get("name") or rid or "alert"),
                        "rule_json": rule_json,
                        "enabled": enabled,
                        "created_at": created_at,
                    }
                )
            _json_response(self, {"items": items}, cache_control="no-store")
            return

        if path == "/v1/stream" or path == "/v1/stream/events":
            params = parse_qs(parsed.query)
            types_csv = str((params.get("types") or [""])[0] or "").strip()
            if types_csv:
                types = {x.strip() for x in types_csv.split(",") if x.strip()}
            else:
                types = set()
            variant_id_filter = (params.get("variant_id") or [None])[0]
            collection_id_filter = (params.get("collection_id") or [None])[0]
            allowed_types = {"signal.created", "metric.updated", "listing.event", "market.status", "provider.health", "variant.updated", "collection.updated"}
            unknown_types = sorted([t for t in types if t not in allowed_types])
            if unknown_types:
                _json_response(
                    self,
                    {"ok": False, "error": "unsupported_stream_type", "unsupported": unknown_types},
                    status=HTTPStatus.BAD_REQUEST,
                    cache_control="no-store",
                )
                return
            mode = (params.get("mode") or [None])[0]
            try:
                heartbeat_ms = int((params.get("heartbeat") or ["15000"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_heartbeat"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if heartbeat_ms < 5000 or heartbeat_ms > 60000:
                _json_response(self, {"ok": False, "error": "invalid_heartbeat_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            sleep_sec = max(1.0, heartbeat_ms / 1000.0)

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            stream_key = "v1/stream"
            _observe_sse_open(stream_key)
            abrupt_close = False
            try:
                last_snapshot_token = ""
                deadline = time.time() + 25
                while time.time() < deadline:
                    svc = _state()
                    snapshot_token = _v1_stream_snapshot_token(svc)
                    try:
                        if snapshot_token != last_snapshot_token:
                            last_snapshot_token = snapshot_token
                            for ev in svc.stream_events_v1(
                                types=types,
                                mode=mode,
                                variant_id=variant_id_filter,
                                collection_id=collection_id_filter,
                            ):
                                ev_name = str(ev.get("type") or "provider.health")
                                self.wfile.write(f"event: {ev_name}\n".encode("utf-8"))
                                self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8"))
                        else:
                            self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        abrupt_close = True
                        break
                    time.sleep(sleep_sec)
            finally:
                _observe_sse_close(stream_key, abrupt=abrupt_close)
            return

        if path == "/v1/stream/signals":
            params = parse_qs(parsed.query)
            mode = (params.get("mode") or [None])[0]
            try:
                heartbeat_ms = int((params.get("heartbeat") or ["15000"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_heartbeat"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if heartbeat_ms < 5000 or heartbeat_ms > 60000:
                _json_response(self, {"ok": False, "error": "invalid_heartbeat_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                limit = int((params.get("limit") or ["100"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 500:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                dedupe_ttl_sec = int((params.get("dedupe_ttl_sec") or ["600"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_dedupe_ttl_sec"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if dedupe_ttl_sec < 60 or dedupe_ttl_sec > 3600:
                _json_response(self, {"ok": False, "error": "invalid_dedupe_ttl_sec_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            sleep_sec = max(1.0, heartbeat_ms / 1000.0)
            sent_signal_ids: dict[str, float] = {}

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            stream_key = "v1/stream/signals"
            _observe_sse_open(stream_key)
            abrupt_close = False
            try:
                last_snapshot_token = ""
                deadline = time.time() + 25
                while time.time() < deadline:
                    now = time.time()
                    try:
                        sent_signal_ids = {k: v for k, v in sent_signal_ids.items() if (now - v) <= float(dedupe_ttl_sec)}
                        svc = _state()
                        snapshot_token = _v1_signals_stream_snapshot_token(svc, mode=mode)
                        emitted = 0
                        if snapshot_token != last_snapshot_token:
                            last_snapshot_token = snapshot_token
                            payload = svc.signals_v1(limit=limit, mode=mode)
                            rows = payload.get("items") if isinstance(payload.get("items"), list) else []
                            for row in reversed(rows):
                                sid = str((row or {}).get("signal_id") or "")
                                if not sid:
                                    continue
                                if sid in sent_signal_ids:
                                    continue
                                sent_signal_ids[sid] = now
                                env = svc.build_signal_created_event_v2(row, ts=_tz_now_iso())
                                self.wfile.write(b"event: signal.created\n")
                                self.wfile.write(f"data: {json.dumps(env, ensure_ascii=False)}\n\n".encode("utf-8"))
                                emitted += 1
                        if emitted == 0:
                            self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        abrupt_close = True
                        break
                    time.sleep(sleep_sec)
            finally:
                _observe_sse_close(stream_key, abrupt=abrupt_close)
            return

        if path == "/v1/stream/screeners":
            params = parse_qs(parsed.query)
            try:
                heartbeat_ms = int((params.get("heartbeat") or ["15000"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_heartbeat"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if heartbeat_ms < 5000 or heartbeat_ms > 60000:
                _json_response(self, {"ok": False, "error": "invalid_heartbeat_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                limit = int((params.get("limit") or ["100"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 500:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                dedupe_ttl_sec = int((params.get("dedupe_ttl_sec") or ["600"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_dedupe_ttl_sec"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if dedupe_ttl_sec < 60 or dedupe_ttl_sec > 3600:
                _json_response(self, {"ok": False, "error": "invalid_dedupe_ttl_sec_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            sleep_sec = max(1.0, heartbeat_ms / 1000.0)
            sent_event_ids: dict[str, float] = {}
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            stream_key = "v1/stream/screeners"
            _observe_sse_open(stream_key)
            abrupt_close = False
            try:
                deadline = time.time() + 25
                while time.time() < deadline:
                    now = time.time()
                    sent_event_ids = {k: v for k, v in sent_event_ids.items() if (now - v) <= float(dedupe_ttl_sec)}
                    try:
                        svc = _state()
                        emitted = 0
                        payload = svc.screeners_stream_events_v1(limit=limit)
                        events = payload.get("items") if isinstance(payload.get("items"), list) else []
                        for item in events:
                            if not isinstance(item, dict):
                                continue
                            event_id = str(item.get("event_id") or "").strip()
                            row = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                            if not event_id:
                                event_id = f"{row.get('variant_id')}|{row.get('screener_type')}|{row.get('ts')}"
                            if event_id in sent_event_ids:
                                continue
                            sent_event_ids[event_id] = now
                            env = svc.build_screener_row_event_v1(row, ts=str(item.get("ts") or _tz_now_iso()))
                            self.wfile.write(b"event: screener.row\n")
                            self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
                            self.wfile.write(f"data: {json.dumps(env, ensure_ascii=False)}\n\n".encode("utf-8"))
                            emitted += 1
                        if emitted == 0:
                            self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        abrupt_close = True
                        break
                    time.sleep(sleep_sec)
            finally:
                _observe_sse_close(stream_key, abrupt=abrupt_close)
            return

        if path == "/v1/stream/catalog":
            params = parse_qs(parsed.query)
            try:
                heartbeat_ms = int((params.get("heartbeat") or ["15000"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_heartbeat"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if heartbeat_ms < 5000 or heartbeat_ms > 60000:
                _json_response(self, {"ok": False, "error": "invalid_heartbeat_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                limit = int((params.get("limit") or ["200"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_limit"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if limit < 1 or limit > 1000:
                _json_response(self, {"ok": False, "error": "invalid_limit_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                dedupe_ttl_sec = int((params.get("dedupe_ttl_sec") or ["600"])[0])
            except Exception:
                _json_response(self, {"ok": False, "error": "invalid_dedupe_ttl_sec"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            if dedupe_ttl_sec < 60 or dedupe_ttl_sec > 3600:
                _json_response(self, {"ok": False, "error": "invalid_dedupe_ttl_sec_range"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            sleep_sec = max(1.0, heartbeat_ms / 1000.0)
            sent_event_ids: dict[str, float] = {}
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            stream_key = "v1/stream/catalog"
            _observe_sse_open(stream_key)
            abrupt_close = False
            try:
                deadline = time.time() + 25
                while time.time() < deadline:
                    now = time.time()
                    sent_event_ids = {k: v for k, v in sent_event_ids.items() if (now - v) <= float(dedupe_ttl_sec)}
                    try:
                        svc = _state()
                        emitted = 0
                        payload = svc.catalog_stream_events_v1(limit=limit)
                        events = payload.get("items") if isinstance(payload.get("items"), list) else []
                        for item in events:
                            if not isinstance(item, dict):
                                continue
                            event_id = str(item.get("event_id") or "").strip()
                            row = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                            if not event_id:
                                event_id = str(row.get("variant_id") or "")
                            if not event_id or event_id in sent_event_ids:
                                continue
                            sent_event_ids[event_id] = now
                            env = svc.build_catalog_row_event_v1(row, ts=str(item.get("ts") or _tz_now_iso()))
                            self.wfile.write(b"event: catalog.row\n")
                            self.wfile.write(f"id: {event_id}\n".encode("utf-8"))
                            self.wfile.write(f"data: {json.dumps(env, ensure_ascii=False)}\n\n".encode("utf-8"))
                            emitted += 1
                        if emitted == 0:
                            self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        abrupt_close = True
                        break
                    time.sleep(sleep_sec)
            finally:
                _observe_sse_close(stream_key, abrupt=abrupt_close)
            return

        if path in {"/v1/stream/trades", "/v1/stream/pnl"}:
            user, wallet = _require_trading_user(self)
            if user is None:
                return
            params = parse_qs(parsed.query)
            wallet_address = str((params.get("wallet_address") or [""])[0] or "").strip()
            ok_wallet, reason = _validate_wallet_match(wallet, wallet_address)
            if not ok_wallet:
                _json_response(self, {"code": reason, "message": reason}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            heartbeat_ms = int((params.get("heartbeat") or ["15000"])[0]) if str((params.get("heartbeat") or ["15000"])[0]).isdigit() else 15000
            limit = int((params.get("limit") or ["100"])[0]) if str((params.get("limit") or ["100"])[0]).isdigit() else 100
            sleep_sec = max(1.0, heartbeat_ms / 1000.0)
            stream_name = "pnl" if path.endswith("/pnl") else "trades"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            abrupt_close = False
            try:
                last_token = ""
                deadline = time.time() + 25
                while time.time() < deadline:
                    payload = _state().trades_stream_events_v1(wallet_address, stream=stream_name, limit=limit)
                    token = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
                    try:
                        if token != last_token:
                            last_token = token
                            for ev in payload.get("items") if isinstance(payload.get("items"), list) else []:
                                name = str((ev or {}).get("event") or "trades.keepalive")
                                self.wfile.write(f"event: {name}\n".encode("utf-8"))
                                self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8"))
                        else:
                            self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        abrupt_close = True
                        break
                    time.sleep(sleep_sec)
            finally:
                _observe_sse_close(path, abrupt=abrupt_close)
            return

        if path.startswith("/api/") and not path.startswith("/api/auth/"):
            if not _require_auth(self):
                return

        if path == "/api/admin/runtime/http-metrics":
            if AUTH_REQUIRED and (not _require_admin(self)):
                return
            _json_response(self, _http_metrics_snapshot(), cache_control="no-store")
            return

        if path == "/api/admin/listings/errors":
            if AUTH_REQUIRED and (not _require_admin(self)):
                return
            params = parse_qs(parsed.query)
            try:
                limit = int((params.get("limit") or ["50"])[0])
            except Exception:
                limit = 50
            limit = max(1, min(limit, 500))
            block = (params.get("block") or [None])[0]
            _json_response(
                self,
                _state().listing_runtime_errors_v1(limit=limit, block=block),
                cache_control="no-store",
            )
            return

        if path == "/api/admin/signal-engine/config":
            if not _require_admin(self):
                return
            defaults, overrides, effective = _signal_engine_effective_config()
            _json_response(
                self,
                {
                    "ok": True,
                    "defaults": defaults,
                    "overrides": overrides,
                    "effective": effective,
                },
                cache_control="no-store",
            )
            return

        if path == "/api/admin/signal-engine/signals":
            if not _require_admin(self):
                return
            params = parse_qs(parsed.query)
            try:
                limit = int((params.get("limit") or ["100"])[0])
            except Exception:
                limit = 100
            limit = max(1, min(limit, 500))
            _, _, effective = _signal_engine_effective_config()
            _json_response(self, _signal_engine_signal_preview(limit=limit, cfg=effective), cache_control="no-store")
            return

        if path == "/api/admin/telegram-delivery/config":
            if not _require_authenticated_telegram_user(self):
                return
            _json_response(self, _state().telegram_delivery_config_v1(), cache_control="no-store")
            return

        if path == "/api/admin/telegram-delivery/status":
            if not _require_authenticated_telegram_user(self):
                return
            _json_response(self, _state().telegram_delivery_status_v1(), cache_control="no-store")
            return

        if path == "/api/admin/telegram-delivery/journal":
            if not _require_authenticated_telegram_user(self):
                return
            params = parse_qs(parsed.query)
            try:
                limit = int((params.get("limit") or ["50"])[0])
            except Exception:
                limit = 50
            _json_response(self, _state().telegram_delivery_journal_v1(limit=limit), cache_control="no-store")
            return

        if path == "/api/admin/telegram-delivery/recommendation":
            if not _require_authenticated_telegram_user(self):
                return
            _json_response(self, _state().telegram_delivery_gate_recommendation_v1(limit=300), cache_control="no-store")
            return

        if path == "/api/admin/formula-gates/status":
            if AUTH_REQUIRED and (not _require_admin(self)):
                return
            if not TZ_GATES_STATUS_FILE.exists():
                try:
                    payload = _build_tz_gates_payload_runtime()
                    TZ_GATES_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
                    TZ_GATES_STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    _json_response(self, payload, cache_control="no-store")
                except Exception as exc:
                    payload = _normalize_tz_gates_payload(
                        payload=None,
                        report_source="runtime_failed",
                        error=f"tz_gates_status_not_found:{exc.__class__.__name__}",
                    )
                    _json_response(self, payload, cache_control="no-store")
                return
            try:
                payload = json.loads(TZ_GATES_STATUS_FILE.read_text(encoding="utf-8"))
            except Exception:
                try:
                    payload = _build_tz_gates_payload_runtime()
                    TZ_GATES_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
                    TZ_GATES_STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    _json_response(self, payload, cache_control="no-store")
                except Exception as exc:
                    payload = _normalize_tz_gates_payload(
                        payload=None,
                        report_source="runtime_failed",
                        error=f"tz_gates_status_invalid:{exc.__class__.__name__}",
                    )
                    _json_response(self, payload, cache_control="no-store")
                return
            _json_response(self, _normalize_tz_gates_payload(payload, report_source="file"), cache_control="no-store")
            return

        if path == "/api/rates/stars":
            _json_response(self, _state().stars_rate())
            return

        if path == "/api/ai/status":
            params = parse_qs(parsed.query)
            probe = ((params.get("probe") or ["0"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            _json_response(self, _state().ai_status(probe=probe))
            return

        if path == "/api/bot/status":
            _json_response(self, {"ok": True, "data": _BOT_STATUS}, cache_control="no-store")
            return

        if path == "/api/market/overview":
            _json_response(self, _state().market_overview())
            return

        if path == "/api/admin/refresh/status":
            _json_response(self, _refresh_status_snapshot(), cache_control="no-store")
            return

        if path == "/api/bases":
            svc = _state()
            _json_response(self, {"items": svc.list_bases(), "stars_rate": svc.stars_rate()})
            return

        if path.startswith("/api/bases/") and path.count("/") == 3:
            base_id = unquote(path.split("/")[-1])
            base = _state().get_base(base_id)
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
            svc = _state()
            data = svc.list_dimensions(base_id, dim_type, period)
            data["stars_rate"] = svc.stars_rate()
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
            svc = _state()
            data = svc.list_variants(
                base_id=base_id,
                filters=filters,
                sort=sort,
                page=page,
                page_size=page_size,
                include_ai=include_ai,
            )
            data["stars_rate"] = svc.stars_rate()
            _json_response(self, data)
            return

        if path.startswith("/api/variants/") and path.count("/") == 3:
            variant_id = unquote(path.split("/")[-1])
            data = _state().get_variant(variant_id)
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
            data = _state().list_variant_listings(variant_id)
            _json_response(self, data)
            return

        if path.startswith("/api/variants/") and path.endswith("/timeseries"):
            variant_id = unquote(path.split("/")[3])
            params = parse_qs(parsed.query)
            metric = (params.get("metric") or ["floor"])[0]
            period = (params.get("period") or ["24h"])[0]
            data = _state().list_variant_timeseries(variant_id, metric, period)
            _json_response(self, data)
            return

        if path.startswith("/api/screeners/"):
            screener = path.split("/")[-1]
            params = parse_qs(parsed.query)
            entity = (params.get("entity") or ["variant"])[0]
            period = (params.get("period") or ["24h"])[0]
            metric_type = (params.get("type") or ["price"])[0]
            include_ai = ((params.get("ai") or ["0"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            data = _state().screeners(screener, entity, period, metric_type, include_ai=include_ai)
            _json_response(self, data)
            return

        if path == "/api/recommendations":
            params = parse_qs(parsed.query)
            scope = (params.get("scope") or ["all"])[0]
            entity = (params.get("entity") or ["variant"])[0]
            include_ai = ((params.get("ai") or ["0"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            data = _state().recommendations(scope, entity, include_ai=include_ai)
            _json_response(self, data)
            return

        if path == "/api/signals/latest":
            params = parse_qs(parsed.query)
            action = (params.get("filter") or ["all"])[0]
            limit = int((params.get("limit") or ["1000"])[0])
            data = _state().signals_latest(action=action, limit=limit)
            _json_response(self, data, cache_control="no-store")
            return

        if path == "/api/alerts":
            _json_response(self, {"items": _state().alerts_list()})
            return

        _safe_send_error(self, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/v1/favorites":
            user = _require_auth(self)
            if not user:
                return
            payload = _read_json_body(self)
            variant_id = str(payload.get("variant_id") or "").strip()
            if not variant_id:
                _json_response(self, {"ok": False, "error": "variant_id_required"}, status=HTTPStatus.BAD_REQUEST)
                return
            note = payload.get("note")
            _json_response(self, _state().favorite_upsert(_user_storage_key(user), variant_id, note))
            return

        if parsed.path == "/v1/alerts":
            user = _require_auth(self)
            if not user:
                return
            payload = _read_json_body(self)
            rule_id = payload.get("rule_id")
            name = str(payload.get("name") or "").strip() or "alert"
            if not str(payload.get("name") or "").strip():
                _json_response(self, {"ok": False, "error": "name_required"}, status=HTTPStatus.BAD_REQUEST)
                return
            if not isinstance(payload.get("rule_json"), dict):
                _json_response(self, {"ok": False, "error": "rule_json_required"}, status=HTTPStatus.BAD_REQUEST)
                return
            rule_json = payload.get("rule_json") or {}
            enabled = bool(payload.get("enabled", True))
            rule_payload = {"id": rule_id, "name": name, "enabled": enabled, **rule_json}
            if rule_id:
                updated = _state().alerts_update(str(rule_id), rule_payload)
                if updated:
                    _json_response(self, {"ok": True})
                    return
            _state().alerts_create(rule_payload)
            _json_response(self, {"ok": True})
            return

        if parsed.path == "/v1/alerts/test":
            user = _require_auth(self)
            if not user:
                return
            payload = _read_json_body(self)
            rule_id = str(payload.get("rule_id") or "").strip()
            if not rule_id:
                _json_response(self, {"ok": False, "error": "rule_id_required"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                if signal_bot.BOT_TOKEN and signal_bot.CHAT_ID:
                    signal_bot.send_message(f"Тестовый алерт: rule_id={rule_id}")
            except Exception:
                pass
            _json_response(self, {"ok": True})
            return

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
            _json_response(self, _start_manual_refresh(), cache_control="no-store")
            return
        if parsed.path == "/api/admin/runtime/http-metrics/reset":
            if AUTH_REQUIRED and (not _require_admin(self)):
                return
            _json_response(self, _http_metrics_reset(), cache_control="no-store")
            return
        if parsed.path == "/api/admin/signal-engine/config/reset":
            if not _require_admin(self):
                return
            try:
                if SIGNAL_ENGINE_OVERRIDES_FILE.exists():
                    SIGNAL_ENGINE_OVERRIDES_FILE.unlink()
            except Exception:
                pass
            defaults, overrides, effective = _signal_engine_effective_config()
            _json_response(
                self,
                {"ok": True, "defaults": defaults, "overrides": overrides, "effective": effective},
                cache_control="no-store",
            )
            return
        if parsed.path == "/api/admin/telegram-delivery/config/reset":
            if not _require_authenticated_telegram_user(self):
                return
            _json_response(self, _state().telegram_delivery_reset_config_v1(), cache_control="no-store")
            return
        if parsed.path == "/api/admin/telegram-delivery/test":
            if not _require_authenticated_telegram_user(self):
                return
            payload = _read_json_body(self)
            kind = str(payload.get("kind") or "gift_signal") if isinstance(payload, dict) else "gift_signal"
            _json_response(self, _state().telegram_delivery_test_v1(kind=kind), cache_control="no-store")
            return
        if parsed.path == "/api/admin/telegram-delivery/recommendation/apply":
            if not _require_authenticated_telegram_user(self):
                return
            _json_response(self, _state().telegram_delivery_apply_recommendation_v1(), cache_control="no-store")
            return
        if parsed.path == "/v1/trades/fast/confirm":
            user, wallet = _require_trading_user(self)
            if user is None:
                return
            payload = _read_json_body(self)
            ok_wallet, reason = _validate_wallet_match(wallet, payload.get("wallet_address"))
            if not ok_wallet:
                _json_response(self, {"code": reason, "message": reason}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                item = _state().trades_fast_confirm_v1(payload)
                _json_response(self, item, cache_control="no-store")
            except TimeoutError:
                _json_response(self, {"code": "quote_expired", "message": "quote expired"}, status=HTTPStatus.GONE, cache_control="no-store")
            except RuntimeError as exc:
                _json_response(self, {"code": "conflict", "message": str(exc)}, status=HTTPStatus.CONFLICT, cache_control="no-store")
            except Exception as exc:
                _json_response(self, {"code": "bad_request", "message": f"fast_confirm_failed:{exc.__class__.__name__}"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            return
        if parsed.path == "/v1/trades/intents":
            user, wallet = _require_trading_user(self)
            if user is None:
                return
            payload = _read_json_body(self)
            ok_wallet, reason = _validate_wallet_match(wallet, payload.get("wallet_address"))
            if not ok_wallet:
                _json_response(self, {"code": reason, "message": reason}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                _json_response(self, _state().trades_create_intent_v1(payload), cache_control="no-store")
            except RuntimeError as exc:
                _json_response(self, {"code": "conflict", "message": str(exc)}, status=HTTPStatus.CONFLICT, cache_control="no-store")
            except Exception as exc:
                _json_response(self, {"code": "bad_request", "message": f"create_intent_failed:{exc.__class__.__name__}"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            return
        if parsed.path.endswith("/confirm_signature") and parsed.path.startswith("/v1/trades/intents/"):
            user, wallet = _require_trading_user(self)
            if user is None:
                return
            intent_id = parsed.path.split("/")[-2]
            payload = _read_json_body(self)
            if payload.get("wallet_address"):
                ok_wallet, reason = _validate_wallet_match(wallet, payload.get("wallet_address"))
                if not ok_wallet:
                    _json_response(self, {"code": reason, "message": reason}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                    return
            try:
                _json_response(self, _state().trades_confirm_signature_v1(intent_id, payload), cache_control="no-store")
            except KeyError:
                _json_response(self, {"code": "not_found", "message": "intent_not_found"}, status=HTTPStatus.NOT_FOUND, cache_control="no-store")
            except Exception as exc:
                _json_response(self, {"code": "bad_request", "message": f"confirm_signature_failed:{exc.__class__.__name__}"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            return
        if parsed.path.endswith("/retry_list") and parsed.path.startswith("/v1/trades/intents/"):
            user, _wallet = _require_trading_user(self)
            if user is None:
                return
            parent_intent_id = parsed.path.split("/")[-2]
            try:
                _json_response(self, _state().trades_retry_chain_list_v1(parent_intent_id), cache_control="no-store")
            except KeyError:
                _json_response(self, {"code": "not_found", "message": "parent_intent_not_found"}, status=HTTPStatus.NOT_FOUND, cache_control="no-store")
            except Exception as exc:
                _json_response(self, {"code": "bad_request", "message": f"retry_list_failed:{exc.__class__.__name__}"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            return
        if parsed.path == "/v1/trades/autosell/rules":
            user, wallet = _require_trading_user(self)
            if user is None:
                return
            payload = _read_json_body(self)
            ok_wallet, reason = _validate_wallet_match(wallet, payload.get("wallet_address"))
            if not ok_wallet:
                _json_response(self, {"code": reason, "message": reason}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
                return
            try:
                _json_response(self, _state().trades_upsert_autosell_rule_v1(payload), cache_control="no-store")
            except Exception as exc:
                _json_response(self, {"code": "bad_request", "message": f"autosell_rule_failed:{exc.__class__.__name__}"}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            return
        if parsed.path == "/api/alerts":
            rule = _read_json_body(self)
            _json_response(self, _state().alerts_create(rule), status=201)
            return
        _safe_send_error(self, HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") and not parsed.path.startswith("/api/auth/"):
            if not _require_auth(self):
                return
        if parsed.path == "/api/admin/signal-engine/config":
            if not _require_admin(self):
                return
            payload = _read_json_body(self)
            overrides = payload.get("overrides") if isinstance(payload.get("overrides"), dict) else payload
            if not isinstance(overrides, dict):
                _json_response(
                    self,
                    {"ok": False, "error": "invalid_payload", "message": "Ожидался JSON-объект overrides"},
                    status=HTTPStatus.BAD_REQUEST,
                    cache_control="no-store",
                )
                return
            _save_signal_engine_overrides(overrides)
            defaults, saved_overrides, effective = _signal_engine_effective_config()
            _json_response(
                self,
                {"ok": True, "defaults": defaults, "overrides": saved_overrides, "effective": effective},
                cache_control="no-store",
            )
            return
        if parsed.path == "/api/admin/telegram-delivery/config":
            if not _require_authenticated_telegram_user(self):
                return
            payload = _read_json_body(self)
            overrides = payload.get("overrides") if isinstance(payload, dict) and isinstance(payload.get("overrides"), dict) else payload
            if not isinstance(overrides, dict):
                _json_response(
                    self,
                    {"ok": False, "error": "invalid_payload", "message": "Ожидался JSON-объект overrides"},
                    status=HTTPStatus.BAD_REQUEST,
                    cache_control="no-store",
                )
                return
            _json_response(self, _state().telegram_delivery_update_config_v1(overrides), cache_control="no-store")
            return
        if parsed.path.startswith("/api/alerts/"):
            alert_id = parsed.path.split("/")[-1]
            rule = _read_json_body(self)
            updated = _state().alerts_update(alert_id, rule)
            if not updated:
                _safe_send_error(self, HTTPStatus.NOT_FOUND)
                return
            _json_response(self, updated)
            return
        _safe_send_error(self, HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/v1/favorites":
            user = _require_auth(self)
            if not user:
                return
            params = parse_qs(parsed.query)
            variant_id = str((params.get("variant_id") or [""])[0]).strip()
            if not variant_id:
                _json_response(self, {"ok": False, "error": "variant_id_required"}, status=HTTPStatus.BAD_REQUEST)
                return
            _json_response(self, _state().favorite_delete(_user_storage_key(user), variant_id))
            return

        if parsed.path.startswith("/api/") and not parsed.path.startswith("/api/auth/"):
            if not _require_auth(self):
                return
        if parsed.path.startswith("/api/alerts/"):
            alert_id = parsed.path.split("/")[-1]
            ok = _state().alerts_delete(alert_id)
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
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer((host, port), RequestHandler)
    # Warm-up analytics state in background: healthcheck becomes fast while data stack initializes.
    threading.Thread(target=_state, daemon=True, name="state-warmup").start()
    _start_signal_bot_loop(port)
    print(f"Server started on http://{host}:{port}")
    server.serve_forever()


def _start_signal_bot_loop(port: int) -> None:
    if not signal_bot.BOT_TOKEN or not signal_bot.CHAT_ID:
        _BOT_STATUS["enabled"] = False
        _BOT_STATUS["last_error"] = "TG_BOT_TOKEN/TG_CHAT_ID not configured"
        return

    signal_bot.API_BASE_URL = BOT_API_BASE_URL or f"http://127.0.0.1:{port}"
    signal_bot.API_AUTH_TOKEN = BOT_API_AUTH_TOKEN
    signal_bot.set_recent_signal_fetcher(lambda limit=20: _state().telegram_delivery_journal_v1(limit=limit))
    signal_bot.set_notifier(_state().telegram_notifier)
    _BOT_STATUS["enabled"] = True

    def _loop() -> None:
        cache = signal_bot._load_cache()
        _BOT_STATUS["running"] = True
        last_run_ts = 0
        last_seen_data_ts = None
        while True:
            now_ts = int(time.time())
            svc = _state()
            data_ts = svc.state.get("updated_at")
            should_run = False
            # Run immediately when new market snapshot is ingested.
            if data_ts and data_ts != last_seen_data_ts:
                should_run = True
                last_seen_data_ts = data_ts
            # Fallback periodic run (commands, retries, stale windows).
            if (now_ts - last_run_ts) >= BOT_INTERVAL_SEC:
                should_run = True
            if not should_run:
                time.sleep(5)
                continue
            _BOT_STATUS["last_run_at"] = now_ts
            try:
                if BOT_AUTORUN:
                    signal_bot.cycle(cache)
                else:
                    signal_bot.command_cycle(cache)
                signal_bot._save_cache(cache)
                _BOT_STATUS["last_ok_at"] = int(time.time())
                _BOT_STATUS["last_error"] = ""
                last_run_ts = int(time.time())
            except Exception as e:  # noqa: BLE001
                _BOT_STATUS["last_error"] = str(e)
                last_run_ts = int(time.time())
            time.sleep(2)

    threading.Thread(target=_loop, daemon=True, name="signal-bot-loop").start()


if __name__ == "__main__":
    run()

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
BOT_AUTORUN = os.getenv("BOT_AUTORUN", "true").strip().lower() in {"1", "true", "yes", "on"}
BOT_INTERVAL_SEC = max(15, int(os.getenv("BOT_POLL_INTERVAL", "30")))
BOT_API_BASE_URL = os.getenv("BOT_API_BASE_URL", "").strip()
BOT_API_AUTH_TOKEN = os.getenv("BOT_API_AUTH_TOKEN", "").strip() or API_AUTH_TOKEN
BRIDGE_API_TOKEN = os.getenv("BRIDGE_API_TOKEN", "").strip() or os.getenv("TELEGRAM_GIFTS_API_TOKEN", "").strip()
BRIDGE_API_PATH = (os.getenv("BRIDGE_API_PATH", "/bridge/gifts/verified").strip() or "/bridge/gifts/verified")
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
    return _normalize_tz_gates_payload(payload, report_source="runtime")


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
    return {
        "ok": True,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total": len(out),
        "items": out,
    }

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

    def handle(self) -> None:
        try:
            super().handle()
        except BaseException as exc:
            if self._is_benign_disconnect(exc):
                return
            raise

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
            _serve_file(self, path.replace("/assets/", ""))
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

        if path == "/v1/signals":
            params = parse_qs(parsed.query)
            signal_type = (params.get("type") or [None])[0]
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
                data = _state().signals_v1(signal_type=signal_type, min_score=min_score, since=since, limit=limit, cursor=cursor, mode=mode)
                _json_response(self, data, cache_control="no-store")
            except ValueError as exc:
                _json_response(self, {"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST, cache_control="no-store")
            return

        if path == "/v1/listings":
            params = parse_qs(parsed.query)
            try:
                limit = int((params.get("limit") or ["100"])[0])
            except Exception:
                limit = 100
            cursor = (params.get("cursor") or [None])[0]
            only_new = ((params.get("only_new") or ["0"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            try:
                new_window_sec = int((params.get("new_window_sec") or ["120"])[0])
            except Exception:
                new_window_sec = 120
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

        if path == "/v1/listings/summary":
            params = parse_qs(parsed.query)
            try:
                new_window_sec = int((params.get("new_window_sec") or ["120"])[0])
            except Exception:
                new_window_sec = 120
            _json_response(self, _state().listings_summary_v1(new_window_sec=new_window_sec), cache_control="no-store")
            return

        if path == "/v1/listings/events":
            params = parse_qs(parsed.query)
            try:
                limit = int((params.get("limit") or ["100"])[0])
            except Exception:
                limit = 100
            cursor = (params.get("cursor") or [None])[0]
            since = (params.get("since") or [None])[0]
            try:
                new_window_sec = int((params.get("new_window_sec") or ["120"])[0])
            except Exception:
                new_window_sec = 120
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
                min_score = None
            since = (params.get("since") or [None])[0]
            mode = (params.get("mode") or [None])[0]
            try:
                limit = int((params.get("limit") or ["50"])[0])
            except Exception:
                limit = 50
            cursor = (params.get("cursor") or [None])[0]
            try:
                new_window_sec = int((params.get("new_window_sec") or ["120"])[0])
            except Exception:
                new_window_sec = 120
            include_relisted = ((params.get("include_relisted") or ["1"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            try:
                page = int((params.get("page") or [None])[0]) if (params.get("page") or [None])[0] not in (None, "") else None
            except Exception:
                page = None
            try:
                page_size = int((params.get("page_size") or [None])[0]) if (params.get("page_size") or [None])[0] not in (None, "") else None
            except Exception:
                page_size = None
            sort_by = (params.get("sort_by") or [None])[0]
            sort_dir = (params.get("sort_dir") or [None])[0]
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
            return

        if path == "/v1/listings/stream":
            params = parse_qs(parsed.query)
            since = (params.get("since") or [None])[0]
            try:
                limit = int((params.get("limit") or ["200"])[0])
            except Exception:
                limit = 200
            try:
                new_window_sec = int((params.get("new_window_sec") or ["120"])[0])
            except Exception:
                new_window_sec = 120
            include_relisted = ((params.get("include_relisted") or ["1"])[0]).strip().lower() in {"1", "true", "yes", "on"}
            try:
                interval_sec = float((params.get("interval_sec") or ["2.5"])[0])
            except Exception:
                interval_sec = 2.5
            interval_sec = max(0.8, min(interval_sec, 10.0))

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            last_seen_ts = since or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            sent_ids: set[str] = set()
            deadline = time.time() + 25
            while time.time() < deadline:
                payload = _state().listings_events_v1(
                    limit=limit,
                    cursor=None,
                    since=last_seen_ts,
                    new_window_sec=new_window_sec,
                    include_relisted=include_relisted,
                )
                items = payload.get("items") if isinstance(payload, dict) else []
                fresh = []
                max_ts = last_seen_ts
                for ev in reversed(items if isinstance(items, list) else []):
                    ts = str(ev.get("ts") or "")
                    event_id = f"{ev.get('topic')}|{ev.get('listing_key')}|{ts}"
                    if not ts or event_id in sent_ids:
                        continue
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
            return

        if path == "/api/listing/source-status":
            _json_response(self, _state().listing_source_status_v1(), cache_control="no-store")
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

        if path == "/v1/stream":
            params = parse_qs(parsed.query)
            types_csv = str((params.get("types") or [""])[0] or "").strip()
            if types_csv:
                types = {x.strip() for x in types_csv.split(",") if x.strip()}
            else:
                types = set()
            allowed_types = {"signal.created", "metric.updated", "listing.event", "provider.health", "variant.updated", "collection.updated"}
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
            last_updated = ""
            deadline = time.time() + 25
            while time.time() < deadline:
                overview = _state().overview_v1()
                updated = str((_state().state or {}).get("updated_at") or "")
                try:
                    if updated != last_updated:
                        last_updated = updated
                        for ev in _state().stream_events_v1(types=types, mode=mode):
                            ev_name = str(ev.get("type") or "provider.health")
                            self.wfile.write(f"event: {ev_name}\n".encode("utf-8"))
                            self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8"))
                    else:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
                time.sleep(sleep_sec)
            return

        if path.startswith("/api/") and not path.startswith("/api/auth/"):
            if not _require_auth(self):
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
    port = int(os.getenv("PORT", "8091"))
    server = ThreadingHTTPServer((host, port), RequestHandler)
    # Warm-up analytics state in background: healthcheck becomes fast while data stack initializes.
    threading.Thread(target=_state, daemon=True, name="state-warmup").start()
    _start_signal_bot_loop(port)
    print(f"Server started on http://{host}:{port}")
    server.serve_forever()


def _start_signal_bot_loop(port: int) -> None:
    if not BOT_AUTORUN:
        _BOT_STATUS["enabled"] = False
        return
    if not signal_bot.BOT_TOKEN or not signal_bot.CHAT_ID:
        _BOT_STATUS["enabled"] = False
        _BOT_STATUS["last_error"] = "TG_BOT_TOKEN/TG_CHAT_ID not configured"
        return

    signal_bot.API_BASE_URL = BOT_API_BASE_URL or f"http://127.0.0.1:{port}"
    signal_bot.API_AUTH_TOKEN = BOT_API_AUTH_TOKEN
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
                signal_bot.cycle(cache)
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

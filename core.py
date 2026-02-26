from __future__ import annotations

import json
import math
import os
import ssl
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Dict, Iterable, List, Tuple
import urllib.request
import urllib.error
import re

from fragment import FragmentClient, ListingEvent, VariantTraits, BaseInfo

DATA_DIR = Path(__file__).parent / "data"
VARIANT_HISTORY_FILE = DATA_DIR / "variant_history.json"
LISTING_STATE_FILE = DATA_DIR / "listing_state.json"
TRADE_EVENTS_FILE = DATA_DIR / "trade_events.json"
STATE_FILE = DATA_DIR / "state.json"
ALERTS_FILE = DATA_DIR / "alerts.json"
ALERT_EVENTS_FILE = DATA_DIR / "alert_events.json"
FAVORITES_FILE = DATA_DIR / "favorites_by_user.json"
INGEST_LOG_FILE = DATA_DIR / "ingest.log"
AI_RECO_CACHE_FILE = DATA_DIR / "ai_reco_cache.json"
STARS_RATE_CACHE_FILE = DATA_DIR / "stars_rate_cache.json"
LISTING_TRACKER_STATE_FILE = DATA_DIR / "listing_tracker_state.json"
MT_LISTINGS_SNAPSHOT_FILE = DATA_DIR / "mt_listings_snapshot.json"

WINDOWS = {
    "1h": 60 * 60,
    "12h": 12 * 60 * 60,
    "24h": 24 * 60 * 60,
    "7d": 7 * 24 * 60 * 60,
    "30d": 30 * 24 * 60 * 60,
}

METRIC_UNITS: dict[str, str] = {
    "FLOOR_REALTIME": "TON",
    "FLOOR_HISTORY": "TON",
    "NEW_LISTINGS_REALTIME": "COUNT",
    "LISTING_FEED": "JSON",
    "LISTING_VELOCITY": "RATIO",
    "LISTING_PRESSURE": "RATIO",
    "FAIR_PRICE": "TON",
    "UNDERVALUE": "RATIO",
    "EXPECTED_PROFIT": "RATIO",
    "LIQUIDITY_SCORE": "SCORE_0_1",
    "LIQUIDITY_HEATMAP": "JSON",
    "LIQUIDITY_CHART": "JSON",
    "VOLUME_CHART": "JSON",
    "VOLUME_VELOCITY": "RATIO",
    "VELOCITY_SCORE": "SCORE_0_100",
    "ABSORPTION_RATE": "RATIO",
    "MARKET_DEPTH": "JSON",
    "BUY_WALL_SCORE": "RATIO",
    "WHALE_RATIO": "RATIO",
    "WHALE_IMPULSE": "RATIO",
    "RARITY_SCORE": "SCORE_0_1",
    "VOLATILITY": "RATIO",
    "SUPPLY_CHART": "JSON",
    "EDGE_SCORE": "SCORE_0_1",
    "BUY_SCORE": "SCORE_0_100",
    "SELL_SCORE": "SCORE_0_100",
    "MARKET_INDEX": "SCORE_0_100",
    "TREND_SCORE": "RATIO",
}

METRIC_DEFINITIONS_V1: list[dict] = [
    {"metric": "FLOOR_REALTIME", "scope": "VARIANT", "title_ru": "Минимальная цена", "unit": "TON", "is_timeseries": False, "description": "Текущий floor (min listing price)."},
    {"metric": "FLOOR_HISTORY", "scope": "VARIANT", "title_ru": "История floor", "unit": "TON", "is_timeseries": True, "description": "Исторические точки floor."},
    {"metric": "NEW_LISTINGS_REALTIME", "scope": "VARIANT", "title_ru": "Новые листинги", "unit": "COUNT", "is_timeseries": False, "description": "Количество новых листингов за окно."},
    {"metric": "LISTING_FEED", "scope": "VARIANT", "title_ru": "Лента листингов", "unit": "JSON", "is_timeseries": False, "description": "Последние listing events."},
    {"metric": "LISTING_VELOCITY", "scope": "VARIANT", "title_ru": "Скорость листингов", "unit": "RATIO", "is_timeseries": False, "description": "new_listings_10m."},
    {"metric": "LISTING_PRESSURE", "scope": "VARIANT", "title_ru": "Давление продавцов", "unit": "RATIO", "is_timeseries": False, "description": "active_lots / max(sales24h,1)."},
    {"metric": "FAIR_PRICE", "scope": "VARIANT", "title_ru": "Справедливая цена", "unit": "TON", "is_timeseries": False, "description": "0.7*median24h + 0.3*floor."},
    {"metric": "UNDERVALUE", "scope": "VARIANT", "title_ru": "Недооценка", "unit": "RATIO", "is_timeseries": False, "description": "(Fair-P)/Fair."},
    {"metric": "EXPECTED_PROFIT", "scope": "VARIANT", "title_ru": "Ожидаемая прибыль", "unit": "RATIO", "is_timeseries": False, "description": "((target_sell-P)/P)-fees."},
    {"metric": "LIQUIDITY_SCORE", "scope": "VARIANT", "title_ru": "Ликвидность", "unit": "SCORE_0_1", "is_timeseries": False, "description": "clamp(sales24h/1000,0,1)."},
    {"metric": "LIQUIDITY_HEATMAP", "scope": "VARIANT", "title_ru": "Тепловая карта ликвидности", "unit": "JSON", "is_timeseries": True, "description": "Временной срез ликвидности."},
    {"metric": "LIQUIDITY_CHART", "scope": "VARIANT", "title_ru": "График ликвидности", "unit": "JSON", "is_timeseries": True, "description": "Таймсерия ликвидности."},
    {"metric": "VOLUME_CHART", "scope": "VARIANT", "title_ru": "График объема", "unit": "JSON", "is_timeseries": True, "description": "Таймсерия объема."},
    {"metric": "VOLUME_VELOCITY", "scope": "VARIANT", "title_ru": "Скорость объема", "unit": "RATIO", "is_timeseries": False, "description": "volume_10m / (volume_30m/3)."},
    {"metric": "VELOCITY_SCORE", "scope": "MARKET", "title_ru": "Индекс скорости", "unit": "SCORE_0_100", "is_timeseries": False, "description": "Интегральная скорость рынка."},
    {"metric": "ABSORPTION_RATE", "scope": "VARIANT", "title_ru": "Скорость поглощения", "unit": "RATIO", "is_timeseries": False, "description": "sales_30m / max(new_listings_30m,1)."},
    {"metric": "MARKET_DEPTH", "scope": "VARIANT", "title_ru": "Глубина рынка", "unit": "JSON", "is_timeseries": False, "description": "Лоты в диапазоне floor..floor*1.05."},
    {"metric": "BUY_WALL_SCORE", "scope": "VARIANT", "title_ru": "Стена покупателей", "unit": "RATIO", "is_timeseries": False, "description": "near_floor_sales_30m / near_floor_listings."},
    {"metric": "WHALE_RATIO", "scope": "VARIANT", "title_ru": "Доля китов", "unit": "RATIO", "is_timeseries": False, "description": "whale_volume_24h/total_volume_24h."},
    {"metric": "WHALE_IMPULSE", "scope": "VARIANT", "title_ru": "Импульс китов", "unit": "RATIO", "is_timeseries": False, "description": "Прирост whale ratio за окно."},
    {"metric": "RARITY_SCORE", "scope": "VARIANT", "title_ru": "Редкость", "unit": "SCORE_0_1", "is_timeseries": False, "description": "Скор редкости варианта."},
    {"metric": "VOLATILITY", "scope": "VARIANT", "title_ru": "Волатильность", "unit": "RATIO", "is_timeseries": False, "description": "std(log_returns)*sqrt(N)."},
    {"metric": "SUPPLY_CHART", "scope": "VARIANT", "title_ru": "График предложения", "unit": "JSON", "is_timeseries": True, "description": "Таймсерия активных лотов."},
    {"metric": "EDGE_SCORE", "scope": "VARIANT", "title_ru": "Edge score", "unit": "SCORE_0_1", "is_timeseries": False, "description": "Главная формула edge."},
    {"metric": "BUY_SCORE", "scope": "VARIANT", "title_ru": "BUY score", "unit": "SCORE_0_100", "is_timeseries": False, "description": "Прокси buy score."},
    {"metric": "SELL_SCORE", "scope": "VARIANT", "title_ru": "SELL score", "unit": "SCORE_0_100", "is_timeseries": False, "description": "Прокси sell score."},
    {"metric": "MARKET_INDEX", "scope": "MARKET", "title_ru": "Индекс рынка", "unit": "SCORE_0_100", "is_timeseries": False, "description": "Средняя рыночная оценка."},
    {"metric": "TREND_SCORE", "scope": "MARKET", "title_ru": "Тренд", "unit": "RATIO", "is_timeseries": False, "description": "Нормированный тренд рынка."},
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return _now()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return _now()


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _pct_change(current: float, previous: float | None) -> float | None:
    if previous in (None, 0):
        return None
    return (current / previous - 1) * 100


def _safe_mean(values: Iterable[float]) -> float:
    vals = list(values)
    return float(mean(vals)) if vals else 0.0


def _safe_median(values: Iterable[float]) -> float:
    vals = list(values)
    return float(median(vals)) if vals else 0.0


def _safe_pstdev(values: Iterable[float]) -> float:
    vals = list(values)
    return float(pstdev(vals)) if len(vals) > 1 else 0.0


def _market_regime(trend_score: float, breadth_24h: float) -> str:
    if trend_score >= 0.8 or breadth_24h >= 0.56:
        return "bull"
    if trend_score <= -0.8 or breadth_24h <= 0.44:
        return "bear"
    return "sideways"


def _signals_quality_degraded(variants_count: int, gifts_count: int, model_count: int) -> bool:
    min_gifts = max(1, int(os.getenv("SIGNALS_QUALITY_MIN_GIFTS", "5000")))
    min_variants_abs = max(1, int(os.getenv("SIGNALS_QUALITY_MIN_VARIANTS_ABS", "200")))
    min_variants_ratio = max(0.0, min(1.0, float(os.getenv("SIGNALS_QUALITY_MIN_VARIANTS_RATIO", "0.02"))))
    min_models = max(1, int(os.getenv("SIGNALS_QUALITY_MIN_MODELS", "120")))
    if gifts_count < min_gifts:
        return False
    variants_floor = max(min_variants_abs, int(gifts_count * min_variants_ratio))
    # If model diversity is sufficiently high, allow signal generation even when
    # variant buckets are still being enriched asynchronously.
    if model_count >= min_models:
        return False
    return variants_count <= variants_floor


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = max(0, min(len(values) - 1, int(round((len(values) - 1) * p))))
    return float(values[k])


def _normalize(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.5
    return _clamp((value - lo) / (hi - lo), 0.0, 1.0)


def _slug_to_name(value: str) -> str:
    return " ".join(part.capitalize() for part in str(value or "").split("_") if part) or "Unknown"


def _sanitize_openai_key(value: str | None) -> str:
    raw = str(value or "").strip().strip("'").strip('"')
    # Remove accidental zero-width/non-ascii chars from copied keys.
    cleaned = "".join(ch for ch in raw if ord(ch) < 128 and ch not in "\r\n\t ")
    return cleaned


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, payload) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Compact JSON reduces write latency and memory/IO overhead for large runtime files.
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _log_ingest(message: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ts = _iso(_now())
    with INGEST_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{ts} {message}\n")



@dataclass
class StarsRate:
    stars_per_ton: float | None
    ton_per_star: float | None
    source: str
    fetched_at: str | None
    expires_at: str | None
    is_stale: bool
    error: str | None = None


class StarsRateService:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.rate: StarsRate | None = None
        self.ttl_sec = int(os.getenv("STARS_RATE_TTL_SEC", "900"))
        self.source = os.getenv("STARS_RATE_SOURCE", "manual")
        self._refresh()

    def _save_cache(self) -> None:
        if not self.rate:
            return
        _save_json(STARS_RATE_CACHE_FILE, self.to_dict())

    def _load_cache(self) -> StarsRate | None:
        data = _load_json(STARS_RATE_CACHE_FILE, {})
        if not isinstance(data, dict):
            return None
        spt = data.get("stars_per_ton")
        tps = data.get("ton_per_star")
        if spt in (None, "") and tps in (None, ""):
            return None
        try:
            spt_f = float(spt) if spt not in (None, "") else None
            tps_f = float(tps) if tps not in (None, "") else (1.0 / spt_f if spt_f else None)
        except Exception:
            return None
        return StarsRate(
            stars_per_ton=spt_f,
            ton_per_star=tps_f,
            source=str(data.get("source") or "cached"),
            fetched_at=data.get("fetched_at"),
            expires_at=data.get("expires_at"),
            is_stale=bool(data.get("is_stale", False)),
            error=data.get("error"),
        )

    def _refresh(self) -> None:
        now = _now()
        stars_per_ton = os.getenv("STARS_PER_TON")
        ton_per_star = os.getenv("TON_PER_STAR")
        if stars_per_ton:
            spt = float(stars_per_ton)
            tps = 1.0 / spt if spt else None
            self.rate = StarsRate(
                stars_per_ton=spt,
                ton_per_star=tps,
                source=self.source,
                fetched_at=_iso(now),
                expires_at=_iso(now + timedelta(seconds=self.ttl_sec)),
                is_stale=False,
            )
            self._save_cache()
            return
        if ton_per_star:
            tps = float(ton_per_star)
            spt = 1.0 / tps if tps else None
            self.rate = StarsRate(
                stars_per_ton=spt,
                ton_per_star=tps,
                source=self.source,
                fetched_at=_iso(now),
                expires_at=_iso(now + timedelta(seconds=self.ttl_sec)),
                is_stale=False,
            )
            self._save_cache()
            return
        cached = self._load_cache()
        if cached:
            self.rate = cached
            return
        fallback = os.getenv("STARS_PER_TON_FALLBACK", "500").strip()
        try:
            fallback_spt = float(fallback)
        except Exception:
            fallback_spt = 0.0
        if fallback_spt > 0:
            self.rate = StarsRate(
                stars_per_ton=fallback_spt,
                ton_per_star=1.0 / fallback_spt,
                source="fallback",
                fetched_at=_iso(now),
                expires_at=_iso(now + timedelta(seconds=self.ttl_sec)),
                is_stale=True,
                error="FALLBACK_RATE",
            )
            self._save_cache()
            return
        self.rate = StarsRate(
            stars_per_ton=None,
            ton_per_star=None,
            source="unavailable",
            fetched_at=None,
            expires_at=None,
            is_stale=True,
            error="RATE_UNAVAILABLE",
        )

    def set_derived_rate(self, stars_per_ton: float, source: str = "fragment_derived") -> None:
        if stars_per_ton <= 0:
            return
        now = _now()
        with self.lock:
            current = self.rate
            # Manual env settings have highest priority.
            if current and current.source == "manual" and current.stars_per_ton:
                return
            self.rate = StarsRate(
                stars_per_ton=float(stars_per_ton),
                ton_per_star=1.0 / float(stars_per_ton),
                source=source,
                fetched_at=_iso(now),
                expires_at=_iso(now + timedelta(seconds=self.ttl_sec)),
                is_stale=False,
                error=None,
            )
            self._save_cache()

    def get(self) -> StarsRate:
        with self.lock:
            if not self.rate:
                self._refresh()
            return self.rate

    def to_dict(self) -> dict:
        r = self.get()
        return {
            "stars_per_ton": r.stars_per_ton,
            "ton_per_star": r.ton_per_star,
            "source": r.source,
            "fetched_at": r.fetched_at,
            "expires_at": r.expires_at,
            "is_stale": r.is_stale,
            "error": r.error,
        }


class GiftAnalyticsService:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.fragment = FragmentClient()
        self.stars = StarsRateService()
        # Fail-closed by default: always use verified snapshot unless explicitly disabled.
        self.verified_only = os.getenv("VERIFIED_ONLY", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.ingest_interval_sec = int(os.getenv("INGEST_INTERVAL_SEC", "300"))
        self.data_stale_sec = int(os.getenv("DATA_STALE_SEC", "600"))
        self.max_collections = int(os.getenv("FRAGMENT_MAX_COLLECTIONS", "0"))
        self.max_pages = int(os.getenv("FRAGMENT_MAX_PAGES_PER_COLLECTION", "500"))
        self.state: dict = {
            "updated_at": None,
            "ingestion_lag_seconds": None,
            "data_stale": True,
            "last_error": None,
            "ingest_in_progress": False,
            "last_ingest_started_at": None,
        }
        self.bases: Dict[str, BaseInfo] = {}
        self.variants: Dict[str, dict] = {}
        self.variant_history: Dict[str, List[dict]] = _load_json(VARIANT_HISTORY_FILE, {})
        self.listing_state: Dict[str, dict] = _load_json(LISTING_STATE_FILE, {})
        self.listing_tracker_state: Dict[str, dict] = _load_json(LISTING_TRACKER_STATE_FILE, {})
        self.mt_listings_snapshot: Dict[str, object] = _load_json(MT_LISTINGS_SNAPSHOT_FILE, {})
        self.trade_events: List[dict] = _load_json(TRADE_EVENTS_FILE, [])
        self.alert_rules: List[dict] = _load_json(ALERTS_FILE, [])
        self.alert_events: List[dict] = _load_json(ALERT_EVENTS_FILE, [])
        self.ai_reco_cache: Dict[str, dict] = _load_json(AI_RECO_CACHE_FILE, {})
        self.ai_enabled = os.getenv("AI_RECO_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.ai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.ai_timeout_sec = int(os.getenv("OPENAI_TIMEOUT_SEC", "10"))
        self.ai_ssl_no_verify = os.getenv("OPENAI_SSL_NO_VERIFY", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.ai_cache_ttl_sec = int(os.getenv("AI_RECO_CACHE_TTL_SEC", "900"))
        self.ai_min_interval_sec = float(os.getenv("AI_RECO_MIN_INTERVAL_SEC", "1.2"))
        self.ai_max_retries = int(os.getenv("AI_RECO_MAX_RETRIES", "2"))
        self.ai_retry_backoff_sec = float(os.getenv("AI_RECO_RETRY_BACKOFF_SEC", "1.0"))
        self.ai_pipeline_enabled = os.getenv("AI_PIPELINE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.ai_pipeline_live_per_request = int(os.getenv("AI_PIPELINE_LIVE_PER_REQUEST", "8"))
        self.ai_status_probe_ttl_sec = int(os.getenv("AI_STATUS_PROBE_TTL_SEC", "120"))
        self.ai_cache_prune_interval_sec = int(os.getenv("AI_RECO_CACHE_PRUNE_INTERVAL_SEC", "300"))
        self.ai_cache_save_debounce_sec = float(os.getenv("AI_RECO_CACHE_SAVE_DEBOUNCE_SEC", "2.0"))
        self.ai_key_rejected = False
        self.ai_last_error = ""
        self.ai_lock = threading.Lock()
        self.ai_next_allowed_ts = 0.0
        self.ai_probe_cache: dict = {"checked_at_ts": 0, "payload": None}
        self.ai_cache_last_prune_ts = 0
        self.ai_cache_dirty = False
        self.ai_cache_last_save_mono = 0.0
        self.ai_inflight_lock = threading.Lock()
        self.ai_inflight: Dict[str, threading.Event] = {}
        self.ai_failure_streak = 0
        self.ai_cooldown_until_mono = 0.0
        self.ai_cooldown_base_sec = float(os.getenv("AI_RECO_COOLDOWN_BASE_SEC", "15"))
        self.ai_cooldown_max_sec = float(os.getenv("AI_RECO_COOLDOWN_MAX_SEC", "300"))
        self._data_version = 0
        self._reco_version = -1
        self._view_cache: Dict[tuple, tuple[int, dict | list]] = {}
        self.source_totals: Dict[str, int] = {
            "for_sale": 0,
            "sold": 0,
            "auction": 0,
        }
        self.fragment_bootstrap_cache = os.getenv("FRAGMENT_BOOTSTRAP_CACHE", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.verified_source = os.getenv("VERIFIED_SOURCE", "telegram_api").strip().lower()
        # Production default is TZ; legacy remains available via mode=legacy or env override.
        self.v1_signal_engine_mode = os.getenv("V1_SIGNAL_ENGINE_MODE", "tz").strip().lower()
        self.listing_new_window_sec = max(30, int(os.getenv("LISTING_NEW_WINDOW_SEC", "120")))
        self.listing_tracker_retention_sec = max(3600, int(os.getenv("LISTING_TRACKER_RETENTION_SEC", "1209600")))
        self.listing_primary_source = str(os.getenv("LISTING_PRIMARY_SOURCE", "auto") or "auto").strip().lower()
        self.listing_mt_api_url = str(os.getenv("LISTING_MT_API_URL", "") or "").strip()
        self.listing_mt_api_token = str(os.getenv("LISTING_MT_API_TOKEN", "") or "").strip()
        self.listing_mt_api_token_header = str(os.getenv("LISTING_MT_API_TOKEN_HEADER", "Authorization") or "Authorization").strip()
        self.listing_mt_api_token_prefix = str(os.getenv("LISTING_MT_API_TOKEN_PREFIX", "Bearer ") or "")
        self.listing_mt_api_timeout_sec = max(3.0, float(os.getenv("LISTING_MT_API_TIMEOUT_SEC", "8")))
        self.listing_mt_cache_ttl_sec = max(1.0, float(os.getenv("LISTING_MT_CACHE_TTL_SEC", "2")))
        self._listing_mt_runtime_cache: dict = {
            "fetched_mono": 0.0,
            "rows": [],
            "source": "disabled",
            "error": "",
            "updated_at": None,
        }
        self._restore_from_listing_state()
        self._sync_listing_tracker_state(_now(), persist=True)
        allow_bootstrap_from_file = self.verified_source in {"file", "fragment", "hybrid"}
        if self.fragment_bootstrap_cache and allow_bootstrap_from_file and not self.variants:
            self._bootstrap_from_verified_file()
        self._prune_ai_cache(force=True)
        self._start_ingest_loop()

    def _invalidate_view_cache(self) -> None:
        self._view_cache.clear()

    def _cache_get(self, key: tuple):
        cached = self._view_cache.get(key)
        if not cached:
            return None
        version, payload = cached
        if version != self._data_version:
            self._view_cache.pop(key, None)
            return None
        return payload

    def _cache_set(self, key: tuple, payload):
        # Small bounded cache to avoid repeated heavy aggregations per request.
        if len(self._view_cache) > 128:
            self._view_cache.clear()
        self._view_cache[key] = (self._data_version, payload)

    def _ensure_recos(self) -> None:
        if self._reco_version == self._data_version:
            return
        self.recompute_recos()
        self._reco_version = self._data_version

    def _restore_from_listing_state(self) -> None:
        if not self.listing_state:
            return
        now = _now()
        events: List[ListingEvent] = []
        base_map: Dict[str, BaseInfo] = {}
        for item in self.listing_state.values():
            if item.get("status") != "ACTIVE":
                continue
            variant_id = str(item.get("variant_id") or "").strip()
            if not variant_id:
                continue
            parts = variant_id.split("|")
            if len(parts) < 4:
                continue
            base_id, model_id, background_id, pattern_id = parts[0], parts[1], parts[2], parts[3]
            listing_id = str(item.get("listing_id") or "").strip()
            if not listing_id:
                continue
            ev = ListingEvent(
                listing_id=listing_id,
                base_id=base_id,
                variant_id=variant_id,
                price_ton=float(item.get("price_ton") or 0.0),
                status="auction" if item.get("sale_type") == "AUCTION" else "sale",
                ts=str(item.get("last_seen") or _iso(now)),
                traits=VariantTraits(
                    model=_slug_to_name(model_id),
                    background=_slug_to_name(background_id),
                    pattern=_slug_to_name(pattern_id),
                ),
                preview_url=str(item.get("preview_url") or ""),
            )
            events.append(ev)
            if base_id not in base_map:
                base_map[base_id] = BaseInfo(base_id=base_id, name=_slug_to_name(base_id), slug=base_id)

        if not events:
            return

        self.bases = base_map
        self._build_variants(events, now)
        self.state["updated_at"] = _iso(now)
        self.state["ingestion_lag_seconds"] = 0
        self.state["data_stale"] = True
        self.state["last_error"] = "RESTORED_FROM_LOCAL_SNAPSHOT"
        self.state["ingest_in_progress"] = False
        self._save_state()

    def _start_ingest_loop(self) -> None:
        def loop() -> None:
            while True:
                self.ingest_safe()
                time.sleep(self.ingest_interval_sec)

        thread = threading.Thread(target=loop, daemon=True, name="ingest-loop")
        thread.start()

    def _save_state(self) -> None:
        _save_json(STATE_FILE, self.state)

    def _save_variants(self) -> None:
        _save_json(VARIANT_HISTORY_FILE, self.variant_history)

    def _save_listing_state(self) -> None:
        _save_json(LISTING_STATE_FILE, self.listing_state)

    def _save_listing_tracker_state(self) -> None:
        _save_json(LISTING_TRACKER_STATE_FILE, self.listing_tracker_state)

    def _save_mt_listings_snapshot(self) -> None:
        _save_json(MT_LISTINGS_SNAPSHOT_FILE, self.mt_listings_snapshot)

    def _save_trade_events(self) -> None:
        _save_json(TRADE_EVENTS_FILE, self.trade_events)

    def _save_alerts(self) -> None:
        _save_json(ALERTS_FILE, self.alert_rules)
        _save_json(ALERT_EVENTS_FILE, self.alert_events)

    def _prune_ai_cache(self, force: bool = False) -> None:
        now_ts = int(time.time())
        if not force and (now_ts - self.ai_cache_last_prune_ts) < max(10, self.ai_cache_prune_interval_sec):
            return
        self.ai_cache_last_prune_ts = now_ts
        before = len(self.ai_reco_cache)
        if before <= 0:
            return
        self.ai_reco_cache = {
            k: v
            for k, v in self.ai_reco_cache.items()
            if isinstance(v, dict) and int(v.get("expires_at_ts", 0) or 0) > now_ts
        }
        if len(self.ai_reco_cache) != before:
            self.ai_cache_dirty = True
            self._save_ai_cache(force=False)

    def _save_ai_cache(self, force: bool = False) -> None:
        if not self.ai_cache_dirty and not force:
            return
        now_mono = time.monotonic()
        if (not force) and (now_mono - self.ai_cache_last_save_mono) < max(0.1, self.ai_cache_save_debounce_sec):
            return
        _save_json(AI_RECO_CACHE_FILE, self.ai_reco_cache)
        self.ai_cache_dirty = False
        self.ai_cache_last_save_mono = now_mono

    def stars_rate(self) -> dict:
        return self.stars.to_dict()

    def ingest(self) -> None:
        now = _now()
        max_inflight_sec = max(60, int(os.getenv("INGEST_MAX_INFLIGHT_SEC", "300")))
        with self.lock:
            if self.state.get("ingest_in_progress"):
                started_raw = self.state.get("last_ingest_started_at")
                started_dt = _parse_ts(str(started_raw)) if started_raw else None
                inflight_age = int((now - started_dt).total_seconds()) if started_dt else 0
                if started_dt and inflight_age >= max_inflight_sec:
                    self.state["ingest_in_progress"] = False
                    self.state["last_error"] = f"INGEST_LOCK_RESET(age={inflight_age}s)"
                    _log_ingest(f"ingest stale lock reset age={inflight_age}s max={max_inflight_sec}s")
                else:
                    _log_ingest("ingest skipped (already in progress)")
                    return
            self.state["ingest_in_progress"] = True
            self.state["last_ingest_started_at"] = _iso(now)
        _log_ingest("ingest start")
        try:
            events, bases = self._fetch_with_timeout()
        except Exception as exc:
            with self.lock:
                self.state["data_stale"] = True
                self.state["last_error"] = str(exc)
                self.state["ingestion_lag_seconds"] = None
                self.state["ingest_in_progress"] = False
                self._save_state()
            _log_ingest(f"ingest fetch error: {exc}")
            return
        derived_stars = getattr(self.fragment, "derived_stars_per_ton", None)
        if derived_stars:
            self.stars.set_derived_rate(float(derived_stars))

        with self.lock:
            if not events or not bases:
                # Fragment can occasionally return an empty temporary window.
                # Keep the last valid snapshot instead of replacing analytics with zeros.
                has_snapshot = bool(self.variants) and bool(self.listing_state)
                self.state["last_error"] = "NO_ACTIVE_LISTINGS_FROM_FRAGMENT"
                self.state["data_stale"] = has_snapshot
                updated_at = _parse_ts(self.state.get("updated_at"))
                if has_snapshot and self.state.get("updated_at"):
                    self.state["ingestion_lag_seconds"] = max(0, int((now - updated_at).total_seconds()))
                else:
                    self.state["ingestion_lag_seconds"] = None
                self.state["ingest_in_progress"] = False
                self._save_state()
                _log_ingest("ingest empty snapshot ignored (kept previous dataset)")
                return

            self.bases = {b.base_id: b for b in bases}
            self._process_listings(events, now)
            self._build_variants(events, now)
            self._evaluate_alerts(now)
            self.state["updated_at"] = _iso(now)
            self.state["ingestion_lag_seconds"] = 0
            self.state["data_stale"] = False
            self.state["last_error"] = None
            self.state["ingest_in_progress"] = False
            self._save_state()
        _log_ingest(f"ingest done events={len(events)} bases={len(bases)}")

    def _fetch_with_timeout(self) -> Tuple[List[ListingEvent], List[BaseInfo]]:
        if self.verified_only:
            return self._fetch_from_verified_snapshot()
        return self.fragment.fetch_active_listings(
            max_collections=self.max_collections,
            max_pages=self.max_pages,
        )

    def _fetch_from_verified_snapshot(self) -> Tuple[List[ListingEvent], List[BaseInfo]]:
        from market_data import load_verified_dataset_source

        dataset = load_verified_dataset_source()
        meta = dataset.get("meta") if isinstance(dataset, dict) else {}
        fallback_mode = str((meta or {}).get("source_fallback") or "").strip().lower() == "file"
        allow_live_recovery = os.getenv("VERIFIED_FALLBACK_LIVE_RECOVERY", "false").strip().lower() in {"1", "true", "yes", "on"}
        if fallback_mode and allow_live_recovery and self.verified_source in {"hybrid", "fragment", "file"}:
            # Degradation path: verified source returned file fallback.
            # Try direct Fragment client fetch as a live recovery channel.
            try:
                events_live, bases_live = self.fragment.fetch_active_listings(
                    max_collections=self.max_collections,
                    max_pages=self.max_pages,
                )
                if events_live and bases_live:
                    self._update_source_totals_from_events(events_live)
                    return events_live, bases_live
            except Exception:
                # Keep fallback dataset path below.
                pass
        self._update_source_totals(dataset)
        return self._events_bases_from_verified_dataset(dataset)

    def _update_source_totals_from_events(self, events: List[ListingEvent]) -> None:
        for_sale = 0
        sold = 0
        auction = 0
        for ev in events or []:
            st = str(getattr(ev, "status", "") or "").strip().lower()
            if st == "sold":
                sold += 1
            elif st == "auction":
                auction += 1
                for_sale += 1
            else:
                for_sale += 1
        self.source_totals = {"for_sale": for_sale, "sold": sold, "auction": auction}

    def _update_source_totals(self, dataset: Dict) -> None:
        meta = dataset.get("meta") if isinstance(dataset, dict) else {}
        if isinstance(meta, dict):
            fs = meta.get("total_for_sale")
            sd = meta.get("total_sold")
            aq = meta.get("total_auction")
            if fs is not None or sd is not None or aq is not None:
                self.source_totals = {
                    "for_sale": int(fs or 0),
                    "sold": int(sd or 0),
                    "auction": int(aq or 0),
                }
                return
        gifts = dataset.get("gifts") if isinstance(dataset, dict) else []
        for_sale = 0
        sold = 0
        auction = 0
        for g in gifts if isinstance(gifts, list) else []:
            if not isinstance(g, dict):
                continue
            st = str(g.get("latest_status") or "").strip().lower()
            if st == "sold":
                sold += 1
            elif st == "auction":
                auction += 1
                for_sale += 1
            else:
                for_sale += 1
        self.source_totals = {"for_sale": for_sale, "sold": sold, "auction": auction}

    def _events_bases_from_verified_dataset(self, dataset: Dict) -> Tuple[List[ListingEvent], List[BaseInfo]]:
        gifts = dataset.get("gifts") or []
        events: List[ListingEvent] = []
        base_map: Dict[str, BaseInfo] = {}

        def _slug_text(text: str) -> str:
            return re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_") or "unknown"

        def _base_name_from_gift(gift: dict, base_id: str) -> str:
            raw = str(gift.get("name") or "").strip()
            if raw:
                # Lot titles are like "Artisan Bricks #2975" – keep only collection name.
                cleaned = re.sub(r"\s*#\d+\s*$", "", raw).strip()
                if cleaned:
                    return cleaned
            return str(gift.get("collection_slug") or base_id).replace("_", " ").title()

        for g in gifts:
            if not isinstance(g, dict):
                continue
            status = str(g.get("latest_status") or "").strip().lower()
            if status == "sold":
                continue

            base_id = str(g.get("collection_slug") or "").strip().lower()
            if not base_id:
                continue

            profile = g.get("profile") or {}
            model = str(profile.get("model") or "").strip() or "Unknown"
            background = str(profile.get("background") or "").strip() or "Unknown"
            pattern = str(profile.get("pattern") or "").strip() or "Unknown"
            traits = VariantTraits(model=model, background=background, pattern=pattern)

            series = g.get("series") or []
            last_point = series[-1] if series else {}
            price = last_point.get("price")
            if price in (None, ""):
                price = profile.get("value_ton_estimate")
            try:
                price_ton = float(price)
            except Exception:
                continue
            if price_ton <= 0:
                continue

            listing_id = str(g.get("last_lot_id") or g.get("gift_id") or "").strip()
            if not listing_id:
                continue

            variant_id = f"{base_id}|{_slug_text(model)}|{_slug_text(background)}|{_slug_text(pattern)}"
            ts = str(last_point.get("dt") or _iso(_now()))
            preview_url = str(g.get("preview_image_url") or "").strip()

            events.append(
                ListingEvent(
                    listing_id=listing_id,
                    base_id=base_id,
                    variant_id=variant_id,
                    price_ton=price_ton,
                    status="sale",
                    ts=ts,
                    traits=traits,
                    preview_url=preview_url,
                )
            )

            if base_id not in base_map:
                base_name = _base_name_from_gift(g, base_id)
                base_map[base_id] = BaseInfo(base_id=base_id, name=base_name, slug=base_id)

        return events, list(base_map.values())

    def _bootstrap_from_verified_file(self) -> None:
        from market_data import load_verified_dataset

        file_path = os.getenv("VERIFIED_DATA_FILE", "").strip() or None
        try:
            dataset = load_verified_dataset(file_path)
            events, bases = self._events_bases_from_verified_dataset(dataset)
            if not events or not bases:
                return
            now = _now()
            with self.lock:
                self.bases = {b.base_id: b for b in bases}
                self._process_listings(events, now)
                self._build_variants(events, now)
                self.state["updated_at"] = _iso(now)
                self.state["ingestion_lag_seconds"] = 0
                self.state["data_stale"] = True
                self.state["last_error"] = "RESTORED_FROM_LOCAL_SNAPSHOT"
                self.state["ingest_in_progress"] = False
                self._save_state()
            _log_ingest(f"bootstrap from file: events={len(events)} bases={len(bases)}")
        except Exception as exc:
            _log_ingest(f"bootstrap from file failed: {exc}")

    def ingest_safe(self) -> None:
        try:
            self.ingest()
        except Exception as exc:
            with self.lock:
                self.state["data_stale"] = True
                self.state["last_error"] = f"INGEST_FAILED: {exc}"
                self.state["ingestion_lag_seconds"] = None
                self.state["ingest_in_progress"] = False
                self._save_state()
            _log_ingest(f"ingest exception: {exc}")

    def _process_listings(self, events: List[ListingEvent], now: datetime) -> None:
        current_ids = set()
        new_by_variant: Dict[str, int] = {}
        for ev in events:
            listing_id = ev.listing_id
            current_ids.add(listing_id)
            existing = self.listing_state.get(listing_id)
            if not existing:
                new_by_variant[ev.variant_id] = new_by_variant.get(ev.variant_id, 0) + 1
            self.listing_state[listing_id] = {
                "listing_id": listing_id,
                "variant_id": ev.variant_id,
                "base_id": ev.base_id,
                "price_ton": ev.price_ton,
                "status": "ACTIVE",
                "sale_type": "AUCTION" if ev.status == "auction" else "FIXED",
                "seller_id": None,
                "end_at": None,
                "auction": {
                    "current_bid_ton": ev.price_ton if ev.status == "auction" else None,
                    "bid_count": None,
                },
                "preview_url": ev.preview_url,
                "last_seen": _iso(now),
            }

        removed_ids = [lid for lid in self.listing_state.keys() if lid not in current_ids]
        for lid in removed_ids:
            old = self.listing_state.pop(lid, None)
            if not old:
                continue
            self.trade_events.append(
                {
                    "ts": _iso(now),
                    "variant_id": old["variant_id"],
                    "base_id": old["base_id"],
                    "price_ton": float(old.get("price_ton") or 0),
                }
            )

        cutoff = _now() - timedelta(days=30)
        self.trade_events = [e for e in self.trade_events if _parse_ts(e.get("ts")) >= cutoff]

        if new_by_variant:
            for vid, count in new_by_variant.items():
                self._append_history(vid, now, extras={"new_listings": count})

        self._sync_listing_tracker_state(now, persist=True)
        self._save_listing_state()
        self._save_trade_events()

    def _listing_tracker_key(self, row: dict) -> str | None:
        base_id = str((row or {}).get("base_id") or "").strip().lower()
        listing_id = str((row or {}).get("listing_id") or "").strip()
        if not base_id or not listing_id:
            return None
        return f"{base_id}:{listing_id}"

    def _variant_attrs_from_id(self, variant_id: str) -> tuple[str, str, str]:
        parts = str(variant_id or "").split("|")
        model = _slug_to_name(parts[1]) if len(parts) > 1 else "Unknown"
        background = _slug_to_name(parts[2]) if len(parts) > 2 else "Unknown"
        pattern = _slug_to_name(parts[3]) if len(parts) > 3 else "Unknown"
        return model, background, pattern

    def _sync_listing_tracker_state(self, now: datetime, persist: bool = True) -> None:
        if not isinstance(self.listing_tracker_state, dict):
            self.listing_tracker_state = {}
        tracker = self.listing_tracker_state
        now_iso = _iso(now)
        active_keys: set[str] = set()
        changed = False

        for row in self.listing_state.values():
            if str((row or {}).get("status") or "ACTIVE").upper() != "ACTIVE":
                continue
            key = self._listing_tracker_key(row)
            if not key:
                continue
            active_keys.add(key)
            price_ton = float((row or {}).get("price_ton") or 0.0)
            variant_id = str((row or {}).get("variant_id") or "")
            base_id = str((row or {}).get("base_id") or "").lower()
            listing_id = str((row or {}).get("listing_id") or "")
            last_seen = str((row or {}).get("last_seen") or now_iso)
            entry = tracker.get(key)
            if not isinstance(entry, dict):
                tracker[key] = {
                    "listing_key": key,
                    "base_id": base_id,
                    "listing_id": listing_id,
                    "variant_id": variant_id,
                    "first_seen_at": last_seen,
                    "last_seen_at": last_seen,
                    "last_price_ton": price_ton,
                    "active": True,
                    "relist_count": 0,
                    "last_relisted_at": None,
                    "last_absent_at": None,
                }
                changed = True
                continue

            was_active = bool(entry.get("active"))
            if not was_active:
                entry["relist_count"] = int(entry.get("relist_count") or 0) + 1
                entry["last_relisted_at"] = now_iso
                changed = True

            if str(entry.get("variant_id") or "") != variant_id:
                entry["variant_id"] = variant_id
                changed = True
            if float(entry.get("last_price_ton") or 0.0) != price_ton:
                entry["last_price_ton"] = price_ton
                changed = True
            if str(entry.get("last_seen_at") or "") != last_seen:
                entry["last_seen_at"] = last_seen
                changed = True
            if not was_active:
                entry["active"] = True
                changed = True
            if entry.get("last_absent_at") is not None:
                entry["last_absent_at"] = None
                changed = True

        for key, entry in list(tracker.items()):
            if not isinstance(entry, dict):
                tracker.pop(key, None)
                changed = True
                continue
            if key in active_keys:
                continue
            if bool(entry.get("active")):
                entry["active"] = False
                entry["last_absent_at"] = now_iso
                changed = True

        cutoff = now - timedelta(seconds=self.listing_tracker_retention_sec)
        for key, entry in list(tracker.items()):
            if bool((entry or {}).get("active")):
                continue
            last_seen_dt = _parse_ts((entry or {}).get("last_seen_at"))
            if last_seen_dt < cutoff:
                tracker.pop(key, None)
                changed = True

        if changed:
            self._data_version += 1
            self._invalidate_view_cache()
            if persist:
                self._save_listing_tracker_state()

    def _append_history(self, variant_id: str, ts: datetime, extras: dict | None = None) -> None:
        extras = extras or {}
        history = self.variant_history.setdefault(variant_id, [])
        history.append({"ts": _iso(ts), **extras})
        cutoff = _now() - timedelta(days=30)
        self.variant_history[variant_id] = [h for h in history if _parse_ts(h.get("ts")) >= cutoff]

    def _build_variants(self, events: List[ListingEvent], now: datetime) -> None:
        by_variant: Dict[str, List[ListingEvent]] = {}
        for ev in events:
            by_variant.setdefault(ev.variant_id, []).append(ev)

        variants: Dict[str, dict] = {}
        for variant_id, items in by_variant.items():
            prices = [x.price_ton for x in items]
            active_listings = len(prices)
            if active_listings == 0:
                continue
            prices_sorted = sorted(prices)
            floor = prices_sorted[0]
            median_price = _safe_median(prices_sorted)
            vwap = _safe_mean(prices_sorted)
            p10 = _percentile(prices_sorted, 0.1)
            spread_proxy = (p10 - floor) / floor if floor else 0.0

            traits = items[0].traits
            preview = items[0].preview_url
            base_id = items[0].base_id

            history = self.variant_history.get(variant_id, [])
            history.append(
                {
                    "ts": _iso(now),
                    "floor_ton": floor,
                    "median_ton": median_price,
                    "vwap_ton": vwap,
                    "active_listings": active_listings,
                }
            )
            self.variant_history[variant_id] = history[-5000:]

            metrics = {
                "floor_ton": round(floor, 6),
                "floor_stars_est": self._stars_est(floor),
                "median_ton": round(median_price, 6),
                "vwap_ton": round(vwap, 6),
                "active_listings": active_listings,
                "spread_proxy_24h": round(spread_proxy, 6),
            }
            metrics.update(self._window_metrics(variant_id, now))

            variants[variant_id] = {
                "variant_id": variant_id,
                "base_id": base_id,
                "traits": {
                    "model": {"id": traits.model_id, "name": traits.model},
                    "background": {"id": traits.background_id, "name": traits.background},
                    "pattern": {"id": traits.pattern_id, "name": traits.pattern},
                },
                "preview_url": preview,
                "updated_at": _iso(now),
                "metrics": metrics,
            }

        self.variants = variants
        self._data_version += 1
        self._reco_version = -1
        self._invalidate_view_cache()
        self._save_variants()
        self._compute_liquidity()
        self._ensure_recos()

    def _window_metrics(self, variant_id: str, now: datetime) -> dict:
        metrics = {}
        history = self.variant_history.get(variant_id, [])
        for label, seconds in WINDOWS.items():
            snapshot = self._snapshot_before(history, now - timedelta(seconds=seconds))
            if snapshot is None and history:
                # Bootstrap mode: dataset is younger than the requested window.
                # Use the oldest known point so metrics are not frozen at 0%.
                snapshot = history[0]
            current = self._snapshot_before(history, now)
            floor_now = (current or {}).get("floor_ton")
            floor_then = (snapshot or {}).get("floor_ton")
            active_then = (snapshot or {}).get("active_listings")
            active_now = (current or {}).get("active_listings")
            change = _pct_change(floor_now, floor_then)
            median_now = (current or {}).get("median_ton")
            median_then = (snapshot or {}).get("median_ton")
            if median_now in (None, 0) or median_then in (None, 0):
                median_now = (current or {}).get("vwap_ton")
                median_then = (snapshot or {}).get("vwap_ton")
            price_change = _pct_change(median_now, median_then)
            supply_change = _pct_change(active_now or 0, active_then or 0)
            trades_count, volume_ton = self._trades_in_window(variant_id, now, seconds)
            vol = self._volatility(history, now, seconds)
            floor_series = self._floor_series(history, now, seconds)
            median_floor = _safe_median(floor_series)
            vwap = volume_ton / trades_count if trades_count else 0.0
            key = f"_{label}"
            metrics[f"floor_change_pct{key}"] = round(change, 3) if change is not None else 0.0
            metrics[f"price_change_pct{key}"] = round(price_change, 3) if price_change is not None else 0.0
            metrics[f"supply_change_pct{key}"] = round(supply_change, 3) if supply_change is not None else 0.0
            metrics[f"trades_count{key}"] = int(trades_count)
            metrics[f"volume_ton{key}"] = round(volume_ton, 6)
            metrics[f"volatility{key}"] = round(vol, 6)
            metrics[f"buy_velocity{key}"] = round(trades_count / max(seconds / 3600, 1), 4)
            if label == "24h":
                metrics["vwap_ton_24h"] = round(vwap, 6)
            if label == "7d":
                metrics["median_ton_7d"] = round(median_floor, 6)

        metrics["new_listings_24h"] = self._new_listings_in_window(variant_id, now, WINDOWS["24h"])
        # If raw deltas are still 0 due sparse history/new variant bootstrap,
        # derive non-zero proxy deltas from current spread and volatility.
        current = self._snapshot_before(history, now) or {}
        floor_now = float(current.get("floor_ton") or 0)
        median_now = float(current.get("median_ton") or 0)
        if median_now <= 0:
            median_now = float(current.get("vwap_ton") or 0)
        spread_proxy_pct = _pct_change(floor_now, median_now) if floor_now > 0 and median_now > 0 else 0.0
        vol_proxy_pct = float(metrics.get("volatility_24h", 0) or 0) * 100.0
        base_proxy = spread_proxy_pct if spread_proxy_pct not in (None, 0) else vol_proxy_pct
        if base_proxy in (None, 0):
            base_proxy = 0.0

        def _fill_delta_if_zero(key: str, value: float) -> None:
            cur = float(metrics.get(key, 0) or 0)
            if abs(cur) < 0.001 and abs(value) >= 0.001:
                metrics[key] = round(value, 3)

        _fill_delta_if_zero("floor_change_pct_24h", base_proxy)
        _fill_delta_if_zero("price_change_pct_24h", base_proxy)
        _fill_delta_if_zero("floor_change_pct_12h", base_proxy * 0.6)
        _fill_delta_if_zero("price_change_pct_12h", base_proxy * 0.6)
        _fill_delta_if_zero("floor_change_pct_1h", base_proxy * 0.2)
        _fill_delta_if_zero("price_change_pct_1h", base_proxy * 0.2)

        supply_24h = float(metrics.get("supply_change_pct_24h", 0) or 0)
        if abs(supply_24h) < 0.001:
            active_now = float(current.get("active_listings") or 0)
            new_listings = float(metrics.get("new_listings_24h", 0) or 0)
            supply_proxy = (new_listings / active_now) * 100.0 if active_now > 0 and new_listings > 0 else 0.0
            if abs(supply_proxy) < 0.001:
                supply_proxy = base_proxy * 0.35
            _fill_delta_if_zero("supply_change_pct_24h", supply_proxy)
            _fill_delta_if_zero("supply_change_pct_12h", supply_proxy * 0.6)
            _fill_delta_if_zero("supply_change_pct_1h", supply_proxy * 0.2)
        return metrics

    def _snapshot_before(self, history: List[dict], ts: datetime) -> dict | None:
        target = None
        for h in history:
            if _parse_ts(h.get("ts")) <= ts:
                target = h
        return target

    def _trades_in_window(self, variant_id: str, now: datetime, seconds: int) -> Tuple[int, float]:
        cutoff = now - timedelta(seconds=seconds)
        count = 0
        volume = 0.0
        for ev in self.trade_events:
            if ev.get("variant_id") != variant_id:
                continue
            ts = _parse_ts(ev.get("ts"))
            if ts >= cutoff:
                count += 1
                volume += float(ev.get("price_ton") or 0)
        return count, volume

    def _new_listings_in_window(self, variant_id: str, now: datetime, seconds: int) -> int:
        cutoff = now - timedelta(seconds=seconds)
        count = 0
        for h in self.variant_history.get(variant_id, []):
            ts = _parse_ts(h.get("ts"))
            if ts >= cutoff and h.get("new_listings"):
                count += int(h.get("new_listings") or 0)
        return count

    def _volatility(self, history: List[dict], now: datetime, seconds: int) -> float:
        cutoff = now - timedelta(seconds=seconds)
        series = [h.get("floor_ton") for h in history if _parse_ts(h.get("ts")) >= cutoff and h.get("floor_ton")]
        if not series:
            return 0.0
        mean_val = _safe_mean(series)
        if mean_val == 0:
            return 0.0
        return _safe_pstdev(series) / mean_val

    def _floor_series(self, history: List[dict], now: datetime, seconds: int) -> List[float]:
        cutoff = now - timedelta(seconds=seconds)
        return [h.get("floor_ton") for h in history if _parse_ts(h.get("ts")) >= cutoff and h.get("floor_ton")]

    def _compute_liquidity(self) -> None:
        trades = [v["metrics"].get("trades_count_24h", 0) for v in self.variants.values()]
        volumes = [v["metrics"].get("volume_ton_24h", 0) for v in self.variants.values()]
        spreads = [v["metrics"].get("spread_proxy_24h", 0) for v in self.variants.values()]
        active = [v["metrics"].get("active_listings", 0) for v in self.variants.values()]
        if not self.variants:
            return
        min_t, max_t = min(trades), max(trades)
        min_v, max_v = min(volumes), max(volumes)
        min_s, max_s = min(spreads), max(spreads)
        min_a, max_a = min(active), max(active)

        for v in self.variants.values():
            m = v["metrics"]
            trades_n = _normalize(m.get("trades_count_24h", 0), min_t, max_t)
            volume_n = _normalize(m.get("volume_ton_24h", 0), min_v, max_v)
            spread_n = _normalize(m.get("spread_proxy_24h", 0), min_s, max_s)
            liquidity = _clamp(0.4 * trades_n + 0.4 * volume_n + 0.2 * (1 - spread_n), 0, 1)
            thin_risk = _clamp(1 - _normalize(m.get("active_listings", 0), min_a, max_a), 0, 1)
            pump_risk = _clamp(max(0.0, m.get("floor_change_pct_24h", 0)) / 25 * (1 - liquidity), 0, 1)
            m["liquidity_score_24h"] = round(liquidity, 4)
            m["thin_market_risk_24h"] = round(thin_risk, 4)
            m["pump_risk_24h"] = round(pump_risk, 4)

    def recompute_recos(self) -> None:
        variants = list(self.variants.values())
        if not variants:
            return
        avg_1h = _safe_mean([float((v.get("metrics") or {}).get("floor_change_pct_1h", 0) or 0) for v in variants])
        avg_12h = _safe_mean([float((v.get("metrics") or {}).get("floor_change_pct_12h", 0) or 0) for v in variants])
        avg_24h = _safe_mean([float((v.get("metrics") or {}).get("floor_change_pct_24h", 0) or 0) for v in variants])
        positive_24h = sum(1 for v in variants if float((v.get("metrics") or {}).get("floor_change_pct_24h", 0) or 0) > 0)
        breadth_24h = positive_24h / max(len(variants), 1)
        trend_score = (0.18 * avg_1h) + (0.27 * avg_12h) + (0.35 * avg_24h)
        regime = _market_regime(trend_score, breadth_24h)

        contrarian_enabled = os.getenv("SIGNALS_CONTRARIAN_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
        oversold_q = _clamp(float(os.getenv("SIGNALS_CONTRARIAN_OVERSOLD_Q", "0.18")), 0.02, 0.45)
        min_liq = _clamp(float(os.getenv("SIGNALS_CONTRARIAN_MIN_LIQUIDITY", "0.52")), 0.1, 1.0)
        min_active = max(1, int(os.getenv("SIGNALS_CONTRARIAN_MIN_ACTIVE", "180")))
        boost_pts = _clamp(float(os.getenv("SIGNALS_CONTRARIAN_SCORE_BOOST", "10.0")), 0.0, 25.0)
        ch24_samples = [float((v.get("metrics") or {}).get("floor_change_pct_24h", 0) or 0) for v in variants]
        oversold_threshold = _percentile(ch24_samples, oversold_q)

        ranges = self._market_ranges()
        for v in variants:
            m = v["metrics"]
            # Multi-horizon momentum: fast move + intraday + daily trend.
            mom_1h = _signed_norm(m.get("floor_change_pct_1h", 0), 8.0)
            mom_12h = _signed_norm(m.get("floor_change_pct_12h", 0), 15.0)
            mom_24h = _signed_norm(m.get("floor_change_pct_24h", 0), 25.0)
            momentum = (0.2 * mom_1h) + (0.35 * mom_12h) + (0.45 * mom_24h)

            trades_n = _normalize(m.get("trades_count_24h", 0), ranges["trades_min"], ranges["trades_max"])
            active_n = _normalize(m.get("active_listings", 0), ranges["active_min"], ranges["active_max"])
            liquidity = float(m.get("liquidity_score_24h", 0) or 0)
            scarcity = _clamp(1 - active_n, 0, 1)
            spread_penalty = _normalize(m.get("spread_proxy_24h", 0), ranges["spread_min"], ranges["spread_max"])
            volatility_penalty = _normalize(m.get("volatility_24h", 0), 0, 0.22)
            thin_penalty = float(m.get("thin_market_risk_24h", 0) or 0)
            pump_penalty = float(m.get("pump_risk_24h", 0) or 0)

            # Data quality gate: low-activity variants must not produce aggressive recommendations.
            data_quality = _clamp(
                (0.45 * active_listings_score(int(m.get("active_listings", 0) or 0)))
                + (0.40 * trades_n)
                + (0.15 * liquidity),
                0,
                1,
            )

            edge = (
                0.42 * momentum
                + 0.18 * trades_n
                + 0.14 * liquidity
                + 0.08 * scarcity
                - 0.22 * volatility_penalty
                - 0.20 * thin_penalty
                - 0.14 * pump_penalty
                - 0.08 * spread_penalty
            )
            contrarian_opportunity = (
                contrarian_enabled
                and regime == "bear"
                and float(m.get("floor_change_pct_24h", 0) or 0) <= float(oversold_threshold)
                and liquidity >= min_liq
                and int(m.get("active_listings", 0) or 0) >= min_active
                and volatility_penalty <= 0.65
                and thin_penalty <= 0.7
            )
            raw_score = 50 + (edge * 50) + (boost_pts if contrarian_opportunity else 0.0)
            reco = _clamp(raw_score, 0, 100)

            signal_strength = _clamp(abs(edge), 0, 1)
            confidence = int(round(_clamp((0.58 * data_quality + 0.42 * signal_strength) * 100, 5, 99)))
            action = _reco_action(
                reco,
                liquidity,
                (0.45 * volatility_penalty + 0.35 * thin_penalty + 0.20 * pump_penalty),
                confidence=confidence,
                data_quality=data_quality,
                regime=regime,
                contrarian_opportunity=bool(contrarian_opportunity),
            )

            forecast = _build_forecast(m, momentum, confidence)
            v["reco"] = {
                "action": action,
                "reco_score": round(reco, 1),
                "confidence": confidence,
                "reasons": _build_reasons(m, momentum, trades_n, liquidity, scarcity),
                "risks": _build_risks(m, volatility_penalty, thin_penalty, pump_penalty, spread_penalty, data_quality),
                "forecast": forecast,
                "summary": _build_reco_summary(action, round(reco, 1), confidence, forecast),
            }

    def _market_ranges(self) -> dict:
        active = [v["metrics"].get("active_listings", 0) for v in self.variants.values()]
        trades = [v["metrics"].get("trades_count_24h", 0) for v in self.variants.values()]
        spreads = [v["metrics"].get("spread_proxy_24h", 0) for v in self.variants.values()]
        if not active:
            return {
                "active_min": 0,
                "active_max": 1,
                "trades_min": 0,
                "trades_max": 1,
                "spread_min": 0,
                "spread_max": 1,
            }
        return {
            "active_min": min(active),
            "active_max": max(active),
            "trades_min": min(trades),
            "trades_max": max(trades),
            "spread_min": min(spreads) if spreads else 0,
            "spread_max": max(spreads) if spreads else 1,
        }

    def is_stale(self) -> bool:
        updated = self.state.get("updated_at")
        if not updated:
            return True
        ts = _parse_ts(updated)
        return (_now() - ts).total_seconds() > self.data_stale_sec

    def market_overview(self) -> dict:
        self._ensure_recos()
        cache_key = ("market_overview",)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        with self.lock:
            variants = list(self.variants.values())
            state_updated_at = self.state.get("updated_at")
            state_ingestion_lag = self.state.get("ingestion_lag_seconds")
            state_last_error = self.state.get("last_error")
            state_ingest_in_progress = self.state.get("ingest_in_progress")
            state_last_ingest_started_at = self.state.get("last_ingest_started_at")
            source_for_sale = int(self.source_totals.get("for_sale", 0) or 0)
            source_sold = int(self.source_totals.get("sold", 0) or 0)
            trades_total = len(self.trade_events)

            floors = [v["metrics"]["floor_ton"] for v in variants]
            active = [v["metrics"]["active_listings"] for v in variants]
            models = {v.get("traits", {}).get("model", {}).get("id") for v in variants if v.get("traits", {}).get("model", {}).get("id")}
            avg_1h = _safe_mean([v["metrics"].get("floor_change_pct_1h", 0) for v in variants])
            avg_12h = _safe_mean([v["metrics"].get("floor_change_pct_12h", 0) for v in variants])
            avg_24h = _safe_mean([v["metrics"].get("floor_change_pct_24h", 0) for v in variants])
            avg_7d = _safe_mean([v["metrics"].get("floor_change_pct_7d", 0) for v in variants])
            avg_30d = _safe_mean([v["metrics"].get("floor_change_pct_30d", 0) for v in variants])
            buy_signals = sum(1 for v in variants if v.get("reco", {}).get("action") == "BUY")
            sell_signals = sum(1 for v in variants if v.get("reco", {}).get("action") == "SELL")
            positive_24h = sum(1 for v in variants if float(v["metrics"].get("floor_change_pct_24h", 0) or 0) > 0)
            breadth_24h = positive_24h / max(len(variants), 1)
            trend_score = (0.18 * avg_1h) + (0.27 * avg_12h) + (0.35 * avg_24h) + (0.20 * avg_7d)

        net_signal = buy_signals - sell_signals
        market_state = "Боковик"
        if trend_score >= 0.8 or (breadth_24h >= 0.56 and net_signal > 0):
            market_state = "Рост"
        elif trend_score <= -0.8 or (breadth_24h <= 0.44 and net_signal < 0):
            market_state = "Падение"

        anomalies = sum(1 for v in variants if v["metrics"].get("pump_risk_24h", 0) > 0.7)
        active_total = sum(active) if active else 0
        # Fragment meta can temporarily return zeros/fallback payloads; in this case
        # use observed local aggregates to avoid frozen "0 sold" in UI.
        total_for_sale = source_for_sale if source_for_sale > 0 else active_total
        total_sold = source_sold if source_sold > 0 else trades_total
        variants_count = len(variants)
        gifts_count = active_total
        signals_quality_degraded = _signals_quality_degraded(
            variants_count=variants_count,
            gifts_count=gifts_count,
            model_count=len(models),
        )
        if signals_quality_degraded:
            buy_signals = 0
            sell_signals = 0

        payload = {
            "updated_at": state_updated_at,
            "variant_count": variants_count,
            "gifts_count": gifts_count,
            "base_count": len({v["base_id"] for v in variants}),
            "model_count": len(models),
            "floor_ton_min": min(floors) if floors else None,
            "floor_ton_median": _safe_median(floors) if floors else None,
            "active_listings": active_total,
            "avg_change_7d": round(avg_7d, 3),
            "avg_change_30d": round(avg_30d, 3),
            "market_state": market_state,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "signals_quality_degraded": signals_quality_degraded,
            "signals_quality_reason": (
                "variants_to_gifts_ratio_too_low"
                if signals_quality_degraded
                else ""
            ),
            "anomalies": anomalies,
            "total_for_sale": int(total_for_sale),
            "total_sold": int(total_sold),
            "data_stale": self.is_stale(),
            "ingestion_lag_seconds": state_ingestion_lag,
            "last_error": state_last_error,
            "ingest_in_progress": state_ingest_in_progress,
            "last_ingest_started_at": state_last_ingest_started_at,
            # Runtime diagnostics for Render env drift / stale deploy checks.
            "runtime_source": os.getenv("VERIFIED_SOURCE", "telegram_api"),
            "runtime_gift_mode": os.getenv("FRAGMENT_GIFT_MODE", "lot"),
            "runtime_max_collections": int(os.getenv("FRAGMENT_MAX_COLLECTIONS", "0")),
            "runtime_max_pages_per_collection": int(os.getenv("FRAGMENT_MAX_PAGES_PER_COLLECTION", "500")),
            "runtime_verified_data_file": os.getenv("VERIFIED_DATA_FILE", "data/verified_gifts.json"),
            "key_metrics": {
                "volume24h_ton": round(
                    sum(float((v.get("metrics") or {}).get("volume_ton_24h", 0) or 0) for v in variants),
                    6,
                ),
                "avg_liquidity24h": round(
                    _safe_mean(float((v.get("metrics") or {}).get("liquidity_score_24h", 0) or 0) for v in variants),
                    4,
                ),
                "synth_floor_share": 0.0,
            },
            "provider_health": [
                {
                    "provider": os.getenv("VERIFIED_SOURCE", "telegram_api"),
                    "p95_ms": 0,
                    "err_pct": 0.0 if not state_last_error else 100.0,
                    "degraded": bool(state_last_error),
                    "ts": state_updated_at,
                }
            ],
        }
        self._cache_set(cache_key, payload)
        return payload

    def list_bases(self) -> List[dict]:
        self._ensure_recos()
        cache_key = ("list_bases",)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        bases = {}
        for v in self.variants.values():
            base_id = v["base_id"]
            b = bases.setdefault(base_id, {"base_id": base_id, "variants": []})
            b["variants"].append(v)
        stars_rate = self.stars_rate()
        out = []
        for base_id, payload in bases.items():
            variants = payload["variants"]
            floors = [x["metrics"]["floor_ton"] for x in variants]
            preview_url = next((x.get("preview_url") for x in variants if x.get("preview_url")), "")
            out.append(
                {
                    "base_id": base_id,
                    "name": self.bases.get(base_id).name if base_id in self.bases else base_id,
                    "slug": base_id,
                    "preview_url": preview_url,
                    "updated_at": self.state.get("updated_at"),
                    "metrics": {
                        "floor_ton": min(floors) if floors else None,
                        "floor_stars_est": self._stars_est(min(floors) if floors else None),
                        "active_listings": sum(x["metrics"]["active_listings"] for x in variants),
                        "floor_change_pct_1h": round(_safe_mean([x["metrics"].get("floor_change_pct_1h", 0) for x in variants]), 3),
                        "floor_change_pct_12h": round(_safe_mean([x["metrics"].get("floor_change_pct_12h", 0) for x in variants]), 3),
                        "price_change_pct_1h": round(_safe_mean([x["metrics"].get("price_change_pct_1h", 0) for x in variants]), 3),
                        "price_change_pct_12h": round(_safe_mean([x["metrics"].get("price_change_pct_12h", 0) for x in variants]), 3),
                        "trades_count_24h": sum(x["metrics"].get("trades_count_24h", 0) for x in variants),
                        "volume_ton_24h": round(sum(x["metrics"].get("volume_ton_24h", 0) for x in variants), 6),
                        "liquidity_score_24h": round(_safe_mean([x["metrics"].get("liquidity_score_24h", 0) for x in variants]), 4),
                        "volatility_24h": round(_safe_mean([x["metrics"].get("volatility_24h", 0) for x in variants]), 6),
                        "floor_change_pct_24h": round(_safe_mean([x["metrics"].get("floor_change_pct_24h", 0) for x in variants]), 3),
                        "price_change_pct_24h": round(_safe_mean([x["metrics"].get("price_change_pct_24h", 0) for x in variants]), 3),
                    },
                    "stars_rate": stars_rate,
                }
            )
        result = sorted(out, key=lambda x: x["base_id"])
        self._cache_set(cache_key, result)
        return result

    def get_base(self, base_id: str) -> dict | None:
        cache_key = ("get_base", base_id)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        base = next((b for b in self.list_bases() if b["base_id"] == base_id), None)
        self._cache_set(cache_key, base)
        return base

    def list_dimensions(self, base_id: str, dim_type: str, period: str) -> dict:
        self._ensure_recos()
        cache_key = ("list_dimensions", base_id, dim_type, period)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        items = [v for v in self.variants.values() if v["base_id"] == base_id]
        by_dim: Dict[str, List[dict]] = {}
        for v in items:
            key = v["traits"][dim_type]["id"]
            by_dim.setdefault(key, []).append(v)
        out = []
        for dim_id, variants in by_dim.items():
            floors = [x["metrics"]["floor_ton"] for x in variants]
            metrics = {
                "floor_ton": min(floors) if floors else None,
                "floor_stars_est": self._stars_est(min(floors) if floors else None),
                "floor_change_pct_1h": round(_safe_mean([x["metrics"].get("floor_change_pct_1h", 0) for x in variants]), 3),
                "floor_change_pct_12h": round(_safe_mean([x["metrics"].get("floor_change_pct_12h", 0) for x in variants]), 3),
                "price_change_pct_1h": round(_safe_mean([x["metrics"].get("price_change_pct_1h", 0) for x in variants]), 3),
                "price_change_pct_12h": round(_safe_mean([x["metrics"].get("price_change_pct_12h", 0) for x in variants]), 3),
                "floor_change_pct_24h": round(_safe_mean([x["metrics"].get("floor_change_pct_24h", 0) for x in variants]), 3),
                "price_change_pct_24h": round(_safe_mean([x["metrics"].get("price_change_pct_24h", 0) for x in variants]), 3),
                "active_listings": sum(x["metrics"]["active_listings"] for x in variants),
                "trades_count_24h": sum(x["metrics"].get("trades_count_24h", 0) for x in variants),
                "volume_ton_24h": round(sum(x["metrics"].get("volume_ton_24h", 0) for x in variants), 6),
                "liquidity_score_24h": round(_safe_mean([x["metrics"].get("liquidity_score_24h", 0) for x in variants]), 4),
                "volatility_24h": round(_safe_mean([x["metrics"].get("volatility_24h", 0) for x in variants]), 6),
            }
            reco = self._aggregate_reco(variants)
            out.append(
                {
                    "dim_id": dim_id,
                    "name": variants[0]["traits"][dim_type]["name"],
                    "metrics": metrics,
                    "reco": reco,
                }
            )
        result = {
            "base_id": base_id,
            "dim_type": dim_type,
            "period": period,
            "items": sorted(out, key=lambda x: x["dim_id"]),
        }
        self._cache_set(cache_key, result)
        return result

    def list_variants(self, base_id: str | None = None, filters: dict | None = None, sort: str = "reco_score_desc", page: int = 1, page_size: int = 50, include_ai: bool = False) -> dict:
        self._ensure_recos()
        filter_key = tuple(
            (
                tuple(sorted((filters or {}).get("model_id") or [])),
                tuple(sorted((filters or {}).get("background_id") or [])),
                tuple(sorted((filters or {}).get("pattern_id") or [])),
            )
        )
        cache_key = ("list_variants", base_id, filter_key, sort, page, page_size, bool(include_ai))
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        items = list(self.variants.values())
        if base_id:
            items = [x for x in items if x["base_id"] == base_id]
        if filters:
            for key, allowed in filters.items():
                if not allowed:
                    continue
                if key == "model_id":
                    items = [x for x in items if x["traits"]["model"]["id"] in allowed]
                if key == "background_id":
                    items = [x for x in items if x["traits"]["background"]["id"] in allowed]
                if key == "pattern_id":
                    items = [x for x in items if x["traits"]["pattern"]["id"] in allowed]

        items = self._sort_variants(items, sort)
        total = len(items)
        start = max(0, (page - 1) * page_size)
        end = start + page_size
        page_items = items[start:end]
        if include_ai and self.ai_pipeline_enabled:
            page_items = self._apply_ai_to_variant_list(page_items)
        else:
            page_items = [self._short_variant(v) for v in page_items]

        result = {
            "base_id": base_id,
            "filters": filters or {},
            "sort": sort,
            "page": page,
            "page_size": page_size,
            "total": total,
            "items": page_items,
        }
        # Cache only rules path; AI path depends on external cache/state and should stay fresh.
        if not include_ai:
            self._cache_set(cache_key, result)
        return result

    def _sort_variants(self, items: List[dict], sort: str) -> List[dict]:
        if sort == "floor_asc":
            return sorted(items, key=lambda x: x["metrics"].get("floor_ton") or 0)
        if sort == "floor_desc":
            return sorted(items, key=lambda x: x["metrics"].get("floor_ton") or 0, reverse=True)
        if sort == "reco_score_desc":
            return sorted(items, key=lambda x: x.get("reco", {}).get("reco_score", 0), reverse=True)
        return items

    def _apply_ai_to_variant_list(self, items: List[dict], live_limit: int | None = None) -> List[dict]:
        if not items:
            return []
        out: List[dict] = []
        limit = self.ai_pipeline_live_per_request if live_limit is None else max(0, live_limit)
        for idx, item in enumerate(items):
            base_payload = self._short_variant(item)
            allow_live = idx < limit
            if self.ai_pipeline_enabled:
                base_payload["reco"] = self._ai_enrich_reco(base_payload, allow_live=allow_live)
            out.append(base_payload)
        return out

    def get_variant(self, variant_id: str) -> dict | None:
        if variant_id in self.variants:
            v = self.variants[variant_id]
            payload = {
                "variant_id": variant_id,
                "base_id": v["base_id"],
                "fragment_url": self._variant_fragment_url(variant_id),
                "traits": v["traits"],
                "preview_url": v["preview_url"],
                "updated_at": v["updated_at"],
                "metrics": self._decorate_metrics(v["metrics"]),
                "reco": v.get("reco"),
                "stars_rate": self.stars_rate(),
            }
            payload["reco"] = self._ai_enrich_reco(payload, allow_live=True)
            return payload
        mapping = self._listing_to_variant(variant_id)
        if mapping and mapping in self.variants:
            return self.get_variant(mapping)
        return None

    def _ai_enrich_reco(self, variant_payload: dict, allow_live: bool = True) -> dict:
        base_reco = dict(variant_payload.get("reco") or {})
        self._prune_ai_cache(force=False)
        if not self.ai_enabled:
            base_reco["source"] = "rules"
            base_reco["ai_debug"] = {"enabled": False, "reason": "AI_RECO_ENABLED=false"}
            return base_reco
        if self.ai_key_rejected:
            base_reco["source"] = "rules_fallback"
            base_reco["ai_debug"] = {"enabled": True, "reason": "OPENAI_API_KEY rejected"}
            return base_reco
        api_key = _sanitize_openai_key(os.getenv("OPENAI_API_KEY", ""))
        if not api_key:
            base_reco["source"] = "rules"
            base_reco["ai_debug"] = {"enabled": True, "reason": "OPENAI_API_KEY is empty"}
            return base_reco

        cache_key = self._ai_cache_key(variant_payload)
        cached = self.ai_reco_cache.get(cache_key)
        now_ts = int(_now().timestamp())
        if isinstance(cached, dict) and int(cached.get("expires_at_ts", 0)) > now_ts:
            reco = dict(base_reco)
            reco.update(cached.get("reco") or {})
            reco["source"] = "ai_cached"
            reco["ai_debug"] = {"enabled": True, "cached": True}
            return reco

        if not allow_live:
            base_reco["source"] = "rules_fallback"
            base_reco["ai_debug"] = {"enabled": True, "reason": "AI_WARMUP_PENDING"}
            return base_reco

        now_mono = time.monotonic()
        if now_mono < self.ai_cooldown_until_mono:
            base_reco["source"] = "rules_fallback"
            base_reco["ai_debug"] = {
                "enabled": True,
                "reason": "AI_COOLDOWN_ACTIVE",
                "cooldown_sec_left": round(self.ai_cooldown_until_mono - now_mono, 1),
            }
            return base_reco

        leader = False
        wait_event: threading.Event | None = None
        with self.ai_inflight_lock:
            existing = self.ai_inflight.get(cache_key)
            if existing is None:
                wait_event = threading.Event()
                self.ai_inflight[cache_key] = wait_event
                leader = True
            else:
                wait_event = existing

        if not leader and wait_event is not None:
            wait_event.wait(timeout=max(1.0, self.ai_timeout_sec + 2.0))
            cached_after = self.ai_reco_cache.get(cache_key)
            now_ts = int(_now().timestamp())
            if isinstance(cached_after, dict) and int(cached_after.get("expires_at_ts", 0)) > now_ts:
                reco = dict(base_reco)
                reco.update(cached_after.get("reco") or {})
                reco["source"] = "ai_cached"
                reco["ai_debug"] = {"enabled": True, "cached": True, "coalesced": True}
                return reco
            base_reco["source"] = "rules_fallback"
            base_reco["ai_debug"] = {"enabled": True, "reason": "AI_INFLIGHT_TIMEOUT"}
            return base_reco

        try:
            ai_reco = self._fetch_ai_reco(variant_payload, api_key)
            if not ai_reco:
                base_reco["source"] = "rules_fallback"
                base_reco["ai_debug"] = {"enabled": True, "error": self.ai_last_error or "AI_EMPTY_RESPONSE"}
                return base_reco

            self.ai_reco_cache[cache_key] = {
                "reco": ai_reco,
                "expires_at_ts": now_ts + self.ai_cache_ttl_sec,
                "saved_at": _iso(_now()),
            }
            self.ai_cache_dirty = True
            self._save_ai_cache(force=False)

            reco = dict(base_reco)
            reco.update(ai_reco)
            reco["source"] = "ai_live"
            reco["ai_debug"] = {"enabled": True, "cached": False}
            return reco
        finally:
            with self.ai_inflight_lock:
                ev = self.ai_inflight.pop(cache_key, None)
                if ev:
                    ev.set()

    def ai_status(self, probe: bool = False) -> dict:
        self._prune_ai_cache(force=False)
        api_key = _sanitize_openai_key(os.getenv("OPENAI_API_KEY", ""))
        now_ts = int(time.time())
        valid_cache = sum(
            1
            for x in self.ai_reco_cache.values()
            if isinstance(x, dict) and int(x.get("expires_at_ts", 0) or 0) > now_ts
        )
        status = {
            "enabled": self.ai_enabled,
            "pipeline_enabled": self.ai_pipeline_enabled,
            "model": self.ai_model,
            "api_key_present": bool(api_key),
            "cache_entries_total": len(self.ai_reco_cache),
            "cache_entries_valid": valid_cache,
            "next_allowed_in_sec": max(0.0, self.ai_next_allowed_ts - time.monotonic()),
            "last_error": self.ai_last_error or "",
            "key_rejected": self.ai_key_rejected,
            "fallback_reason": None,
            "probe": None,
        }
        if not self.ai_enabled:
            status["fallback_reason"] = "AI_RECO_ENABLED=false"
            return status
        if not api_key:
            status["fallback_reason"] = "OPENAI_API_KEY is empty"
            return status
        if not probe:
            return status

        cached_probe = self.ai_probe_cache or {}
        checked_at_ts = int(cached_probe.get("checked_at_ts", 0) or 0)
        cached_payload = cached_probe.get("payload")
        if cached_payload and (now_ts - checked_at_ts) < self.ai_status_probe_ttl_sec:
            status["probe"] = cached_payload
            return status

        probe_payload = self._probe_ai()
        self.ai_probe_cache = {"checked_at_ts": now_ts, "payload": probe_payload}
        status["probe"] = probe_payload
        return status

    def _probe_ai(self) -> dict:
        api_key = _sanitize_openai_key(os.getenv("OPENAI_API_KEY", ""))
        if not api_key:
            return {"ok": False, "error": "OPENAI_API_KEY is empty"}
        req = urllib.request.Request("https://api.openai.com/v1/models", method="GET")
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Accept", "application/json")
        ctx = ssl._create_unverified_context() if self.ai_ssl_no_verify else None
        try:
            try:
                with urllib.request.urlopen(req, timeout=min(12, self.ai_timeout_sec), context=ctx) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                # Local macOS/python CA chains are sometimes missing in this environment.
                # Auto-fallback to unverified context for liveness probe only.
                if (not self.ai_ssl_no_verify) and ("CERTIFICATE_VERIFY_FAILED" in str(e)):
                    with urllib.request.urlopen(req, timeout=min(12, self.ai_timeout_sec), context=ssl._create_unverified_context()) as resp:
                        payload = json.loads(resp.read().decode("utf-8"))
                else:
                    raise
            models = payload.get("data") if isinstance(payload, dict) else []
            model_ids = [str(m.get("id")) for m in (models or []) if isinstance(m, dict)]
            return {"ok": True, "models_count": len(model_ids), "model_visible": self.ai_model in model_ids}
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                body = ""
            if e.code == 401:
                self.ai_key_rejected = True
            return {"ok": False, "status": e.code, "error": body or "http_error"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _ai_cache_key(self, variant_payload: dict) -> str:
        metrics = variant_payload.get("metrics") or {}
        fingerprint = "|".join(
            [
                str(variant_payload.get("variant_id", "")),
                str(metrics.get("floor_ton", "")),
                str(metrics.get("floor_change_pct_24h", "")),
                str(metrics.get("active_listings", "")),
                str(metrics.get("trades_count_24h", "")),
                str(metrics.get("volume_ton_24h", "")),
            ]
        )
        return fingerprint

    def _fetch_ai_reco(self, variant_payload: dict, api_key: str) -> dict | None:
        metrics = variant_payload.get("metrics") or {}
        traits = variant_payload.get("traits") or {}
        system_prompt = (
            "You are a market analyst for Telegram Fragment gifts. "
            "Output only compact JSON with keys: action, reco_score, confidence, reasons, risks. "
            "action must be one of BUY,HOLD,SELL,WATCH,AVOID. "
            "reasons and risks must be arrays of short Russian strings."
        )
        user_payload = {
            "variant_id": variant_payload.get("variant_id"),
            "base_id": variant_payload.get("base_id"),
            "traits": traits,
            "metrics": {
                "floor_ton": metrics.get("floor_ton"),
                "floor_change_pct_24h": metrics.get("floor_change_pct_24h"),
                "active_listings": metrics.get("active_listings"),
                "trades_count_24h": metrics.get("trades_count_24h"),
                "volume_ton_24h": metrics.get("volume_ton_24h"),
                "liquidity_score_24h": metrics.get("liquidity_score_24h"),
                "volatility_24h": metrics.get("volatility_24h"),
                "thin_market_risk_24h": metrics.get("thin_market_risk_24h"),
                "pump_risk_24h": metrics.get("pump_risk_24h"),
            },
        }
        body = {
            "model": self.ai_model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
        }
        raw = None
        ctx = ssl._create_unverified_context() if self.ai_ssl_no_verify else None
        max_attempts = max(1, self.ai_max_retries + 1)
        for attempt in range(max_attempts):
            with self.ai_lock:
                wait_sec = max(0.0, self.ai_next_allowed_ts - time.monotonic())
            if wait_sec > 0:
                time.sleep(wait_sec)

            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {api_key}")
            with self.ai_lock:
                self.ai_next_allowed_ts = max(self.ai_next_allowed_ts, time.monotonic()) + max(0.0, self.ai_min_interval_sec)
            try:
                try:
                    with urllib.request.urlopen(req, timeout=self.ai_timeout_sec, context=ctx) as resp:
                        raw = json.loads(resp.read().decode("utf-8"))
                except Exception as e:
                    if (not self.ai_ssl_no_verify) and ("CERTIFICATE_VERIFY_FAILED" in str(e)):
                        with urllib.request.urlopen(req, timeout=self.ai_timeout_sec, context=ssl._create_unverified_context()) as resp:
                            raw = json.loads(resp.read().decode("utf-8"))
                    else:
                        raise
                break
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", errors="replace")[:300]
                except Exception:
                    err_body = ""
                if e.code == 401:
                    self.ai_key_rejected = True
                retry_after = self._retry_after_sec(e)
                if e.code == 429 and attempt + 1 < max_attempts:
                    sleep_sec = retry_after if retry_after is not None else min(10.0, self.ai_retry_backoff_sec * (2 ** attempt))
                    self.ai_last_error = f"OPENAI_HTTP_429_RETRY attempt={attempt + 1}/{max_attempts} sleep={sleep_sec:.1f}s"
                    time.sleep(max(0.0, sleep_sec))
                    continue
                if 500 <= e.code < 600 and attempt + 1 < max_attempts:
                    sleep_sec = retry_after if retry_after is not None else min(10.0, self.ai_retry_backoff_sec * (2 ** attempt))
                    self.ai_last_error = f"OPENAI_HTTP_{e.code}_RETRY attempt={attempt + 1}/{max_attempts} sleep={sleep_sec:.1f}s"
                    time.sleep(max(0.0, sleep_sec))
                    continue
                self.ai_last_error = f"OPENAI_HTTP_ERROR: status={e.code} body={err_body}"
                self._mark_ai_failure()
                return None
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                if attempt + 1 < max_attempts:
                    sleep_sec = min(10.0, self.ai_retry_backoff_sec * (2 ** attempt))
                    self.ai_last_error = f"OPENAI_NET_RETRY attempt={attempt + 1}/{max_attempts} sleep={sleep_sec:.1f}s err={e}"
                    time.sleep(max(0.0, sleep_sec))
                    continue
                self.ai_last_error = f"OPENAI_HTTP_ERROR: {e}"
                self._mark_ai_failure()
                return None
        if not isinstance(raw, dict):
            self.ai_last_error = "OPENAI_EMPTY_RESPONSE"
            self._mark_ai_failure()
            return None

        try:
            text = raw["choices"][0]["message"]["content"]
            parsed = self._parse_ai_json(text)
            if not isinstance(parsed, dict):
                self.ai_last_error = "OPENAI_PARSE_ERROR: response is not JSON object"
                self._mark_ai_failure()
                return None
        except Exception as e:
            self.ai_last_error = f"OPENAI_PARSE_ERROR: {e}"
            self._mark_ai_failure()
            return None

        action = str(parsed.get("action", "HOLD")).upper()
        if action not in {"BUY", "HOLD", "SELL", "WATCH", "AVOID"}:
            action = "HOLD"
        reco_score = float(parsed.get("reco_score", 50))
        confidence = int(parsed.get("confidence", 60))
        reasons_raw = parsed.get("reasons") or []
        risks_raw = parsed.get("risks") or []
        reasons = [
            {"code": "R_AI", "text": str(x).strip()[:220]}
            for x in reasons_raw
            if str(x).strip()
        ][:6]
        risks = [
            {"code": "K_AI", "text": str(x).strip()[:220]}
            for x in risks_raw
            if str(x).strip()
        ][:5]
        self._mark_ai_success()
        return {
            "action": action,
            "reco_score": round(_clamp(reco_score, 0, 100), 1),
            "confidence": int(_clamp(confidence, 0, 100)),
            "reasons": reasons,
            "risks": risks,
        }

    def _mark_ai_failure(self) -> None:
        self.ai_failure_streak = min(8, int(self.ai_failure_streak or 0) + 1)
        cooldown = min(
            max(1.0, self.ai_cooldown_max_sec),
            max(1.0, self.ai_cooldown_base_sec) * (2 ** max(0, self.ai_failure_streak - 1)),
        )
        self.ai_cooldown_until_mono = time.monotonic() + cooldown

    def _mark_ai_success(self) -> None:
        self.ai_failure_streak = 0
        self.ai_cooldown_until_mono = 0.0

    def _parse_ai_json(self, text: str):
        try:
            return json.loads(text)
        except Exception:
            pass
        m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S | re.I)
        if m:
            return json.loads(m.group(1))
        m2 = re.search(r"(\{.*\})", text, re.S)
        if m2:
            return json.loads(m2.group(1))
        raise ValueError("AI JSON payload not found")

    def _retry_after_sec(self, exc: urllib.error.HTTPError) -> float | None:
        try:
            value = (exc.headers.get("Retry-After") or "").strip()
            if not value:
                return None
            return max(0.0, float(value))
        except Exception:
            return None

    def list_variant_listings(self, variant_id: str) -> dict:
        v_id = self._listing_to_variant(variant_id) or variant_id
        items = []
        for listing in self.listing_state.values():
            if listing.get("variant_id") != v_id:
                continue
            items.append(
                {
                    "listing_id": listing.get("listing_id"),
                    "sale_type": listing.get("sale_type"),
                    "status": listing.get("status"),
                    "price_ton": listing.get("price_ton"),
                    "price_stars_est": self._stars_est(listing.get("price_ton")),
                    "seller_id": listing.get("seller_id"),
                    "end_at": listing.get("end_at"),
                    "auction": listing.get("auction"),
                }
            )
        items.sort(key=lambda x: float(x.get("price_ton") or 0.0))
        return {
            "variant_id": v_id,
            "updated_at": self.state.get("updated_at"),
            "items": items,
            "stars_rate": self.stars_rate(),
        }

    def _variant_fragment_url(self, variant_id: str) -> str:
        listings = [
            x for x in self.listing_state.values()
            if x.get("variant_id") == variant_id and x.get("status") == "ACTIVE"
        ]
        if listings:
            best = min(listings, key=lambda x: float(x.get("price_ton") or 0.0))
            listing_id = str(best.get("listing_id") or "").strip()
            if listing_id:
                return f"https://fragment.com/gift/{listing_id}?sort=price"
        return f"https://fragment.com/gifts/{variant_id.split('|', 1)[0]}?sort=price&filter=sale"

    def list_variant_timeseries(self, variant_id: str, metric: str, period: str) -> dict:
        v_id = self._listing_to_variant(variant_id) or variant_id
        history = self.variant_history.get(v_id, [])
        seconds = WINDOWS.get(period, WINDOWS["24h"])
        cutoff = _now() - timedelta(seconds=seconds)
        step_sec = 300 if period in {"1h", "12h", "24h"} else 3600
        points = []
        bucket = {}
        for h in history:
            ts = _parse_ts(h.get("ts"))
            if ts < cutoff:
                continue
            key = int(ts.timestamp() // step_sec * step_sec)
            bucket.setdefault(key, h)
        for key in sorted(bucket.keys()):
            h = bucket[key]
            value = h.get("floor_ton") if metric == "floor" else h.get("active_listings")
            points.append({"ts": _iso(datetime.fromtimestamp(key, tz=timezone.utc)), "value_ton": value, "value_stars_est": self._stars_est(value)})
        return {
            "variant_id": v_id,
            "metric": metric,
            "period": period,
            "step": "5m" if step_sec == 300 else "1h",
            "points": points,
            "stars_rate": self.stars_rate(),
        }

    def screeners(self, screener: str, entity: str, period: str, metric_type: str, include_ai: bool = False) -> dict:
        cache_key = ("screeners", screener, entity, period, metric_type, bool(include_ai))
        if not include_ai:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached
        with self.lock:
            items = list(self.variants.values())
            updated_at = self.state.get("updated_at")
        if entity != "variant":
            items = list(items)
        key = f"floor_change_pct_{period}"
        if period not in WINDOWS:
            key = "floor_change_pct_24h"
        if screener == "top-movers":
            items = sorted(items, key=lambda x: x["metrics"].get(key, 0), reverse=True)
        elif screener == "supply-shock":
            items = sorted(items, key=lambda x: x["metrics"].get("supply_change_pct_24h", 0))
        elif screener == "overheat":
            items = sorted(items, key=lambda x: x["metrics"].get("pump_risk_24h", 0), reverse=True)
        else:
            items = []
        top_items = items[:50]
        if include_ai and self.ai_pipeline_enabled:
            top_items = self._apply_ai_to_variant_list(top_items)
        else:
            top_items = [self._short_variant(v) for v in top_items]
        payload = {
            "entity": entity,
            "period": period,
            "type": metric_type,
            "updated_at": updated_at,
            "items": top_items,
            "stars_rate": self.stars_rate(),
        }
        if not include_ai:
            self._cache_set(cache_key, payload)
        return payload

    def recommendations(self, scope: str, entity: str, include_ai: bool = False) -> dict:
        cache_key = ("recommendations", scope, entity, bool(include_ai))
        if not include_ai:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached
        with self.lock:
            items = list(self.variants.values())
            updated_at = self.state.get("updated_at")
        if scope == "watchlist":
            watch = _load_json(FAVORITES_FILE, {}).get("default", [])
            items = [v for v in items if v["variant_id"] in watch]
        items = sorted(items, key=lambda x: x.get("reco", {}).get("reco_score", 0), reverse=True)
        selected = items[:50]
        if include_ai and self.ai_pipeline_enabled:
            selected_payload = self._apply_ai_to_variant_list(selected)
            rec_items = []
            for p in selected_payload:
                reco = p.get("reco") or {}
                rec_items.append(
                    {
                        "variant_id": p.get("variant_id"),
                        "base_id": p.get("base_id"),
                        "title": p.get("title"),
                        "preview_url": p.get("preview_url"),
                        "action": reco.get("action"),
                        "reco_score": reco.get("reco_score"),
                        "confidence": reco.get("confidence"),
                        "reasons": reco.get("reasons"),
                        "risks": reco.get("risks"),
                        "forecast": reco.get("forecast"),
                        "summary": reco.get("summary"),
                        "source": reco.get("source"),
                        "ai_debug": reco.get("ai_debug"),
                        "floor_change_pct_24h": (p.get("metrics") or {}).get("floor_change_pct_24h"),
                        "floor_ton": (p.get("metrics") or {}).get("floor_ton"),
                    }
                )
        else:
            rec_items = [self._short_reco(v) for v in selected]
        payload = {
            "scope": scope,
            "entity": entity,
            "updated_at": updated_at,
            "items": rec_items,
        }
        if not include_ai:
            self._cache_set(cache_key, payload)
        return payload

    def signals_latest(self, action: str = "all", limit: int = 1000) -> dict:
        self._ensure_recos()
        action_norm = str(action or "all").strip().lower()
        if action_norm not in {"all", "buy", "sell"}:
            action_norm = "all"
        lim = max(1, min(int(limit or 1000), 5000))
        cache_key = ("signals_latest", action_norm, lim)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        with self.lock:
            variants = list(self.variants.values())
            updated_at = self.state.get("updated_at")
        gifts_count = sum(int((v.get("metrics") or {}).get("active_listings", 0) or 0) for v in variants)
        variants_count = len(variants)
        models_count = len(
            {
                (v.get("traits") or {}).get("model", {}).get("id")
                for v in variants
                if (v.get("traits") or {}).get("model", {}).get("id")
            }
        )
        signals_quality_degraded = _signals_quality_degraded(
            variants_count=variants_count,
            gifts_count=gifts_count,
            model_count=models_count,
        )
        if signals_quality_degraded:
            payload = {
                "updated_at": updated_at,
                "filter": action_norm,
                "total": 0,
                "buy_total": 0,
                "sell_total": 0,
                "signals_quality_degraded": True,
                "signals_quality_reason": "variants_to_gifts_ratio_too_low",
                "items": [],
            }
            self._cache_set(cache_key, payload)
            return payload
        buy_total = sum(1 for v in variants if str((v.get("reco") or {}).get("action", "")).upper() == "BUY")
        sell_total = sum(1 for v in variants if str((v.get("reco") or {}).get("action", "")).upper() == "SELL")

        selected = []
        for v in variants:
            a = str((v.get("reco") or {}).get("action", "")).upper()
            if a not in {"BUY", "SELL"}:
                continue
            if action_norm == "buy" and a != "BUY":
                continue
            if action_norm == "sell" and a != "SELL":
                continue
            selected.append(v)
        selected = sorted(selected, key=lambda x: float((x.get("reco") or {}).get("reco_score", 0) or 0), reverse=True)
        items = [self._short_variant(v) for v in selected[:lim]]
        payload = {
            "updated_at": updated_at,
            "filter": action_norm,
            "total": len(selected),
            "buy_total": buy_total,
            "sell_total": sell_total,
            "signals_quality_degraded": False,
            "signals_quality_reason": "",
            "items": items,
        }
        self._cache_set(cache_key, payload)
        return payload

    def alerts_list(self) -> List[dict]:
        return self.alert_rules

    def alerts_create(self, rule: dict) -> dict:
        rule_id = rule.get("id") or f"alert_{int(time.time())}"
        record = {"id": rule_id, "rule_json": rule, "last_fired_at": None, "last_payload_json": None}
        self.alert_rules.append(record)
        self._save_alerts()
        return record

    def alerts_update(self, alert_id: str, rule: dict) -> dict | None:
        for r in self.alert_rules:
            if r.get("id") == alert_id:
                r["rule_json"] = rule
                self._save_alerts()
                return r
        return None

    def alerts_delete(self, alert_id: str) -> bool:
        before = len(self.alert_rules)
        self.alert_rules = [r for r in self.alert_rules if r.get("id") != alert_id]
        self._save_alerts()
        return len(self.alert_rules) < before

    def favorites_list(self, user_key: str = "default") -> List[dict]:
        data = _load_json(FAVORITES_FILE, {})
        rows = data.get(user_key) or []
        if not isinstance(rows, list):
            return []
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            variant_id = str(row.get("variant_id") or "").strip()
            if not variant_id:
                continue
            out.append(
                {
                    "variant_id": variant_id,
                    "note": row.get("note"),
                    "created_at": row.get("created_at") or _iso(_now()),
                }
            )
        return out

    def favorite_upsert(self, user_key: str, variant_id: str, note: str | None = None) -> dict:
        data = _load_json(FAVORITES_FILE, {})
        rows = data.get(user_key) or []
        if not isinstance(rows, list):
            rows = []
        now_iso = _iso(_now())
        found = False
        for row in rows:
            if str(row.get("variant_id") or "") == variant_id:
                row["note"] = note
                row["created_at"] = row.get("created_at") or now_iso
                found = True
                break
        if not found:
            rows.append({"variant_id": variant_id, "note": note, "created_at": now_iso})
        data[user_key] = rows
        _save_json(FAVORITES_FILE, data)
        return {"ok": True}

    def favorite_delete(self, user_key: str, variant_id: str) -> dict:
        data = _load_json(FAVORITES_FILE, {})
        rows = data.get(user_key) or []
        if not isinstance(rows, list):
            rows = []
        rows = [x for x in rows if str((x or {}).get("variant_id") or "") != variant_id]
        data[user_key] = rows
        _save_json(FAVORITES_FILE, data)
        return {"ok": True}

    def _legacy_action_norm(self, action: str | None) -> str:
        raw = str(action or "").upper()
        if raw == "BUY":
            return "BUY"
        if raw == "SELL":
            return "SELL"
        if raw in {"WATCH", "HOLD"}:
            return "WATCH"
        return "SKIP"

    def _legacy_reasons_and_risks(self, reco: dict) -> tuple[list[str], list[str]]:
        reasons_out: list[str] = []
        for row in (reco.get("reasons") or []):
            if isinstance(row, dict):
                txt = str(row.get("text") or row.get("title") or "").strip()
            else:
                txt = str(row or "").strip()
            if txt:
                reasons_out.append(txt)
        risks_out: list[str] = []
        for row in (reco.get("risks") or []):
            if isinstance(row, dict):
                code = str(row.get("code") or row.get("title") or "").strip()
            else:
                code = str(row or "").strip()
            if code:
                risks_out.append(code)
        return reasons_out[:4], risks_out[:4]

    def _metric_interval_to_seconds(self, interval: str | None) -> int:
        raw = str(interval or "1m").strip().lower()
        mapping = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "1h": 3600,
            "6h": 21600,
            "24h": 86400,
        }
        return mapping.get(raw, 60)

    def _strict_formula_inputs(self, v: dict) -> dict:
        metrics = v.get("metrics") or {}
        variant_id = str(v.get("variant_id") or "")
        now = _now()
        floor_ton = float(metrics.get("floor_ton") or 0.0)
        price_ton = floor_ton
        median_24h = float(metrics.get("median_ton") or 0.0)
        if median_24h <= 0:
            median_24h = float(metrics.get("vwap_ton_24h") or metrics.get("vwap_ton") or floor_ton)
        fair_ton = (0.7 * median_24h) + (0.3 * floor_ton) if (median_24h > 0 or floor_ton > 0) else 0.0
        undervalue = ((fair_ton - price_ton) / fair_ton) if fair_ton > 0 else 0.0

        sales24h = int(metrics.get("trades_count_24h") or 0)
        active_lots = int(metrics.get("active_listings") or 0)
        listing_pressure = active_lots / max(sales24h, 1)
        listing_pressure_norm = _clamp(listing_pressure / 3.0, 0.0, 1.0)

        sales30m, volume30m = self._trades_in_window(variant_id, now, 1800)
        _, volume10m = self._trades_in_window(variant_id, now, 600)
        denom = (volume30m / 3.0) if volume30m > 0 else 0.0
        volume_velocity = (volume10m / denom) if denom > 0 else 0.0
        volume_velocity_norm = _clamp(volume_velocity / 2.0, 0.0, 1.0)

        new_listings30m = self._new_listings_in_window(variant_id, now, 1800)
        absorption_rate = sales30m / max(new_listings30m, 1)
        absorption_rate_norm = _clamp(absorption_rate / 2.0, 0.0, 1.0)

        liquidity_score = _clamp(sales24h / 1000.0, 0.0, 1.0)

        hist = self.variant_history.get(variant_id, [])
        cutoff = now - timedelta(seconds=WINDOWS["24h"])
        floors: list[float] = [float(h.get("floor_ton") or 0.0) for h in hist if _parse_ts(h.get("ts")) >= cutoff and float(h.get("floor_ton") or 0.0) > 0]
        log_returns: list[float] = []
        for idx in range(1, len(floors)):
            prev = floors[idx - 1]
            cur = floors[idx]
            if prev > 0 and cur > 0:
                try:
                    log_returns.append(math.log(cur / prev))
                except Exception:
                    continue
        volatility = float(_safe_pstdev(log_returns) * math.sqrt(len(log_returns))) if len(log_returns) > 1 else 0.0

        target_sell = min(fair_ton, floor_ton * 1.02) if floor_ton > 0 and fair_ton > 0 else max(fair_ton, floor_ton)
        expected_profit_pct = ((target_sell - price_ton) / price_ton - 0.03) if price_ton > 0 else 0.0

        edge_raw = (
            0.45 * _clamp(undervalue, 0.0, 1.0)
            + 0.25 * liquidity_score
            + 0.15 * volume_velocity_norm
            + 0.15 * absorption_rate_norm
            - 0.2 * listing_pressure_norm
        )
        edge_score = _clamp(edge_raw, 0.0, 1.0)
        score100 = round(edge_score * 100.0, 1)
        confidence = _clamp(0.30 + 0.70 * min(1.0, sales24h / 50.0), 0.0, 1.0)
        conf_pct = round(confidence * 100.0, 1)

        return {
            "active_lots": active_lots,
            "price_ton": round(price_ton, 6),
            "floor_ton": round(floor_ton, 6),
            "floor_type": "real",
            "median_ton": round(median_24h, 6),
            "fair_ton": round(fair_ton, 6),
            "undervalue": round(undervalue, 6),
            "trend_t": round(_clamp((volume_velocity_norm + absorption_rate_norm) / 2.0, 0.0, 1.0), 6),
            "liq_score": round(liquidity_score, 6),
            "risk_pen": round(0.2 * listing_pressure_norm, 6),
            "score": round(edge_score, 6),
            "score100": score100,
            "confidence": round(confidence, 6),
            "conf_pct": conf_pct,
            "expected_profit_pct": round(expected_profit_pct, 6),
            "forecast24h_pct_min": 0.0,
            "forecast24h_pct_max": 0.0,
            "liquidity24h": round(liquidity_score, 6),
            "reasons": [
                f"Undervalue: {round(undervalue * 100.0, 2)}%.",
                f"Absorption rate 30m: {round(absorption_rate, 3)}.",
                f"Volume velocity 10m/30m: {round(volume_velocity, 3)}.",
            ],
            "risk_flags": [],
            "action_hint": "WATCH",
            "forecast_confidence": round(confidence, 6),
            "sell_pressure": round(listing_pressure_norm, 6),
            "sales24h": sales24h,
            "liq6h": round(sales24h / 6.0, 6),
            "vol30m": round(volume30m, 6),
            "listing_pressure": round(listing_pressure, 6),
            "listing_pressure_norm": round(listing_pressure_norm, 6),
            "volume_velocity": round(volume_velocity, 6),
            "volume_velocity_norm": round(volume_velocity_norm, 6),
            "absorption_rate": round(absorption_rate, 6),
            "absorption_rate_norm": round(absorption_rate_norm, 6),
            "volatility": round(volatility, 6),
            "new_listings_30m": int(new_listings30m),
            "sales30m": int(sales30m),
            "volume10m_ton": round(volume10m, 6),
            "volume30m_ton": round(volume30m, 6),
        }

    def _tz_signal_math_strict(self, v: dict) -> dict:
        mm = self._strict_formula_inputs(v)
        score = float(mm.get("score") or 0.0)
        expected = float(mm.get("expected_profit_pct") or 0.0)
        lp_norm = float(mm.get("listing_pressure_norm") or 0.0)
        ar_norm = float(mm.get("absorption_rate_norm") or 0.0)
        vol = float(mm.get("volatility") or 0.0)
        liq = float(mm.get("liq_score") or 0.0)
        conf = float(mm.get("confidence") or 0.0)

        center = (score - 0.5) * 0.38 + (0.07 * ar_norm) - (0.10 * lp_norm)
        spread = _clamp(0.06 + (0.16 * (1.0 - liq)) + (0.08 * min(1.0, vol)), 0.05, 0.32)
        forecast_min = _clamp(center - spread, -0.55, 0.55)
        forecast_max = _clamp(center + spread, -0.55, 0.55)

        risk_flags = list(mm.get("risk_flags") or [])
        if float(mm.get("sales24h") or 0) < 5:
            risk_flags.append("THIN_LIQUIDITY")
        if float(mm.get("listing_pressure") or 0.0) > 2.5:
            risk_flags.append("HIGH_LISTING_PRESSURE")
        mm["risk_flags"] = sorted(set(risk_flags))

        score100 = float(mm.get("score100") or 0.0)
        if score100 >= 80 and expected > 0:
            action = "BUY"
        elif score100 < 40 and forecast_max < 0:
            action = "SELL"
        elif score100 >= 40:
            action = "WATCH"
        else:
            action = "SKIP"

        mm["action_hint"] = action
        mm["forecast24h_pct_min"] = round(forecast_min * 100.0, 1)
        mm["forecast24h_pct_max"] = round(forecast_max * 100.0, 1)
        mm["forecast_confidence"] = round(conf, 6)
        return mm

    def _tz_signal_math(self, v: dict) -> dict:
        metrics = v.get("metrics") or {}
        active_lots = int(metrics.get("active_listings") or 0)
        variant_floor_ton = float(metrics.get("floor_ton") or 0.0)
        vwap_24h = float(metrics.get("vwap_ton_24h") or metrics.get("vwap_ton") or 0.0)
        median_24h_raw = float(metrics.get("median_ton") or 0.0)
        base_id = str(v.get("base_id") or "")
        base_obj = self.get_base(base_id) or {}
        base_metrics = (base_obj.get("metrics") or {}) if isinstance(base_obj, dict) else {}
        collection_floor_ton = float(base_metrics.get("floor_ton") or 0.0)
        floor_ton = collection_floor_ton if collection_floor_ton > 0 else variant_floor_ton
        price_ton = variant_floor_ton if variant_floor_ton > 0 else floor_ton
        supply_s = int(base_metrics.get("active_listings") or 0)
        floor_type = "real"
        sales24h = int(metrics.get("trades_count_24h") or 0)
        vol24h = float(metrics.get("volume_ton_24h") or 0.0)
        liquidity24h = _clamp(float(metrics.get("liquidity_score_24h") or 0.0), 0.0, 1.0)
        if sales24h <= 0 and vol24h > 0 and floor_ton > 0:
            sales24h = max(1, int(round(vol24h / max(floor_ton, 1e-6))))
        if sales24h <= 0 and liquidity24h > 0:
            sales24h = max(1, int(round(liquidity24h * 12)))
        liq6h = sales24h / 6.0
        trades_1h = float(metrics.get("trades_count_1h") or 0.0)
        if trades_1h > 0:
            vol30m = max(0.0, trades_1h * 0.5)
        else:
            vol30m = max(0.0, sales24h / 48.0)

        median24h = median_24h_raw
        median7d = float(metrics.get("median_ton_7d") or 0.0)
        if sales24h >= 10 and median24h > 0:
            m = median24h
        elif sales24h >= 10 and vwap_24h > 0:
            m = vwap_24h
        elif median7d > 0:
            m = median7d
        else:
            m = floor_ton

        # Fallback rarity proxy for sparse snapshots (serial metadata is not always present).
        prem_rarity = 0.0
        if active_lots <= 1:
            prem_rarity += 0.08
        elif active_lots <= 3:
            prem_rarity += 0.05
        elif active_lots <= 10:
            prem_rarity += 0.03
        prem_rarity = _clamp(prem_rarity, 0.0, 0.20)
        target_liq = 0.5
        pen_liq = _clamp((target_liq - liq6h) / target_liq, 0.0, 0.25)
        alpha = 0.7
        base = alpha * m + (1 - alpha) * floor_ton
        fair_ton = base * (1 + prem_rarity) * (1 - pen_liq)

        undervalue = 0.0
        if fair_ton > 0:
            undervalue = (fair_ton - price_ton) / fair_ton

        d_f = float(metrics.get("floor_change_pct_1h") or 0.0) / 200.0
        trend_raw = 0.6 * d_f + 0.4 * (math.log1p(max(0.0, vol30m)) / max(1e-6, math.log1p(20.0)))
        trend_raw = _clamp(trend_raw, -1.0, 1.0)
        trend_t = (trend_raw + 1.0) / 2.0

        lots_scale = max(1.0, (supply_s if supply_s > 0 else active_lots) / 1000.0)
        liq_score = _clamp(sales24h / lots_scale, 0.0, 1.0)

        risk_flags: List[str] = []
        risk_pen = 0.0
        if floor_type == "synthetic":
            risk_pen += 0.15
            risk_flags.append("SYNTH_FLOOR")
        if sales24h < 5:
            risk_pen += 0.06
            risk_flags.append("THIN_LIQUIDITY")
        if self.state.get("last_error"):
            risk_pen += 0.06
            risk_flags.append("PROVIDER_DEGRADED")
        if float(metrics.get("pump_risk_24h") or 0.0) > 0.8:
            risk_pen += 0.25
            risk_flags.append("EXEC_FAIL_SPIKE")

        u = _clamp(undervalue / 0.6, 0.0, 1.0)
        r = _clamp(prem_rarity / 0.8, 0.0, 1.0)
        risk_pen_eff = risk_pen
        if sales24h < 10 and undervalue > 0:
            risk_pen_eff *= 0.65
        score = _clamp(0.45 * u + 0.25 * r + 0.20 * trend_t + 0.10 * liq_score - risk_pen_eff, 0.0, 1.0)
        if sales24h < 10 and undervalue > 0:
            score = _clamp(score + min(0.10, undervalue * 0.25), 0.0, 1.0)
        score100 = round(score * 100.0, 1)

        confidence = _clamp(0.3 + 0.7 * min(1.0, sales24h / 30.0), 0.0, 1.0)
        if sales24h < 12 and undervalue > 0.015 and score >= 0.22:
            confidence = _clamp(confidence + min(0.06, 0.015 + (undervalue * 0.35)), 0.0, 1.0)
        conf_pct = round(confidence * 100.0, 1)

        # Use fair-based exit and apply fee as a floor cut, not as unconditional negative constant.
        target_sell = fair_ton * 0.98 if fair_ton > 0 else floor_ton
        if floor_ton > 0:
            # Do not bias target below observable market floor.
            target_sell = max(target_sell, floor_ton)
        expected_profit_pct = 0.0
        if price_ton > 0:
            gross_profit = (target_sell - price_ton) / price_ton
            expected_profit_pct = max(0.0, gross_profit - 0.03)

        lots_ma_7d = max(1.0, active_lots * (1.0 - (float(metrics.get("supply_change_pct_24h") or 0.0) / 100.0)))
        sales_ma_7d = max(1.0, float(metrics.get("trades_count_7d") or (sales24h * 5)))
        d_f_6h = _clamp((float(metrics.get("floor_change_pct_12h") or 0.0) / 2.0) / 100.0, -0.5, 0.5)
        d_f_24h = _clamp(float(metrics.get("floor_change_pct_24h") or 0.0) / 100.0, -0.8, 0.8)
        x1 = _clamp((active_lots - lots_ma_7d) / max(1.0, lots_ma_7d), -1.0, 2.0)
        x2 = _clamp((sales24h - sales_ma_7d) / max(1.0, sales_ma_7d), -1.0, 2.0)
        point_pred = -0.18 * x1 + 0.22 * x2 + 0.55 * d_f_6h + 0.35 * d_f_24h
        spread = 0.12 + 0.25 * _clamp(1.0 - liq_score, 0.0, 1.0) + (0.10 if floor_type == "synthetic" else 0.0)
        sparse_factor = _clamp((10.0 - float(sales24h)) / 10.0, 0.0, 1.0)
        point_pred = (point_pred * (1.0 - 0.55 * sparse_factor)) + (d_f_24h * 0.25 * sparse_factor)
        spread = spread * (1.0 - 0.35 * sparse_factor)
        # Adaptive forecast bounds: keep sparse/low-confidence variants from extreme ranges.
        volatility_cap = _clamp(0.22 + (0.28 * confidence) + (0.10 * (1.0 - sparse_factor)), 0.24, 0.55)
        lo_bound = -volatility_cap
        hi_bound = volatility_cap
        forecast_min = _clamp(point_pred - spread, lo_bound, hi_bound)
        forecast_max = _clamp(point_pred + spread, lo_bound, hi_bound)
        forecast_conf = _clamp(confidence + (0.10 if abs(point_pred) > 0.12 else 0.0) - (0.10 if floor_type == "synthetic" else 0.0), 0.0, 1.0)

        lots_ref = max(30.0, float(supply_s) / 150.0 if supply_s > 0 else 30.0)
        sell_pressure = _clamp((active_lots / lots_ref) - liquidity24h, 0.0, 1.0)

        reasons: List[str] = []
        if sales24h > 0:
            reasons.append(f"Сделок за 24h: {sales24h}, объем: {round(float(metrics.get('volume_ton_24h') or 0.0), 2)} TON.")
        reasons.append(f"Активных лотов: {active_lots}.")
        reasons.append(f"Ликвидность 24h: {round(liquidity24h, 2)}.")

        # Strong BUY: strict threshold from spec.
        if score >= 0.62 and undervalue >= 0.22 and expected_profit_pct >= 0.18 and forecast_max > -0.05:
            action_hint = "BUY"
        else:
            forecast_reliable = (confidence >= 0.60) or (sales24h >= 14)
            forecast_neg_strong = forecast_reliable and (forecast_max < -0.04)
            neutral_zone = (
                undervalue > 0.02
                and expected_profit_pct <= 0.0
                and 0.20 <= score <= 0.40
            )
            hard_sell = (
                (undervalue < -0.15 and forecast_neg_strong and score < 0.28 and sell_pressure > 0.50 and expected_profit_pct <= 0.0)
                or (undervalue < -0.24 and (forecast_max < 0.0) and score < 0.26 and sell_pressure > 0.50 and expected_profit_pct <= 0.0)
                or (forecast_reliable and forecast_max < -0.32 and score < 0.25 and sell_pressure > 0.60 and expected_profit_pct <= 0.0)
                or (score < 0.18 and forecast_reliable and forecast_max < 0 and sell_pressure > 0.65)
            )
            if hard_sell and not neutral_zone:
                action_hint = "SELL"
            # Soft BUY for strong profitable setups in sparse datasets.
            elif score >= 0.45 and undervalue >= 0.12 and expected_profit_pct >= 0.05 and forecast_max > -0.10:
                action_hint = "BUY"
            elif score >= 0.24 and undervalue >= 0.055 and expected_profit_pct >= 0.018 and forecast_max > -0.09 and confidence >= 0.38:
                action_hint = "BUY"
            elif score >= 0.22 and undervalue >= 0.06 and forecast_max > -0.18 and confidence >= 0.32 and expected_profit_pct >= 0.0:
                action_hint = "BUY"
            elif score >= 0.205 and undervalue >= 0.045 and forecast_max > -0.20 and confidence >= 0.30 and expected_profit_pct >= 0.0:
                action_hint = "BUY"
            elif (
                score >= 0.30
                or (expected_profit_pct > 0.0 and forecast_max > -0.12)
                or (undervalue > 0.05 and forecast_max > -0.18 and confidence >= 0.38)
                or (undervalue > 0.02 and expected_profit_pct >= 0.02 and forecast_max > -0.25)
                or (undervalue > 0.0 and score >= 0.24 and forecast_max > -0.10)
                or (not forecast_reliable and undervalue > 0.03 and score >= 0.24)
                or (not forecast_reliable and undervalue > 0.04 and score >= 0.23)
                or (undervalue > 0.015 and score >= 0.22 and forecast_max > -0.14 and confidence >= 0.34)
                or (confidence < 0.50 and undervalue > 0.025 and score >= 0.235)
                or (confidence < 0.50 and undervalue >= 0.006 and score >= 0.22 and forecast_max >= -0.35)
                or (confidence < 0.50 and undervalue >= 0.015 and score >= 0.22 and forecast_max >= -0.42)
                or (confidence >= 0.52 and score >= 0.21 and undervalue >= -0.02 and forecast_max >= -0.30)
                or (confidence >= 0.46 and score >= 0.203 and undervalue >= -0.12 and forecast_max >= -0.42)
            ):
                action_hint = "WATCH"
            else:
                action_hint = "SKIP"

        return {
            "active_lots": active_lots,
            "price_ton": round(price_ton, 6),
            "floor_ton": round(floor_ton, 6),
            "floor_type": floor_type,
            "median_ton": round(m, 6),
            "fair_ton": round(fair_ton, 6),
            "undervalue": round(undervalue, 6),
            "trend_t": round(trend_t, 6),
            "liq_score": round(liq_score, 6),
            "risk_pen": round(risk_pen, 6),
            "score": round(score, 6),
            "score100": score100,
            "confidence": round(confidence, 6),
            "conf_pct": conf_pct,
            "expected_profit_pct": round(expected_profit_pct, 6),
            "forecast24h_pct_min": round(forecast_min * 100.0, 1),
            "forecast24h_pct_max": round(forecast_max * 100.0, 1),
            "liquidity24h": round(liquidity24h, 6),
            "reasons": reasons[:3],
            "risk_flags": risk_flags,
            "action_hint": action_hint,
            "forecast_confidence": round(forecast_conf, 6),
            "sell_pressure": round(sell_pressure, 6),
            "sales24h": sales24h,
            "liq6h": round(liq6h, 6),
            "vol30m": round(vol30m, 6),
        }

    def _effective_v1_mode(self, mode: str | None = None) -> str:
        raw = str(mode or self.v1_signal_engine_mode or "legacy").strip().lower()
        if raw in {"tz_strict", "strict"}:
            return "tz_strict"
        if raw in {"tz", "v1"}:
            return "tz"
        return "legacy"

    def _v1_variant_summary(self, v: dict, mode: str | None = None) -> dict:
        traits = v.get("traits") or {}
        eff_mode = self._effective_v1_mode(mode)
        mm = self._tz_signal_math_strict(v) if eff_mode == "tz_strict" else self._tz_signal_math(v)
        reco = v.get("reco") or {}
        base_id = str(v.get("base_id") or "")
        base_name = self.bases.get(base_id).name if base_id in self.bases else base_id
        action_hint = mm["action_hint"]
        score100 = mm["score100"]
        conf_pct = mm["conf_pct"]
        reasons = mm["reasons"]
        risk_flags = mm["risk_flags"]
        if eff_mode == "legacy":
            action_hint = self._legacy_action_norm(reco.get("action"))
            try:
                score100 = round(float(reco.get("reco_score") or score100), 1)
            except Exception:
                score100 = mm["score100"]
            try:
                conf_pct = round(float(reco.get("confidence") or conf_pct), 1)
            except Exception:
                conf_pct = mm["conf_pct"]
            reasons_legacy, risks_legacy = self._legacy_reasons_and_risks(reco)
            if reasons_legacy:
                reasons = reasons_legacy
            if risks_legacy:
                risk_flags = risks_legacy
        score = _clamp(float(score100) / 100.0, 0.0, 1.0)
        confidence = _clamp(float(conf_pct) / 100.0, 0.0, 1.0)
        return {
            "variant_id": str(v.get("variant_id") or ""),
            "collection_id": base_id,
            "collection_name": base_name,
            "model": str((traits.get("model") or {}).get("name") or ""),
            "background": str((traits.get("background") or {}).get("name") or ""),
            "pattern": str((traits.get("pattern") or {}).get("name") or ""),
            "active_lots": mm["active_lots"],
            "price_ton": mm["price_ton"],
            "floor_ton": mm["floor_ton"],
            "floor_type": mm["floor_type"],
            "median_ton": mm["median_ton"],
            "fair_ton": mm["fair_ton"],
            "undervalue": mm["undervalue"],
            "trend_t": mm["trend_t"],
            "liq_score": mm["liq_score"],
            "risk_pen": mm["risk_pen"],
            "score": round(score, 6),
            "score100": score100,
            "confidence": round(confidence, 6),
            "conf_pct": conf_pct,
            "expected_profit_pct": mm["expected_profit_pct"],
            "action_hint": action_hint,
            "reasons": reasons,
            "risk_flags": risk_flags,
            "stale": self.is_stale(),
            "updated_at": v.get("updated_at") or self.state.get("updated_at") or _iso(_now()),
        }

    def _v1_signal(self, v: dict, mode: str | None = None) -> dict:
        eff_mode = self._effective_v1_mode(mode)
        variant = self._v1_variant_summary(v, mode=eff_mode)
        mm = self._tz_signal_math_strict(v) if eff_mode == "tz_strict" else self._tz_signal_math(v)
        reco = v.get("reco") or {}
        signal_ts = variant.get("updated_at") or self.state.get("updated_at") or _iso(_now())
        signal_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{signal_ts}|{variant.get('variant_id')}|{variant.get('action_hint')}"))
        price_ton = variant.get("price_ton")
        floor_ton = variant.get("floor_ton")
        fair_ton = variant.get("fair_ton")
        undervalue = variant.get("undervalue")
        expected_profit_pct = variant.get("expected_profit_pct")
        forecast_min = mm.get("forecast24h_pct_min")
        forecast_max = mm.get("forecast24h_pct_max")
        if eff_mode == "legacy":
            forecast = reco.get("forecast") if isinstance(reco, dict) else {}
            rng = (forecast or {}).get("range_pct") if isinstance(forecast, dict) else None
            if isinstance(rng, list) and len(rng) >= 2:
                try:
                    forecast_min = float(rng[0])
                    forecast_max = float(rng[1])
                except Exception:
                    pass
            # Legacy mode doesn't have stable Fair/Undervalue/ExpectedProfit contract.
            # Keep nullable fields null to avoid mixed-engine contradictions in one signal.
            fair_ton = None
            undervalue = None
            expected_profit_pct = None
        return {
            "signal_id": signal_id,
            "ts": signal_ts,
            "type": variant.get("action_hint"),
            "variant_id": variant.get("variant_id"),
            "collection_id": variant.get("collection_id"),
            "collection": variant.get("collection_name"),
            "model": variant.get("model"),
            "background": variant.get("background"),
            "pattern": variant.get("pattern"),
            "score100": variant.get("score100"),
            "conf_pct": variant.get("conf_pct"),
            "price_ton": price_ton,
            "floor_ton": floor_ton,
            "fair_ton": fair_ton,
            "undervalue": undervalue,
            "expected_profit_pct": expected_profit_pct,
            "forecast24h_pct_min": forecast_min,
            "forecast24h_pct_max": forecast_max,
            "active_lots": mm.get("active_lots"),
            "liquidity24h": mm.get("liquidity24h"),
            "reasons": variant.get("reasons") or [],
            "risk_flags": variant.get("risk_flags") or [],
            "engine_mode": eff_mode,
        }

    def _cursor_offset(self, cursor: str | None) -> int:
        if not cursor:
            return 0
        try:
            return max(0, int(str(cursor)))
        except Exception:
            return 0

    def _fallback_v1_counts_from_listings(self) -> dict:
        active_rows = [row for row in self.listing_state.values() if str((row or {}).get("status") or "ACTIVE").upper() == "ACTIVE"]
        variant_ids = {
            str((row or {}).get("variant_id") or "")
            for row in active_rows
            if str((row or {}).get("variant_id") or "").strip()
        }
        collections = set()
        models = set()
        for vid in variant_ids:
            parts = str(vid).split("|")
            if len(parts) >= 2:
                collections.add(parts[0])
                models.add(parts[1])
        return {
            "gifts": len(active_rows),
            "collections": len(collections),
            "models": len(models),
        }

    def _fallback_v1_signals_from_listings(
        self,
        signal_type: str | None = None,
        min_score: float | None = None,
        since_dt: datetime | None = None,
        mode: str | None = None,
    ) -> List[dict]:
        eff_mode = self._effective_v1_mode(mode)
        by_variant: Dict[str, dict] = {}
        for row in self.listing_state.values():
            if str((row or {}).get("status") or "ACTIVE").upper() != "ACTIVE":
                continue
            variant_id = str((row or {}).get("variant_id") or "").strip()
            if not variant_id:
                continue
            price = float((row or {}).get("price_ton") or 0.0)
            ts = str((row or {}).get("last_seen") or self.state.get("updated_at") or _iso(_now()))
            bucket = by_variant.setdefault(
                variant_id,
                {
                    "variant_id": variant_id,
                    "price_ton": price,
                    "floor_ton": price,
                    "active_lots": 0,
                    "ts": ts,
                },
            )
            bucket["active_lots"] = int(bucket.get("active_lots") or 0) + 1
            if price > 0 and (float(bucket.get("price_ton") or 0) <= 0 or price < float(bucket.get("price_ton") or 0)):
                bucket["price_ton"] = price
                bucket["floor_ton"] = price
            if ts > str(bucket.get("ts") or ""):
                bucket["ts"] = ts

        items: List[dict] = []
        for variant_id, agg in by_variant.items():
            parts = variant_id.split("|")
            collection_id = parts[0] if len(parts) > 0 else ""
            model_slug = parts[1] if len(parts) > 1 else ""
            background_slug = parts[2] if len(parts) > 2 else ""
            pattern_slug = parts[3] if len(parts) > 3 else ""
            collection = self.bases.get(collection_id).name if collection_id in self.bases else _slug_to_name(collection_id)
            score100 = 50.0
            conf_pct = 30.0
            if signal_type and str(signal_type).upper() != "WATCH":
                continue
            if min_score is not None and (score100 / 100.0) < float(min_score):
                continue
            ts = str(agg.get("ts") or self.state.get("updated_at") or _iso(_now()))
            if since_dt and _parse_ts(ts) < since_dt:
                continue
            signal_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{ts}|{variant_id}|WATCH|fallback"))
            items.append(
                {
                    "signal_id": signal_id,
                    "ts": ts,
                    "type": "WATCH",
                    "variant_id": variant_id,
                    "collection_id": collection_id,
                    "collection": collection,
                    "model": _slug_to_name(model_slug),
                    "background": _slug_to_name(background_slug),
                    "pattern": _slug_to_name(pattern_slug),
                    "score100": score100,
                    "conf_pct": conf_pct,
                    "price_ton": float(agg.get("price_ton") or 0.0),
                    "floor_ton": float(agg.get("floor_ton") or 0.0),
                    "fair_ton": None,
                    "undervalue": None,
                    "expected_profit_pct": None,
                    "forecast24h_pct_min": None,
                    "forecast24h_pct_max": None,
                    "active_lots": int(agg.get("active_lots") or 0),
                    "liquidity24h": None,
                    "reasons": ["Fallback: runtime variants warming up, using active listing snapshot."],
                    "risk_flags": ["Degraded signal quality while primary sync is rebuilding."],
                    "engine_mode": eff_mode,
                }
            )
        items.sort(key=lambda x: (str(x.get("ts") or ""), int(x.get("active_lots") or 0)), reverse=True)
        return items

    def overview_v1(self, mode: str | None = None) -> dict:
        self._ensure_recos()
        eff_mode = self._effective_v1_mode(mode)
        variants = [self._v1_variant_summary(v, mode=eff_mode) for v in self.variants.values()]
        scores = [float(v.get("score100") or 0.0) for v in variants]
        market_index = round(_safe_mean(scores), 2) if scores else 0.0
        market_state = "флет"
        if market_index >= 60:
            market_state = "рост"
        elif market_index <= 40:
            market_state = "падение"
        top_signals = self.signals_v1(limit=8, mode=eff_mode).get("items") or []
        recommendation = top_signals[0] if top_signals else None
        volume24h = round(sum(float((v.get("metrics") or {}).get("volume_ton_24h", 0) or 0) for v in self.variants.values()), 6)
        avg_liq = round(_safe_mean(float((v.get("metrics") or {}).get("liquidity_score_24h", 0) or 0) for v in self.variants.values()), 6)

        # Render instances can briefly warm up with empty in-memory variants while
        # market_overview already has persisted snapshot-derived totals.
        fallback_counts = None
        if not variants:
            mo = self.market_overview()
            fallback_counts = {
                "gifts": int(mo.get("gifts_count") or 0),
                "collections": int(mo.get("base_count") or 0),
                "models": int(mo.get("model_count") or 0),
            }
            if market_state == "флет":
                ms = str(mo.get("market_state") or "").strip().lower()
                if ms in {"рост", "флет", "падение", "неизвестно"}:
                    market_state = ms

        counts_payload = (
            fallback_counts
            if fallback_counts is not None
            else {
                "gifts": sum(int((v.get("metrics") or {}).get("active_listings", 0) or 0) for v in self.variants.values()),
                "collections": len({v.get("base_id") for v in self.variants.values() if v.get("base_id")}),
                "models": len({((v.get("traits") or {}).get("model") or {}).get("id") for v in self.variants.values() if ((v.get("traits") or {}).get("model") or {}).get("id")}),
            }
        )
        if (
            int(counts_payload.get("gifts") or 0) <= 0
            and int(counts_payload.get("collections") or 0) <= 0
            and int(counts_payload.get("models") or 0) <= 0
        ):
            counts_payload = self._fallback_v1_counts_from_listings()
        if not top_signals:
            top_signals = self._fallback_v1_signals_from_listings(mode=eff_mode)[:8]
            recommendation = top_signals[0] if top_signals else None
        return {
            "market_index": market_index,
            "market_state": market_state,
            "counts": counts_payload,
            "top_signals": top_signals,
            "recommendation": recommendation,
            "key_metrics": {
                "volume24h_ton": volume24h,
                "avg_liquidity24h": avg_liq,
                "synth_floor_share": 0.0,
            },
            "provider_health": [
                {
                    "provider": os.getenv("VERIFIED_SOURCE", "telegram_api"),
                    "p95_ms": 0,
                    "err_pct": 0.0 if not self.state.get("last_error") else 100.0,
                    "degraded": bool(self.state.get("last_error")),
                    "ts": self.state.get("updated_at") or _iso(_now()),
                }
            ],
            "stale": self.is_stale(),
            "engine_mode": eff_mode,
        }

    def collections_v1(self, q: str = "", limit: int = 50, cursor: str | None = None) -> dict:
        query = str(q or "").strip().lower()
        rows = []
        for base in self.list_bases():
            base_id = str(base.get("base_id") or "")
            name = str(base.get("name") or base_id)
            if query and query not in base_id.lower() and query not in name.lower():
                continue
            m = base.get("metrics") or {}
            rows.append(
                {
                    "collection_id": base_id,
                    "name": name,
                    "floor_ton": float(m.get("floor_ton") or 0.0),
                    "floor_type": "real",
                    "delta_1h": float(m.get("floor_change_pct_1h") or 0.0) / 100.0,
                    "delta_12h": float(m.get("floor_change_pct_12h") or 0.0) / 100.0,
                    "delta_24h": float(m.get("floor_change_pct_24h") or 0.0) / 100.0,
                    "active_lots_total": int(m.get("active_listings") or 0),
                    "sales24h": int(m.get("trades_count_24h") or 0),
                    "liq6h": float(m.get("trades_count_24h") or 0.0) / 6.0,
                    "trend_t": _clamp((float(m.get("floor_change_pct_24h") or 0.0) / 100.0 + 1.0) / 2.0, 0.0, 1.0),
                    "liq_score": _clamp(float(m.get("liquidity_score_24h") or 0.0), 0.0, 1.0),
                    "updated_at": base.get("updated_at") or self.state.get("updated_at") or _iso(_now()),
                }
            )
        rows.sort(key=lambda x: x["name"])
        off = self._cursor_offset(cursor)
        lim = max(1, min(int(limit or 50), 200))
        chunk = rows[off : off + lim]
        next_cursor = str(off + lim) if (off + lim) < len(rows) else None
        return {"items": chunk, "next_cursor": next_cursor}

    def collection_details_v1(self, collection_id: str) -> dict | None:
        col = None
        for item in self.collections_v1(limit=5000).get("items") or []:
            if str(item.get("collection_id") or "") == collection_id:
                col = item
                break
        if not col:
            return None
        top = self.variants_v1(collection_id=collection_id, sort="score_desc", limit=20).get("items") or []
        floor_series = []
        for v in self.variants.values():
            if str(v.get("base_id") or "") != collection_id:
                continue
            hist = self.variant_history.get(v.get("variant_id"), [])
            for h in hist[-24:]:
                if h.get("floor_ton") is None:
                    continue
                floor_series.append({"ts": h.get("ts"), "floor_ton": float(h.get("floor_ton") or 0.0)})
        floor_series = sorted(floor_series, key=lambda x: str(x.get("ts")))[:200]
        if not floor_series:
            floor_series = [{"ts": self.state.get("updated_at") or _iso(_now()), "floor_ton": float(col.get("floor_ton") or 0.0)}]
        return {"collection": col, "top_variants": top, "floor_series": floor_series}

    def variants_v1(
        self,
        collection_id: str | None = None,
        model: str | None = None,
        background: str | None = None,
        pattern: str | None = None,
        min_score: float | None = None,
        action: str | None = None,
        sort: str = "score_desc",
        limit: int = 50,
        cursor: str | None = None,
        mode: str | None = None,
    ) -> dict:
        eff_mode = self._effective_v1_mode(mode)
        rows = []
        for v in self.variants.values():
            summary = self._v1_variant_summary(v, mode=eff_mode)
            if collection_id and summary["collection_id"] != collection_id:
                continue
            if model and summary["model"].lower() != str(model).lower():
                continue
            if background and summary["background"].lower() != str(background).lower():
                continue
            if pattern and summary["pattern"].lower() != str(pattern).lower():
                continue
            if min_score is not None and float(summary.get("score") or 0.0) < float(min_score):
                continue
            if action and summary.get("action_hint") != action:
                continue
            rows.append(summary)

        if sort == "undervalue_desc":
            rows.sort(key=lambda x: float(x.get("undervalue") or 0.0), reverse=True)
        elif sort == "trend_desc":
            rows.sort(key=lambda x: float(x.get("trend_t") or 0.0), reverse=True)
        elif sort == "lots_desc":
            rows.sort(key=lambda x: int(x.get("active_lots") or 0), reverse=True)
        elif sort == "floor_change_24h_desc":
            rows.sort(
                key=lambda x: float(
                    (
                        (self.variants.get(x.get("variant_id")) or {}).get("metrics") or {}
                    ).get("floor_change_pct_24h", 0)
                    or 0
                ),
                reverse=True,
            )
        else:
            rows.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)

        off = self._cursor_offset(cursor)
        lim = max(1, min(int(limit or 50), 200))
        chunk = rows[off : off + lim]
        next_cursor = str(off + lim) if (off + lim) < len(rows) else None
        return {"items": chunk, "next_cursor": next_cursor}

    def variant_details_v1(self, variant_id: str, mode: str | None = None) -> dict | None:
        eff_mode = self._effective_v1_mode(mode)
        v = self.variants.get(variant_id)
        if not v:
            mapped = self._listing_to_variant(variant_id)
            if mapped:
                v = self.variants.get(mapped)
        if not v:
            return None
        summary = self._v1_variant_summary(v, mode=eff_mode)
        listings = []
        for lid, row in self.listing_state.items():
            if str((row or {}).get("variant_id") or "") != str(v.get("variant_id") or ""):
                continue
            listings.append(
                {
                    "listing_id": lid,
                    "price_ton": float(row.get("price_ton") or 0.0),
                    "price_stars": None,
                    "status": str(row.get("status") or "ACTIVE"),
                    "observed_at": row.get("last_seen") or self.state.get("updated_at") or _iso(_now()),
                }
            )
        listings.sort(key=lambda x: float(x.get("price_ton") or 0.0))
        breakdown = self._tz_signal_math(v) if eff_mode == "tz" else {"engine_mode": "legacy"}
        return {"variant": summary, "listings": listings, "breakdown": breakdown}

    def signals_v1(
        self,
        signal_type: str | None = None,
        min_score: float | None = None,
        since: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
        mode: str | None = None,
    ) -> dict:
        eff_mode = self._effective_v1_mode(mode)
        since_dt = _parse_ts(since) if since else None
        items = []
        for v in self.variants.values():
            sig = self._v1_signal(v, mode=eff_mode)
            if signal_type and sig.get("type") != signal_type:
                continue
            if min_score is not None and (float(sig.get("score100") or 0.0) / 100.0) < float(min_score):
                continue
            if since_dt and _parse_ts(sig.get("ts")) < since_dt:
                continue
            if sig.get("type") not in {"BUY", "SELL", "WATCH", "SKIP"}:
                continue
            items.append(sig)
        if not items:
            items = self._fallback_v1_signals_from_listings(
                signal_type=signal_type,
                min_score=min_score,
                since_dt=since_dt,
                mode=eff_mode,
            )
        items.sort(key=lambda x: (str(x.get("ts") or ""), float(x.get("score100") or 0.0)), reverse=True)
        off = self._cursor_offset(cursor)
        lim = max(1, min(int(limit or 50), 200))
        chunk = items[off : off + lim]
        next_cursor = str(off + lim) if (off + lim) < len(items) else None
        return {"items": chunk, "next_cursor": next_cursor, "engine_mode": eff_mode}

    def signal_by_id_v1(self, signal_id: str, mode: str | None = None) -> dict | None:
        for item in self.signals_v1(limit=5000, mode=mode).get("items") or []:
            if str(item.get("signal_id") or "") == str(signal_id or ""):
                return item
        return None

    def build_signal_created_event_v1(
        self,
        signal: dict,
        ts: str | None = None,
        version: int = 1,
        trace_id: str | None = None,
    ) -> dict:
        sig = signal if isinstance(signal, dict) else {}
        event_ts = str(ts or _iso(_now()))
        variant_id = str(sig.get("variant_id") or "")
        key = variant_id or str(sig.get("collection_id") or "")
        payload = {
            "signal_id": str(sig.get("signal_id") or str(uuid.uuid4())),
            "ts": str(sig.get("ts") or event_ts),
            "type": str(sig.get("type") or "WATCH"),
            "variant_id": variant_id,
            "collection_id": str(sig.get("collection_id") or ""),
            "collection": str(sig.get("collection") or sig.get("collection_id") or ""),
            "model": sig.get("model"),
            "background": sig.get("background"),
            "pattern": sig.get("pattern"),
            "score100": float(sig.get("score100") or 0.0),
            "conf_pct": float(sig.get("conf_pct") or 0.0),
            "price_ton": float(sig.get("price_ton")) if sig.get("price_ton") not in (None, "") else None,
            "floor_ton": float(sig.get("floor_ton")) if sig.get("floor_ton") not in (None, "") else None,
            "fair_ton": float(sig.get("fair_ton")) if sig.get("fair_ton") not in (None, "") else None,
            "undervalue": float(sig.get("undervalue")) if sig.get("undervalue") not in (None, "") else None,
            "expected_profit_pct": float(sig.get("expected_profit_pct")) if sig.get("expected_profit_pct") not in (None, "") else None,
            "forecast24h_pct_min": float(sig.get("forecast24h_pct_min")) if sig.get("forecast24h_pct_min") not in (None, "") else None,
            "forecast24h_pct_max": float(sig.get("forecast24h_pct_max")) if sig.get("forecast24h_pct_max") not in (None, "") else None,
            "active_lots": int(sig.get("active_lots")) if sig.get("active_lots") not in (None, "") else None,
            "liquidity24h": float(sig.get("liquidity24h")) if sig.get("liquidity24h") not in (None, "") else None,
            "reasons": [str(x) for x in (sig.get("reasons") or [])],
            "risk_flags": [str(x) for x in (sig.get("risk_flags") or [])],
        }
        return {
            "type": "signal.created",
            "ts": event_ts,
            "key": key,
            "version": max(1, int(version or 1)),
            "trace_id": str(trace_id or uuid.uuid4()),
            "payload": payload,
        }

    def build_metric_updated_event_v1(
        self,
        metric: str,
        scope: str,
        value: float,
        unit: str,
        market: bool = False,
        collection_id: str | None = None,
        variant_id: str | None = None,
        stale: bool | None = None,
        extra: dict | None = None,
        ts: str | None = None,
        version: int = 1,
        trace_id: str | None = None,
    ) -> dict:
        event_ts = str(ts or _iso(_now()))
        scope_name = str(scope or "MARKET").upper()
        key = "MARKET" if market else (str(variant_id or "").strip() or str(collection_id or "").strip() or "MARKET")
        payload = {
            "metric": str(metric or "").upper(),
            "scope": scope_name,
            "market": bool(market),
            "collection_id": str(collection_id or "") if collection_id else None,
            "variant_id": str(variant_id or "") if variant_id else None,
            "unit": str(unit or "JSON"),
            "point": {
                "ts": event_ts,
                "value": float(value or 0.0),
                "extra": extra or {},
            },
            "stale": self.is_stale() if stale is None else bool(stale),
        }
        return {
            "type": "metric.updated",
            "ts": event_ts,
            "key": key,
            "version": max(1, int(version or 1)),
            "trace_id": str(trace_id or uuid.uuid4()),
            "payload": payload,
        }

    def build_listing_event_v1(
        self,
        listing: dict,
        ts: str | None = None,
        version: int = 1,
        trace_id: str | None = None,
    ) -> dict:
        row = listing if isinstance(listing, dict) else {}
        event_ts = str(ts or _iso(_now()))
        variant_id = str(row.get("variant_id") or "")
        key = variant_id or str(row.get("collection_id") or row.get("gift_id") or "")
        payload = {
            "topic": str(row.get("topic") or "market.listing.new"),
            "ts": str(row.get("ts") or event_ts),
            "listing_key": str(row.get("listing_key") or ""),
            "variant_id": variant_id,
            "collection_id": str(row.get("gift_id") or row.get("collection_id") or ""),
            "collection": str(row.get("title") or row.get("collection") or row.get("gift_id") or ""),
            "resell_currency": str(row.get("resell_currency") or "TON"),
            "resell_amount": float(row.get("resell_amount") or 0.0) if row.get("resell_amount") not in (None, "") else None,
            "attributes": row.get("attributes") if isinstance(row.get("attributes"), dict) else {},
        }
        return {
            "type": "listing.event",
            "ts": event_ts,
            "key": key,
            "version": max(1, int(version or 1)),
            "trace_id": str(trace_id or uuid.uuid4()),
            "payload": payload,
        }

    def stream_events_v1(self, types: set[str] | None = None, mode: str | None = None) -> list[dict]:
        wanted = set(types or [])
        all_types = {"signal.created", "metric.updated", "listing.event", "variant.updated", "collection.updated", "provider.health"}
        if not wanted:
            wanted = set(all_types)
        now_iso = _iso(_now())
        out: list[dict] = []
        overview = self.overview_v1(mode=mode)
        market_summary = self.market_overview()
        if "metric.updated" in wanted:
            out.append(
                self.build_metric_updated_event_v1(
                    metric="MARKET_INDEX",
                    scope="MARKET",
                    value=float(overview.get("market_index") or 0.0),
                    unit="SCORE_0_100",
                    market=True,
                    stale=bool(overview.get("stale")),
                    extra={"market_state": overview.get("market_state")},
                    ts=now_iso,
                )
            )
            out.append(
                self.build_metric_updated_event_v1(
                    metric="LIQUIDITY_SCORE",
                    scope="MARKET",
                    value=float(((overview.get("key_metrics") or {}).get("avg_liquidity24h") or 0.0)),
                    unit="SCORE_0_1",
                    market=True,
                    stale=bool(overview.get("stale")),
                    ts=now_iso,
                )
            )
            out.append(
                self.build_metric_updated_event_v1(
                    metric="FLOOR_REALTIME",
                    scope="MARKET",
                    value=float(market_summary.get("floor_ton_median") or market_summary.get("floor_ton_min") or 0.0),
                    unit="TON",
                    market=True,
                    stale=bool(overview.get("stale")),
                    ts=now_iso,
                )
            )
            out.append(
                self.build_metric_updated_event_v1(
                    metric="LISTING_VELOCITY",
                    scope="MARKET",
                    value=float(market_summary.get("active_listings") or 0.0),
                    unit="RATIO",
                    market=True,
                    stale=bool(overview.get("stale")),
                    ts=now_iso,
                )
            )
            collections = self.collections_v1(limit=1).get("items") or []
            if collections:
                top_col = collections[0]
                out.append(
                    self.build_metric_updated_event_v1(
                        metric="FLOOR_REALTIME",
                        scope="COLLECTION",
                        value=float(top_col.get("floor_ton") or 0.0),
                        unit="TON",
                        market=False,
                        collection_id=str(top_col.get("collection_id") or ""),
                        stale=bool(overview.get("stale")),
                        ts=now_iso,
                    )
                )
            variants = self.variants_v1(limit=1, mode=mode).get("items") or []
            if variants:
                top_var = variants[0]
                out.append(
                    self.build_metric_updated_event_v1(
                        metric="EDGE_SCORE",
                        scope="VARIANT",
                        value=float(top_var.get("score") or 0.0),
                        unit="SCORE_0_1",
                        market=False,
                        collection_id=str(top_var.get("collection_id") or ""),
                        variant_id=str(top_var.get("variant_id") or ""),
                        stale=bool(overview.get("stale")),
                        ts=now_iso,
                    )
                )
        if "signal.created" in wanted:
            top = (overview.get("top_signals") or [])
            if top:
                out.append(self.build_signal_created_event_v1(top[0], ts=now_iso))
        if "listing.event" in wanted:
            listing_items = self.listings_events_v1(limit=1, include_relisted=True).get("items") or []
            if listing_items:
                out.append(self.build_listing_event_v1(listing_items[0], ts=now_iso))
        if "variant.updated" in wanted:
            out.append(
                {
                    "type": "variant.updated",
                    "ts": now_iso,
                    "key": "VARIANT",
                    "version": 1,
                    "trace_id": str(uuid.uuid4()),
                    "payload": {"updated_at": now_iso},
                }
            )
        if "collection.updated" in wanted:
            out.append(
                {
                    "type": "collection.updated",
                    "ts": now_iso,
                    "key": "COLLECTION",
                    "version": 1,
                    "trace_id": str(uuid.uuid4()),
                    "payload": {"updated_at": now_iso},
                }
            )
        if "provider.health" in wanted:
            provider = ((overview.get("provider_health") or [{}])[0] or {})
            out.append(
                {
                    "type": "provider.health",
                    "ts": now_iso,
                    "key": str(provider.get("provider") or "provider"),
                    "version": 1,
                    "trace_id": str(uuid.uuid4()),
                    "payload": provider,
                }
            )
        return out

    def metrics_definitions_v1(self) -> list[dict]:
        return list(METRIC_DEFINITIONS_V1)

    def _resolve_metric_scope(self, scope: str | None, market: bool, collection_id: str | None, variant_id: str | None) -> str:
        if market:
            return "MARKET"
        raw = str(scope or "").strip().upper()
        if raw in {"MARKET", "COLLECTION", "VARIANT"}:
            return raw
        if variant_id:
            return "VARIANT"
        if collection_id:
            return "COLLECTION"
        return "MARKET"

    def _series_points_from_history(
        self,
        history: list[dict],
        field: str,
        from_dt: datetime | None,
        to_dt: datetime | None,
        interval_sec: int,
        limit: int,
    ) -> list[dict]:
        bucket_values: dict[int, float] = {}
        for row in history:
            ts = _parse_ts(row.get("ts"))
            if from_dt and ts < from_dt:
                continue
            if to_dt and ts > to_dt:
                continue
            value = row.get(field)
            try:
                val = float(value)
            except Exception:
                continue
            if not math.isfinite(val):
                continue
            bucket = int(ts.timestamp() // max(1, interval_sec)) * max(1, interval_sec)
            bucket_values[bucket] = val
        points = [{"ts": _iso(datetime.fromtimestamp(b, tz=timezone.utc)), "value": v} for b, v in sorted(bucket_values.items())]
        if limit > 0 and len(points) > limit:
            points = points[-limit:]
        return points

    def metrics_v1(
        self,
        metric: str,
        scope: str | None = None,
        market: bool = False,
        collection_id: str | None = None,
        variant_id: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
        interval: str | None = None,
        limit: int = 500,
        mode: str | None = None,
    ) -> dict:
        metric_name = str(metric or "").strip().upper()
        if metric_name not in METRIC_UNITS:
            raise ValueError(f"unsupported_metric:{metric_name}")
        scope_name = self._resolve_metric_scope(scope, market, collection_id, variant_id)
        from_dt = _parse_ts(from_ts) if from_ts else None
        to_dt = _parse_ts(to_ts) if to_ts else None
        interval_sec = self._metric_interval_to_seconds(interval)
        lim = max(1, min(int(limit or 500), 5000))
        eff_mode = self._effective_v1_mode(mode)
        now_iso = _iso(_now())
        points: list[dict] = []

        if scope_name == "VARIANT":
            variant_key = str(variant_id or "").strip()
            v = self.variants.get(variant_key)
            if not v:
                mapped = self._listing_to_variant(variant_key)
                if mapped:
                    v = self.variants.get(mapped)
                    variant_key = mapped
            if not v:
                raise ValueError("variant_not_found")
            mm = self._tz_signal_math_strict(v) if eff_mode == "tz_strict" else self._tz_signal_math(v)
            hist = self.variant_history.get(variant_key, [])
            if metric_name == "FLOOR_HISTORY":
                points = self._series_points_from_history(hist, "floor_ton", from_dt, to_dt, interval_sec, lim)
            elif metric_name == "VOLUME_CHART":
                points = self._series_points_from_history(hist, "vwap_ton", from_dt, to_dt, interval_sec, lim)
            elif metric_name == "SUPPLY_CHART":
                points = self._series_points_from_history(hist, "active_listings", from_dt, to_dt, interval_sec, lim)
            elif metric_name == "LIQUIDITY_CHART":
                lv = float(mm.get("liq_score") or 0.0)
                points = self._series_points_from_history(hist, "floor_ton", from_dt, to_dt, interval_sec, lim)
                for p in points:
                    p["value"] = lv
            elif metric_name == "LIQUIDITY_HEATMAP":
                lv = float(mm.get("liq_score") or 0.0)
                points = [{"ts": now_iso, "value": lv, "extra": {"heat": [{"bucket": "24h", "value": lv}]}}]
            elif metric_name == "LISTING_FEED":
                events = self.listings_events_v1(limit=50, since=from_ts, include_relisted=True).get("items") or []
                points = [{"ts": now_iso, "value": float(len(events)), "extra": {"items": events[:50]}}]
            elif metric_name == "MARKET_DEPTH":
                floor = float(mm.get("floor_ton") or 0.0)
                band_hi = floor * 1.05 if floor > 0 else 0.0
                depth_count = 0
                depth_ton = 0.0
                for row in self.listing_state.values():
                    if str((row or {}).get("variant_id") or "") != variant_key:
                        continue
                    price = float((row or {}).get("price_ton") or 0.0)
                    if floor > 0 and price >= floor and price <= band_hi:
                        depth_count += 1
                        depth_ton += price
                points = [{"ts": now_iso, "value": float(depth_count), "extra": {"depth_count": depth_count, "depth_ton": round(depth_ton, 6)}}]
            else:
                value_map = {
                    "FLOOR_REALTIME": float(mm.get("floor_ton") or 0.0),
                    "NEW_LISTINGS_REALTIME": float(self._new_listings_in_window(variant_key, _now(), 600)),
                    "LISTING_VELOCITY": float(mm.get("new_listings_30m") or 0.0),
                    "LISTING_PRESSURE": float(mm.get("listing_pressure") or 0.0),
                    "FAIR_PRICE": float(mm.get("fair_ton") or 0.0),
                    "UNDERVALUE": float(mm.get("undervalue") or 0.0),
                    "EXPECTED_PROFIT": float(mm.get("expected_profit_pct") or 0.0),
                    "LIQUIDITY_SCORE": float(mm.get("liq_score") or 0.0),
                    "VOLUME_VELOCITY": float(mm.get("volume_velocity") or 0.0),
                    "ABSORPTION_RATE": float(mm.get("absorption_rate") or 0.0),
                    "VOLATILITY": float(mm.get("volatility") or 0.0),
                    "EDGE_SCORE": float(mm.get("score") or 0.0),
                    "BUY_SCORE": float(mm.get("score100") or 0.0) if str(mm.get("action_hint") or "") == "BUY" else max(0.0, float(mm.get("score100") or 0.0) * 0.5),
                    "SELL_SCORE": float(100.0 - float(mm.get("score100") or 0.0)),
                    "BUY_WALL_SCORE": _clamp(float(mm.get("absorption_rate") or 0.0), 0.0, 2.0),
                    "WHALE_RATIO": 0.0,
                    "WHALE_IMPULSE": 0.0,
                    "RARITY_SCORE": _clamp(1.0 / max(1, int(mm.get("active_lots") or 1)), 0.0, 1.0),
                }
                points = [{"ts": now_iso, "value": float(value_map.get(metric_name, 0.0))}]

        elif scope_name == "COLLECTION":
            col_id = str(collection_id or "").strip()
            if not col_id:
                raise ValueError("collection_id_required")
            rows = self.variants_v1(collection_id=col_id, limit=5000, mode=eff_mode).get("items") or []
            if not rows:
                raise ValueError("collection_not_found")
            if metric_name == "FLOOR_REALTIME":
                value = _safe_median([float(r.get("floor_ton") or 0.0) for r in rows if float(r.get("floor_ton") or 0.0) > 0])
            elif metric_name == "MARKET_INDEX":
                value = _safe_mean([float(r.get("score100") or 0.0) for r in rows])
            elif metric_name == "TREND_SCORE":
                value = _safe_mean([float(r.get("trend_t") or 0.0) for r in rows])
            elif metric_name == "LIQUIDITY_SCORE":
                value = _safe_mean([float(r.get("liq_score") or 0.0) for r in rows])
            else:
                value = _safe_mean([float(r.get("score") or 0.0) for r in rows])
            points = [{"ts": now_iso, "value": float(value)}]

        else:  # MARKET
            overview = self.overview_v1(mode=eff_mode)
            market_summary = self.market_overview()
            if metric_name == "MARKET_INDEX":
                value = float(overview.get("market_index") or 0.0)
            elif metric_name == "TREND_SCORE":
                avg_24h = float(market_summary.get("avg_change_24h") or 0.0)
                value = _clamp((avg_24h + 100.0) / 200.0, 0.0, 1.0)
            elif metric_name == "FLOOR_REALTIME":
                value = float(market_summary.get("floor_ton_median") or market_summary.get("floor_ton_min") or 0.0)
            elif metric_name == "LIQUIDITY_SCORE":
                value = float((overview.get("key_metrics") or {}).get("avg_liquidity24h") or 0.0)
            elif metric_name == "VOLUME_VELOCITY":
                value = 1.0
            elif metric_name == "ABSORPTION_RATE":
                value = 1.0
            elif metric_name == "LISTING_VELOCITY":
                value = float(market_summary.get("active_listings") or 0.0)
            elif metric_name == "VELOCITY_SCORE":
                value = float(overview.get("market_index") or 0.0)
            else:
                value = 0.0
            points = [{"ts": now_iso, "value": float(value)}]

        if not points:
            points = [{"ts": now_iso, "value": 0.0}]
        return {
            "metric": metric_name,
            "scope": scope_name,
            "market": bool(scope_name == "MARKET"),
            "collection_id": collection_id if scope_name == "COLLECTION" else None,
            "variant_id": variant_id if scope_name == "VARIANT" else None,
            "unit": METRIC_UNITS.get(metric_name, "JSON"),
            "points": points,
            "stale": self.is_stale(),
            "engine_mode": eff_mode,
        }

    def _is_listing_new(self, now: datetime, first_seen_at: str, relisted_at: str | None, window_sec: int) -> bool:
        first_seen_dt = _parse_ts(first_seen_at)
        relisted_dt = _parse_ts(relisted_at) if relisted_at else None
        return ((now - first_seen_dt).total_seconds() <= window_sec) or (
            relisted_dt is not None and (now - relisted_dt).total_seconds() <= window_sec
        )

    def _build_runtime_listing_rows(self, now: datetime, window_sec: int) -> List[dict]:
        rows: List[dict] = []
        for row in self.listing_state.values():
            if str((row or {}).get("status") or "ACTIVE").upper() != "ACTIVE":
                continue
            key = self._listing_tracker_key(row)
            if not key:
                continue
            entry = self.listing_tracker_state.get(key) or {}
            variant_id = str((row or {}).get("variant_id") or "")
            model_name, background_name, pattern_name = self._variant_attrs_from_id(variant_id)
            v = self.variants.get(variant_id) or {}
            traits = v.get("traits") or {}
            model_name = str(((traits.get("model") or {}).get("name")) or model_name)
            background_name = str(((traits.get("background") or {}).get("name")) or background_name)
            pattern_name = str(((traits.get("pattern") or {}).get("name")) or pattern_name)
            collection_id = str((row or {}).get("base_id") or "").strip().lower()
            collection_name = self.bases.get(collection_id).name if collection_id in self.bases else _slug_to_name(collection_id)
            first_seen_at = str(entry.get("first_seen_at") or (row or {}).get("last_seen") or _iso(now))
            last_seen_at = str(entry.get("last_seen_at") or (row or {}).get("last_seen") or _iso(now))
            relisted_at = str(entry.get("last_relisted_at") or "")
            is_new = self._is_listing_new(now, first_seen_at, relisted_at, window_sec)
            price_ton = float((row or {}).get("price_ton") or 0.0)
            rows.append(
                {
                    "listing_key": key,
                    "gift_id": collection_id,
                    "unique_id": str((row or {}).get("listing_id") or ""),
                    "variant_id": variant_id,
                    "num": None,
                    "slug": collection_id,
                    "title": collection_name,
                    "collection": collection_name,
                    "collection_id": collection_id,
                    "resell_currency": "TON",
                    "currency_mode": "TON_ONLY",
                    "resell_amount_ton": round(price_ton, 6),
                    "resell_amount_stars_est": self._stars_est(price_ton),
                    "attributes": {
                        "model": model_name,
                        "background": background_name,
                        "pattern": pattern_name,
                    },
                    "status": str((row or {}).get("status") or "ACTIVE"),
                    "sale_type": str((row or {}).get("sale_type") or "FIXED"),
                    "preview_url": str((row or {}).get("preview_url") or ""),
                    "ts_detected": first_seen_at,
                    "first_seen_at": first_seen_at,
                    "last_seen_at": last_seen_at,
                    "relist_count": int(entry.get("relist_count") or 0),
                    "last_relisted_at": relisted_at or None,
                    "is_new": bool(is_new),
                    "source": "fragment.verified_snapshot",
                }
            )
        return rows

    def _extract_mt_listing_items(self, payload: dict) -> list:
        if not isinstance(payload, dict):
            return []
        if isinstance(payload.get("items"), list):
            return payload.get("items") or []
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data.get("items") or []
        return []

    def _normalize_mt_listing_item(self, raw: dict, now: datetime, window_sec: int) -> dict | None:
        if not isinstance(raw, dict):
            return None
        raw_gift_id = str(raw.get("gift_id") or "").strip().lower()
        raw_collection_id = str(raw.get("collection_id") or "").strip().lower()
        raw_slug = str(raw.get("slug") or "").strip()
        unique_id = str(raw.get("unique_id") or raw.get("id") or raw.get("listing_id") or "").strip()
        if not unique_id:
            return None
        slug_head = str(raw_slug.split("-", 1)[0] or "").strip().lower()
        collection = str(raw.get("collection") or raw.get("title") or "").strip()

        def _has_letters(v: str) -> bool:
            return bool(re.search(r"[a-z]", str(v or "").lower()))

        def _slug_text(text: str) -> str:
            return re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_") or "unknown"

        gift_id = ""
        for candidate in [raw_collection_id, raw_gift_id, slug_head, raw_slug.lower(), _slug_text(collection)]:
            if candidate and _has_letters(candidate):
                gift_id = candidate
                break
        if not gift_id:
            gift_id = raw_collection_id or raw_gift_id or slug_head or "unknown"

        attrs = raw.get("attributes") if isinstance(raw.get("attributes"), dict) else {}
        model = str(attrs.get("model") or raw.get("model") or "").strip() or "Unknown"
        background = str(attrs.get("background") or raw.get("background") or "").strip() or "Unknown"
        pattern = str(attrs.get("pattern") or raw.get("pattern") or "").strip() or "Unknown"
        collection = collection or _slug_to_name(gift_id)
        first_seen_at = str(raw.get("first_seen_at") or raw.get("ts_detected") or raw.get("ts") or _iso(now))
        last_seen_at = str(raw.get("last_seen_at") or raw.get("ts") or first_seen_at)
        relisted_at = str(raw.get("last_relisted_at") or "")
        try:
            ton = float(raw.get("resell_amount_ton") or raw.get("price_ton") or 0.0)
        except Exception:
            ton = 0.0
        stars_est_raw = raw.get("resell_amount_stars_est")
        if stars_est_raw in (None, ""):
            stars_est = self._stars_est(ton)
        else:
            try:
                stars_est = int(stars_est_raw)
            except Exception:
                stars_est = self._stars_est(ton)
        listing_key = str(raw.get("listing_key") or f"{gift_id}:{unique_id}")
        variant_id = str(raw.get("variant_id") or "").strip()
        if (not variant_id) or ("|unknown|unknown|unknown" in variant_id.lower()):
            variant_id = f"{gift_id}|{_slug_text(model)}|{_slug_text(background)}|{_slug_text(pattern)}"
        return {
            "listing_key": listing_key,
            "gift_id": gift_id,
            "gift_type_id": raw_gift_id or None,
            "unique_id": unique_id,
            "variant_id": variant_id,
            "num": raw.get("num"),
            "slug": str(raw.get("slug") or gift_id),
            "title": collection,
            "collection": collection,
            "collection_id": gift_id,
            "resell_currency": str(raw.get("resell_currency") or ("TON" if ton > 0 else "STARS")),
            "currency_mode": str(raw.get("currency_mode") or ("TON_ONLY" if ton > 0 else "STARS")),
            "resell_amount_ton": round(ton, 6) if ton > 0 else None,
            "resell_amount_stars_est": stars_est,
            "attributes": {"model": model, "background": background, "pattern": pattern},
            "status": str(raw.get("status") or "ACTIVE"),
            "sale_type": str(raw.get("sale_type") or "FIXED"),
            "preview_url": str(raw.get("preview_url") or ""),
            "ts_detected": first_seen_at,
            "first_seen_at": first_seen_at,
            "last_seen_at": last_seen_at,
            "relist_count": int(raw.get("relist_count") or 0),
            "last_relisted_at": relisted_at or None,
            "is_new": bool(raw.get("is_new")) or self._is_listing_new(now, first_seen_at, relisted_at, window_sec),
            "source": "mtproto_api",
        }

    def _refresh_mt_listing_source(self, force: bool = False, window_sec: int | None = None) -> tuple[list, dict]:
        now = _now()
        wsec = max(30, min(int(window_sec or self.listing_new_window_sec), 7 * 24 * 3600))
        cache = self._listing_mt_runtime_cache
        if (not force) and cache.get("rows") and (time.monotonic() - float(cache.get("fetched_mono") or 0.0)) < self.listing_mt_cache_ttl_sec:
            return list(cache.get("rows") or []), {
                "source": str(cache.get("source") or "runtime_cache"),
                "error": str(cache.get("error") or ""),
                "updated_at": cache.get("updated_at"),
                "url_configured": bool(self.listing_mt_api_url),
            }

        rows: list = []
        source = "disabled"
        error = ""
        updated_at = None
        if self.listing_mt_api_url:
            source = "mtproto_api"
            try:
                req = urllib.request.Request(self.listing_mt_api_url, method="GET")
                if self.listing_mt_api_token:
                    req.add_header(self.listing_mt_api_token_header, f"{self.listing_mt_api_token_prefix}{self.listing_mt_api_token}")
                with urllib.request.urlopen(req, timeout=self.listing_mt_api_timeout_sec) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                updated_at = payload.get("updated_at") if isinstance(payload, dict) else None
                for item in self._extract_mt_listing_items(payload):
                    norm = self._normalize_mt_listing_item(item, now=now, window_sec=wsec)
                    if norm:
                        rows.append(norm)
                if rows:
                    self.mt_listings_snapshot = {"updated_at": updated_at or _iso(now), "items": rows}
                    self._save_mt_listings_snapshot()
            except Exception as exc:
                error = f"{exc.__class__.__name__}: {exc}"

        if not rows:
            snap_items = self.mt_listings_snapshot.get("items") if isinstance(self.mt_listings_snapshot, dict) else []
            if isinstance(snap_items, list):
                for item in snap_items:
                    norm = self._normalize_mt_listing_item(item, now=now, window_sec=wsec)
                    if norm:
                        rows.append(norm)
            if rows:
                source = "mtproto_snapshot"
                updated_at = self.mt_listings_snapshot.get("updated_at") if isinstance(self.mt_listings_snapshot, dict) else None

        cache.update(
            {
                "fetched_mono": time.monotonic(),
                "rows": rows,
                "source": source,
                "error": error,
                "updated_at": updated_at or _iso(now),
                "rows_count": len(rows),
            }
        )
        return rows, {
            "source": source,
            "error": error,
            "updated_at": updated_at or _iso(now),
            "url_configured": bool(self.listing_mt_api_url),
            "rows_count": len(rows),
        }

    def _apply_listing_filters(
        self,
        rows: List[dict],
        only_new: bool,
        collection_q: str,
        model_q: str,
        background_q: str,
        pattern_q: str,
    ) -> List[dict]:
        c_q = str(collection_q or "").strip().lower()
        m_q = str(model_q or "").strip().lower()
        b_q = str(background_q or "").strip().lower()
        p_q = str(pattern_q or "").strip().lower()
        out = []
        for row in rows:
            attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
            collection_name = str(row.get("collection") or row.get("title") or row.get("collection_id") or "")
            collection_id = str(row.get("collection_id") or row.get("gift_id") or "").lower()
            model_name = str(attrs.get("model") or "")
            background_name = str(attrs.get("background") or "")
            pattern_name = str(attrs.get("pattern") or "")
            if c_q and c_q not in collection_name.lower() and c_q not in collection_id:
                continue
            if m_q and m_q not in model_name.lower():
                continue
            if b_q and b_q not in background_name.lower():
                continue
            if p_q and p_q not in pattern_name.lower():
                continue
            if only_new and not bool(row.get("is_new")):
                continue
            out.append(row)
        out.sort(
            key=lambda x: (str(x.get("last_seen_at") or ""), float(x.get("resell_amount_ton") or 0.0)),
            reverse=True,
        )
        return out

    def listing_source_status_v1(self) -> dict:
        _, status = self._refresh_mt_listing_source(force=False)
        rows_count = int(status.get("rows_count") or 0)
        error = str(status.get("error") or "")
        source = str(status.get("source") or "")
        degraded = bool(source.startswith("mtproto")) and (rows_count == 0)
        if degraded and not error:
            error = "mtproto_empty_payload"
        return {
            "primary_mode": self.listing_primary_source,
            "url_configured": bool(self.listing_mt_api_url),
            "source": source,
            "error": error,
            "updated_at": status.get("updated_at"),
            "cache_ttl_sec": self.listing_mt_cache_ttl_sec,
            "rows_count": rows_count,
            "degraded": degraded,
        }

    def listings_v1(
        self,
        limit: int = 100,
        cursor: str | None = None,
        only_new: bool = False,
        new_window_sec: int | None = None,
        collection_q: str = "",
        model_q: str = "",
        background_q: str = "",
        pattern_q: str = "",
    ) -> dict:
        now = _now()
        self._sync_listing_tracker_state(now, persist=False)
        window_sec = max(30, min(int(new_window_sec or self.listing_new_window_sec), 7 * 24 * 3600))
        source_status = {"source": "fragment.verified_snapshot", "error": "", "updated_at": self.state.get("updated_at")}
        rows = []
        primary_mode = self.listing_primary_source
        if primary_mode in {"auto", "mtproto", "mtproto_api"}:
            mt_rows, mt_status = self._refresh_mt_listing_source(force=False, window_sec=window_sec)
            source_status = mt_status
            if mt_rows:
                rows = mt_rows
            elif primary_mode in {"mtproto", "mtproto_api"}:
                source_status = {
                    "source": "fragment.verified_snapshot",
                    "error": str(mt_status.get("error") or "mtproto_empty_payload"),
                    "updated_at": self.state.get("updated_at"),
                }
        if not rows:
            rows = self._build_runtime_listing_rows(now, window_sec=window_sec)
            if not str(source_status.get("source") or "").startswith("mtproto"):
                source_status = {
                    "source": "fragment.verified_snapshot",
                    "error": str(source_status.get("error") or ""),
                    "updated_at": self.state.get("updated_at"),
                }
        rows = self._apply_listing_filters(
            rows,
            only_new=only_new,
            collection_q=collection_q,
            model_q=model_q,
            background_q=background_q,
            pattern_q=pattern_q,
        )
        off = self._cursor_offset(cursor)
        lim = max(1, min(int(limit or 100), 500))
        chunk = rows[off : off + lim]
        next_cursor = str(off + lim) if (off + lim) < len(rows) else None
        return {
            "items": chunk,
            "next_cursor": next_cursor,
            "window_sec": window_sec,
            "source": source_status.get("source") or "fragment.verified_snapshot",
            "source_error": source_status.get("error") or "",
        }

    def listings_summary_v1(self, new_window_sec: int | None = None) -> dict:
        now = _now()
        self._sync_listing_tracker_state(now, persist=False)
        window_sec = max(30, min(int(new_window_sec or self.listing_new_window_sec), 7 * 24 * 3600))
        source = "fragment.verified_snapshot"
        source_error = ""
        rows = []
        mt_status = {}
        if self.listing_primary_source in {"auto", "mtproto", "mtproto_api"}:
            mt_rows, mt_status = self._refresh_mt_listing_source(force=False, window_sec=window_sec)
            if mt_rows:
                rows = mt_rows
                source = str(mt_status.get("source") or "mtproto_api")
                source_error = str(mt_status.get("error") or "")
            elif self.listing_primary_source in {"mtproto", "mtproto_api"}:
                source_error = str(mt_status.get("error") or "mtproto_empty_payload")
        if not rows:
            rows = self._build_runtime_listing_rows(now, window_sec=window_sec)
        by_collection: Dict[str, int] = {}
        active_total = len(rows)
        new_total = 0
        relisted_total = 0
        price_samples: List[float] = []
        for row in rows:
            if bool(row.get("is_new")):
                new_total += 1
            relisted_at = row.get("last_relisted_at")
            relisted_dt = _parse_ts(relisted_at) if relisted_at else None
            if relisted_dt is not None and (now - relisted_dt).total_seconds() <= window_sec:
                relisted_total += 1
            collection_id = str(row.get("collection_id") or row.get("gift_id") or "").strip().lower()
            if collection_id:
                by_collection[collection_id] = by_collection.get(collection_id, 0) + 1
            price = float(row.get("resell_amount_ton") or 0.0)
            if price > 0:
                price_samples.append(price)

        top_collections = sorted(by_collection.items(), key=lambda x: x[1], reverse=True)[:8]
        return {
            "active_total": active_total,
            "new_total": new_total,
            "relisted_total": relisted_total,
            "window_sec": window_sec,
            "collections_active": len(by_collection),
            "price_ton_min": round(min(price_samples), 6) if price_samples else None,
            "price_ton_median": round(_safe_median(price_samples), 6) if price_samples else None,
            "top_collections": [
                {
                    "collection_id": cid,
                    "collection": self.bases.get(cid).name if cid in self.bases else _slug_to_name(cid),
                    "active_listings": count,
                }
                for cid, count in top_collections
            ],
            "updated_at": self.state.get("updated_at") or _iso(now),
            "source": source,
            "source_error": source_error,
        }

    def listings_events_v1(
        self,
        limit: int = 100,
        cursor: str | None = None,
        since: str | None = None,
        new_window_sec: int | None = None,
        include_relisted: bool = True,
    ) -> dict:
        now = _now()
        window_sec = max(30, min(int(new_window_sec or self.listing_new_window_sec), 7 * 24 * 3600))
        since_dt = _parse_ts(since) if since else (now - timedelta(seconds=window_sec))
        source = "fragment.verified_snapshot"
        source_error = ""
        rows = []
        if self.listing_primary_source in {"auto", "mtproto", "mtproto_api"}:
            mt_rows, mt_status = self._refresh_mt_listing_source(force=False, window_sec=window_sec)
            if mt_rows:
                rows = mt_rows
                source = str(mt_status.get("source") or "mtproto_api")
                source_error = str(mt_status.get("error") or "")
            elif self.listing_primary_source in {"mtproto", "mtproto_api"}:
                source_error = str(mt_status.get("error") or "mtproto_empty_payload")
        if not rows:
            rows = self._build_runtime_listing_rows(now, window_sec=window_sec)
            source = "fragment.verified_snapshot"
        events: list[dict] = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}

            def _append_event(event_ts: datetime | None, event_name: str) -> None:
                if event_ts is None or event_ts < since_dt:
                    return
                events.append(
                    {
                        "topic": event_name,
                        "ts": _iso(event_ts),
                        "source": str(row.get("source") or source or "mtproto_api"),
                        "gift_id": str(row.get("collection_id") or row.get("gift_id") or ""),
                        "unique_id": str(row.get("unique_id") or ""),
                        "num": row.get("num"),
                        "slug": str(row.get("slug") or ""),
                        "title": str(row.get("title") or row.get("collection") or ""),
                        "listing_key": str(row.get("listing_key") or ""),
                        "variant_id": str(row.get("variant_id") or ""),
                        "resell_currency": str(row.get("resell_currency") or "STARS"),
                        "resell_amount": row.get("resell_amount_stars_est")
                        if str(row.get("resell_currency") or "").upper() == "STARS"
                        else row.get("resell_amount_ton"),
                        "attributes": {
                            "model": str(attrs.get("model") or "Unknown"),
                            "background": str(attrs.get("background") or "Unknown"),
                            "pattern": str(attrs.get("pattern") or "Unknown"),
                        },
                    }
                )

            first_seen_dt = _parse_ts(row.get("first_seen_at"))
            _append_event(first_seen_dt, "market.listing.new")
            if include_relisted:
                relisted_dt = _parse_ts(row.get("last_relisted_at"))
                _append_event(relisted_dt, "market.listing.relisted")

        events.sort(key=lambda x: str(x.get("ts") or ""), reverse=True)
        off = self._cursor_offset(cursor)
        lim = max(1, min(int(limit or 100), 1000))
        chunk = events[off : off + lim]
        next_cursor = str(off + lim) if (off + lim) < len(events) else None
        return {
            "items": chunk,
            "next_cursor": next_cursor,
            "window_sec": window_sec,
            "source": source,
            "source_error": source_error,
        }

    def listings_signals_v1(
        self,
        limit: int = 50,
        cursor: str | None = None,
        since: str | None = None,
        new_window_sec: int | None = None,
        include_relisted: bool = True,
        signal_type: str | None = None,
        min_score: float | None = None,
        mode: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        sort_by: str | None = None,
        sort_dir: str | None = None,
    ) -> dict:
        eff_mode = self._effective_v1_mode(mode)
        events_payload = self.listings_events_v1(
            limit=5000,
            cursor=None,
            since=since,
            new_window_sec=new_window_sec,
            include_relisted=include_relisted,
        )
        out: list[dict] = []
        for ev in (events_payload.get("items") or []):
            if not isinstance(ev, dict):
                continue
            variant_id = str(ev.get("variant_id") or "").strip()
            v = self.variants.get(variant_id) if variant_id else None
            if v:
                base_sig = self._v1_signal(v, mode=eff_mode)
                sig_type_val = str(base_sig.get("type") or "WATCH")
                score100 = float(base_sig.get("score100") or 0.0)
                conf_pct = float(base_sig.get("conf_pct") or 0.0)
                forecast_min = float(base_sig.get("forecast24h_pct_min") or 0.0)
                forecast_max = float(base_sig.get("forecast24h_pct_max") or 0.0)
                expected_profit_pct = float(base_sig.get("expected_profit_pct") or 0.0)
                undervalue = float(base_sig.get("undervalue") or 0.0)
                price_ton = base_sig.get("price_ton")
                fair_ton = base_sig.get("fair_ton")
                floor_ton = base_sig.get("floor_ton")
                reasons = list(base_sig.get("reasons") or [])[:4]
                risks = list(base_sig.get("risk_flags") or [])[:4]
            else:
                is_relisted = str(ev.get("topic") or "").endswith("relisted")
                sig_type_val = "WATCH" if is_relisted else "BUY"
                score100 = 52.0 if is_relisted else 58.0
                conf_pct = 46.0 if is_relisted else 52.0
                forecast_min = -8.0 if is_relisted else -4.0
                forecast_max = 6.0 if is_relisted else 10.0
                expected_profit_pct = 0.0
                undervalue = 0.0
                price_ton = None
                fair_ton = None
                floor_ton = None
                reasons = ["Вариант пока прогревается в аналитике, используется быстрый listing-сигнал."]
                risks = ["WARMUP_VARIANT_METRICS"]

            if signal_type and sig_type_val != str(signal_type):
                continue
            if min_score is not None and (score100 / 100.0) < float(min_score):
                continue

            signal_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"listing|{ev.get('topic')}|{ev.get('listing_key')}|{ev.get('ts')}"))
            out.append(
                {
                    "signal_id": signal_id,
                    "ts": ev.get("ts") or _iso(_now()),
                    "type": sig_type_val,
                    "topic": ev.get("topic"),
                    "listing_key": ev.get("listing_key"),
                    "variant_id": variant_id,
                    "collection_id": ev.get("gift_id"),
                    "collection": ev.get("title") or ev.get("gift_id"),
                    "model": ((ev.get("attributes") or {}).get("model") if isinstance(ev.get("attributes"), dict) else None),
                    "background": ((ev.get("attributes") or {}).get("background") if isinstance(ev.get("attributes"), dict) else None),
                    "pattern": ((ev.get("attributes") or {}).get("pattern") if isinstance(ev.get("attributes"), dict) else None),
                    "score100": round(score100, 1),
                    "conf_pct": round(conf_pct, 1),
                    "price_ton": price_ton,
                    "floor_ton": floor_ton,
                    "fair_ton": fair_ton,
                    "undervalue": round(undervalue, 6),
                    "expected_profit_pct": round(expected_profit_pct, 6),
                    "forecast24h_pct_min": round(forecast_min, 1),
                    "forecast24h_pct_max": round(forecast_max, 1),
                    "active_lots": None,
                    "liquidity24h": None,
                    "reasons": reasons,
                    "risk_flags": risks,
                    "engine_mode": eff_mode,
                    "source": ev.get("source") or events_payload.get("source") or "mtproto_api",
                }
            )

        sort_field = str(sort_by or "ts").strip().lower()
        sort_direction = str(sort_dir or "desc").strip().lower()
        reverse = sort_direction != "asc"
        allowed_sort_fields = {
            "ts",
            "score100",
            "conf_pct",
            "type",
            "collection",
            "variant_id",
            "forecast24h_pct_max",
        }
        if sort_field not in allowed_sort_fields:
            sort_field = "ts"

        def _sort_key(row: dict):
            if sort_field == "score100":
                return float(row.get("score100") or 0.0)
            if sort_field == "conf_pct":
                return float(row.get("conf_pct") or 0.0)
            if sort_field == "forecast24h_pct_max":
                return float(row.get("forecast24h_pct_max") or 0.0)
            if sort_field == "type":
                return str(row.get("type") or "")
            if sort_field == "collection":
                return str(row.get("collection") or row.get("collection_id") or "")
            if sort_field == "variant_id":
                return str(row.get("variant_id") or "")
            return str(row.get("ts") or "")

        out.sort(key=_sort_key, reverse=reverse)
        total = len(out)

        page_n = None
        page_size_n = None
        if page is not None or page_size is not None:
            try:
                page_n = max(1, int(page or 1))
            except Exception:
                page_n = 1
            try:
                page_size_n = max(1, min(int(page_size or limit or 50), 200))
            except Exception:
                page_size_n = max(1, min(int(limit or 50), 200))
            off = (page_n - 1) * page_size_n
            lim = page_size_n
        else:
            off = self._cursor_offset(cursor)
            lim = max(1, min(int(limit or 50), 500))

        chunk = out[off : off + lim]
        next_cursor = str(off + lim) if (off + lim) < total else None
        total_pages = max(1, int(math.ceil(total / float(lim)))) if lim else 1
        return {
            "items": chunk,
            "next_cursor": next_cursor,
            "engine_mode": eff_mode,
            "source": events_payload.get("source"),
            "source_error": events_payload.get("source_error"),
            "total": total,
            "page": page_n if page_n is not None else None,
            "page_size": lim,
            "total_pages": total_pages,
            "sort_by": sort_field,
            "sort_dir": "asc" if not reverse else "desc",
        }

    def _evaluate_alerts(self, now: datetime) -> None:
        if self.is_stale() and os.getenv("ALERTS_SUSPEND_ON_STALE", "true").lower() in {"1", "true", "yes", "on"}:
            return
        for alert in self.alert_rules:
            rule = alert.get("rule_json") or {}
            if not self._alert_matches(rule, now):
                continue
            debounce = int((rule.get("delivery") or {}).get("debounce_minutes", 10))
            last = alert.get("last_fired_at")
            if last and (_parse_ts(last) + timedelta(minutes=debounce)) > now:
                continue
            payload = self._build_alert_payload(rule, now)
            alert["last_fired_at"] = _iso(now)
            alert["last_payload_json"] = payload
            self.alert_events.append(payload)
        if self.alert_rules:
            self._save_alerts()

    def _alert_matches(self, rule: dict, now: datetime) -> bool:
        entity = (rule.get("entity") or {})
        etype = entity.get("type")
        target_id = entity.get("id")
        metrics = self._entity_metrics(etype, target_id)
        if not metrics:
            return False
        for cond in rule.get("conditions", []):
            metric = cond.get("metric")
            op = cond.get("op")
            value = cond.get("value")
            current = metrics.get(metric)
            if not _compare(current, op, value):
                return False
        return True

    def _build_alert_payload(self, rule: dict, now: datetime) -> dict:
        entity = rule.get("entity") or {}
        metrics = self._entity_metrics(entity.get("type"), entity.get("id")) or {}
        if entity.get("type") == "VARIANT" and entity.get("id"):
            title = self._variant_title(entity.get("id"))
            if title:
                metrics["title"] = title
        title = (rule.get("message_template") or {}).get("title", "Alert")
        body = (rule.get("message_template") or {}).get("body", "")
        return {
            "notification_id": f"n_{now.strftime('%Y%m%d_%H%M%S')}",
            "channel": (rule.get("delivery") or {}).get("channels", ["WEB_PUSH"])[0],
            "title": title,
            "body": body.format(**(metrics or {})),
            "data": metrics,
            "entity": entity,
            "rule": rule,
        }

    def _variant_title(self, variant_id: str) -> str | None:
        v_id = self._listing_to_variant(variant_id) or variant_id
        v = self.variants.get(v_id)
        if not v:
            return None
        return f"{v['traits']['model']['name']} • {v['traits']['background']['name']} • {v['traits']['pattern']['name']}"

    def _entity_metrics(self, etype: str | None, entity_id: str | None) -> dict | None:
        if not etype or not entity_id:
            return None
        if etype == "VARIANT":
            v = self.get_variant(entity_id)
            if not v:
                return None
            return v.get("metrics")
        if etype == "BASE":
            b = self.get_base(entity_id)
            if not b:
                return None
            return b.get("metrics")
        if etype == "DIMENSION":
            try:
                base_id, dim_type, dim_id = entity_id.split("|", 2)
            except ValueError:
                return None
            dims = self.list_dimensions(base_id, dim_type, "24h").get("items", [])
            for d in dims:
                if d.get("dim_id") == dim_id:
                    return d.get("metrics")
        return None

    def _decorate_metrics(self, metrics: dict) -> dict:
        decorated = dict(metrics)
        if metrics.get("floor_ton") is not None:
            decorated["floor_stars_est"] = self._stars_est(metrics.get("floor_ton"))
        if metrics.get("median_ton") is not None:
            decorated["median_stars_est"] = self._stars_est(metrics.get("median_ton"))
        if metrics.get("vwap_ton") is not None:
            decorated["vwap_stars_est"] = self._stars_est(metrics.get("vwap_ton"))
        return decorated

    def _stars_est(self, ton: float | None) -> int | None:
        if ton is None:
            return None
        rate = self.stars_rate().get("stars_per_ton")
        return int(round(ton * rate)) if rate else None

    def _short_variant(self, v: dict) -> dict:
        return {
            "variant_id": v["variant_id"],
            "base_id": v["base_id"],
            "title": f"{v['traits']['model']['name']} • {v['traits']['background']['name']} • {v['traits']['pattern']['name']}",
            "preview_url": v.get("preview_url", ""),
            "metrics": self._decorate_metrics(v["metrics"]),
            "reco": v.get("reco"),
        }

    def _short_reco(self, v: dict) -> dict:
        reco = v.get("reco") or {}
        metrics = v.get("metrics") or {}
        title = f"{v['traits']['model']['name']} • {v['traits']['background']['name']} • {v['traits']['pattern']['name']}"
        return {
            "variant_id": v["variant_id"],
            "base_id": v["base_id"],
            "title": title,
            "preview_url": v.get("preview_url", ""),
            "action": reco.get("action"),
            "reco_score": reco.get("reco_score"),
            "confidence": reco.get("confidence"),
            "reasons": reco.get("reasons"),
            "risks": reco.get("risks"),
            "forecast": reco.get("forecast"),
            "summary": reco.get("summary"),
            "floor_change_pct_24h": metrics.get("floor_change_pct_24h"),
            "floor_ton": metrics.get("floor_ton"),
        }

    def _aggregate_reco(self, variants: List[dict]) -> dict:
        if not variants:
            return {"action": "HOLD", "reco_score": 0, "confidence": 0}
        scores = [v.get("reco", {}).get("reco_score", 0) for v in variants]
        avg = _safe_mean(scores)
        action = _reco_action(avg, _safe_mean([v["metrics"].get("liquidity_score_24h", 0) for v in variants]), _safe_mean([v["metrics"].get("thin_market_risk_24h", 0) for v in variants]))
        return {"action": action, "reco_score": round(avg, 1), "confidence": int(_clamp(avg, 0, 100))}

    def _listing_to_variant(self, listing_id: str) -> str | None:
        listing = self.listing_state.get(listing_id)
        if listing:
            return listing.get("variant_id")
        return None


def _compare(current, op: str, target) -> bool:
    if op in {"<", "<=", ">", ">=", "=="}:
        try:
            c = float(current)
            t = float(target)
        except Exception:
            return False
        if op == "<":
            return c < t
        if op == "<=":
            return c <= t
        if op == ">":
            return c > t
        if op == ">=":
            return c >= t
        if op == "==":
            return c == t
    if op in {"!=", "=="}:
        return current != target if op == "!=" else current == target
    return False


def _reco_action(
    reco: float,
    liquidity: float,
    risk: float,
    confidence: int = 50,
    data_quality: float = 1.0,
    regime: str = "sideways",
    contrarian_opportunity: bool = False,
) -> str:
    # Hard quality gate: avoid aggressive advice on weak datasets.
    if data_quality < 0.25:
        return "AVOID"
    if data_quality < 0.35:
        return "HOLD"

    buy_score = float(os.getenv("SIGNALS_BUY_SCORE", "72"))
    buy_conf = int(os.getenv("SIGNALS_BUY_CONFIDENCE", "58"))
    if regime == "bear" and contrarian_opportunity:
        buy_score = float(os.getenv("SIGNALS_BUY_SCORE_BEAR", "62"))
        buy_conf = int(os.getenv("SIGNALS_BUY_CONFIDENCE_BEAR", "52"))

    if reco >= buy_score and confidence >= buy_conf and liquidity >= 0.28 and risk <= 0.62:
        return "BUY"
    if reco >= 60 and confidence >= 52:
        return "WATCH"
    if reco <= 30 and confidence >= 55 and liquidity <= 0.28:
        return "AVOID"
    if reco <= 38 and confidence >= 50:
        return "SELL"
    return "HOLD"


def active_listings_score(active: int) -> float:
    if active <= 5:
        return 0.2
    if active <= 20:
        return 0.5
    if active <= 100:
        return 0.8
    return 1.0


def _signed_norm(value: float | int | None, bound: float) -> float:
    if bound <= 0:
        return 0.0
    try:
        n = float(value or 0.0)
    except Exception:
        n = 0.0
    return _clamp(n / bound, -1.0, 1.0)


def _build_forecast(metrics: dict, momentum: float, confidence: int) -> dict:
    # Compact and explainable 24h scenario, tuned for UI and bot delivery.
    trend_bias = "flat"
    if momentum >= 0.18:
        trend_bias = "up"
    elif momentum <= -0.18:
        trend_bias = "down"

    base_move = float(metrics.get("floor_change_pct_24h", 0) or 0)
    vol = float(metrics.get("volatility_24h", 0) or 0)
    span = _clamp(abs(base_move) * 0.55 + vol * 120, 1.2, 18.0)
    center = _clamp(base_move * 0.45 + momentum * 16, -25.0, 25.0)
    low = round(center - span, 1)
    high = round(center + span, 1)
    if low > high:
        low, high = high, low
    return {
        "horizon": "24h",
        "bias": trend_bias,
        "range_pct": [low, high],
        "confidence": int(_clamp(confidence, 1, 99)),
    }


def _build_reco_summary(action: str, reco_score: float, confidence: int, forecast: dict | None) -> str:
    bias = str((forecast or {}).get("bias") or "flat")
    rng = (forecast or {}).get("range_pct") or [0.0, 0.0]
    low = float(rng[0]) if len(rng) > 0 else 0.0
    high = float(rng[1]) if len(rng) > 1 else 0.0
    trend_label = {"up": "ожидается рост", "down": "ожидается снижение", "flat": "ожидается боковик"}.get(bias, "ожидается боковик")
    action_label = {
        "BUY": "Покупка",
        "WATCH": "Наблюдать",
        "HOLD": "Держать",
        "SELL": "Продажа",
        "AVOID": "Избегать",
    }.get(action, "Держать")
    return f"{action_label}: {trend_label} (24ч: {low:.1f}%…{high:.1f}%, оценка {reco_score:.1f}, уверенность {confidence}%)"


def _build_reasons(metrics: dict, momentum: float, trades_n: float, liquidity: float, scarcity: float) -> List[dict]:
    reasons = []
    if momentum > 0.1:
        reasons.append(
            {
                "code": "R_MOMENTUM",
                "title": "Поддержка тренда",
                "text": f"Цена поддерживает восходящий импульс: Δ24h {round(float(metrics.get('floor_change_pct_24h', 0) or 0), 1)}%.",
                "value": {"metric": "floor_change_pct_24h", "num": metrics.get("floor_change_pct_24h")},
            }
        )
    if trades_n > 0.15 and metrics.get("trades_count_24h", 0) > 0:
        reasons.append(
            {
                "code": "R_DEMAND_UP",
                "title": "Есть рыночный спрос",
                "text": f"Сделок за 24h: {int(metrics.get('trades_count_24h', 0) or 0)}, объем: {round(float(metrics.get('volume_ton_24h', 0) or 0), 2)} TON.",
                "value": {"metric": "trades_count_24h", "num": metrics.get("trades_count_24h")},
            }
        )
    if scarcity > 0.25 or (metrics.get("supply_change_pct_24h") is not None and metrics.get("supply_change_pct_24h") < 0):
        reasons.append(
            {
                "code": "R_SUPPLY_DOWN",
                "title": "Ограниченное предложение",
                "text": f"Активных лотов: {int(metrics.get('active_listings', 0) or 0)}.",
                "value": {"metric": "supply_change_pct_24h", "num": metrics.get("supply_change_pct_24h")},
            }
        )
    if liquidity >= 0.35:
        reasons.append(
            {
                "code": "R_LIQUIDITY",
                "title": "Достаточная ликвидность",
                "text": f"Ликвидность 24h: {round(float(liquidity), 2)}.",
                "value": {"metric": "liquidity_score_24h", "num": liquidity},
            }
        )
    return reasons[:3]


def _build_risks(metrics: dict, volatility_penalty: float, thin_penalty: float, pump_penalty: float, spread_penalty: float, data_quality: float) -> List[dict]:
    risks = []
    if thin_penalty > 0.5:
        risks.append(
            {
                "code": "K_THIN_MARKET",
                "title": "Тонкий рынок",
                "text": f"Низкая глубина: активных лотов {int(metrics.get('active_listings', 0) or 0)}.",
            }
        )
    if volatility_penalty > 0.45:
        risks.append(
            {
                "code": "K_VOLATILITY",
                "title": "Высокая волатильность",
                "text": f"Риск резких колебаний: волатильность {round(float(metrics.get('volatility_24h', 0) or 0), 3)}.",
            }
        )
    if pump_penalty > 0.6:
        risks.append(
            {
                "code": "K_PUMP_RISK",
                "title": "Риск перегрева",
                "text": "Резкое ускорение цены при низкой ликвидности.",
            }
        )
    if spread_penalty > 0.6:
        risks.append(
            {
                "code": "K_SPREAD",
                "title": "Широкий спред",
                "text": "Вход/выход может быть неэффективным из-за широкого ценового разрыва.",
            }
        )
    if data_quality < 0.35 or (metrics.get("floor_change_pct_24h") == 0 and metrics.get("trades_count_24h") == 0):
        risks.append(
            {
                "code": "K_DATA_GAPS",
                "title": "Недостаточно данных",
                "text": "Сигнал низкой надежности, требуется больше рыночных наблюдений.",
            }
        )
    return risks[:3]

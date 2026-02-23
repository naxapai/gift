from __future__ import annotations

import json
import math
import os
import ssl
import threading
import time
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

WINDOWS = {
    "1h": 60 * 60,
    "12h": 12 * 60 * 60,
    "24h": 24 * 60 * 60,
    "7d": 7 * 24 * 60 * 60,
    "30d": 30 * 24 * 60 * 60,
}


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
        self.ai_key_rejected = False
        self.ai_last_error = ""
        self.ai_lock = threading.Lock()
        self.ai_next_allowed_ts = 0.0
        self.ai_probe_cache: dict = {"checked_at_ts": 0, "payload": None}
        self._data_version = 0
        self._reco_version = -1
        self._view_cache: Dict[tuple, tuple[int, dict | list]] = {}
        self.source_totals: Dict[str, int] = {
            "for_sale": 0,
            "sold": 0,
            "auction": 0,
        }
        self.fragment_bootstrap_cache = os.getenv("FRAGMENT_BOOTSTRAP_CACHE", "true").strip().lower() in {"1", "true", "yes", "on"}
        self._restore_from_listing_state()
        if self.fragment_bootstrap_cache and not self.variants:
            self._bootstrap_from_verified_file()
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

    def _save_trade_events(self) -> None:
        _save_json(TRADE_EVENTS_FILE, self.trade_events)

    def _save_alerts(self) -> None:
        _save_json(ALERTS_FILE, self.alert_rules)
        _save_json(ALERT_EVENTS_FILE, self.alert_events)

    def _save_ai_cache(self) -> None:
        _save_json(AI_RECO_CACHE_FILE, self.ai_reco_cache)

    def stars_rate(self) -> dict:
        return self.stars.to_dict()

    def ingest(self) -> None:
        now = _now()
        with self.lock:
            if self.state.get("ingest_in_progress"):
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
        self._update_source_totals(dataset)
        return self._events_bases_from_verified_dataset(dataset)

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

        self._save_listing_state()
        self._save_trade_events()

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
        ranges = self._market_ranges()
        for v in self.variants.values():
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
            raw_score = 50 + (edge * 50)
            reco = _clamp(raw_score, 0, 100)

            signal_strength = _clamp(abs(edge), 0, 1)
            confidence = int(round(_clamp((0.58 * data_quality + 0.42 * signal_strength) * 100, 5, 99)))
            action = _reco_action(
                reco,
                liquidity,
                (0.45 * volatility_penalty + 0.35 * thin_penalty + 0.20 * pump_penalty),
                confidence=confidence,
                data_quality=data_quality,
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
        variants = list(self.variants.values())
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
        payload = {
            "updated_at": self.state.get("updated_at"),
            "variant_count": len(variants),
            "gifts_count": sum(active) if active else 0,
            "base_count": len({v["base_id"] for v in variants}),
            "model_count": len(models),
            "floor_ton_min": min(floors) if floors else None,
            "floor_ton_median": _safe_median(floors) if floors else None,
            "active_listings": sum(active) if active else 0,
            "avg_change_7d": round(avg_7d, 3),
            "avg_change_30d": round(avg_30d, 3),
            "market_state": market_state,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "anomalies": anomalies,
            "total_for_sale": int(self.source_totals.get("for_sale", sum(active) if active else 0)),
            "total_sold": int(self.source_totals.get("sold", len(self.trade_events))),
            "data_stale": self.is_stale(),
            "ingestion_lag_seconds": self.state.get("ingestion_lag_seconds"),
            "last_error": self.state.get("last_error"),
            "ingest_in_progress": self.state.get("ingest_in_progress"),
            "last_ingest_started_at": self.state.get("last_ingest_started_at"),
            # Runtime diagnostics for Render env drift / stale deploy checks.
            "runtime_source": os.getenv("VERIFIED_SOURCE", "file"),
            "runtime_gift_mode": os.getenv("FRAGMENT_GIFT_MODE", "lot"),
            "runtime_max_collections": int(os.getenv("FRAGMENT_MAX_COLLECTIONS", "0")),
            "runtime_max_pages_per_collection": int(os.getenv("FRAGMENT_MAX_PAGES_PER_COLLECTION", "500")),
            "runtime_verified_data_file": os.getenv("VERIFIED_DATA_FILE", "data/verified_gifts.json"),
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
        self._save_ai_cache()

        reco = dict(base_reco)
        reco.update(ai_reco)
        reco["source"] = "ai_live"
        reco["ai_debug"] = {"enabled": True, "cached": False}
        return reco

    def ai_status(self, probe: bool = False) -> dict:
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
                return None
            except (urllib.error.URLError, TimeoutError, ValueError) as e:
                if attempt + 1 < max_attempts:
                    sleep_sec = min(10.0, self.ai_retry_backoff_sec * (2 ** attempt))
                    self.ai_last_error = f"OPENAI_NET_RETRY attempt={attempt + 1}/{max_attempts} sleep={sleep_sec:.1f}s err={e}"
                    time.sleep(max(0.0, sleep_sec))
                    continue
                self.ai_last_error = f"OPENAI_HTTP_ERROR: {e}"
                return None
        if not isinstance(raw, dict):
            self.ai_last_error = "OPENAI_EMPTY_RESPONSE"
            return None

        try:
            text = raw["choices"][0]["message"]["content"]
            parsed = self._parse_ai_json(text)
            if not isinstance(parsed, dict):
                self.ai_last_error = "OPENAI_PARSE_ERROR: response is not JSON object"
                return None
        except Exception as e:
            self.ai_last_error = f"OPENAI_PARSE_ERROR: {e}"
            return None

        action = str(parsed.get("action", "HOLD")).upper()
        if action not in {"BUY", "HOLD", "SELL", "WATCH", "AVOID"}:
            action = "HOLD"
        reco_score = float(parsed.get("reco_score", 50))
        confidence = int(parsed.get("confidence", 60))
        reasons_raw = parsed.get("reasons") or []
        risks_raw = parsed.get("risks") or []
        reasons = [{"code": "R_AI", "text": str(x)} for x in reasons_raw[:6]]
        risks = [{"code": "K_AI", "text": str(x)} for x in risks_raw[:5]]
        return {
            "action": action,
            "reco_score": round(_clamp(reco_score, 0, 100), 1),
            "confidence": int(_clamp(confidence, 0, 100)),
            "reasons": reasons,
            "risks": risks,
        }

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
        items = list(self.variants.values())
        if entity != "variant":
            items = list(self.variants.values())
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
        return {
            "entity": entity,
            "period": period,
            "type": metric_type,
            "updated_at": self.state.get("updated_at"),
            "items": top_items,
            "stars_rate": self.stars_rate(),
        }

    def recommendations(self, scope: str, entity: str, include_ai: bool = False) -> dict:
        items = list(self.variants.values())
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
        return {
            "scope": scope,
            "entity": entity,
            "updated_at": self.state.get("updated_at"),
            "items": rec_items,
        }

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
) -> str:
    # Hard quality gate: avoid aggressive advice on weak datasets.
    if data_quality < 0.25:
        return "AVOID"
    if data_quality < 0.35:
        return "HOLD"

    if reco >= 72 and confidence >= 58 and liquidity >= 0.28 and risk <= 0.62:
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

from __future__ import annotations

import json
import os
import random
import re
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from http import cookiejar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlencode, parse_qsl, urlparse, urlunparse

DATA_FILE = Path(__file__).parent / "data" / "gifts_history.json"
VERIFIED_DATA_FILE = Path(__file__).parent / "data" / "verified_gifts.json"
FRAGMENT_ANALYTICS_STORE_FILE = Path(__file__).parent / "data" / "fragment_analytics_store.json"
FRAGMENT_SNAPSHOT_META_FILE = Path(__file__).parent / "data" / "fragment_snapshot_meta.json"
FRAGMENT_LOT_TRAITS_CACHE_FILE = Path(__file__).parent / "data" / "fragment_lot_traits_cache.json"
MIN_GIFTS_COUNT = 200
REQUIRED_GIFT_IDS = {"input_key_magic_8_ball_60441"}


@dataclass
class GiftPoint:
    dt: str
    price: float
    demand: float
    supply: float
    volume: int


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _atomic_write_json(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{random.randint(1000, 9999)}")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def _load_json_with_retry(path: Path, retries: int = 3, delay_sec: float = 0.08) -> Dict:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError(f"Invalid JSON root in {path}: expected object")
            return payload
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(delay_sec)
                continue
            raise last_err
    raise RuntimeError(f"Unable to load JSON from {path}")


def _gift_templates() -> List[Dict]:
    bases = [
        ("Rose", "Flowers", 38.0, 0.031),
        ("Tulip", "Flowers", 28.0, 0.029),
        ("Gift Box", "Boxes", 60.0, 0.039),
        ("Diamond Heart", "Premium", 110.0, 0.052),
        ("Golden Star", "Premium", 82.0, 0.043),
        ("Lucky Balloon", "Fun", 21.0, 0.03),
        ("Sakura", "Flowers", 49.0, 0.037),
        ("Ocean Pearl", "Luxury", 72.0, 0.041),
        ("Neon Comet", "Digital", 90.0, 0.048),
        ("Royal Crown", "Luxury", 130.0, 0.05),
    ]
    tiers = [
        "Classic", "Prime", "Luxe", "Ultra", "Rare", "Elite", "Nova", "Pulse", "Spark", "Zen",
        "Core", "Pro", "Plus", "Max", "Aura", "Flash", "Orbit", "Crystal", "Legend", "Infinity",
    ]

    templates: List[Dict] = []
    for base_name, group, base_price, base_vol in bases:
        for idx, tier in enumerate(tiers):
            full_name = f"{base_name} {tier}"
            gift_id = (
                full_name.lower()
                .replace(" ", "_")
                .replace("-", "_")
                .replace("__", "_")
            )
            price_mult = 0.74 + idx * 0.055
            vol_add = idx * 0.0015
            templates.append(
                {
                    "gift_id": gift_id,
                    "name": full_name,
                    "group": group,
                    "base_price": round(base_price * price_mult, 2),
                    "volatility": round(base_vol + vol_add, 4),
                }
            )
    templates.append(
        {
            "gift_id": "input_key_magic_8_ball_60441",
            "name": "Input Key (magic 8 ball) #60441",
            "group": "Portals Collection",
            "base_price": 88.0,
            "volatility": 0.047,
        }
    )
    return templates


def generate_dataset(days: int = 180, seed: int = 42) -> Dict:
    random.seed(seed)
    start = date.today() - timedelta(days=days - 1)
    gifts = []

    for template in _gift_templates():
        series: List[GiftPoint] = []
        price = template["base_price"] * random.uniform(0.85, 1.15)
        demand = random.uniform(0.9, 1.4)
        supply = random.uniform(0.8, 1.5)
        drift = random.uniform(-0.0004, 0.0014)

        for idx in range(days):
            current_date = start + timedelta(days=idx)
            month_cycle = (idx % 30) / 30.0
            season_component = 0.012 if 0.12 <= month_cycle <= 0.33 else -0.004
            noise = random.gauss(0, template["volatility"])
            price_change = drift + season_component + noise
            price_change = _clamp(price_change, -0.18, 0.2)
            price = max(1.0, price * (1 + price_change))

            demand = _clamp(demand * (1 + random.gauss(0.0, 0.05)), 0.5, 2.8)
            supply = _clamp(supply * (1 + random.gauss(0.0, 0.05)), 0.45, 3.0)

            if random.random() < 0.03:
                demand = _clamp(demand * random.uniform(1.08, 1.28), 0.6, 3.1)
            if random.random() < 0.03:
                supply = _clamp(supply * random.uniform(1.1, 1.32), 0.5, 3.2)

            volume = int(300 + 430 * demand / max(supply, 0.35) + random.randint(-60, 90))
            volume = max(50, volume)

            series.append(
                GiftPoint(
                    dt=current_date.isoformat(),
                    price=round(price, 4),
                    demand=round(demand, 4),
                    supply=round(supply, 4),
                    volume=volume,
                )
            )

        gifts.append(
            {
                "gift_id": template["gift_id"],
                "name": template["name"],
                "group": template["group"],
                "series": [point.__dict__ for point in series],
            }
        )

    return {"generated_at": date.today().isoformat(), "gifts": gifts}


def load_dataset() -> Dict:
    if not DATA_FILE.exists():
        dataset = generate_dataset()
        save_dataset(dataset)
        return dataset

    with DATA_FILE.open("r", encoding="utf-8") as f:
        dataset = json.load(f)

    gifts = dataset.get("gifts", [])
    gift_ids = {g.get("gift_id", "") for g in gifts}
    has_required = REQUIRED_GIFT_IDS.issubset(gift_ids)
    if len(gifts) < MIN_GIFTS_COUNT or not has_required:
        dataset = generate_dataset()
        save_dataset(dataset)
    return dataset


def _validate_verified_dataset(dataset: Dict) -> None:
    gifts = dataset.get("gifts")
    if not isinstance(gifts, list) or not gifts:
        raise ValueError("Verified dataset is empty or invalid: 'gifts' must be a non-empty list.")

    for gift in gifts:
        if not gift.get("gift_id") or not gift.get("name"):
            raise ValueError("Each verified gift must contain 'gift_id' and 'name'.")
        series = gift.get("series")
        if not isinstance(series, list) or not series:
            raise ValueError(f"Verified gift '{gift.get('gift_id')}' has empty series.")
        for point in series:
            for key in ("dt", "price", "demand", "supply", "volume"):
                if key not in point:
                    raise ValueError(f"Verified gift '{gift.get('gift_id')}' has invalid point: missing '{key}'.")
            price = float(point.get("price") or 0)
            demand = float(point.get("demand") or 0)
            supply = float(point.get("supply") or 0)
            volume = float(point.get("volume") or 0)
            if price <= 0 or demand <= 0 or supply <= 0 or volume <= 0:
                raise ValueError(f"Verified gift '{gift.get('gift_id')}' has non-positive metrics.")
        if "profile" not in gift:
            raise ValueError(f"Verified gift '{gift.get('gift_id')}' must include 'profile'.")


def load_verified_dataset(path: str | None = None) -> Dict:
    source = Path(path) if path else VERIFIED_DATA_FILE
    if not source.exists():
        raise FileNotFoundError(
            f"Verified dataset file not found: {source}. "
            "Create it or set VERIFIED_DATA_FILE=/absolute/path/to/file.json"
        )

    dataset = _load_json_with_retry(source)
    _validate_verified_dataset(dataset)
    _reconcile_dataset_spot_prices(dataset)
    return dataset


def save_verified_dataset(dataset: Dict, path: str | None = None) -> None:
    target = Path(path) if path else VERIFIED_DATA_FILE
    _atomic_write_json(target, dataset)


def fetch_verified_dataset_from_api(
    api_url: str,
    api_token: str = "",
    timeout_sec: int = 25,
    token_header: str = "Authorization",
    token_prefix: str = "Bearer ",
) -> Dict:
    if not api_url:
        raise ValueError("VERIFIED_API_URL is required for VERIFIED_SOURCE=api")

    req = urllib.request.Request(api_url, method="GET")
    req.add_header("Accept", "application/json")
    if api_token:
        req.add_header(token_header, f"{token_prefix}{api_token}".strip())

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Unable to fetch verified API dataset: {e}") from e

    dataset = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    if not isinstance(dataset, dict):
        raise ValueError("Verified API response must be an object with dataset or {data: dataset}.")

    _validate_verified_dataset(dataset)
    return dataset


def _coerce_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _slugify_soft(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug


def _normalize_telegram_gifts_dataset(payload: Dict) -> Dict:
    if not isinstance(payload, dict):
        raise ValueError("Telegram gifts payload must be a JSON object.")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        raise ValueError("Telegram gifts payload must contain an object dataset.")

    raw_items = data.get("gifts")
    if not isinstance(raw_items, list):
        raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("Telegram gifts dataset must contain 'gifts' or 'items' list.")

    filters = data.get("filters") if isinstance(data.get("filters"), dict) else {}
    out_filters = {
        "collections": list(filters.get("collections") or []) if isinstance(filters.get("collections"), list) else [],
        "models": dict(filters.get("models") or {}) if isinstance(filters.get("models"), dict) else {},
        "backdrops": dict(filters.get("backdrops") or {}) if isinstance(filters.get("backdrops"), dict) else {},
        "symbols": dict(filters.get("symbols") or {}) if isinstance(filters.get("symbols"), dict) else {},
    }
    collections_seen = {str(c.get("slug") or "").strip().lower() for c in out_filters["collections"] if isinstance(c, dict)}
    collections_seen.discard("")

    now_day = datetime.now(timezone.utc).date().isoformat()
    gifts: List[dict] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
        model = str(
            profile.get("model")
            or attrs.get("model")
            or attrs.get("Model")
            or item.get("model")
            or item.get("gift_model")
            or ""
        ).strip()
        background = str(
            profile.get("background")
            or attrs.get("background")
            or attrs.get("Backdrop")
            or attrs.get("backdrop")
            or item.get("background")
            or item.get("backdrop")
            or ""
        ).strip()
        pattern = str(
            profile.get("pattern")
            or attrs.get("pattern")
            or attrs.get("Symbol")
            or attrs.get("symbol")
            or item.get("pattern")
            or item.get("symbol")
            or ""
        ).strip()

        gift_id = str(item.get("gift_id") or item.get("id") or item.get("slug") or "").strip()
        if not gift_id:
            continue
        gift_name = str(item.get("name") or item.get("title") or gift_id).strip()
        collection_name = str(
            item.get("collection_name")
            or item.get("collection")
            or item.get("base_name")
            or item.get("base")
            or ""
        ).strip()
        collection_slug = str(item.get("collection_slug") or item.get("base_id") or "").strip()
        if not collection_slug and collection_name:
            collection_slug = _slugify_soft(collection_name)
        if not collection_slug:
            collection_slug = _slugify_soft(gift_name.split("•")[0].strip())
        if not collection_name:
            collection_name = str(item.get("base_name") or collection_slug).strip()

        floor_ton = _coerce_float(
            profile.get("value_ton_estimate")
            or item.get("floor_ton")
            or item.get("price_ton")
            or item.get("price")
            or 0.0
        )
        if floor_ton <= 0:
            floor_ton = 0.0001

        series = item.get("series")
        if not isinstance(series, list) or not series:
            series = [
                {
                    "dt": now_day,
                    "price": round(floor_ton, 6),
                    "demand": 1.0,
                    "supply": 1.0,
                    "volume": int(_coerce_float(item.get("volume_24h") or 1, 1.0)) or 1,
                }
            ]

        normalized_profile = dict(profile)
        if model:
            normalized_profile["model"] = model
        if background:
            normalized_profile["background"] = background
        if pattern:
            normalized_profile["pattern"] = pattern
        if not normalized_profile.get("value_ton_estimate"):
            normalized_profile["value_ton_estimate"] = round(floor_ton, 6)
        normalized_profile.setdefault("source_note", "telegram gifts api")

        if model:
            out_filters["models"][model] = int(out_filters["models"].get(model, 0)) + 1
        if background:
            out_filters["backdrops"][background] = int(out_filters["backdrops"].get(background, 0)) + 1
        if pattern:
            out_filters["symbols"][pattern] = int(out_filters["symbols"].get(pattern, 0)) + 1
        if collection_slug and collection_slug.lower() not in collections_seen:
            collections_seen.add(collection_slug.lower())
            out_filters["collections"].append(
                {
                    "slug": collection_slug,
                    "name": collection_name or collection_slug,
                    "total_supply": int(_coerce_float(item.get("total_supply") or 0, 0.0)),
                }
            )

        gifts.append(
            {
                "gift_id": gift_id,
                "name": gift_name,
                "group": str(item.get("group") or "Telegram Gifts"),
                "collection_slug": collection_slug,
                "last_lot_id": str(item.get("last_lot_id") or item.get("lot_id") or gift_id).strip(),
                "preview_image_url": str(item.get("preview_image_url") or item.get("preview_url") or "").strip(),
                "latest_status": str(item.get("latest_status") or item.get("status") or "sale").strip().lower(),
                "status_counts": item.get("status_counts") if isinstance(item.get("status_counts"), dict) else {},
                "series": series,
                "profile": normalized_profile,
            }
        )

    generated_at = str(data.get("generated_at") or data.get("updated_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    out_meta = dict(meta)
    out_meta.setdefault("source", "telegram_api")
    out_meta.setdefault("gifts", len(gifts))
    out_meta.setdefault("collections_total", len(out_filters["collections"]))
    out_meta.setdefault("gift_mode", "lot")
    out_meta.setdefault("incomplete", False)

    return {
        "generated_at": generated_at,
        "gifts": gifts,
        "filters": out_filters,
        "meta": out_meta,
    }


def fetch_verified_dataset_from_telegram_api(
    api_url: str,
    api_token: str = "",
    timeout_sec: int = 25,
    token_header: str = "Authorization",
    token_prefix: str = "Bearer ",
) -> Dict:
    if not api_url:
        raise ValueError("TELEGRAM_GIFTS_API_URL is required for VERIFIED_SOURCE=telegram_api")

    attempts: list[tuple[str, str, dict[str, str], str]] = []
    attempts.append(("base", api_url, {}, ""))
    if api_token:
        # 1) Primary configured auth header.
        attempts.append(
            (
                "configured_header",
                api_url,
                {token_header: f"{token_prefix}{api_token}".strip()},
                "",
            )
        )
        # 2) Standard Bearer auth.
        attempts.append(("authorization_bearer", api_url, {"Authorization": f"Bearer {api_token}"}, ""))
        # 3) API key header.
        attempts.append(("x_api_key", api_url, {"X-API-Key": api_token}, ""))
        # 4) Query token fallback.
        parsed = urlparse(api_url)
        q = parse_qsl(parsed.query, keep_blank_values=True)
        q = [(k, v) for (k, v) in q if k != "token"]
        q.append(("token", api_token))
        token_url = urlunparse(parsed._replace(query=urlencode(q)))
        attempts.append(("query_token", token_url, {}, ""))

    payload = None
    last_error = ""
    for name, url, headers, _ in attempts:
        req = urllib.request.Request(url, method="GET")
        req.add_header("Accept", "application/json")
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            last_error = f"{name}:HTTP_{e.code}"
            continue
        except urllib.error.URLError as e:
            last_error = f"{name}:URLError:{e}"
            continue
        except Exception as e:
            last_error = f"{name}:{type(e).__name__}:{str(e)[:120]}"
            continue

    if payload is None:
        raise RuntimeError(f"Unable to fetch telegram gifts dataset: {last_error or 'unknown_error'}")

    dataset = _normalize_telegram_gifts_dataset(payload)
    _reconcile_dataset_spot_prices(dataset)
    _validate_verified_dataset(dataset)
    return dataset


def _clean_fragment_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()


def _fragment_to_iso_day(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return datetime.utcnow().date().isoformat()


def _fragment_build_series(events: List[dict]) -> List[dict]:
    by_day: dict[str, list[float]] = defaultdict(list)
    for event in events:
        day = _fragment_to_iso_day(event["datetime"])
        by_day[day].append(float(event["price_ton"]))

    days = sorted(by_day.keys())
    if not days:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        return [{"dt": now, "price": 0.0, "demand": 1.0, "supply": 1.0, "volume": 1}]

    daily = [(d, sum(vals) / len(vals), len(vals)) for d, vals in ((d, by_day[d]) for d in days)]
    max_volume = max(v for _, _, v in daily) or 1
    series: List[dict] = []
    for idx, (day, avg_price, volume) in enumerate(daily):
        price = max(0.0001, round(avg_price, 6))
        demand = round(0.9 + 1.1 * (volume / max_volume), 4)
        prev_price = daily[idx - 1][1] if idx > 0 else avg_price
        supply = 1.0
        if prev_price > 0:
            # Lower relative price usually means higher available supply.
            supply = 0.9 + 1.1 * max(0.2, min(1.8, prev_price / max(avg_price, 1e-9)))
        series.append(
            {
                "dt": day,
                "price": price,
                "demand": max(0.3, round(demand, 4)),
                "supply": max(0.3, round(supply, 4)),
                "volume": int(volume),
            }
        )
    return series


def _apply_spot_price_to_series(series: List[dict], spot_ton: float | None, asof_day: str) -> List[dict]:
    if not isinstance(series, list) or not series:
        return series
    if spot_ton is None:
        return series
    try:
        spot = float(spot_ton)
    except Exception:
        return series
    if spot <= 0:
        return series

    out = list(series)
    last = dict(out[-1])
    last_dt = str(last.get("dt", "")).strip()
    today = (asof_day or "").strip() or datetime.utcnow().date().isoformat()
    # Keep historical points intact; append a latest market snapshot (floor/spot).
    if last_dt != today:
        out.append(
            {
                "dt": today,
                "price": round(spot, 6),
                "demand": float(last.get("demand", 1.0) or 1.0),
                "supply": float(last.get("supply", 1.0) or 1.0),
                "volume": int(last.get("volume", 1) or 1),
            }
        )
    else:
        out[-1]["price"] = round(spot, 6)
    return out


def _reconcile_dataset_spot_prices(dataset: Dict) -> None:
    if not isinstance(dataset, dict):
        return
    asof_day = datetime.utcnow().date().isoformat()
    gifts = dataset.get("gifts")
    if not isinstance(gifts, list):
        return
    for gift in gifts:
        profile = gift.get("profile") if isinstance(gift, dict) else None
        series = gift.get("series") if isinstance(gift, dict) else None
        spot = None
        if isinstance(profile, dict):
            spot = profile.get("value_ton_estimate")
        if isinstance(series, list) and series:
            gift["series"] = _apply_spot_price_to_series(series, spot, asof_day)


def _fragment_parse_collections(html: str) -> List[dict]:
    collections: List[dict] = []
    pattern = re.compile(
        r'<a href="/gifts/(?P<slug>[a-z0-9]+)"[^>]*data-value="(?P<value>[^"]+)"[^>]*>.*?'
        r'<div class="tm-main-filters-name">(?P<name>[^<]+)</div>\s*'
        r'<div class="tm-main-filters-count">(?P<count>[^<]+)</div>',
        re.S | re.I,
    )
    seen: set[str] = set()
    for m in pattern.finditer(html):
        slug = _clean_fragment_text(m.group("slug")).lower()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        count_raw = _clean_fragment_text(m.group("count"))
        count_digits = re.sub(r"[^\d]", "", count_raw)
        total_supply = int(count_digits) if count_digits else 0
        collections.append(
            {
                "slug": slug,
                "name": _clean_fragment_text(m.group("name")),
                "total_supply": total_supply,
            }
        )
    return collections


def _fragment_parse_item_cards(html: str, default_status: str | None = None) -> List[dict]:
    cards: List[dict] = []
    status_map = {
        "sold": "sold",
        "for sale": "sale",
        "sale": "sale",
        "on auction": "auction",
        "auction": "auction",
        "available": "sale",
    }
    pattern = re.compile(
        r'<a href="/gift/(?P<gift_id>[a-z0-9\-]+)(?:\?[^"]*)?" class="tm-grid-item">.*?'
        r'<time datetime="(?P<dt>[^"]+)"[^>]*>.*?</time>.*?'
        r'icon-ton">(?P<price>[0-9][0-9,]*(?:\.[0-9]+)?)</div>.*?'
        r'(?:tm-grid-item-status[^"]*">(?P<status>[^<]+)</div>)?',
        re.S | re.I,
    )
    for m in pattern.finditer(html):
        try:
            raw_status = _clean_fragment_text(m.group("status") or "").lower()
            status = status_map.get(raw_status, raw_status)
            if status not in {"sold", "sale", "auction"} and default_status:
                status = default_status
            cards.append(
                {
                    "gift_id": _clean_fragment_text(m.group("gift_id")),
                    "datetime": _clean_fragment_text(m.group("dt")),
                    "price_ton": float(_clean_fragment_text(m.group("price")).replace(",", "")),
                    "status": status,
                }
            )
        except ValueError:
            continue
    return cards


def _fragment_extract_next_offset(html: str) -> str:
    m = re.search(r'data-next-offset="([^"]+)"', html, re.I)
    return _clean_fragment_text(m.group(1)) if m else ""


def _fragment_extract_api_hash(html: str) -> str:
    m = re.search(r'api\?hash=([a-f0-9]+)', html)
    if not m:
        raise ValueError("Unable to find Fragment API hash on page")
    return m.group(1)


def _fragment_parse_detail_profile(html: str) -> dict:
    def _extract_attr(labels: List[str]) -> tuple[str, str | None]:
        for label in labels:
            rx = re.compile(
                rf'<div class="table-cell">{re.escape(label)}</div>.*?<div class="table-cell-value tm-value">.*?'
                r'<a [^>]*class="table-cell-value-link">([^<]+)</a>.*?'
                r'<span class="tm-rarity">\s*([^<]+)\s*</span>',
                re.S | re.I,
            )
            m = rx.search(html)
            if not m:
                continue
            return (_clean_fragment_text(m.group(1)), _clean_fragment_text(m.group(2)))
        return ("N/A", None)

    model, model_share = _extract_attr(["Model"])
    pattern, pattern_share = _extract_attr(["Symbol", "Pattern"])
    background, background_share = _extract_attr(["Backdrop", "Background"])

    issued = 0
    total_supply = 0
    m_issued = re.search(r'<div class="table-cell">Issued</div>.*?<div class="table-cell-value tm-value">\s*([^<]+)\s*</div>', html, re.S | re.I)
    if m_issued:
        raw = _clean_fragment_text(m_issued.group(1))
        nums = re.findall(r"\d+", raw.replace(",", ""))
        if len(nums) >= 2:
            issued = int(nums[0])
            total_supply = int(nums[1])

    m_price = re.search(r'<div class="table-cell-value tm-value icon-before icon-ton">([0-9.]+)</div>', html, re.S | re.I)
    value_ton = float(m_price.group(1)) if m_price else None

    return {
        "model": model,
        "model_share": model_share,
        "pattern": pattern,
        "pattern_share": pattern_share,
        "background": background,
        "background_share": background_share,
        "issued": issued,
        "total_supply": total_supply,
        "value_ton_estimate": value_ton,
        "value_rub_estimate": None,
        "value_score": 50,
        "source_note": "fragment.com verified",
    }


def _fragment_parse_og_image(html: str) -> str:
    meta_re = re.compile(r"<meta\s+([^>]+)>", re.I)
    attr_re = re.compile(r'([a-zA-Z_:.-]+)\s*=\s*"([^"]*)"')
    for m in meta_re.finditer(html):
        attrs_raw = m.group(1)
        attrs = {k.lower(): _clean_fragment_text(v) for k, v in attr_re.findall(attrs_raw)}
        marker = attrs.get("property") or attrs.get("name") or ""
        if marker.lower() in {"og:image", "twitter:image"} and attrs.get("content"):
            return attrs["content"]
    return ""


def _fragment_parse_detail_status(html: str) -> str:
    status_map = {
        "sold": "sold",
        "for sale": "sale",
        "sale": "sale",
        "on auction": "auction",
        "auction": "auction",
        "available": "sale",
    }
    patterns = [
        re.compile(r'tm-gift-status[^>]*>\s*([^<]+)\s*<', re.I),
        re.compile(r'tm-grid-item-status[^>]*>\s*([^<]+)\s*<', re.I),
        re.compile(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', re.I),
    ]
    for pat in patterns:
        m = pat.search(html)
        if not m:
            continue
        raw = _clean_fragment_text(m.group(1)).lower()
        for key, value in status_map.items():
            if key in raw:
                return value
    return ""


def _load_fragment_lot_traits_cache() -> Dict[str, dict]:
    if not FRAGMENT_LOT_TRAITS_CACHE_FILE.exists():
        return {}
    try:
        payload = _load_json_with_retry(FRAGMENT_LOT_TRAITS_CACHE_FILE)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {}
    return {}


def _save_fragment_lot_traits_cache(cache: Dict[str, dict]) -> None:
    try:
        _atomic_write_json(FRAGMENT_LOT_TRAITS_CACHE_FILE, cache)
    except Exception:
        return


def _seed_lot_traits_cache_from_verified_file(cache: Dict[str, dict], file_path: str | None = None) -> tuple[Dict[str, dict], int]:
    # Warm lot-traits cache from last verified snapshot to keep lot-mode traits stable
    # across partial/live cycles where Fragment may throttle detail pages.
    if not isinstance(cache, dict):
        cache = {}
    path = Path(file_path or os.getenv("VERIFIED_DATA_FILE", "").strip() or VERIFIED_DATA_FILE)
    if not path.exists():
        return cache, 0
    try:
        payload = _load_json_with_retry(path)
    except Exception:
        return cache, 0
    if not isinstance(payload, dict):
        return cache, 0
    gifts = payload.get("gifts")
    if not isinstance(gifts, list) or not gifts:
        return cache, 0

    seeded = 0
    for gift in gifts:
        if not isinstance(gift, dict):
            continue
        lot_id = str(gift.get("last_lot_id") or "").strip()
        if not lot_id or lot_id in cache:
            continue
        profile = gift.get("profile")
        if not isinstance(profile, dict):
            continue
        model = str(profile.get("model") or "").strip()
        background = str(profile.get("background") or "").strip()
        pattern = str(profile.get("pattern") or "").strip()
        if not model or not background or not pattern:
            continue
        cache[lot_id] = {
            "profile": {
                "model": model,
                "model_share": profile.get("model_share"),
                "pattern": pattern,
                "pattern_share": profile.get("pattern_share"),
                "background": background,
                "background_share": profile.get("background_share"),
                "issued": profile.get("issued"),
                "total_supply": profile.get("total_supply"),
                "value_ton_estimate": profile.get("value_ton_estimate"),
                "value_rub_estimate": profile.get("value_rub_estimate"),
                "value_score": profile.get("value_score"),
                "source_note": profile.get("source_note") or "verified cache seed",
            },
            "preview_image_url": str(gift.get("preview_image_url") or "").strip(),
            "detail_status": str(gift.get("latest_status") or "").strip().lower(),
        }
        seeded += 1
    return cache, seeded


def _fragment_parse_attribute_options(html: str, label: str) -> List[dict]:
    # Extract filter options from Fragment sidebar blocks for Model/Backdrop/Symbol.
    box_re = re.compile(
        rf'<div class="tm-main-filters-name">{re.escape(label)}</div>.*?<div class="tm-main-filters-content[^"]*">(.*?)</div>\s*</div>',
        re.S | re.I,
    )
    box_match = box_re.search(html)
    if not box_match:
        return []

    content = box_match.group(1)
    item_re = re.compile(
        r'js-attribute-item"[^>]*data-value="([^"]+)".*?'
        r'<div class="tm-main-filters-name">([^<]+)</div>\s*'
        r'<div class="tm-main-filters-count">([^<]+)</div>',
        re.S | re.I,
    )
    out: List[dict] = []
    seen: set[str] = set()
    for m in item_re.finditer(content):
        value = _clean_fragment_text(m.group(1))
        if not value or value.lower() == "select all":
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        count_raw = _clean_fragment_text(m.group(3))
        count_digits = re.sub(r"[^\d]", "", count_raw)
        out.append(
            {
                "value": value,
                "count": int(count_digits) if count_digits else 0,
            }
        )
    out.sort(key=lambda x: x["count"], reverse=True)
    return out


def fetch_verified_dataset_from_fragment(
    root_url: str = "https://fragment.com/gifts",
    timeout_sec: int = 25,
    max_collections: int = 0,
    max_pages_per_collection: int = 500,
    collection_start: int = 0,
) -> Dict:
    started_at = time.monotonic()
    fetch_budget_sec = max(30, int(os.getenv("FRAGMENT_FETCH_BUDGET_SEC", "180")))
    hard_budget_sec = fetch_budget_sec
    max_detail_lots_per_collection = max(0, int(os.getenv("FRAGMENT_MAX_DETAIL_LOTS_PER_COLLECTION", "120")))
    cj = cookiejar.CookieJar()
    no_verify_ssl = os.getenv("FRAGMENT_SSL_NO_VERIFY", "").strip().lower() in {"1", "true", "yes", "on"}
    ssl_context = ssl._create_unverified_context() if no_verify_ssl else ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=ssl_context),
    )
    min_request_interval_sec = max(0.0, float(os.getenv("FRAGMENT_MIN_REQUEST_INTERVAL_SEC", "0.18")))
    request_jitter_sec = max(0.0, float(os.getenv("FRAGMENT_REQUEST_JITTER_SEC", "0.06")))
    request_retries = max(1, int(os.getenv("FRAGMENT_REQUEST_RETRIES", "3")))
    request_backoff_sec = max(0.1, float(os.getenv("FRAGMENT_REQUEST_BACKOFF_SEC", "0.8")))
    req_lock = threading.Lock()
    last_req_ts = 0.0

    def _out_of_budget() -> bool:
        return (time.monotonic() - started_at) > hard_budget_sec

    def _throttle_request() -> None:
        nonlocal last_req_ts
        with req_lock:
            now = time.monotonic()
            wait_sec = max(0.0, (last_req_ts + min_request_interval_sec) - now)
            if wait_sec > 0:
                time.sleep(wait_sec)
            if request_jitter_sec > 0:
                time.sleep(random.uniform(0.0, request_jitter_sec))
            last_req_ts = time.monotonic()

    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, urllib.error.HTTPError):
            return exc.code in {403, 408, 409, 425, 429, 500, 502, 503, 504}
        if isinstance(exc, urllib.error.URLError):
            return True
        return False

    def _get_text(url: str) -> str:
        last_err: Exception | None = None
        for attempt in range(1, request_retries + 1):
            try:
                req = urllib.request.Request(url, method="GET")
                req.add_header("User-Agent", "Mozilla/5.0 (compatible; GiftMarketZone/1.0)")
                req.add_header("Accept", "text/html,application/xhtml+xml")
                _throttle_request()
                with opener.open(req, timeout=timeout_sec) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception as e:
                last_err = e
                if attempt >= request_retries or not _is_retryable(e):
                    break
                sleep_sec = min(30.0, request_backoff_sec * (2 ** (attempt - 1)) + random.uniform(0.0, 0.35))
                time.sleep(sleep_sec)
        raise last_err if last_err else RuntimeError(f"GET failed: {url}")

    def _post_json(api_hash: str, referer: str, params: dict) -> dict:
        last_err: Exception | None = None
        for attempt in range(1, request_retries + 1):
            try:
                api_url = f"https://fragment.com/api?hash={api_hash}"
                body = urlencode(params).encode("utf-8")
                req = urllib.request.Request(api_url, data=body, method="POST")
                req.add_header("User-Agent", "Mozilla/5.0 (compatible; GiftMarketZone/1.0)")
                req.add_header("Accept", "application/json")
                req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
                req.add_header("X-Requested-With", "XMLHttpRequest")
                req.add_header("Origin", "https://fragment.com")
                req.add_header("Referer", referer)
                _throttle_request()
                with opener.open(req, timeout=timeout_sec) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                last_err = e
                if attempt >= request_retries or not _is_retryable(e):
                    break
                sleep_sec = min(30.0, request_backoff_sec * (2 ** (attempt - 1)) + random.uniform(0.0, 0.35))
                time.sleep(sleep_sec)
        raise last_err if last_err else RuntimeError(f"POST failed: hash={api_hash}")

    root_html = _get_text(root_url)
    collections = _fragment_parse_collections(root_html)
    active_only = os.getenv("FRAGMENT_ACTIVE_ONLY", "true").strip().lower() in {"1", "true", "yes", "on"}
    if active_only:
        sale_html = _get_text(f"{root_url}?sort=price&filter=sale")
        auction_html = _get_text(f"{root_url}?sort=price&filter=auction")
        sold_html = _get_text(f"{root_url}?sort=price&filter=sold")
        sale_cols = _fragment_parse_collections(sale_html)
        auction_cols = _fragment_parse_collections(auction_html)
        sold_cols = _fragment_parse_collections(sold_html)
        merged = {c["slug"]: c for c in sale_cols + auction_cols + sold_cols}
        # Keep stable ordering by name
        collections = sorted(merged.values(), key=lambda x: x.get("name", ""))
    total_collections = len(collections)
    if collection_start > 0:
        collections = collections[collection_start:]
    if max_collections and max_collections > 0:
        collections = collections[:max_collections]

    gifts: List[dict] = []
    filter_index = {
        "collections": [],
        "models": {},
        "backdrops": {},
        "symbols": {},
    }
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    gift_mode = os.getenv("FRAGMENT_GIFT_MODE", "lot").strip().lower()
    include_sold = os.getenv("FRAGMENT_INCLUDE_SOLD", "true").strip().lower() in {"1", "true", "yes", "on"}
    enrich_lot_traits = os.getenv("FRAGMENT_ENRICH_LOT_TRAITS", "true").strip().lower() in {"1", "true", "yes", "on"}
    detail_workers = max(1, int(os.getenv("FRAGMENT_LOT_DETAIL_WORKERS", "10")))
    total_for_sale = 0
    total_sold = 0
    total_auction = 0
    # Reuse cached per-lot traits even in fast mode to avoid collapsing all lots
    # into one collection-level profile when detail enrichment is disabled.
    lot_traits_cache = _load_fragment_lot_traits_cache()
    lot_traits_cache_seeded = 0
    lot_traits_cache, lot_traits_cache_seeded = _seed_lot_traits_cache_from_verified_file(lot_traits_cache)
    lot_traits_cache_dirty = False
    if lot_traits_cache_seeded:
        lot_traits_cache_dirty = True
    lot_traits_cache_hits_total = 0
    lot_traits_fetched_total = 0
    lot_traits_active_lots_total = 0
    lot_traits_covered_active_total = 0

    requested_collections = len(collections)
    processed_collections = 0
    collections_with_events = 0
    failed_collections: list[str] = []
    budget_exhausted = False

    for collection in collections:
        if _out_of_budget():
            budget_exhausted = True
            break
        slug = collection["slug"]
        try:
            def _fetch_events(filter_value: str) -> list[dict]:
                if _out_of_budget():
                    return []
                page_url = f"https://fragment.com/gifts/{slug}?sort=price&filter={filter_value}"
                collection_html = _get_text(page_url)
                api_hash = _fragment_extract_api_hash(collection_html)
                params = {
                    "method": "searchAuctions",
                    "type": "gifts",
                    "collection": slug,
                    "sort": "price",
                    "filter": filter_value,
                    "view": "",
                    "query": "",
                    "attr[Model]": "",
                    "attr[Backdrop]": "",
                    "attr[Symbol]": "",
                }
                first = _post_json(api_hash, page_url, params)
                first_html = first.get("html") or first.get("body") or ""
                first_foot = first.get("foot") or ""
                events = _fragment_parse_item_cards(first_html, default_status=filter_value)
                next_offset = _fragment_extract_next_offset(first_foot or first_html)

                page_no = 1
                while next_offset and page_no < max_pages_per_collection:
                    if _out_of_budget():
                        break
                    page_no += 1
                    params["offset_id"] = next_offset
                    part = _post_json(api_hash, page_url, params)
                    body_html = part.get("body") or part.get("html") or ""
                    foot_html = part.get("foot") or ""
                    if body_html:
                        events.extend(_fragment_parse_item_cards(body_html, default_status=filter_value))
                    next_offset = _fragment_extract_next_offset(foot_html or body_html)
                    if not body_html:
                        break
                return events

            page_url = f"https://fragment.com/gifts/{slug}?sort=price"
            collection_html = _get_text(page_url)
            api_hash = _fragment_extract_api_hash(collection_html)
            model_options = _fragment_parse_attribute_options(collection_html, "Model")
            backdrop_options = _fragment_parse_attribute_options(collection_html, "Backdrop")
            symbol_options = _fragment_parse_attribute_options(collection_html, "Symbol")

            filter_index["collections"].append(
                {
                    "slug": slug,
                    "name": collection["name"],
                    "total_supply": collection.get("total_supply", 0),
                }
            )
            for item in model_options:
                filter_index["models"][item["value"]] = filter_index["models"].get(item["value"], 0) + item["count"]
            for item in backdrop_options:
                filter_index["backdrops"][item["value"]] = filter_index["backdrops"].get(item["value"], 0) + item["count"]
            for item in symbol_options:
                filter_index["symbols"][item["value"]] = filter_index["symbols"].get(item["value"], 0) + item["count"]

            sale_events = _fetch_events("sale")
            auction_events = _fetch_events("auction")
            sold_events = _fetch_events("sold") if (include_sold and not _out_of_budget()) else []
            events = sale_events + auction_events + sold_events

            if not events:
                continue
            collections_with_events += 1

            events.sort(key=lambda x: x["datetime"])
            last_event = events[-1]
            detail_html = _get_text(f"https://fragment.com/gift/{last_event['gift_id']}?sort=price")
            profile = _fragment_parse_detail_profile(detail_html)
            preview_image_url = _fragment_parse_og_image(detail_html)
            if not profile.get("total_supply"):
                profile["total_supply"] = collection.get("total_supply", 0)
            if not profile.get("issued"):
                profile["issued"] = min(collection.get("total_supply", 0), collection.get("total_supply", 0))
            profile["source_note"] = "fragment.com verified"

            status_counts: dict[str, int] = {}
            for ev in events:
                key = str(ev.get("status", "")).strip().lower()
                if not key:
                    continue
                status_counts[key] = status_counts.get(key, 0) + 1

            gift_name = collection["name"] if collection["name"] else slug
            if gift_mode == "lot":
                lot_latest: dict[str, dict] = {}
                lot_status_counts: dict[str, dict[str, int]] = {}
                for ev in events:
                    lot_id = str(ev.get("gift_id") or "").strip()
                    if not lot_id:
                        continue
                    prev = lot_latest.get(lot_id)
                    if not prev or str(ev.get("datetime", "")) > str(prev.get("datetime", "")):
                        lot_latest[lot_id] = ev
                    st = str(ev.get("status") or "").strip().lower()
                    if st:
                        per_lot = lot_status_counts.setdefault(lot_id, {})
                        per_lot[st] = per_lot.get(st, 0) + 1

                lot_details: dict[str, dict] = {}
                if lot_latest:
                    for lot_id in lot_latest.keys():
                        cached = lot_traits_cache.get(lot_id)
                        if isinstance(cached, dict):
                            lot_details[lot_id] = cached
                            lot_traits_cache_hits_total += 1

                lot_items_sorted = sorted(
                    lot_latest.items(),
                    key=lambda kv: str((kv[1] or {}).get("datetime") or ""),
                    reverse=True,
                )
                active_lot_ids = [
                    lot_id
                    for lot_id, ev in lot_items_sorted
                    if str((ev or {}).get("status") or "").strip().lower() != "sold"
                ]
                lot_traits_active_lots_total += len(active_lot_ids)

                if enrich_lot_traits and lot_latest:
                    # Prioritize currently active lots for detail pages. Sold lots are skipped
                    # below and should not consume the lot-detail budget.
                    missing_lot_ids = [lot_id for lot_id in active_lot_ids if lot_id not in lot_details]
                    if max_detail_lots_per_collection > 0:
                        missing_lot_ids = missing_lot_ids[:max_detail_lots_per_collection]

                    def _fetch_lot_detail(lot_id: str) -> dict:
                        detail = _get_text(f"https://fragment.com/gift/{lot_id}?sort=price")
                        detail_profile = _fragment_parse_detail_profile(detail)
                        detail_preview = _fragment_parse_og_image(detail)
                        detail_status = _fragment_parse_detail_status(detail)
                        return {
                            "profile": detail_profile,
                            "preview_image_url": detail_preview,
                            "detail_status": detail_status,
                        }

                    if missing_lot_ids and not _out_of_budget():
                        with ThreadPoolExecutor(max_workers=detail_workers) as pool:
                            fut_to_lot = {pool.submit(_fetch_lot_detail, lot_id): lot_id for lot_id in missing_lot_ids}
                            for fut in as_completed(fut_to_lot):
                                if _out_of_budget():
                                    break
                                lot_id = fut_to_lot[fut]
                                try:
                                    payload = fut.result()
                                except Exception:
                                    payload = {}
                                lot_details[lot_id] = payload
                                if payload:
                                    lot_traits_fetched_total += 1
                                    lot_traits_cache[lot_id] = payload
                                    lot_traits_cache_dirty = True

                lot_traits_covered_active_total += sum(1 for lot_id in active_lot_ids if lot_id in lot_details)

                for ev in lot_latest.values():
                    st = str(ev.get("status") or "").strip().lower()
                    if st == "sold":
                        total_sold += 1
                    elif st == "auction":
                        total_auction += 1
                        total_for_sale += 1
                    else:
                        total_for_sale += 1

                for lot_id, ev in lot_latest.items():
                    latest_status = str(ev.get("status") or "").strip().lower()
                    detail_payload = lot_details.get(lot_id)
                    if isinstance(detail_payload, dict):
                        detail_status = str(detail_payload.get("detail_status") or "").strip().lower()
                        if detail_status in {"sold", "sale", "auction"}:
                            latest_status = detail_status
                    if latest_status == "sold":
                        continue
                    lot_price = float(ev.get("price_ton") or 0.0)
                    if lot_price <= 0:
                        continue
                    lot_profile = dict(profile)
                    if isinstance(detail_payload, dict):
                        profile_override = detail_payload.get("profile")
                        if isinstance(profile_override, dict):
                            for key in ("model", "model_share", "pattern", "pattern_share", "background", "background_share", "issued", "total_supply"):
                                if profile_override.get(key):
                                    lot_profile[key] = profile_override.get(key)
                    lot_profile["value_ton_estimate"] = lot_price
                    lot_profile["source_note"] = "fragment.com verified (lot snapshot)"
                    lot_day = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    lot_series = [
                        {
                            "dt": lot_day,
                            "price": round(lot_price, 6),
                            "demand": 1.0,
                            "supply": 1.0,
                            "volume": 1,
                        }
                    ]
                    lot_suffix = lot_id.split("-")[-1]
                    gifts.append(
                        {
                            # Keep collection slug in ID to preserve correct base split on backend.
                            "gift_id": f"fragment_{slug}_{lot_id.replace('-', '_')}",
                            "name": f"{gift_name} #{lot_suffix}",
                            "group": "Fragment Gifts",
                            "collection_slug": slug,
                            "fragment_market_url": f"https://fragment.com/gift/{lot_id}?sort=price",
                            "last_lot_id": lot_id,
                            "preview_image_url": (
                                str((detail_payload or {}).get("preview_image_url") or "").strip() if isinstance(detail_payload, dict) else ""
                            )
                            or preview_image_url,
                            "available_models": [x["value"] for x in model_options],
                            "available_backdrops": [x["value"] for x in backdrop_options],
                            "available_symbols": [x["value"] for x in symbol_options],
                            "status_counts": lot_status_counts.get(lot_id, {}),
                            "latest_status": latest_status,
                            "series": lot_series,
                            "profile": lot_profile,
                        }
                    )
            else:
                gift_id = f"fragment_{slug}"
                series = _fragment_build_series(events)
                series = _apply_spot_price_to_series(series, profile.get("value_ton_estimate"), datetime.utcnow().date().isoformat())
                latest_status = str(last_event.get("status") or "").strip().lower()
                if latest_status == "sold":
                    total_sold += 1
                elif latest_status == "auction":
                    total_auction += 1
                    total_for_sale += 1
                else:
                    total_for_sale += 1
                gifts.append(
                    {
                        "gift_id": gift_id,
                        "name": gift_name,
                        "group": "Fragment Gifts",
                        "collection_slug": slug,
                        "fragment_market_url": f"https://fragment.com/gifts/{slug}",
                        "last_lot_id": last_event["gift_id"],
                        "latest_status": latest_status,
                        "preview_image_url": preview_image_url,
                        "available_models": [x["value"] for x in model_options],
                        "available_backdrops": [x["value"] for x in backdrop_options],
                        "available_symbols": [x["value"] for x in symbol_options],
                        "status_counts": status_counts,
                        "series": series,
                        "profile": profile,
                    }
                )
        except Exception:
            # Skip broken collection and keep progressing through the catalog.
            failed_collections.append(slug)
            continue
        finally:
            processed_collections += 1

    if not filter_index["models"] or not filter_index["backdrops"] or not filter_index["symbols"]:
        for gift in gifts:
            profile = gift.get("profile") or {}
            model = str(profile.get("model") or "").strip()
            backdrop = str(profile.get("background") or "").strip()
            symbol = str(profile.get("pattern") or "").strip()
            if model:
                filter_index["models"][model] = int(filter_index["models"].get(model, 0)) + 1
            if backdrop:
                filter_index["backdrops"][backdrop] = int(filter_index["backdrops"].get(backdrop, 0)) + 1
            if symbol:
                filter_index["symbols"][symbol] = int(filter_index["symbols"].get(symbol, 0)) + 1

    max_failed_collections = max(0, int(os.getenv("FRAGMENT_MAX_FAILED_COLLECTIONS", "2")))
    min_success_ratio = min(1.0, max(0.0, float(os.getenv("FRAGMENT_MIN_COLLECTION_SUCCESS_RATIO", "0.9"))))
    successful_collections = max(0, processed_collections - len(failed_collections))
    success_ratio = (successful_collections / requested_collections) if requested_collections > 0 else 1.0
    incomplete = bool(
        budget_exhausted
        or processed_collections < requested_collections
        or len(failed_collections) > max_failed_collections
        or success_ratio < min_success_ratio
    )

    meta = {
        "generated_at": generated_at,
        "collections_total": total_collections,
        "collections_used": processed_collections,
        "collections_requested": requested_collections,
        "collections_successful": successful_collections,
        "collections_success_ratio": round(success_ratio, 4),
        "collections_with_events": collections_with_events,
        "collections_failed": len(failed_collections),
        "max_failed_collections": max_failed_collections,
        "min_success_ratio": min_success_ratio,
        "collection_start": collection_start,
        "max_collections": max_collections,
        "max_pages_per_collection": max_pages_per_collection,
        "gifts": len(gifts),
        "gift_mode": gift_mode,
        "total_for_sale": total_for_sale,
        "total_sold": total_sold,
        "total_auction": total_auction,
        "lot_traits_cache_seeded": lot_traits_cache_seeded,
        "lot_traits_cache_hits": lot_traits_cache_hits_total,
        "lot_traits_fetched": lot_traits_fetched_total,
        "lot_traits_active_lots": lot_traits_active_lots_total,
        "lot_traits_covered_active": lot_traits_covered_active_total,
        "lot_traits_coverage": (
            round(lot_traits_covered_active_total / lot_traits_active_lots_total, 4)
            if lot_traits_active_lots_total > 0
            else 0.0
        ),
        "incomplete": incomplete,
    }
    allow_incomplete = os.getenv("FRAGMENT_ALLOW_INCOMPLETE", "false").strip().lower() in {"1", "true", "yes", "on"}
    if meta["incomplete"] and not allow_incomplete:
        sample_failed = ",".join(failed_collections[:6]) if failed_collections else "-"
        raise RuntimeError(
            "fragment fetch incomplete: "
            f"processed={processed_collections}/{requested_collections} "
            f"successful={successful_collections} "
            f"success_ratio={round(success_ratio, 4)} "
            f"with_events={collections_with_events} "
            f"failed={len(failed_collections)} "
            f"max_failed={max_failed_collections} "
            f"min_success_ratio={min_success_ratio} "
            f"budget_exhausted={budget_exhausted} "
            f"failed_sample={sample_failed}"
        )
    meta["allow_incomplete"] = bool(allow_incomplete)
    dataset = {"generated_at": generated_at, "gifts": gifts, "filters": filter_index, "meta": meta}
    if enrich_lot_traits and lot_traits_cache_dirty:
        _save_fragment_lot_traits_cache(lot_traits_cache)
    _merge_fragment_analytics_store(dataset)
    _save_fragment_snapshot_meta(meta)
    _reconcile_dataset_spot_prices(dataset)
    _validate_verified_dataset(dataset)
    return dataset


def _load_fragment_analytics_store() -> Dict:
    if not FRAGMENT_ANALYTICS_STORE_FILE.exists():
        return {"gifts": []}
    try:
        payload = _load_json_with_retry(FRAGMENT_ANALYTICS_STORE_FILE)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {"gifts": []}
    return {"gifts": []}


def _save_fragment_snapshot_meta(meta: Dict) -> None:
    try:
        _atomic_write_json(FRAGMENT_SNAPSHOT_META_FILE, meta)
    except Exception:
        return


def load_fragment_snapshot_meta() -> Dict:
    if not FRAGMENT_SNAPSHOT_META_FILE.exists():
        return {}
    try:
        payload = _load_json_with_retry(FRAGMENT_SNAPSHOT_META_FILE)
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {}
    return {}


def _save_fragment_analytics_store(store: Dict) -> None:
    _atomic_write_json(FRAGMENT_ANALYTICS_STORE_FILE, store)


def _merge_fragment_analytics_store(dataset: Dict) -> None:
    store = _load_fragment_analytics_store()
    old_map = {g.get("gift_id"): g for g in store.get("gifts", []) if g.get("gift_id")}
    merged_gifts = []
    max_points = int(os.getenv("FRAGMENT_SERIES_MAX_POINTS", "8640"))

    for gift in dataset.get("gifts", []):
        gift_id = gift.get("gift_id")
        if not gift_id:
            continue
        old_series = old_map.get(gift_id, {}).get("series", [])
        new_series = gift.get("series", [])
        merged_by_dt: dict[str, dict] = {}
        for p in old_series:
            dt = p.get("dt")
            if dt:
                merged_by_dt[dt] = p
        for p in new_series:
            dt = p.get("dt")
            if dt:
                merged_by_dt[dt] = p
        merged = [merged_by_dt[k] for k in sorted(merged_by_dt.keys())]
        if len(merged) > max_points:
            merged = merged[-max_points:]
        gift["series"] = merged if merged else new_series
        merged_gifts.append({"gift_id": gift_id, "series": gift["series"]})

    store_payload = {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "gifts": merged_gifts,
    }
    _save_fragment_analytics_store(store_payload)


def _dataset_stats(dataset: Dict) -> Dict[str, int]:
    if not isinstance(dataset, dict):
        return {"gifts": 0, "collections": 0, "models": 0, "backdrops": 0, "symbols": 0}
    filters = dataset.get("filters") if isinstance(dataset.get("filters"), dict) else {}
    return {
        "gifts": len(dataset.get("gifts") or []),
        "collections": len(filters.get("collections") or []),
        "models": len(filters.get("models") or {}),
        "backdrops": len(filters.get("backdrops") or {}),
        "symbols": len(filters.get("symbols") or {}),
    }


def _load_verified_fallback_snapshot(file_path: str | None) -> Dict | None:
    try:
        if file_path:
            p = Path(file_path)
            if p.exists():
                return load_verified_dataset(file_path)
        if VERIFIED_DATA_FILE.exists():
            return load_verified_dataset(None)
    except Exception:
        return None
    return None


def _ensure_live_dataset_quality(dataset: Dict, fallback: Dict | None, source: str) -> None:
    stats = _dataset_stats(dataset)
    gifts = int(stats.get("gifts") or 0)
    collections = int(stats.get("collections") or 0)
    models = int(stats.get("models") or 0)
    if gifts <= 0:
        raise ValueError(f"{source} returned empty gifts")

    min_abs_gifts = max(1, int(os.getenv("VERIFIED_MIN_GIFTS_ABS", "200")))
    if gifts < min_abs_gifts:
        raise ValueError(f"{source} gifts below abs minimum: {gifts} < {min_abs_gifts}")

    if not isinstance(fallback, dict):
        return

    prev = _dataset_stats(fallback)
    prev_gifts = int(prev.get("gifts") or 0)
    prev_collections = int(prev.get("collections") or 0)
    prev_models = int(prev.get("models") or 0)

    min_gifts_ratio = max(0.0, min(1.0, float(os.getenv("VERIFIED_MIN_GIFTS_RATIO", "0.6"))))
    min_collections_ratio = max(0.0, min(1.0, float(os.getenv("VERIFIED_MIN_COLLECTIONS_RATIO", "0.5"))))
    min_models_ratio = max(0.0, min(1.0, float(os.getenv("VERIFIED_MIN_MODELS_RATIO", "0.4"))))

    if prev_gifts > 0:
        min_gifts = max(min_abs_gifts, int(prev_gifts * min_gifts_ratio))
        if gifts < min_gifts:
            raise ValueError(f"{source} gifts below baseline ratio: {gifts} < {min_gifts} (prev={prev_gifts})")
    if prev_collections > 0:
        min_collections = max(1, int(prev_collections * min_collections_ratio))
        if collections < min_collections:
            raise ValueError(
                f"{source} collections below baseline ratio: {collections} < {min_collections} (prev={prev_collections})"
            )
    if prev_models > 0:
        min_models = max(1, int(prev_models * min_models_ratio))
        if models < min_models:
            raise ValueError(f"{source} models below baseline ratio: {models} < {min_models} (prev={prev_models})")


def _fetch_fragment_reserve_dataset(file_path: str | None, reason: str) -> Dict:
    root_url = os.getenv("FRAGMENT_GIFTS_URL", "https://fragment.com/gifts").strip()
    max_collections = int(os.getenv("FRAGMENT_MAX_COLLECTIONS", "0"))
    max_pages_per_collection = int(os.getenv("FRAGMENT_MAX_PAGES_PER_COLLECTION", "500"))
    collection_start = int(os.getenv("FRAGMENT_COLLECTION_START", "0"))
    fallback = _load_verified_fallback_snapshot(file_path)
    dataset = fetch_verified_dataset_from_fragment(
        root_url=root_url,
        timeout_sec=int(os.getenv("VERIFIED_API_TIMEOUT_SEC", "25")),
        max_collections=max_collections,
        max_pages_per_collection=max_pages_per_collection,
        collection_start=collection_start,
    )
    _ensure_live_dataset_quality(dataset, fallback, "fragment_reserve")
    try:
        meta = dict(dataset.get("meta") or {})
        meta.update(
            {
                "source_fallback": "fragment",
                "fallback_reason": reason[:240],
                "failed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )
        dataset["meta"] = meta
        _save_fragment_snapshot_meta(meta)
    except Exception:
        pass
    save_verified_dataset(dataset, file_path)
    return dataset


def _fetch_file_fallback_dataset(file_path: str | None, reason: str) -> Dict:
    fallback = load_verified_dataset(file_path)
    try:
        if isinstance(fallback, dict):
            meta = dict(fallback.get("meta") or {})
            meta.update(
                {
                    "source_fallback": "file",
                    "fallback_reason": reason[:240],
                    "failed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
            )
            fallback["meta"] = meta
            _save_fragment_snapshot_meta(meta)
    except Exception:
        pass
    return fallback


def load_verified_dataset_source() -> Dict:
    source = os.getenv("VERIFIED_SOURCE", "telegram_api").strip().lower()
    file_path = os.getenv("VERIFIED_DATA_FILE", "").strip() or None

    def _has_gifts(dataset: Dict) -> bool:
        gifts = dataset.get("gifts") if isinstance(dataset, dict) else None
        return isinstance(gifts, list) and len(gifts) > 0

    if source == "file":
        return load_verified_dataset(file_path)
    if source == "api":
        api_url = os.getenv("VERIFIED_API_URL", "").strip()
        api_token = os.getenv("VERIFIED_API_TOKEN", "").strip()
        token_header = os.getenv("VERIFIED_API_TOKEN_HEADER", "Authorization").strip()
        token_prefix = os.getenv("VERIFIED_API_TOKEN_PREFIX", "Bearer ").strip()
        timeout_sec = int(os.getenv("VERIFIED_API_TIMEOUT_SEC", "25"))

        try:
            fallback = _load_verified_fallback_snapshot(file_path)
            dataset = fetch_verified_dataset_from_api(
                api_url=api_url,
                api_token=api_token,
                timeout_sec=timeout_sec,
                token_header=token_header,
                token_prefix=token_prefix,
            )
            _ensure_live_dataset_quality(dataset, fallback, "verified_api")
            save_verified_dataset(dataset, file_path)
            return dataset
        except Exception as e:
            return _fetch_fragment_reserve_dataset(file_path, f"api_failed:{type(e).__name__}:{str(e)[:180]}")
    if source == "telegram_api":
        api_url = os.getenv("TELEGRAM_GIFTS_API_URL", "").strip()
        api_token = os.getenv("TELEGRAM_GIFTS_API_TOKEN", "").strip() or os.getenv("BRIDGE_API_TOKEN", "").strip()
        token_header = os.getenv("TELEGRAM_GIFTS_API_TOKEN_HEADER", "Authorization").strip()
        token_prefix = os.getenv("TELEGRAM_GIFTS_API_TOKEN_PREFIX", "Bearer ").strip()
        timeout_sec = int(os.getenv("TELEGRAM_GIFTS_API_TIMEOUT_SEC", os.getenv("VERIFIED_API_TIMEOUT_SEC", "25")))
        try:
            # Prevent loop/self-reference to local bridge snapshot unless explicitly allowed.
            allow_local_bridge = os.getenv("TELEGRAM_GIFTS_ALLOW_LOCAL_BRIDGE", "false").strip().lower() in {"1", "true", "yes", "on"}
            parsed_api = urlparse(api_url)
            host = (parsed_api.hostname or "").strip().lower()
            path = (parsed_api.path or "").strip().lower()
            local_hosts = {"127.0.0.1", "localhost", "telegram-gifts-market.onrender.com"}
            if (not allow_local_bridge) and path.endswith("/bridge/gifts/verified") and host in local_hosts:
                raise ValueError("local/self bridge endpoint is disabled for telegram_api source")
            fallback = _load_verified_fallback_snapshot(file_path)
            dataset = fetch_verified_dataset_from_telegram_api(
                api_url=api_url,
                api_token=api_token,
                timeout_sec=timeout_sec,
                token_header=token_header,
                token_prefix=token_prefix,
            )
            _ensure_live_dataset_quality(dataset, fallback, "telegram_api")
            save_verified_dataset(dataset, file_path)
            return dataset
        except Exception as e:
            allow_fragment_reserve = os.getenv("TELEGRAM_GIFTS_FRAGMENT_RESERVE", "false").strip().lower() in {"1", "true", "yes", "on"}
            reason = f"telegram_api_failed:{type(e).__name__}:{str(e)[:180]}"
            if allow_fragment_reserve:
                return _fetch_fragment_reserve_dataset(file_path, reason)
            return _fetch_file_fallback_dataset(file_path, reason)
    if source == "hybrid":
        fallback = _load_verified_fallback_snapshot(file_path)
        # 1) Prefer telegram bridge for fastest, richer traited payload.
        api_url = os.getenv("TELEGRAM_GIFTS_API_URL", "").strip()
        api_token = os.getenv("TELEGRAM_GIFTS_API_TOKEN", "").strip() or os.getenv("BRIDGE_API_TOKEN", "").strip()
        token_header = os.getenv("TELEGRAM_GIFTS_API_TOKEN_HEADER", "Authorization").strip()
        token_prefix = os.getenv("TELEGRAM_GIFTS_API_TOKEN_PREFIX", "Bearer ").strip()
        timeout_sec = int(os.getenv("TELEGRAM_GIFTS_API_TIMEOUT_SEC", os.getenv("VERIFIED_API_TIMEOUT_SEC", "25")))
        if api_url:
            try:
                dataset = fetch_verified_dataset_from_telegram_api(
                    api_url=api_url,
                    api_token=api_token,
                    timeout_sec=timeout_sec,
                    token_header=token_header,
                    token_prefix=token_prefix,
                )
                _ensure_live_dataset_quality(dataset, fallback, "hybrid.telegram_api")
                save_verified_dataset(dataset, file_path)
                return dataset
            except Exception:
                pass
        # 2) Fallback to direct Fragment snapshot.
        try:
            root_url = os.getenv("FRAGMENT_GIFTS_URL", "https://fragment.com/gifts").strip()
            max_collections = int(os.getenv("FRAGMENT_MAX_COLLECTIONS", "0"))
            max_pages_per_collection = int(os.getenv("FRAGMENT_MAX_PAGES_PER_COLLECTION", "500"))
            collection_start = int(os.getenv("FRAGMENT_COLLECTION_START", "0"))
            dataset = fetch_verified_dataset_from_fragment(
                root_url=root_url,
                timeout_sec=int(os.getenv("VERIFIED_API_TIMEOUT_SEC", "25")),
                max_collections=max_collections,
                max_pages_per_collection=max_pages_per_collection,
                collection_start=collection_start,
            )
            _ensure_live_dataset_quality(dataset, fallback, "hybrid.fragment")
            save_verified_dataset(dataset, file_path)
            return dataset
        except Exception:
            # 3) Final stable fallback: last successful snapshot from file.
            return load_verified_dataset(file_path)
    if source == "fragment":
        timeout_sec = int(os.getenv("VERIFIED_API_TIMEOUT_SEC", "25"))
        root_url = os.getenv("FRAGMENT_GIFTS_URL", "https://fragment.com/gifts").strip()
        max_collections = int(os.getenv("FRAGMENT_MAX_COLLECTIONS", "0"))
        max_pages_per_collection = int(os.getenv("FRAGMENT_MAX_PAGES_PER_COLLECTION", "500"))
        collection_start = int(os.getenv("FRAGMENT_COLLECTION_START", "0"))
        try:
            fallback = _load_verified_fallback_snapshot(file_path)
            dataset = fetch_verified_dataset_from_fragment(
                root_url=root_url,
                timeout_sec=timeout_sec,
                max_collections=max_collections,
                max_pages_per_collection=max_pages_per_collection,
                collection_start=collection_start,
            )
            _ensure_live_dataset_quality(dataset, fallback, "fragment")
            save_verified_dataset(dataset, file_path)
            return dataset
        except Exception as e:
            # Fallback to last known snapshot if live fetch failed.
            fallback = load_verified_dataset(file_path)
            err = f"fragment fetch failed: {type(e).__name__}: {str(e)[:240]}"
            try:
                if isinstance(fallback, dict):
                    meta = dict(fallback.get("meta") or {})
                    meta.update(
                        {
                            "source_fallback": "file",
                            "error": err,
                            "failed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        }
                    )
                    fallback["meta"] = meta
                    _save_fragment_snapshot_meta(meta)
            except Exception:
                pass
            return fallback

    raise ValueError("VERIFIED_SOURCE must be one of: 'file', 'api', 'telegram_api', 'hybrid', 'fragment'")


def save_dataset(dataset: Dict) -> None:
    _atomic_write_json(DATA_FILE, dataset)


def refresh_dataset(days: int = 180) -> Dict:
    dataset = generate_dataset(days=days)
    save_dataset(dataset)
    return dataset


def tick_realtime(dataset: Dict, max_points: int = 360) -> None:
    for gift in dataset.get("gifts", []):
        series = gift.get("series", [])
        if not series:
            continue

        last = series[-1]
        price = float(last["price"])
        demand = float(last["demand"])
        supply = float(last["supply"])

        micro_trend = random.uniform(-0.006, 0.008)
        spike = random.uniform(-0.02, 0.02) if random.random() < 0.1 else 0.0
        price_change = _clamp(micro_trend + spike + random.gauss(0.0, 0.008), -0.04, 0.05)
        price = max(1.0, price * (1 + price_change))

        demand = _clamp(demand * (1 + random.gauss(0.0, 0.018)), 0.4, 3.3)
        supply = _clamp(supply * (1 + random.gauss(0.0, 0.018)), 0.35, 3.4)
        volume = int(180 + 320 * demand / max(supply, 0.35) + random.randint(-30, 45))
        volume = max(30, volume)

        series.append(
            {
                "dt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "price": round(price, 4),
                "demand": round(demand, 4),
                "supply": round(supply, 4),
                "volume": volume,
            }
        )
        if len(series) > max_points:
            del series[: len(series) - max_points]

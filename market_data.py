from __future__ import annotations

import json
import os
import random
import re
import ssl
import time
import urllib.error
import urllib.request
from collections import defaultdict
from http import cookiejar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlencode

DATA_FILE = Path(__file__).parent / "data" / "gifts_history.json"
VERIFIED_DATA_FILE = Path(__file__).parent / "data" / "verified_gifts.json"
FRAGMENT_ANALYTICS_STORE_FILE = Path(__file__).parent / "data" / "fragment_analytics_store.json"
FRAGMENT_SNAPSHOT_META_FILE = Path(__file__).parent / "data" / "fragment_snapshot_meta.json"
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
        r'icon-ton">(?P<price>[0-9.]+)</div>.*?'
        r'tm-grid-item-status[^"]*">(?P<status>[^<]+)</div>',
        re.S | re.I,
    )
    for m in pattern.finditer(html):
        try:
            raw_status = _clean_fragment_text(m.group("status")).lower()
            status = status_map.get(raw_status, raw_status)
            if status not in {"sold", "sale", "auction"} and default_status:
                status = default_status
            cards.append(
                {
                    "gift_id": _clean_fragment_text(m.group("gift_id")),
                    "datetime": _clean_fragment_text(m.group("dt")),
                    "price_ton": float(_clean_fragment_text(m.group("price"))),
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
    def _extract_attr(label: str) -> tuple[str, str | None]:
        rx = re.compile(
            rf'<div class="table-cell">{label}</div>.*?<div class="table-cell-value tm-value">.*?'
            r'<a [^>]*class="table-cell-value-link">([^<]+)</a>.*?'
            r'<span class="tm-rarity">\s*([^<]+)\s*</span>',
            re.S | re.I,
        )
        m = rx.search(html)
        if not m:
            return ("N/A", None)
        return (_clean_fragment_text(m.group(1)), _clean_fragment_text(m.group(2)))

    model, model_share = _extract_attr("Model")
    pattern, pattern_share = _extract_attr("Symbol")
    background, background_share = _extract_attr("Backdrop")

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
    cj = cookiejar.CookieJar()
    no_verify_ssl = os.getenv("FRAGMENT_SSL_NO_VERIFY", "").strip().lower() in {"1", "true", "yes", "on"}
    ssl_context = ssl._create_unverified_context() if no_verify_ssl else ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=ssl_context),
    )

    def _get_text(url: str) -> str:
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "Mozilla/5.0 (compatible; GiftMarketZone/1.0)")
        req.add_header("Accept", "text/html,application/xhtml+xml")
        with opener.open(req, timeout=timeout_sec) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def _post_json(api_hash: str, referer: str, params: dict) -> dict:
        api_url = f"https://fragment.com/api?hash={api_hash}"
        body = urlencode(params).encode("utf-8")
        req = urllib.request.Request(api_url, data=body, method="POST")
        req.add_header("User-Agent", "Mozilla/5.0 (compatible; GiftMarketZone/1.0)")
        req.add_header("Accept", "application/json")
        req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
        req.add_header("X-Requested-With", "XMLHttpRequest")
        req.add_header("Origin", "https://fragment.com")
        req.add_header("Referer", referer)
        with opener.open(req, timeout=timeout_sec) as resp:
            return json.loads(resp.read().decode("utf-8"))

    root_html = _get_text(root_url)
    collections = _fragment_parse_collections(root_html)
    active_only = os.getenv("FRAGMENT_ACTIVE_ONLY", "true").strip().lower() in {"1", "true", "yes", "on"}
    if active_only:
        sale_html = _get_text(f"{root_url}?sort=price&filter=sale")
        auction_html = _get_text(f"{root_url}?sort=price&filter=auction")
        sale_cols = _fragment_parse_collections(sale_html)
        auction_cols = _fragment_parse_collections(auction_html)
        merged = {c["slug"]: c for c in sale_cols + auction_cols}
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

    for collection in collections:
        if time.monotonic() - started_at > fetch_budget_sec:
            break
        slug = collection["slug"]
        try:
            def _fetch_events(filter_value: str) -> list[dict]:
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
                    if time.monotonic() - started_at > fetch_budget_sec:
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

            events = _fetch_events("sale") + _fetch_events("auction")

            if not events:
                continue

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

                for lot_id, ev in lot_latest.items():
                    latest_status = str(ev.get("status") or "").strip().lower()
                    if latest_status == "sold":
                        continue
                    lot_price = float(ev.get("price_ton") or 0.0)
                    if lot_price <= 0:
                        continue
                    lot_profile = dict(profile)
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
                            "preview_image_url": preview_image_url,
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
                gifts.append(
                    {
                        "gift_id": gift_id,
                        "name": gift_name,
                        "group": "Fragment Gifts",
                        "collection_slug": slug,
                        "fragment_market_url": f"https://fragment.com/gifts/{slug}",
                        "last_lot_id": last_event["gift_id"],
                        "latest_status": str(last_event.get("status") or "").strip().lower(),
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
            continue

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

    meta = {
        "generated_at": generated_at,
        "collections_total": total_collections,
        "collections_used": len(collections),
        "collection_start": collection_start,
        "max_collections": max_collections,
        "max_pages_per_collection": max_pages_per_collection,
        "gifts": len(gifts),
        "gift_mode": gift_mode,
    }
    dataset = {"generated_at": generated_at, "gifts": gifts, "filters": filter_index, "meta": meta}
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


def load_verified_dataset_source() -> Dict:
    source = os.getenv("VERIFIED_SOURCE", "file").strip().lower()
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
            dataset = fetch_verified_dataset_from_api(
                api_url=api_url,
                api_token=api_token,
                timeout_sec=timeout_sec,
                token_header=token_header,
                token_prefix=token_prefix,
            )
            if not _has_gifts(dataset):
                raise ValueError("verified api returned empty gifts")
            # Cache last successful verified snapshot for audit and fallback debugging.
            save_verified_dataset(dataset, file_path)
            return dataset
        except Exception:
            # Never replace runtime dataset with empty/invalid API payload.
            return load_verified_dataset(file_path)
    if source == "fragment":
        timeout_sec = int(os.getenv("VERIFIED_API_TIMEOUT_SEC", "25"))
        root_url = os.getenv("FRAGMENT_GIFTS_URL", "https://fragment.com/gifts").strip()
        max_collections = int(os.getenv("FRAGMENT_MAX_COLLECTIONS", "0"))
        max_pages_per_collection = int(os.getenv("FRAGMENT_MAX_PAGES_PER_COLLECTION", "500"))
        collection_start = int(os.getenv("FRAGMENT_COLLECTION_START", "0"))
        try:
            dataset = fetch_verified_dataset_from_fragment(
                root_url=root_url,
                timeout_sec=timeout_sec,
                max_collections=max_collections,
                max_pages_per_collection=max_pages_per_collection,
                collection_start=collection_start,
            )
            if not _has_gifts(dataset):
                raise ValueError("fragment returned empty gifts")
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

    raise ValueError("VERIFIED_SOURCE must be one of: 'file', 'api', 'fragment'")


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

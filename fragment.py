from __future__ import annotations

import os
import re
import ssl
import urllib.error
import urllib.request
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import median
from dataclasses import dataclass
from datetime import datetime, timezone
from http import cookiejar
from html import unescape
from typing import Dict, List, Tuple
from urllib.parse import urlencode

_UA = "Mozilla/5.0 (compatible; GiftMarketZone/1.0)"
_RE_NEXT_OFFSET = re.compile(r'data-next-offset="([^"]+)"', re.I)
_RE_API_HASHES = [
    re.compile(r'api\?hash=([a-f0-9]+)', re.I),
    re.compile(r'data-api-hash="([a-f0-9]+)"', re.I),
    re.compile(r'"api_hash"\s*:\s*"([a-f0-9]+)"', re.I),
    re.compile(r'"apiHash"\s*:\s*"([a-f0-9]+)"', re.I),
]
_RE_OG_IMAGE = re.compile(r'<meta property="og:image" content="([^"]+)"', re.I)
_RE_DETAIL_PRICE_TON = [
    re.compile(r'icon-ton">\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*<', re.I),
    re.compile(r'"price"\s*:\s*([0-9]+(?:\.[0-9]+)?)', re.I),
]
_RE_DETAIL_PRICE_STARS = [
    re.compile(r'icon-star[^>]*>\s*([0-9][0-9,]*(?:\.[0-9]+)?)', re.S | re.I),
    re.compile(r'icon-stars[^>]*>\s*([0-9][0-9,]*(?:\.[0-9]+)?)', re.S | re.I),
    re.compile(r'⭐\s*([0-9][0-9,]*(?:\.[0-9]+)?)', re.S | re.I),
]
_RE_DETAIL_STATUS = [
    re.compile(r'tm-gift-status[^>]*>\s*([^<]+)\s*<', re.I),
    re.compile(r'tm-grid-item-status[^>]*>\s*([^<]+)\s*<', re.I),
]


@dataclass
class VariantTraits:
    model: str
    background: str
    pattern: str

    @property
    def model_id(self) -> str:
        return _slugify(self.model)

    @property
    def background_id(self) -> str:
        return _slugify(self.background)

    @property
    def pattern_id(self) -> str:
        return _slugify(self.pattern)


@dataclass
class ListingEvent:
    listing_id: str
    base_id: str
    variant_id: str
    price_ton: float
    status: str
    ts: str
    traits: VariantTraits
    preview_url: str


@dataclass
class BaseInfo:
    base_id: str
    name: str
    slug: str


class FragmentClient:
    def __init__(self) -> None:
        self.ssl_no_verify = os.getenv("FRAGMENT_SSL_NO_VERIFY", "").strip().lower() in {"1", "true", "yes", "on"}
        self.timeout_sec = int(os.getenv("FRAGMENT_TIMEOUT_SEC", "25"))
        self.fetch_budget_sec = int(os.getenv("FRAGMENT_FETCH_BUDGET_SEC", "60"))
        self.max_cards_per_collection = int(os.getenv("FRAGMENT_MAX_CARDS_PER_COLLECTION", "80"))
        self.min_events = int(os.getenv("FRAGMENT_MIN_EVENTS", "30"))
        self.min_collections = int(os.getenv("FRAGMENT_MIN_COLLECTIONS", "0"))
        self.min_backgrounds = int(os.getenv("FRAGMENT_MIN_BACKGROUNDS", "0"))
        self.request_retries = int(os.getenv("FRAGMENT_REQUEST_RETRIES", "2"))
        self.retry_backoff_sec = float(os.getenv("FRAGMENT_RETRY_BACKOFF_SEC", "0.6"))
        self.detail_workers = max(1, int(os.getenv("FRAGMENT_DETAIL_WORKERS", "8")))
        self.detail_cache_ttl_sec = int(os.getenv("FRAGMENT_DETAIL_CACHE_TTL_SEC", "900"))
        self.detail_cache_max = int(os.getenv("FRAGMENT_DETAIL_CACHE_MAX", "25000"))
        ctx = ssl._create_unverified_context() if self.ssl_no_verify else ssl.create_default_context()
        self.cj = cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=ctx),
        )
        self.derived_stars_per_ton: float | None = None
        self._detail_cache: Dict[str, tuple[float, tuple[VariantTraits | None, str, float | None, float | None, str]]] = {}

    def _append_ratio_sample(self, samples: List[float], ratio: float) -> None:
        if ratio <= 0:
            return
        if len(samples) < 2000:
            samples.append(ratio)
            return
        # Replace pseudo-random positions to keep bounded memory with representative samples.
        idx = int((time.monotonic() * 1000) % len(samples))
        samples[idx] = ratio

    def _run_with_retries(self, fn, op: str):
        last_err = None
        for attempt in range(1, self.request_retries + 2):
            try:
                return fn()
            except Exception as e:
                last_err = e
                if attempt >= self.request_retries + 1:
                    break
                time.sleep(min(5.0, self.retry_backoff_sec * attempt))
        raise RuntimeError(f"{op} failed after retries: {last_err}")

    def _build_opener(self, verify_ssl: bool) -> urllib.request.OpenerDirector:
        ctx = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()
        return urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=ctx),
        )

    def _open(self, req: urllib.request.Request):
        try:
            return self.opener.open(req, timeout=self.timeout_sec)
        except urllib.error.URLError as e:
            err = str(e)
            # Fallback for local envs with broken CA chain.
            if "CERTIFICATE_VERIFY_FAILED" in err and not self.ssl_no_verify:
                self.ssl_no_verify = True
                self.opener = self._build_opener(verify_ssl=False)
                return self.opener.open(req, timeout=self.timeout_sec)
            raise

    def _get_text(self, url: str) -> str:
        def _do():
            req = urllib.request.Request(url, method="GET")
            req.add_header("User-Agent", _UA)
            req.add_header("Accept", "text/html,application/xhtml+xml")
            with self._open(req) as resp:
                sock = getattr(getattr(getattr(resp, "fp", None), "raw", None), "_sock", None)
                if sock:
                    try:
                        sock.settimeout(self.timeout_sec)
                    except Exception:
                        pass
                max_bytes = int(os.getenv("FRAGMENT_MAX_BYTES", "2000000"))
                raw = resp.read(max_bytes)
                return raw.decode("utf-8", errors="replace")
        return self._run_with_retries(_do, f"GET {url}")

    def _post_json(self, api_hash: str, referer: str, params: dict) -> dict:
        def _do():
            api_url = f"https://fragment.com/api?hash={api_hash}"
            body = urlencode(params).encode("utf-8")
            req = urllib.request.Request(api_url, data=body, method="POST")
            req.add_header("User-Agent", _UA)
            req.add_header("Accept", "application/json")
            req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
            req.add_header("X-Requested-With", "XMLHttpRequest")
            req.add_header("Origin", "https://fragment.com")
            req.add_header("Referer", referer)
            with self._open(req) as resp:
                import json
                return json.loads(resp.read().decode("utf-8"))
        return self._run_with_retries(_do, f"POST api hash={api_hash}")

    def fetch_active_listings(self, max_collections: int, max_pages: int) -> Tuple[List[ListingEvent], List[BaseInfo]]:
        started_at = time.monotonic()
        root_url = "https://fragment.com/gifts"
        root_html = self._get_text(root_url)
        collections = _parse_collections(root_html)

        sale_html = self._get_text(f"{root_url}?sort=price&filter=sale")
        auction_html = self._get_text(f"{root_url}?sort=price&filter=auction")
        sale_cols = _parse_collections(sale_html)
        auction_cols = _parse_collections(auction_html)
        # Keep root catalog as a base and enrich it with filtered pages.
        merged = {c["slug"]: c for c in collections}
        for c in sale_cols + auction_cols:
            merged[c["slug"]] = c
        collections = sorted(merged.values(), key=lambda x: x.get("name", ""))

        if max_collections and max_collections > 0:
            collections = collections[:max_collections]

        events: List[ListingEvent] = []
        bases: List[BaseInfo] = []
        stars_ratio_samples: List[float] = []
        seen_collections: set[str] = set()
        seen_backgrounds: set[str] = set()

        def targets_met() -> bool:
            if self.min_events > 0 and len(events) < self.min_events:
                return False
            if self.min_collections > 0 and len(seen_collections) < self.min_collections:
                return False
            if self.min_backgrounds > 0 and len(seen_backgrounds) < self.min_backgrounds:
                return False
            return True

        for c in collections:
            if targets_met():
                break
            if time.monotonic() - started_at > self.fetch_budget_sec and targets_met():
                break
            slug = c["slug"]
            base_name = c["name"] or slug
            bases.append(BaseInfo(base_id=slug, name=base_name, slug=slug))
            seen_collections.add(slug)

            for filter_value in ("sale", "auction"):
                page_url = f"{root_url}/{slug}?sort=price&filter={filter_value}"
                page_html = self._get_text(page_url)
                api_hash = _extract_api_hash(page_html)
                cards: List[dict] = []
                if api_hash:
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
                    first = self._post_json(api_hash, page_url, params)
                    if not isinstance(first, dict):
                        first = {}
                    html = first.get("html") or first.get("body") or ""
                    foot = first.get("foot") or ""
                    cards = _parse_item_cards(html, default_status=filter_value)
                    next_offset = _extract_next_offset(foot or html)

                    page_no = 1
                    while next_offset and page_no < max_pages:
                        page_no += 1
                        params["offset_id"] = next_offset
                        part = self._post_json(api_hash, page_url, params)
                        if not isinstance(part, dict):
                            part = {}
                        body_html = part.get("body") or part.get("html") or ""
                        foot_html = part.get("foot") or ""
                        if body_html:
                            cards.extend(_parse_item_cards(body_html, default_status=filter_value))
                        next_offset = _extract_next_offset(foot_html or body_html)
                        if not body_html:
                            break
                else:
                    cards = _parse_item_cards(page_html, default_status=filter_value)

                if self.max_cards_per_collection > 0:
                    cards = cards[: self.max_cards_per_collection]

                traits_by_id: Dict[str, tuple[VariantTraits | None, str, float | None, float | None, str]] = {}
                with ThreadPoolExecutor(max_workers=self.detail_workers) as pool:
                    future_to_id = {pool.submit(self._fetch_traits, card["gift_id"]): card["gift_id"] for card in cards}
                    for fut in as_completed(future_to_id):
                        gid = future_to_id[fut]
                        try:
                            traits_by_id[gid] = fut.result()
                        except Exception:
                            traits_by_id[gid] = (None, "", None, None, "")

                for card in cards:
                    if time.monotonic() - started_at > self.fetch_budget_sec and targets_met():
                        return events, bases
                    traits, preview, detail_price_ton, detail_price_stars, detail_status = traits_by_id.get(
                        card["gift_id"], (None, "", None, None, "")
                    )
                    if not traits:
                        continue
                    status = card["status"]
                    if detail_status in {"sale", "auction", "sold"}:
                        status = detail_status
                    if status == "sold":
                        continue
                    price_ton = float(detail_price_ton) if detail_price_ton is not None else float(card["price_ton"])
                    if detail_price_stars and price_ton > 0:
                        ratio = float(detail_price_stars) / float(price_ton)
                        self._append_ratio_sample(stars_ratio_samples, ratio)
                    variant_id = f"{slug}|{traits.model_id}|{traits.background_id}|{traits.pattern_id}"
                    events.append(
                        ListingEvent(
                            listing_id=card["gift_id"],
                            base_id=slug,
                            variant_id=variant_id,
                            price_ton=price_ton,
                            status=status,
                            ts=card["datetime"],
                            traits=traits,
                            preview_url=preview,
                        )
                    )
                    seen_backgrounds.add(traits.background_id)
                    if targets_met():
                        if stars_ratio_samples:
                            self.derived_stars_per_ton = round(float(median(stars_ratio_samples)), 6)
                        return events, bases
        if stars_ratio_samples:
            self.derived_stars_per_ton = round(float(median(stars_ratio_samples)), 6)
        return events, bases

    def _fetch_traits(self, gift_id: str) -> Tuple[VariantTraits | None, str, float | None, float | None, str]:
        now = time.monotonic()
        cached = self._detail_cache.get(gift_id)
        if cached and (now - cached[0]) <= self.detail_cache_ttl_sec:
            return cached[1]
        try:
            detail_html = self._get_text(f"https://fragment.com/gift/{gift_id}?sort=price")
        except Exception:
            return None, "", None, None, ""
        profile = _parse_detail_profile(detail_html)
        preview = _parse_og_image(detail_html)
        detail_price_ton = _parse_detail_price_ton(detail_html)
        detail_price_stars = _parse_detail_price_stars(detail_html)
        detail_status = _parse_detail_status(detail_html)
        model = profile.get("model") or ""
        background = profile.get("background") or ""
        pattern = profile.get("pattern") or ""
        if not (model and background and pattern):
            return None, preview, detail_price_ton, detail_price_stars, detail_status
        result = (VariantTraits(model=model, background=background, pattern=pattern), preview, detail_price_ton, detail_price_stars, detail_status)
        if len(self._detail_cache) > self.detail_cache_max:
            self._detail_cache.clear()
        self._detail_cache[gift_id] = (now, result)
        return result


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_") or "unknown"


def _parse_collections(html: str) -> List[dict]:
    main_pattern = re.compile(
        r'<a href="/gifts/(?P<slug>[a-z0-9]+)"[^>]*data-value="(?P<value>[^"]+)"[^>]*>.*?'
        r'<div class="tm-main-filters-name">(?P<name>[^<]+)</div>\s*'
        r'<div class="tm-main-filters-count">(?P<count>[^<]+)</div>',
        re.S | re.I,
    )
    out = []
    seen = set()
    for m in main_pattern.finditer(html):
        slug = _clean_text(m.group("slug")).lower()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        count_raw = _clean_text(m.group("count"))
        count_digits = re.sub(r"[^\d]", "", count_raw)
        total_supply = int(count_digits) if count_digits else 0
        out.append({"slug": slug, "name": _clean_text(m.group("name")), "total_supply": total_supply})

    # Fallback parser for pages where dedicated filter cards are absent.
    if not out:
        link_pattern = re.compile(r'<a href="/gifts/(?P<slug>[a-z0-9]+)(?:\?[^"]*)?"[^>]*>(?P<body>.*?)</a>', re.S | re.I)
        for m in link_pattern.finditer(html):
            slug = _clean_text(m.group("slug")).lower()
            if not slug or slug in seen:
                continue
            body = m.group("body") or ""
            name_match = re.search(r'tm-main-filters-name">([^<]+)</', body, re.S | re.I)
            name = _clean_text(name_match.group(1)) if name_match else slug
            count_match = re.search(r'tm-main-filters-count">([^<]+)</', body, re.S | re.I)
            count_digits = re.sub(r"[^\d]", "", _clean_text(count_match.group(1)) if count_match else "")
            total_supply = int(count_digits) if count_digits else 0
            seen.add(slug)
            out.append({"slug": slug, "name": name, "total_supply": total_supply})
    return out


def _parse_item_cards(html: str, default_status: str | None = None) -> List[dict]:
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
        r'<a href="/gift/(?P<gift_id>[a-z0-9\\-]+)(?:\\?[^"]*)?" class="tm-grid-item">.*?'
        r'<time datetime="(?P<dt>[^"]+)"[^>]*>.*?</time>.*?'
        r'icon-ton">(?P<price>[0-9][0-9,]*(?:\.[0-9]+)?)</div>.*?'
        r'tm-grid-item-status[^"]*">(?P<status>[^<]+)</div>',
        re.S | re.I,
    )
    for m in pattern.finditer(html):
        status_raw = _clean_text(m.group("status")).lower()
        status = status_map.get(status_raw, status_raw)
        if status not in {"sold", "sale", "auction"} and default_status:
            status = default_status
        try:
            cards.append(
                {
                    "gift_id": _clean_text(m.group("gift_id")),
                    "datetime": _clean_text(m.group("dt")),
                    "price_ton": float(_clean_text(m.group("price")).replace(",", "")),
                    "status": status,
                }
            )
        except Exception:
            continue
    return cards


def _extract_next_offset(html: str) -> str:
    m = _RE_NEXT_OFFSET.search(html)
    return _clean_text(m.group(1)) if m else ""


def _extract_api_hash(html: str) -> str:
    for pat in _RE_API_HASHES:
        m = pat.search(html)
        if m:
            return m.group(1)
    return ""


def _parse_detail_profile(html: str) -> dict:
    def find(label: str) -> str:
        rx = re.compile(
            rf'<div class="table-cell">{label}</div>.*?<div class="table-cell-value tm-value">.*?'
            r'<a [^>]*class="table-cell-value-link">([^<]+)</a>.*?'
            r'<span class="tm-rarity">\s*([^<]+)\s*</span>',
            re.S | re.I,
        )
        m = rx.search(html)
        if not m:
            return ""
        return _clean_text(m.group(1))

    return {
        "model": find("Model"),
        "background": find("Backdrop"),
        "pattern": find("Symbol"),
    }


def _parse_og_image(html: str) -> str:
    m = _RE_OG_IMAGE.search(html)
    return _clean_text(m.group(1)) if m else ""


def _parse_detail_price_ton(html: str) -> float | None:
    for pat in _RE_DETAIL_PRICE_TON:
        m = pat.search(html)
        if not m:
            continue
        try:
            return float(m.group(1).replace(",", ""))
        except Exception:
            continue
    return None


def _parse_detail_price_stars(html: str) -> float | None:
    for pat in _RE_DETAIL_PRICE_STARS:
        m = pat.search(html)
        if not m:
            continue
        raw = _clean_text(m.group(1)).replace(",", "")
        try:
            value = float(raw)
            if value > 0:
                return value
        except Exception:
            continue
    return None


def _parse_detail_status(html: str) -> str:
    status_map = {
        "sold": "sold",
        "for sale": "sale",
        "sale": "sale",
        "on auction": "auction",
        "auction": "auction",
        "available": "sale",
    }
    for pat in _RE_DETAIL_STATUS:
        m = pat.search(html)
        if not m:
            continue
        raw = _clean_text(m.group(1)).lower()
        if raw in status_map:
            return status_map[raw]
    return ""


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value or "")).strip()

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request
from html import escape
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote
from urllib.parse import parse_qs, urlparse

from analytics import build_chart_series, build_market_summary, get_ranked_signals
from market_data import load_dataset, load_fragment_snapshot_meta, load_verified_dataset, load_verified_dataset_source, refresh_dataset, tick_realtime

ROOT = Path(__file__).parent
STATIC_DIR = ROOT / "static"
FAVORITES_STORE_FILE = ROOT / "data" / "favorites_by_user.json"
VERIFIED_GIFT_OVERRIDES = {
    "input_key_magic_8_ball_60441": {
        "model": "Magic 8 Ball",
        "model_share": "2%",
        "pattern": "Magic Hat",
        "pattern_share": "0.2%",
        "background": "Cyberpunk",
        "background_share": "1.2%",
        "issued": 128809,
        "total_supply": 159750,
        "value_rub_estimate": 976.00,
        "value_score": 94,
        "source_note": "User verified snapshot",
    }
}


class FavoritesStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"users": {}}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict) and isinstance(payload.get("users"), dict):
                return payload
        except Exception:
            pass
        return {"users": {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get(self, user_id: str) -> list[str]:
        with self.lock:
            ids = self.data.get("users", {}).get(user_id, [])
            if not isinstance(ids, list):
                return []
            # Keep deterministic order and avoid duplicates.
            seen: set[str] = set()
            out: list[str] = []
            for v in ids:
                gift_id = str(v or "").strip()
                if not gift_id or gift_id in seen:
                    continue
                seen.add(gift_id)
                out.append(gift_id)
            return out

    def set(self, user_id: str, gift_ids: list[str]) -> list[str]:
        cleaned = []
        seen: set[str] = set()
        for x in gift_ids:
            v = str(x or "").strip()
            if not v or v in seen:
                continue
            seen.add(v)
            cleaned.append(v)
        with self.lock:
            users = self.data.setdefault("users", {})
            users[user_id] = cleaned
            self._save()
            return list(cleaned)

    def toggle(self, user_id: str, gift_id: str) -> tuple[list[str], bool]:
        gid = str(gift_id or "").strip()
        if not gid:
            return self.get(user_id), False
        with self.lock:
            users = self.data.setdefault("users", {})
            ids = [str(x) for x in users.get(user_id, []) if str(x).strip()]
            active = gid in ids
            if active:
                ids = [x for x in ids if x != gid]
            else:
                ids.append(gid)
            users[user_id] = ids
            self._save()
            return list(ids), (not active)


class AppState:
    def __init__(self) -> None:
        self.verified_only = os.getenv("VERIFIED_ONLY", "true").lower() in {"1", "true", "yes", "on"}
        self.verified_data_file = os.getenv("VERIFIED_DATA_FILE", "")
        self.verified_refresh_sec = float(os.getenv("VERIFIED_REFRESH_SEC", "600"))
        self.lock = threading.RLock()
        self.realtime_tick_count = 0
        self.last_tick_at = ""
        self.last_verified_refresh_at = ""
        self.last_verified_refresh_error = ""
        self.realtime_interval_sec = float(os.getenv("REALTIME_INTERVAL_SEC", "3"))
        self.dataset = self._load_initial_dataset()
        if self.verified_only:
            self._start_verified_reload_loop()
        else:
            self._start_realtime_loop()

    def refresh(self) -> None:
        if self.verified_only:
            new_dataset = load_verified_dataset_source()
        else:
            new_dataset = refresh_dataset()
        with self.lock:
            self.dataset = new_dataset
            self.realtime_tick_count = 0
            self.last_tick_at = ""

    def summary(self) -> dict:
        with self.lock:
            summary = build_market_summary(self.dataset)
            ton_usd = self._ton_usd_rate()
            ton_native = self._price_is_ton_native()
            for row in summary.get("rows", []):
                if ton_native:
                    row["price_ton"] = round(float(row["price"]), 4)
                else:
                    row["price_ton"] = round(float(row["price"]) / ton_usd, 4) if ton_usd > 0 else 0.0
            summary["ton_usd_rate"] = ton_usd
            return summary

    def filters(self) -> dict:
        with self.lock:
            rows = build_market_summary(self.dataset)["rows"]
            dataset_filters = self.dataset.get("filters") if isinstance(self.dataset, dict) else None
            if dataset_filters:
                def _to_sorted_options(values: dict) -> list[dict]:
                    items = [{"value": k, "count": int(v)} for k, v in values.items() if k]
                    items.sort(key=lambda x: (-x["count"], x["value"]))
                    return items

                collections = list(dataset_filters.get("collections") or [])
                collections.sort(key=lambda x: x.get("name", ""))
                models = _to_sorted_options(dataset_filters.get("models") or {})
                backdrops = _to_sorted_options(dataset_filters.get("backdrops") or {})
                symbols = _to_sorted_options(dataset_filters.get("symbols") or {})
                if not models:
                    models = [{"value": m, "count": 0} for m in sorted({str(r.get("model", "")).strip() for r in rows if str(r.get("model", "")).strip()})]
                if not backdrops:
                    backdrops = [{"value": b, "count": 0} for b in sorted({str(r.get("backdrop", "")).strip() for r in rows if str(r.get("backdrop", "")).strip()})]
                if not symbols:
                    symbols = [{"value": s, "count": 0} for s in sorted({str(r.get("symbol", "")).strip() for r in rows if str(r.get("symbol", "")).strip()})]
                return {
                    "collections": collections,
                    "models": models,
                    "backdrops": backdrops,
                    "symbols": symbols,
                    "market_statuses": [
                        {"value": "sold", "label": "Sold"},
                        {"value": "sale", "label": "For sale"},
                        {"value": "auction", "label": "On auction"},
                    ],
                }

            collections = sorted({str(r.get("collection", "")).strip() for r in rows if str(r.get("collection", "")).strip()})
            models = sorted({str(r.get("model", "")).strip() for r in rows if str(r.get("model", "")).strip()})
            backdrops = sorted({str(r.get("backdrop", "")).strip() for r in rows if str(r.get("backdrop", "")).strip()})
            symbols = sorted({str(r.get("symbol", "")).strip() for r in rows if str(r.get("symbol", "")).strip()})
            return {
                "collections": [{"slug": c, "name": c, "total_supply": 0} for c in collections],
                "models": [{"value": m, "count": 0} for m in models],
                "backdrops": [{"value": b, "count": 0} for b in backdrops],
                "symbols": [{"value": s, "count": 0} for s in symbols],
                "market_statuses": [
                    {"value": "sold", "label": "Sold"},
                    {"value": "sale", "label": "For sale"},
                    {"value": "auction", "label": "On auction"},
                ],
            }

    def chart(self, gift_id: str) -> dict | None:
        with self.lock:
            gift = next((g for g in self.dataset["gifts"] if g["gift_id"] == gift_id), None)
            if not gift:
                return None
            chart = build_chart_series(gift)
            ton_usd = self._ton_usd_rate()
            ton_native = self._price_is_ton_native()
            if ton_native:
                chart["prices_ton"] = [round(float(p), 4) for p in chart["prices"]]
            else:
                chart["prices_ton"] = [round(float(p) / ton_usd, 4) if ton_usd > 0 else 0.0 for p in chart["prices"]]
            chart["ton_usd_rate"] = ton_usd
            return chart

    def screener(self) -> list[dict]:
        with self.lock:
            rows = build_market_summary(self.dataset)["rows"]
            ton_usd = self._ton_usd_rate()
            ton_native = self._price_is_ton_native()
            for row in rows:
                if ton_native:
                    row["price_ton"] = round(float(row["price"]), 4)
                else:
                    row["price_ton"] = round(float(row["price"]) / ton_usd, 4) if ton_usd > 0 else 0.0
            return rows

    def signals(self) -> list[dict]:
        with self.lock:
            rows = get_ranked_signals(self.dataset)
            gift_map = {g.get("gift_id"): g for g in self.dataset.get("gifts", [])}
            ton_usd = self._ton_usd_rate()
            ton_native = self._price_is_ton_native()
            for row in rows:
                gift = gift_map.get(row.get("gift_id")) or {}
                if ton_native:
                    row["price_ton"] = round(float(row["price"]), 4)
                else:
                    row["price_ton"] = round(float(row["price"]) / ton_usd, 4) if ton_usd > 0 else 0.0
                row["buy_url"] = self._resolve_buy_url(row.get("gift_id", ""), gift)
                row["photo_url"] = str(gift.get("preview_image_url") or "").strip()
            return rows

    def status(self) -> dict:
        with self.lock:
            meta = (
                load_fragment_snapshot_meta()
                if self.verified_only and os.getenv("VERIFIED_SOURCE", "file").strip().lower() == "fragment"
                else {}
            )
            return {
                "realtime_interval_sec": self.realtime_interval_sec,
                "realtime_tick_count": self.realtime_tick_count,
                "last_tick_at": self.last_tick_at,
                "dataset_generated_at": self.dataset.get("generated_at", "") if isinstance(self.dataset, dict) else "",
                "gifts_count": len(self.dataset.get("gifts", [])) if isinstance(self.dataset, dict) else 0,
                "verified_only": self.verified_only,
                "verified_source": os.getenv("VERIFIED_SOURCE", "file"),
                "verified_refresh_sec": self.verified_refresh_sec,
                "last_verified_refresh_at": self.last_verified_refresh_at,
                "last_verified_refresh_error": self.last_verified_refresh_error,
                "bot_enabled": TG_BRIDGE.enabled if "TG_BRIDGE" in globals() else False,
                "fragment_meta": meta,
            }

    def details(self, gift_id: str) -> dict | None:
        with self.lock:
            summary = build_market_summary(self.dataset)["rows"]
            row = next((r for r in summary if r["gift_id"] == gift_id), None)
            gift = next((g for g in self.dataset["gifts"] if g["gift_id"] == gift_id), None)
            if not row or not gift:
                return None

            chart = build_chart_series(gift)
            ton_usd = float(os.getenv("TON_USD_RATE", "4.2"))
            star_usd = float(os.getenv("STAR_USD_RATE", "0.015"))
            ton_native = self._price_is_ton_native()
            if ton_native:
                price_ton = round(float(row["price"]), 4)
                price_usd = round(price_ton * ton_usd, 4)
            else:
                price_usd = float(row["price"])
                price_ton = round(price_usd / ton_usd, 4) if ton_usd > 0 else 0.0
            price_stars = int(round(price_usd / star_usd)) if star_usd > 0 else 0
            buy_url = self._resolve_buy_url(gift_id, gift)
            profile = gift.get("profile") if self.verified_only else _gift_profile(gift_id, price_usd, row["signal"])
            if not profile:
                return None

            return {
                "gift": row,
                "price_usd": round(price_usd, 4),
                "price_ton": price_ton,
                "price_stars": price_stars,
                "buy_url": buy_url,
                "profile": profile,
                "chart_tail": {
                    "dates": chart["dates"][-24:],
                    "prices": chart["prices"][-24:],
                    "volume": chart["volume"][-24:],
                },
            }

    def _resolve_buy_url(self, gift_id: str, gift: dict) -> str:
        buy_url_template = os.getenv("PORTALS_GIFT_URL_TEMPLATE", "https://portals.market/gifts/{gift_id}")
        if gift.get("last_lot_id"):
            return f"https://fragment.com/gift/{quote(str(gift['last_lot_id']), safe='')}?sort=price"
        if gift.get("fragment_market_url"):
            return str(gift["fragment_market_url"])
        return buy_url_template.format(gift_id=quote(str(gift_id), safe=""))

    def gifts_snapshot(self) -> list[dict]:
        with self.lock:
            out: list[dict] = []
            for gift in self.dataset.get("gifts", []):
                gift_id = str(gift.get("gift_id") or "").strip()
                if not gift_id:
                    continue
                out.append(
                    {
                        "gift_id": gift_id,
                        "name": str(gift.get("name") or gift_id),
                        "buy_url": self._resolve_buy_url(gift_id, gift),
                    }
                )
            return out

    def _ton_usd_rate(self) -> float:
        return float(os.getenv("TON_USD_RATE", "4.2"))

    def _price_is_ton_native(self) -> bool:
        return self.verified_only and os.getenv("VERIFIED_SOURCE", "file").strip().lower() == "fragment"

    def _load_initial_dataset(self) -> dict:
        if self.verified_only:
            source = os.getenv("VERIFIED_SOURCE", "file").strip().lower()
            if source == "fragment":
                # Non-blocking start for Fragment: serve health/UI while data loads in background.
                return {"generated_at": "", "gifts": []}
            try:
                return load_verified_dataset_source()
            except Exception:
                return {"generated_at": "", "gifts": []}
        return load_dataset()

    def _start_verified_reload_loop(self) -> None:
        def loop() -> None:
            source = os.getenv("VERIFIED_SOURCE", "file").strip().lower()
            if source == "fragment":
                use_cache = os.getenv("FRAGMENT_BOOTSTRAP_CACHE", "true").strip().lower() in {"1", "true", "yes", "on"}
                cache_path = os.getenv("VERIFIED_DATA_FILE", "").strip() or None
                if use_cache:
                    try:
                        cached = load_verified_dataset(cache_path)
                        with self.lock:
                            self.dataset = cached
                            self.last_verified_refresh_at = time.strftime("%Y-%m-%d %H:%M:%S")
                            self.last_verified_refresh_error = ""
                    except Exception:
                        pass
            while True:
                try:
                    new_dataset = load_verified_dataset_source()
                    with self.lock:
                        self.dataset = new_dataset
                        self.realtime_tick_count += 1
                        self.last_tick_at = time.strftime("%Y-%m-%d %H:%M:%S")
                        self.last_verified_refresh_at = self.last_tick_at
                        self.last_verified_refresh_error = ""
                except Exception as e:
                    # Keep last known verified snapshot if source read failed.
                    with self.lock:
                        self.last_verified_refresh_error = f"verified refresh failed: {type(e).__name__}: {str(e)[:240]}"
                time.sleep(self.verified_refresh_sec)

        thread = threading.Thread(target=loop, daemon=True, name="verified-reloader")
        thread.start()

    def _start_realtime_loop(self) -> None:
        def loop() -> None:
            while True:
                time.sleep(self.realtime_interval_sec)
                with self.lock:
                    tick_realtime(self.dataset)
                    self.realtime_tick_count += 1
                    self.last_tick_at = time.strftime("%Y-%m-%d %H:%M:%S")

        thread = threading.Thread(target=loop, daemon=True, name="realtime-ticker")
        thread.start()


STATE = AppState()


class TelegramBridge:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.bot_token = os.getenv("TG_BOT_TOKEN", "").strip()
        self.default_chat_id = os.getenv("TG_CHAT_ID", "").strip()
        self.webhook_secret = os.getenv("TG_WEBHOOK_SECRET", "").strip()
        self.signal_interval_sec = int(os.getenv("BOT_SIGNAL_INTERVAL_SEC", "300"))
        self.news_interval_sec = int(os.getenv("BOT_NEWS_INTERVAL_SEC", "86400"))
        self.new_gifts_check_sec = int(os.getenv("BOT_NEW_GIFTS_CHECK_SEC", "120"))
        self.min_intensity = float(os.getenv("BOT_MIN_INTENSITY", "10"))
        self.min_price_delta_pct = float(os.getenv("BOT_MIN_PRICE_DELTA_PCT", "1.5"))
        self.min_change_delta = float(os.getenv("BOT_MIN_CHANGE_DELTA", "0.5"))
        self.min_zscore_delta = float(os.getenv("BOT_MIN_ZSCORE_DELTA", "0.4"))
        self.min_volume_trend_delta = float(os.getenv("BOT_MIN_VOLUME_TREND_DELTA", "5"))
        self.min_resend_hours = float(os.getenv("BOT_MIN_RESEND_HOURS", "12"))
        self.sent_cache: set[str] = set()
        self.last_sent_stats: dict[str, dict] = {}
        self.photo_cache: dict[str, str] = {}
        self.photo_cache_ts: dict[str, float] = {}
        self.known_gift_ids: set[str] = {x["gift_id"] for x in self.state.gifts_snapshot()}
        self.enabled = bool(self.bot_token)
        if self.enabled:
            self._start_boot_messages()
            self._start_signal_loop()
            self._start_new_gifts_loop()
            self._start_news_loop()

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}/{method}"

    def _http_post(self, method: str, data: dict[str, str]) -> dict:
        payload = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(self._api_url(method), data=payload, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw)
            if not parsed.get("ok", False):
                raise RuntimeError(f"telegram {method} failed: {parsed.get('description', 'unknown error')}")
            return parsed

    def _http_get_text(self, url: str, timeout: int = 15) -> str:
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "Mozilla/5.0 (compatible; GiftMarketZone/1.0)")
        req.add_header("Accept", "text/html,application/xhtml+xml")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def _extract_meta_image(self, html: str) -> str:
        meta_re = re.compile(r"<meta\s+([^>]+)>", re.I)
        attr_re = re.compile(r'([a-zA-Z_:.-]+)\s*=\s*"([^"]*)"')
        for m in meta_re.finditer(html):
            attrs = {k.lower(): v.strip() for k, v in attr_re.findall(m.group(1))}
            marker = (attrs.get("property") or attrs.get("name") or "").lower()
            if marker in {"og:image", "twitter:image"} and attrs.get("content"):
                return attrs["content"]
        return ""

    def _resolve_photo_url(self, row: dict) -> str:
        gift_id = str(row.get("gift_id") or "").strip()
        direct = str(row.get("photo_url") or "").strip()
        if direct:
            return direct

        now = time.time()
        cache_ttl_sec = 6 * 3600
        if gift_id in self.photo_cache and (now - self.photo_cache_ts.get(gift_id, 0)) < cache_ttl_sec:
            return self.photo_cache[gift_id]

        buy_url = str(row.get("buy_url") or "").strip()
        if not buy_url:
            self.photo_cache[gift_id] = ""
            self.photo_cache_ts[gift_id] = now
            return ""
        try:
            html = self._http_get_text(buy_url, timeout=12)
            found = self._extract_meta_image(html)
            self.photo_cache[gift_id] = found
            self.photo_cache_ts[gift_id] = now
            return found
        except Exception:
            self.photo_cache[gift_id] = ""
            self.photo_cache_ts[gift_id] = now
            return ""

    def send_message(self, chat_id: str, text: str, buy_url: str = "") -> None:
        if not self.enabled or not chat_id:
            return
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
        if buy_url:
            payload["reply_markup"] = json.dumps(
                {"inline_keyboard": [[{"text": "Купить на Fragment", "url": buy_url}]]},
                ensure_ascii=False,
            )
        self._http_post("sendMessage", payload)

    def send_photo(self, chat_id: str, photo_url: str, caption: str, buy_url: str = "") -> None:
        if not self.enabled or not chat_id or not photo_url:
            return
        payload = {
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": "HTML",
        }
        if buy_url:
            payload["reply_markup"] = json.dumps(
                {"inline_keyboard": [[{"text": "Купить на Fragment", "url": buy_url}]]},
                ensure_ascii=False,
            )
        self._http_post("sendPhoto", payload)

    def verify_secret(self, header_value: str | None) -> bool:
        if not self.webhook_secret:
            return True
        return (header_value or "").strip() == self.webhook_secret

    def _score(self, row: dict) -> float:
        change = row.get("change_7d")
        if change is None:
            change = row.get("change_1d")
        if change is None:
            change = row.get("change_6h", 0.0)
        return abs(float(change or 0)) + abs(row["zscore_30d"]) * 2 + abs(row["volume_trend_7_vs_30"]) / 2

    def _fmt_ton(self, value: float) -> str:
        text = f"{float(value):.4f}".rstrip("0").rstrip(".")
        return text or "0"

    def _fmt_pct(self, value: float | None) -> str:
        if value is None:
            return "—"
        return f"{value:+.2f}%"

    def _is_alertable(self, row: dict) -> bool:
        statuses = row.get("market_statuses") or {}
        latest_status = str(row.get("latest_status") or "").strip().lower()
        has_active = int(statuses.get("sale", 0)) > 0 or int(statuses.get("auction", 0)) > 0
        if latest_status == "sold" or not has_active:
            return False
        if row["signal"] in {"BUY", "SELL"}:
            return self._score(row) >= self.min_intensity
        if row["signal"] == "ANOMALY":
            return abs(row["zscore_30d"]) >= 2.2
        return False

    def _has_material_change(self, row: dict) -> bool:
        gid = str(row.get("gift_id") or "")
        if not gid:
            return False
        now = time.time()
        prev = self.last_sent_stats.get(gid)
        if not prev:
            return True

        last_ts = float(prev.get("ts") or 0)
        if self.min_resend_hours > 0 and (now - last_ts) < self.min_resend_hours * 3600:
            # Too soon to resend without strong change.
            pass

        def _get_num(val, default=0.0):
            try:
                return float(val)
            except Exception:
                return default

        price = _get_num(row.get("price_ton", row.get("price")))
        prev_price = _get_num(prev.get("price"))
        price_delta_pct = ((price - prev_price) / prev_price * 100) if prev_price else 0.0

        change_1d = _get_num(row.get("change_1d"))
        prev_change_1d = _get_num(prev.get("change_1d"))
        zscore = _get_num(row.get("zscore_30d"))
        prev_zscore = _get_num(prev.get("zscore_30d"))
        vol_trend = _get_num(row.get("volume_trend_7_vs_30"))
        prev_vol_trend = _get_num(prev.get("volume_trend_7_vs_30"))

        signal_changed = str(row.get("signal")) != str(prev.get("signal"))
        price_changed = abs(price_delta_pct) >= self.min_price_delta_pct
        change_changed = abs(change_1d - prev_change_1d) >= self.min_change_delta
        zscore_changed = abs(zscore - prev_zscore) >= self.min_zscore_delta
        vol_changed = abs(vol_trend - prev_vol_trend) >= self.min_volume_trend_delta

        return signal_changed or price_changed or change_changed or zscore_changed or vol_changed

    def _remember_sent(self, row: dict) -> None:
        gid = str(row.get("gift_id") or "")
        if not gid:
            return
        self.last_sent_stats[gid] = {
            "ts": time.time(),
            "price": float(row.get("price_ton", row.get("price", 0)) or 0),
            "change_1d": row.get("change_1d") or 0,
            "zscore_30d": row.get("zscore_30d") or 0,
            "volume_trend_7_vs_30": row.get("volume_trend_7_vs_30") or 0,
            "signal": row.get("signal"),
        }

    def _format_alert(self, row: dict) -> str:
        price_ton = row.get("price_ton")
        if price_ton is None:
            price_ton = float(row.get("price", 0))
        signal = escape(str(row.get("signal", "HOLD")))
        name = escape(str(row.get("name", "")))
        commentary = escape(str(row.get("commentary", "")))
        gift_id = escape(str(row.get("gift_id", "")))
        return (
            f"#аналитика\n"
            f"<b>{signal}</b> | <b>{name}</b>\n"
            f"ID: <code>{gift_id}</code>\n"
            f"Цена: <b>{self._fmt_ton(float(price_ton))} TON</b>\n"
            f"Изм. 1д: {self._fmt_pct(row.get('change_1d'))} | 7д: {self._fmt_pct(row.get('change_7d'))} | 30д: {self._fmt_pct(row.get('change_30d'))}\n"
            f"D/S: {row['demand_supply_ratio']:.2f} | Объем 7/30: {row['volume_trend_7_vs_30']:+.2f}% | z: {row['zscore_30d']:+.2f}\n"
            f"{commentary}"
        )

    def _status_text(self) -> str:
        summary = self.state.summary()
        avg_7d = summary.get("avg_change_7d")
        avg_30d = summary.get("avg_change_30d")
        def _fmt(v: float | None) -> str:
            if v is None:
                return "—"
            return f"{v:+.2f}%"
        return (
            "#аналитика\n"
            "Статус рынка:\n"
            f"- Состояние: {summary.get('market_state')}\n"
            f"- Средний 7д: {_fmt(avg_7d)}\n"
            f"- BUY: {summary.get('buy_signals')} | SELL: {summary.get('sell_signals')} | Аномалии: {summary.get('anomalies')}"
        )

    def _signals_text(self) -> str:
        rows = [r for r in self.state.signals() if self._is_alertable(r)][:5]
        if not rows:
            return "#аналитика\nСигналы: значимых сигналов сейчас нет."
        lines = ["#аналитика", "Топ сигналы:"]
        for r in rows:
            lines.append(f"- [{r['signal']}] {r['name']} {self._fmt_pct(r.get('change_7d'))} (7д)")
        return "\n".join(lines)

    def handle_update(self, update: dict) -> None:
        msg = update.get("message") or update.get("channel_post") or {}
        text = str(msg.get("text") or "").strip()
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id") or self.default_chat_id)
        if not text or not chat_id:
            return
        cmd = text.split()[0].lower()
        if cmd in {"/start", "/help"}:
            self.send_message(chat_id, "Команды:\n/status — статус рынка\n/signals — топ сигналов")
            return
        if cmd == "/status":
            self.send_message(chat_id, self._status_text())
            return
        if cmd == "/signals":
            self.send_message(chat_id, self._signals_text())
            return

    def signal_cycle(self) -> None:
        if not self.default_chat_id:
            return
        rows = [r for r in self.state.signals() if self._is_alertable(r) and self._has_material_change(r)]
        now_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stale = [k for k in self.sent_cache if not k.startswith(now_tag + ":")]
        for key in stale:
            self.sent_cache.remove(key)
        for row in rows[:8]:
            key = f"{now_tag}:{row['gift_id']}:{row['signal']}"
            if key in self.sent_cache:
                continue
            text = self._format_alert(row)
            photo_url = self._resolve_photo_url(row)
            buy_url = str(row.get("buy_url") or "").strip()
            if photo_url:
                try:
                    self.send_photo(self.default_chat_id, photo_url, text, buy_url)
                except Exception:
                    self.send_message(self.default_chat_id, text, buy_url=buy_url)
            else:
                self.send_message(self.default_chat_id, text, buy_url=buy_url)
            self._remember_sent(row)
            self.sent_cache.add(key)

    def _new_gifts_cycle(self) -> None:
        if not self.default_chat_id:
            return
        snapshot = self.state.gifts_snapshot()
        screener = self.state.screener()
        active_ids = {
            r.get("gift_id")
            for r in screener
            if int((r.get("market_statuses") or {}).get("sale", 0)) > 0
            or int((r.get("market_statuses") or {}).get("auction", 0)) > 0
            and str(r.get("latest_status") or "").strip().lower() != "sold"
        }
        current_ids = {x["gift_id"] for x in snapshot if x.get("gift_id") in active_ids}
        new_ids = sorted(current_ids - self.known_gift_ids)
        if not new_ids:
            return
        by_id = {x["gift_id"]: x for x in snapshot}
        for gift_id in new_ids:
            if gift_id not in active_ids:
                continue
            item = by_id.get(gift_id) or {"gift_id": gift_id, "name": gift_id, "buy_url": ""}
            buy_url = str(item.get("buy_url") or "").strip()
            text = f"#новый\nПоявился новый подарок: <b>{escape(str(item.get('name') or gift_id))}</b>\nID: <code>{escape(gift_id)}</code>"
            self.send_message(self.default_chat_id, text, buy_url=buy_url)
        self.known_gift_ids = current_ids

    def _news_text(self) -> str:
        summary = self.state.summary()
        rows = self.state.screener()
        if not rows:
            return "#новости\nДанных по рынку подарков пока недостаточно."

        gainers = sorted(rows, key=lambda x: x.get("change_1d", 0), reverse=True)[:3]
        losers = sorted(rows, key=lambda x: x.get("change_1d", 0))[:3]
        signals = self.state.signals()
        hot = [r for r in signals if r.get("signal") in {"BUY", "SELL", "ANOMALY"}][:3]

        lines = [
            "#новости",
            "Суточная сводка рынка подарков:",
            f"Состояние: {summary.get('market_state')} | Ср. 7д: {self._fmt_pct(summary.get('avg_change_7d'))}",
            f"BUY: {summary.get('buy_signals', 0)} | SELL: {summary.get('sell_signals', 0)} | Аномалии: {summary.get('anomalies', 0)}",
            "",
            "Лидеры роста (1д):",
        ]
        for r in gainers:
            lines.append(f"• {r.get('name')} {r.get('change_1d', 0):+.2f}%")

        lines.append("")
        lines.append("Лидеры падения (1д):")
        for r in losers:
            lines.append(f"• {r.get('name')} {r.get('change_1d', 0):+.2f}%")

        if hot:
            lines.append("")
            lines.append("Ключевые сигналы:")
            for r in hot:
                lines.append(f"• [{r.get('signal')}] {r.get('name')} 7д: {r.get('change_7d', 0):+.2f}%")

        lines.append("")
        lines.append("Детали: <a href=\"https://telegram-gifts-market.onrender.com\">открыть GiftMarketZone</a>")
        return "\n".join(lines)

    def _start_signal_loop(self) -> None:
        def loop() -> None:
            while True:
                try:
                    self.signal_cycle()
                except Exception:
                    pass
                time.sleep(self.signal_interval_sec)

        thread = threading.Thread(target=loop, daemon=True, name="telegram-signal-loop")
        thread.start()

    def _start_new_gifts_loop(self) -> None:
        def loop() -> None:
            while True:
                try:
                    self._new_gifts_cycle()
                except Exception:
                    pass
                time.sleep(self.new_gifts_check_sec)

        thread = threading.Thread(target=loop, daemon=True, name="telegram-new-gifts-loop")
        thread.start()

    def _start_news_loop(self) -> None:
        def loop() -> None:
            while True:
                time.sleep(self.news_interval_sec)
                try:
                    if self.default_chat_id:
                        self.send_message(self.default_chat_id, self._news_text())
                except Exception:
                    pass

        thread = threading.Thread(target=loop, daemon=True, name="telegram-news-loop")
        thread.start()

    def _start_boot_messages(self) -> None:
        def loop() -> None:
            time.sleep(12)
            if not self.default_chat_id:
                return
            try:
                self.send_message(self.default_chat_id, self._status_text())
            except Exception:
                pass
            try:
                snapshot = self.state.gifts_snapshot()
                if snapshot:
                    item = snapshot[0]
                    buy_url = str(item.get("buy_url") or "").strip()
                    text = (
                        f"#новый\n"
                        f"Появился новый подарок: <b>{escape(str(item.get('name') or item.get('gift_id') or 'Gift'))}</b>\n"
                        f"ID: <code>{escape(str(item.get('gift_id') or ''))}</code>"
                    )
                    self.send_message(self.default_chat_id, text, buy_url=buy_url)
            except Exception:
                pass

        thread = threading.Thread(target=loop, daemon=True, name="telegram-boot-messages")
        thread.start()


TG_BRIDGE = TelegramBridge(STATE)
FAVORITES = FavoritesStore(FAVORITES_STORE_FILE)


def _gift_profile(gift_id: str, price_usd: float, signal: str) -> dict:
    if gift_id in VERIFIED_GIFT_OVERRIDES:
        return VERIFIED_GIFT_OVERRIDES[gift_id]

    models = ["Genesis", "Aurora", "Nebula", "Quantum", "Legacy", "Pulse", "Nova", "Elite"]
    patterns = ["Fractal", "Matrix", "Neon Weave", "Crystal Grid", "Flame Arc", "Pixel Bloom", "Wave Mesh"]
    backgrounds = ["Midnight", "Sunset", "Aurora Sky", "Obsidian", "Pearl Mist", "Deep Ocean", "Violet Dust"]

    seed = sum((i + 1) * ord(ch) for i, ch in enumerate(gift_id))
    model = models[seed % len(models)]
    pattern = patterns[(seed // 3) % len(patterns)]
    background = backgrounds[(seed // 5) % len(backgrounds)]

    total_supply = 1500 + (seed % 5000)
    issued = max(1, int(total_supply * (0.22 + (seed % 65) / 100.0)))
    if issued > total_supply:
        issued = total_supply

    scarcity = (1 - issued / total_supply) * 100
    premium = 14 if signal == "BUY" else -8 if signal == "SELL" else 6 if signal == "ANOMALY" else 0
    value_score = max(1, min(100, int(35 + scarcity * 0.7 + min(price_usd, 200) * 0.12 + premium)))

    return {
        "model": model,
        "model_share": None,
        "pattern": pattern,
        "pattern_share": None,
        "background": background,
        "background_share": None,
        "issued": issued,
        "total_supply": total_supply,
        "value_rub_estimate": None,
        "value_score": value_score,
        "source_note": "Synthetic fallback",
    }


def _json_response(
    handler: BaseHTTPRequestHandler,
    payload: dict,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    if headers:
        for k, v in headers.items():
            handler.send_header(k, v)
    pending_cookie = getattr(handler, "_pending_set_cookie", "")
    if pending_cookie:
        handler.send_header("Set-Cookie", pending_cookie)
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        # Client closed connection before reading response body.
        return


def _error(handler: BaseHTTPRequestHandler, message: str, code: int = 400) -> None:
    _json_response(handler, {"ok": False, "error": message}, status=code)


def _safe_send_error(handler: BaseHTTPRequestHandler, code: int) -> None:
    try:
        handler.send_error(code)
    except (BrokenPipeError, ConnectionResetError):
        # Client closed connection before reading error response.
        return


def _serve_file(handler: BaseHTTPRequestHandler, rel_path: str) -> None:
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

    content = target.read_bytes()
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(content)))
    pending_cookie = getattr(handler, "_pending_set_cookie", "")
    if pending_cookie:
        handler.send_header("Set-Cookie", pending_cookie)
    handler.end_headers()
    try:
        handler.wfile.write(content)
    except (BrokenPipeError, ConnectionResetError):
        # Client closed connection before reading response body.
        return


def _extract_user_id(handler: BaseHTTPRequestHandler) -> str:
    raw = handler.headers.get("Cookie", "")
    if raw:
        try:
            cookie = SimpleCookie()
            cookie.load(raw)
            value = cookie.get("gmz_uid")
            if value:
                uid = str(value.value).strip()
                if uid and len(uid) <= 128 and all(ch.isalnum() or ch in {"_", "-"} for ch in uid):
                    return uid
        except Exception:
            pass
    return ""


def _ensure_user_id(handler: BaseHTTPRequestHandler) -> str:
    uid = _extract_user_id(handler)
    if uid:
        return uid
    uid = secrets.token_urlsafe(24).replace("=", "")
    handler._pending_set_cookie = f"gmz_uid={uid}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax"
    return uid


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            _serve_file(self, "index.html")
            return
        if path.startswith("/assets/"):
            _serve_file(self, path.replace("/assets/", ""))
            return

        if path == "/api/market/summary":
            summary = STATE.summary()
            _json_response(self, {"ok": True, "data": summary})
            return

        if path == "/api/market/chart":
            params = parse_qs(parsed.query)
            gift_id = (params.get("gift_id") or [None])[0]
            if not gift_id:
                _error(self, "gift_id is required")
                return

            chart = STATE.chart(gift_id)
            if not chart:
                _error(self, f"gift_id '{gift_id}' not found", code=404)
                return

            _json_response(self, {"ok": True, "data": chart})
            return
        if path == "/api/market/gift-details":
            params = parse_qs(parsed.query)
            gift_id = (params.get("gift_id") or [None])[0]
            if not gift_id:
                _error(self, "gift_id is required")
                return
            details = STATE.details(gift_id)
            if not details:
                _error(self, f"gift_id '{gift_id}' not found", code=404)
                return
            _json_response(self, {"ok": True, "data": details})
            return

        if path == "/api/market/screener":
            params = parse_qs(parsed.query)
            def _multi(name: str) -> set[str]:
                values: set[str] = set()
                for raw in (params.get(name) or []):
                    for piece in str(raw).split(","):
                        v = piece.strip().lower()
                        if v:
                            values.add(v)
                return values

            sort_by = (params.get("sort_by") or ["change_7d"])[0]
            order = (params.get("order") or ["desc"])[0]
            signal_filter = (params.get("signal") or [""])[0].upper().strip()
            group_filter = (params.get("group") or [""])[0].strip().lower()
            collection_filter = (params.get("collection") or [""])[0].strip().lower()
            model_filters = _multi("model")
            backdrop_filters = _multi("backdrop")
            symbol_filters = _multi("symbol")
            market_filter = (params.get("market") or [""])[0].strip().lower()
            min_ratio_raw = (params.get("min_ratio") or [""])[0].strip()

            rows = STATE.screener()

            if signal_filter:
                rows = [r for r in rows if r["signal"] == signal_filter]
            if group_filter:
                rows = [r for r in rows if str(r.get("group", "")).lower() == group_filter]
            if collection_filter:
                rows = [r for r in rows if str(r.get("collection", "")).lower() == collection_filter]
            if model_filters:
                rows = [r for r in rows if str(r.get("model", "")).lower() in model_filters]
            if backdrop_filters:
                rows = [r for r in rows if str(r.get("backdrop", "")).lower() in backdrop_filters]
            if symbol_filters:
                rows = [r for r in rows if str(r.get("symbol", "")).lower() in symbol_filters]
            if market_filter:
                rows = [
                    r for r in rows
                    if int((r.get("market_statuses") or {}).get(market_filter, 0)) > 0
                ]

            if min_ratio_raw:
                try:
                    min_ratio = float(min_ratio_raw)
                except ValueError:
                    _error(self, "min_ratio must be a number")
                    return
                rows = [r for r in rows if r["demand_supply_ratio"] >= min_ratio]

            if not rows:
                _json_response(self, {"ok": True, "data": []})
                return

            if sort_by not in rows[0]:
                _error(self, f"invalid sort_by '{sort_by}'")
                return

            reverse = order.lower() != "asc"
            rows = sorted(rows, key=lambda x: x[sort_by], reverse=reverse)
            _json_response(self, {"ok": True, "data": rows})
            return
        if path == "/api/market/filters":
            _json_response(self, {"ok": True, "data": STATE.filters()})
            return

        if path == "/api/signals/latest":
            top = STATE.signals()[:10]
            _json_response(self, {"ok": True, "data": top})
            return
        if path == "/healthz":
            _json_response(self, {"ok": True, "service": "telegram-gifts-market", "status": "healthy"})
            return
        if path == "/api/market/realtime-status":
            _json_response(self, {"ok": True, "data": STATE.status()})
            return
        if path == "/api/user/favorites":
            user_id = _ensure_user_id(self)
            gift_ids = FAVORITES.get(user_id)
            _json_response(self, {"ok": True, "data": {"gift_ids": gift_ids}})
            return

        _serve_file(self, path.lstrip("/"))

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/telegram/webhook":
            if not TG_BRIDGE.enabled:
                _error(self, "telegram bot disabled", code=503)
                return
            header_secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if not TG_BRIDGE.verify_secret(header_secret):
                _error(self, "invalid webhook secret", code=403)
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                _error(self, "invalid json", code=400)
                return
            TG_BRIDGE.handle_update(payload)
            _json_response(self, {"ok": True})
            return

        if path == "/api/admin/refresh":
            STATE.refresh()
            _json_response(self, {"ok": True, "message": "dataset refreshed", "generated_at": STATE.dataset.get("generated_at")})
            return

        if path in {"/api/user/favorites/toggle", "/api/user/favorites/set"}:
            user_id = _ensure_user_id(self)
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                _error(self, "invalid json", code=400)
                return
            gift_id = str(payload.get("gift_id") or "").strip()
            if not gift_id:
                _error(self, "gift_id is required", code=400)
                return
            if path.endswith("/toggle"):
                gift_ids, active = FAVORITES.toggle(user_id, gift_id)
            else:
                gift_ids = FAVORITES.set(user_id, [gift_id])
                active = True
            _json_response(self, {"ok": True, "data": {"gift_ids": gift_ids, "gift_id": gift_id, "active": active}})
            return

        if path == "/api/user/favorites/remove":
            user_id = _ensure_user_id(self)
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                _error(self, "invalid json", code=400)
                return
            gift_id = str(payload.get("gift_id") or "").strip()
            if not gift_id:
                _error(self, "gift_id is required", code=400)
                return
            current = FAVORITES.get(user_id)
            next_ids = [x for x in current if x != gift_id]
            FAVORITES.set(user_id, next_ids)
            _json_response(self, {"ok": True, "data": {"gift_ids": next_ids, "gift_id": gift_id, "active": False}})
            return

        _error(self, "not found", code=404)

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

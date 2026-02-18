from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
from urllib.parse import parse_qs, urlparse

from analytics import build_chart_series, build_market_summary, get_ranked_signals
from market_data import load_dataset, load_verified_dataset, load_verified_dataset_source, refresh_dataset, tick_realtime

ROOT = Path(__file__).parent
STATIC_DIR = ROOT / "static"
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
        with self.lock:
            if self.verified_only:
                self.dataset = load_verified_dataset_source()
            else:
                self.dataset = refresh_dataset()
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

    def _ton_usd_rate(self) -> float:
        return float(os.getenv("TON_USD_RATE", "4.2"))

    def _price_is_ton_native(self) -> bool:
        return self.verified_only and os.getenv("VERIFIED_SOURCE", "file").strip().lower() == "fragment"

    def _load_initial_dataset(self) -> dict:
        if self.verified_only and os.getenv("VERIFIED_SOURCE", "file").strip().lower() == "fragment":
            use_cache = os.getenv("FRAGMENT_BOOTSTRAP_CACHE", "true").strip().lower() in {"1", "true", "yes", "on"}
            cache_path = os.getenv("VERIFIED_DATA_FILE", "").strip() or None
            if use_cache:
                try:
                    return load_verified_dataset(cache_path)
                except Exception:
                    pass
        if self.verified_only:
            return load_verified_dataset_source()
        return load_dataset()

    def _start_verified_reload_loop(self) -> None:
        def loop() -> None:
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
        self.min_intensity = float(os.getenv("BOT_MIN_INTENSITY", "10"))
        self.sent_cache: set[str] = set()
        self.enabled = bool(self.bot_token)
        if self.enabled:
            self._start_signal_loop()

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

    def send_message(self, chat_id: str, text: str) -> None:
        if not self.enabled or not chat_id:
            return
        self._http_post(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            },
        )

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
        return abs(row["change_7d"]) + abs(row["zscore_30d"]) * 2 + abs(row["volume_trend_7_vs_30"]) / 2

    def _is_alertable(self, row: dict) -> bool:
        if row["signal"] in {"BUY", "SELL"}:
            return self._score(row) >= self.min_intensity
        if row["signal"] == "ANOMALY":
            return abs(row["zscore_30d"]) >= 2.2
        return False

    def _format_alert(self, row: dict) -> str:
        price_ton = row.get("price_ton")
        if price_ton is None:
            price_ton = float(row.get("price", 0))
        signal = escape(str(row.get("signal", "HOLD")))
        name = escape(str(row.get("name", "")))
        commentary = escape(str(row.get("commentary", "")))
        gift_id = escape(str(row.get("gift_id", "")))
        return (
            f"<b>{signal}</b> | <b>{name}</b>\n"
            f"ID: <code>{gift_id}</code>\n"
            f"Цена: <b>{float(price_ton):.4f} TON</b>\n"
            f"Изм. 1д: {row['change_1d']:+.2f}% | 7д: {row['change_7d']:+.2f}% | 30д: {row['change_30d']:+.2f}%\n"
            f"D/S: {row['demand_supply_ratio']:.2f} | Объем 7/30: {row['volume_trend_7_vs_30']:+.2f}% | z: {row['zscore_30d']:+.2f}\n"
            f"{commentary}"
        )

    def _status_text(self) -> str:
        summary = self.state.summary()
        return (
            "Статус рынка:\n"
            f"- Состояние: {summary.get('market_state')}\n"
            f"- Средний 7д: {summary.get('avg_change_7d'):+.2f}%\n"
            f"- BUY: {summary.get('buy_signals')} | SELL: {summary.get('sell_signals')} | Аномалии: {summary.get('anomalies')}"
        )

    def _signals_text(self) -> str:
        rows = [r for r in self.state.signals() if self._is_alertable(r)][:5]
        if not rows:
            return "Сигналы: значимых сигналов сейчас нет."
        lines = ["Топ сигналы:"]
        for r in rows:
            lines.append(f"- [{r['signal']}] {r['name']} {r['change_7d']:+.2f}% (7д)")
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
        rows = [r for r in self.state.signals() if self._is_alertable(r)]
        now_tag = datetime.utcnow().strftime("%Y-%m-%d")
        stale = [k for k in self.sent_cache if not k.startswith(now_tag + ":")]
        for key in stale:
            self.sent_cache.remove(key)
        for row in rows[:8]:
            key = f"{now_tag}:{row['gift_id']}:{row['signal']}"
            if key in self.sent_cache:
                continue
            text = self._format_alert(row)
            photo_url = str(row.get("photo_url") or "").strip()
            buy_url = str(row.get("buy_url") or "").strip()
            if buy_url:
                text = f"{text}\n<a href=\"{escape(buy_url, quote=True)}\">Купить</a>"
            if photo_url:
                try:
                    self.send_photo(self.default_chat_id, photo_url, text, buy_url)
                except Exception:
                    self.send_message(self.default_chat_id, text)
            else:
                self.send_message(self.default_chat_id, text)
            self.sent_cache.add(key)

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


TG_BRIDGE = TelegramBridge(STATE)


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


def _json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _error(handler: BaseHTTPRequestHandler, message: str, code: int = 400) -> None:
    _json_response(handler, {"ok": False, "error": message}, status=code)


def _serve_file(handler: BaseHTTPRequestHandler, rel_path: str) -> None:
    rel = rel_path.lstrip("/")
    target = (STATIC_DIR / rel).resolve()

    if not str(target).startswith(str(STATIC_DIR.resolve())):
        handler.send_error(HTTPStatus.FORBIDDEN)
        return

    if not target.exists() or not target.is_file():
        handler.send_error(HTTPStatus.NOT_FOUND)
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
    handler.end_headers()
    handler.wfile.write(content)


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

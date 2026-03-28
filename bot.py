from __future__ import annotations

import json
import os
import time
import html
import urllib.error
import urllib.parse
import urllib.request
import fcntl
from datetime import datetime
from datetime import timezone
from datetime import timedelta
from pathlib import Path
from typing import Dict

from telegram_delivery import MessageRenderer, _load_json

BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TG_CHAT_ID", "").strip()
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8080").strip()
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "").strip()
HTTP_TIMEOUT_SEC = int(os.getenv("BOT_HTTP_TIMEOUT_SEC", "90"))
HTTP_RETRIES = int(os.getenv("BOT_HTTP_RETRIES", "3"))
HTTP_BACKOFF_SEC = float(os.getenv("BOT_HTTP_BACKOFF_SEC", "1.5"))
API_WARMUP_MAX_SEC = int(os.getenv("BOT_API_WARMUP_MAX_SEC", "120"))
POLL_INTERVAL_SEC = int(os.getenv("BOT_POLL_INTERVAL", "60"))
MIN_CONFIDENCE = int(os.getenv("BOT_MIN_CONFIDENCE", "51"))
DYNAMICS_PCT = float(os.getenv("BOT_DYNAMICS_PCT", "4.3"))
CACHE_FILE = os.getenv("BOT_CACHE_FILE", "data/bot_cache.json")
LOCK_FILE = os.getenv("BOT_LOCK_FILE", "data/bot_sender.lock")
MIN_REPEAT_SEC = int(os.getenv("BOT_MIN_REPEAT_SEC", "3600"))
SCORE_DELTA_MIN = float(os.getenv("BOT_SCORE_DELTA_MIN", "4.3"))
CONF_DELTA_MIN = float(os.getenv("BOT_CONF_DELTA_MIN", "6.9"))
CHANGE24H_DELTA_MIN = float(os.getenv("BOT_CHANGE24H_DELTA_MIN", "6.9"))
MAX_MESSAGES_PER_CYCLE = int(os.getenv("BOT_MAX_MESSAGES_PER_CYCLE", "8"))
DEBUG = os.getenv("BOT_DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}
FORCE_SEND_TOP1 = os.getenv("BOT_FORCE_SEND_TOP1", "false").strip().lower() in {"1", "true", "yes", "on"}
COMMANDS_ENABLED = os.getenv("BOT_COMMANDS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
UPDATES_TIMEOUT_SEC = int(os.getenv("BOT_UPDATES_TIMEOUT_SEC", "1"))
SIGNAL_COMMAND_WINDOW_SEC = int(os.getenv("BOT_SIGNAL_COMMAND_WINDOW_SEC", "3600"))
SIGNAL_COMMAND_COOLDOWN_SEC = int(os.getenv("BOT_SIGNAL_COMMAND_COOLDOWN_SEC", "3600"))
MSK_TZ = timezone(timedelta(hours=3))
ROOT = Path(__file__).resolve().parent
_RECENT_SIGNAL_FETCHER = None
_RENDERER: MessageRenderer | None = None


def _renderer() -> MessageRenderer:
    global _RENDERER
    if _RENDERER is not None:
        return _RENDERER
    profile = _load_json(ROOT / "config" / "telegram" / "telegram_message_profile_PRO_v1.json", {})
    rules_text = (ROOT / "config" / "telegram" / "telegram_message_templater_rules_PRO_v1.txt").read_text(encoding="utf-8")
    signal_profiles = _load_json(ROOT / "config" / "signals" / "signal_profiles_by_regime.json", {})
    edge_weights = _load_json(ROOT / "config" / "signals" / "edgerank_weights_by_regime.json", {})
    _RENDERER = MessageRenderer(profile=profile, rules_text=rules_text, signal_profiles=signal_profiles, edgerank_weights=edge_weights)
    return _RENDERER


def set_recent_signal_fetcher(func) -> None:
    global _RECENT_SIGNAL_FETCHER
    _RECENT_SIGNAL_FETCHER = func


def _to_msk_text(ts_iso: str | None) -> str:
    if not ts_iso:
        return "-"
    raw = str(ts_iso).strip()
    if not raw:
        return "-"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(MSK_TZ).strftime("%Y-%m-%d %H:%M:%S МСК")
    except Exception:
        return raw


def _now_msk_text() -> str:
    return datetime.now(MSK_TZ).strftime("%Y-%m-%d %H:%M:%S МСК")


def _norm_text(value: str) -> str:
    raw = str(value or "").strip().lower()
    out = []
    prev_space = False
    for ch in raw:
        if ch.isalnum():
            out.append(ch)
            prev_space = False
        else:
            if not prev_space:
                out.append(" ")
                prev_space = True
    return " ".join("".join(out).split())


def _pick_best_match(query: str, items: list[dict], name_key: str, id_key: str) -> dict | None:
    q = _norm_text(query)
    if not q:
        return None
    exact = None
    contains = None
    for item in items:
        name = str(item.get(name_key) or "")
        item_id = str(item.get(id_key) or "")
        name_n = _norm_text(name)
        id_n = _norm_text(item_id)
        if q == name_n or q == id_n:
            exact = item
            break
        if q in name_n or q in id_n:
            contains = contains or item
    return exact or contains


def _signal_item_from_variant(variant: Dict) -> Dict:
    reco = variant.get("reco") or {}
    metrics = variant.get("metrics") or {}
    return {
        "variant_id": variant.get("variant_id"),
        "base_id": variant.get("base_id"),
        "base_name": variant.get("base_name") or variant.get("group") or variant.get("base_id"),
        "title": variant.get("title"),
        "preview_url": variant.get("preview_url"),
        "traits": variant.get("traits") or {},
        "action": reco.get("action"),
        "reco_score": reco.get("reco_score"),
        "confidence": reco.get("confidence"),
        "forecast": reco.get("forecast"),
        "reasons": reco.get("reasons"),
        "risks": reco.get("risks"),
        "summary": reco.get("summary"),
        "floor_change_pct_24h": metrics.get("floor_change_pct_24h"),
        "last_sent_ts": int(time.time()),
    }


def _find_variant_by_gift_input(raw_text: str) -> Dict | None:
    parts = [p.strip() for p in str(raw_text or "").split("/")]
    while parts and not parts[-1]:
        parts.pop()
    if len(parts) < 2:
        return None
    collection_q = parts[0]
    model_q = parts[1]
    background_q = parts[2] if len(parts) >= 3 else ""
    pattern_q = parts[3] if len(parts) >= 4 else ""
    if not collection_q or not model_q:
        return None

    bases = _http_get(f"{API_BASE_URL}/api/bases").get("items") or []
    base = _pick_best_match(collection_q, bases, "name", "base_id")
    if not base:
        return None
    base_id = str(base.get("base_id") or "").strip()
    if not base_id:
        return None

    models_resp = _http_get(f"{API_BASE_URL}/api/bases/{urllib.parse.quote(base_id, safe='')}/dimensions?type=model&period=24h")
    models = [{"dim_id": x.get("dim_id"), "name": x.get("name")} for x in (models_resp.get("items") or [])]
    model = _pick_best_match(model_q, models, "name", "dim_id")
    if not model or not str(model.get("dim_id") or "").strip():
        return None

    bg_id = ""
    if background_q:
        bgs_resp = _http_get(f"{API_BASE_URL}/api/bases/{urllib.parse.quote(base_id, safe='')}/dimensions?type=background&period=24h")
        bgs = [{"dim_id": x.get("dim_id"), "name": x.get("name")} for x in (bgs_resp.get("items") or [])]
        bg = _pick_best_match(background_q, bgs, "name", "dim_id")
        if not bg or not str(bg.get("dim_id") or "").strip():
            return None
        bg_id = str(bg.get("dim_id") or "").strip()

    pattern_id = ""
    if pattern_q:
        patterns_resp = _http_get(f"{API_BASE_URL}/api/bases/{urllib.parse.quote(base_id, safe='')}/dimensions?type=pattern&period=24h")
        patterns = [{"dim_id": x.get("dim_id"), "name": x.get("name")} for x in (patterns_resp.get("items") or [])]
        pattern = _pick_best_match(pattern_q, patterns, "name", "dim_id")
        if not pattern or not str(pattern.get("dim_id") or "").strip():
            return None
        pattern_id = str(pattern.get("dim_id") or "").strip()

    params = [("page_size", "300"), ("page", "1"), ("ai", "1"), ("model_id", str(model.get("dim_id")))]
    if bg_id:
        params.append(("background_id", bg_id))
    if pattern_id:
        params.append(("pattern_id", pattern_id))
    query = urllib.parse.urlencode(params, doseq=True)
    url = f"{API_BASE_URL}/api/bases/{urllib.parse.quote(base_id, safe='')}/variants?{query}"
    variants = _http_get(url).get("items") or []
    if not variants:
        return None
    return variants[0]


def _http_get(url: str) -> Dict:
    last_error = None
    for attempt in range(1, max(1, HTTP_RETRIES) + 1):
        try:
            req = urllib.request.Request(url, method="GET")
            req.add_header("Accept", "application/json")
            if API_AUTH_TOKEN:
                req.add_header("Authorization", f"Bearer {API_AUTH_TOKEN}")
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last_error = e
            if isinstance(e, urllib.error.HTTPError) and e.code in {400, 401, 403, 404}:
                break
            if attempt >= max(1, HTTP_RETRIES):
                break
            time.sleep(HTTP_BACKOFF_SEC * attempt)
    raise last_error


def _http_get_text(url: str) -> str:
    last_error = None
    for attempt in range(1, max(1, HTTP_RETRIES) + 1):
        try:
            req = urllib.request.Request(url, method="GET")
            req.add_header("Accept", "application/json")
            if API_AUTH_TOKEN:
                req.add_header("Authorization", f"Bearer {API_AUTH_TOKEN}")
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as response:
                return response.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001
            last_error = e
            if isinstance(e, urllib.error.HTTPError) and e.code in {400, 401, 403, 404}:
                break
            if attempt >= max(1, HTTP_RETRIES):
                break
            time.sleep(HTTP_BACKOFF_SEC * attempt)
    raise last_error


def _http_post(url: str, data: Dict[str, str]) -> Dict:
    last_error = None
    for attempt in range(1, max(1, HTTP_RETRIES) + 1):
        try:
            payload = urllib.parse.urlencode(data).encode("utf-8")
            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last_error = e
            if attempt >= max(1, HTTP_RETRIES):
                break
            time.sleep(HTTP_BACKOFF_SEC * attempt)
    raise last_error


def send_message(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Set TG_BOT_TOKEN and TG_CHAT_ID env vars")
    send_message_to(CHAT_ID, text)


def send_message_to(chat_id: str | int, text: str, parse_mode: str | None = None) -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Set TG_BOT_TOKEN env var")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": str(chat_id), "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    _http_post(url, payload)


def _get_updates(offset: int | None = None, timeout_sec: int = 0) -> Dict:
    if not BOT_TOKEN:
        return {"ok": False, "result": []}
    params = {"timeout": str(max(0, timeout_sec))}
    if offset is not None:
        params["offset"] = str(offset)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?{urllib.parse.urlencode(params)}"
    try:
        return _http_get(url)
    except urllib.error.HTTPError as e:
        # Telegram returns 409 when getUpdates is used while a webhook is active.
        if e.code == 409:
            _http_get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook?drop_pending_updates=false")
            return _http_get(url)
        raise


def _format_market_status(overview: Dict) -> str:
    return "\n".join(
        [
            "<b>GiftMarketZone: Статус рынка :</b>",
            f"Состояние: <b>{overview.get('market_state', '-')}</b>",
            f"Подарков: {overview.get('gifts_count', 0)}",
            f"Коллекций: {overview.get('base_count', 0)}",
            f"Моделей: {overview.get('model_count', 0)}",
            f"Мин цена: {overview.get('floor_ton_min', '-')} TON",
            f"Медиана: {overview.get('floor_ton_median', '-')} TON",
            f"Всего в продаже: {overview.get('total_for_sale', overview.get('active_listings', 0))}",
            f"Всего продано: {overview.get('total_sold', 0)}",
            f"Сигналы BUY/SELL: {overview.get('buy_signals', 0)}/{overview.get('sell_signals', 0)}",
            f"Обновлено: {_to_msk_text(overview.get('updated_at'))}",
            f"Время ответа: {_now_msk_text()}",
        ]
    )


def _collect_recent_channel_signals(cache: Dict, window_sec: int) -> list[Dict]:
    now_ts = int(time.time())
    out: list[Dict] = []
    for value in (cache or {}).values():
        if not isinstance(value, dict):
            continue
        last_sent_ts = int(value.get("last_sent_ts", 0) or 0)
        if not last_sent_ts or (now_ts - last_sent_ts) > max(1, window_sec):
            continue
        if not str(value.get("variant_id") or "").strip():
            continue
        if not str(value.get("action") or "").strip():
            continue
        out.append(value)
    out.sort(key=lambda x: int(x.get("last_sent_ts", 0) or 0), reverse=True)
    return out


def _collect_recent_delivery_signals(cache: Dict) -> list[Dict]:
    fetcher = _RECENT_SIGNAL_FETCHER
    if callable(fetcher):
        try:
            payload = fetcher(limit=20)
            sent = payload.get("sent") if isinstance(payload, dict) else []
            out = []
            now_ts = int(time.time())
            for row in sent if isinstance(sent, list) else []:
                if not isinstance(row, dict):
                    continue
                if str(row.get("kind") or "") != "gift_signal":
                    continue
                sent_at = str(row.get("sent_at") or "")
                try:
                    sent_ts = int(datetime.fromisoformat(sent_at.replace("Z", "+00:00")).timestamp())
                except Exception:
                    sent_ts = 0
                if sent_ts and (now_ts - sent_ts) > SIGNAL_COMMAND_WINDOW_SEC:
                    continue
                payload_row = row.get("payload") if isinstance(row.get("payload"), dict) else None
                if isinstance(payload_row, dict):
                    out.append(payload_row)
            if out:
                return out
        except Exception:
            pass
    return _collect_recent_channel_signals(cache, SIGNAL_COMMAND_WINDOW_SEC)


def _gift_signal_payload_from_input(raw_text: str) -> Dict | None:
    parts = [p.strip() for p in str(raw_text or "").split("/")]
    while parts and not parts[-1]:
        parts.pop()
    if len(parts) < 2:
        return None
    collection = parts[0]
    model = parts[1]
    background = parts[2] if len(parts) >= 3 else ""
    pattern = parts[3] if len(parts) >= 4 else ""
    if not collection or not model:
        return None
    params = {
        "collection": collection,
        "model": model,
        "active_only": "true",
        "mode": "tz",
    }
    if background:
        params["background"] = background
    if pattern:
        params["pattern"] = pattern
    resolve_url = f"{API_BASE_URL}/v1/variants/resolve?{urllib.parse.urlencode(params)}"
    resolved = _http_get(resolve_url)
    variant_id = str(resolved.get("variant_id") or "").strip()
    if not variant_id:
        return None
    details = _http_get(f"{API_BASE_URL}/v1/catalog/variant/{urllib.parse.quote(variant_id, safe='')}")
    if not isinstance(details, dict):
        return None
    details.setdefault("collection", resolved.get("collection") or collection)
    details.setdefault("model", resolved.get("model") or model)
    details.setdefault("background", resolved.get("background") or background)
    details.setdefault("pattern", resolved.get("pattern") or pattern)
    details.setdefault("preview_url", resolved.get("preview_url") or "")
    details.setdefault("type", details.get("action") or "WATCH")
    details.setdefault("ts", details.get("updated_at") or _utcnow_text_iso())
    details.setdefault("depth_5pct_count", int(details.get("active_lots") or 0))
    details.setdefault("depth_5pct_ton", float(details.get("floor_ton") or 0.0) * min(int(details.get("active_lots") or 0), 5))
    details.setdefault("volume_velocity", 1.0)
    details.setdefault("depth_score", float(details.get("depth_score") or 0.0))
    details.setdefault("score100", float(details.get("score100") or 0.0))
    return details


def _utcnow_text_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _send_gift_signal_payload_to(chat_id: str | int, payload: Dict) -> None:
    renderer = _renderer()
    text = renderer.render_gift_signal(payload)
    preview = str(payload.get("preview_url") or "").strip()
    if preview.startswith("http://") or preview.startswith("https://"):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        _http_post(url, {"chat_id": str(chat_id), "photo": preview, "caption": text[:1024]})
        return
    send_message_to(chat_id, text)


def _send_market_status_payload_to(chat_id: str | int, payload: Dict) -> None:
    renderer = _renderer()
    send_message_to(chat_id, renderer.render_market_status(payload))


def _handle_commands(cache: Dict) -> None:
    if not COMMANDS_ENABLED or not BOT_TOKEN:
        return
    offset = int(cache.get("tg_update_offset", 0) or 0)
    updates = _get_updates(offset=offset, timeout_sec=UPDATES_TIMEOUT_SEC)
    for upd in updates.get("result") or []:
        try:
            update_id = int(upd.get("update_id", 0))
            if update_id >= offset:
                offset = update_id + 1
            msg = upd.get("message") or upd.get("edited_message") or {}
            text = str(msg.get("text") or "").strip()
            chat = msg.get("chat") or {}
            chat_id = chat.get("id")
            if not chat_id:
                continue
            gift_state = cache.setdefault("signal_gift_state", {})
            gift_waiting = bool(gift_state.get(str(chat_id), {}).get("awaiting"))
            if gift_waiting and text and not text.startswith("/"):
                try:
                    signal_payload = _gift_signal_payload_from_input(text)
                    if not signal_payload:
                        send_message_to(
                            chat_id,
                            "Мы не смогли собрать аналитику по введенным вами данным. Проверьте корректность ввода. "
                            "Возможно указанный вами подарок отсутствует в нашей базе. Свяжитесь и нашей командой в "
                            "телеграм канале и мы обязательно внесем необходимые данные в нашу систему аналитики. "
                            "Благодарим за понимание",
                        )
                    else:
                        _send_gift_signal_payload_to(chat_id, signal_payload)
                except Exception:
                    send_message_to(
                        chat_id,
                        "Мы не смогли собрать аналитику по введенным вами данным. Проверьте корректность ввода. "
                        "Возможно указанный вами подарок отсутствует в нашей базе. Свяжитесь и нашей командой в "
                        "телеграм канале и мы обязательно внесем необходимые данные в нашу систему аналитики. "
                        "Благодарим за понимание",
                    )
                finally:
                    gift_state.pop(str(chat_id), None)
                continue
            if not text.startswith("/"):
                continue
            cmd = text.split()[0].split("@")[0].lower()
            if cmd == "/status":
                try:
                    payload = _http_get(f"{API_BASE_URL}/v1/market/status?window=30m")
                    _send_market_status_payload_to(chat_id, payload)
                except Exception as e:  # noqa: BLE001
                    send_message_to(chat_id, f"Ошибка получения статуса: {e}")
            elif cmd == "/signal":
                now_ts = int(time.time())
                key = str(chat_id)
                cmd_state = cache.setdefault("signal_cmd_state", {})
                last_cmd_ts = int(cmd_state.get(key, 0) or 0)
                if last_cmd_ts and (now_ts - last_cmd_ts) < SIGNAL_COMMAND_COOLDOWN_SEC:
                    send_message_to(chat_id, "Доступные сигналы были отправлены, вернитесь через 1 час")
                    continue

                recent = _collect_recent_delivery_signals(cache)
                if not recent:
                    send_message_to(chat_id, "За последний час сигналы в канал не отправлялись")
                    continue

                send_message_to(
                    chat_id,
                    f"Сигналы за последний час: {len(recent)}",
                )
                for item in recent:
                    _send_gift_signal_payload_to(chat_id, item)
                cmd_state[key] = now_ts
            elif cmd == "/signal_gift":
                gift_state[str(chat_id)] = {"awaiting": True, "started_ts": int(time.time())}
                send_message_to(
                    chat_id,
                    "Введите <b>название коллекции, модели, фона и узора в формате: "
                    "коллекция/модель/фон/узор</b>, например: "
                    "<b>berry boxes/clarity/black/baphomet</b>. "
                    "<b>Коллекция и модель необходимо указывать обязательно</b>",
                    parse_mode="HTML",
                )
        except Exception:
            continue
    cache["tg_update_offset"] = offset


def _load_cache() -> Dict:
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: Dict) -> None:
    os.makedirs(os.path.dirname(CACHE_FILE) or ".", exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _format_signal(item: Dict, signal_ts: int | None = None) -> str:
    def _pick_trait_name(value) -> str:
        if isinstance(value, dict):
            for key in ("name", "title", "label", "value", "id"):
                text = str(value.get(key) or "").strip()
                if text:
                    return text
            return ""
        return str(value or "").strip()

    action = str(item.get("action") or "HOLD").upper()
    score = float(item.get("reco_score") or 0)
    conf = int(round(float(item.get("confidence") or 0)))
    forecast = item.get("forecast") or {}
    rng = forecast.get("range_pct") if isinstance(forecast, dict) else []
    fc_range = f"{float(rng[0]):.1f}%…{float(rng[1]):.1f}%" if isinstance(rng, list) and len(rng) >= 2 else "-"
    fc_bias = {"up": "рост", "down": "снижение", "flat": "боковик"}.get(str(forecast.get("bias") or "flat"), "боковик")
    action_ru = {"BUY": "Покупка", "SELL": "Продажа", "HOLD": "Держать", "WATCH": "Наблюдение", "AVOID": "Избегать"}.get(action, action)
    title = str(item.get("title") or "").strip()
    title_parts = [x.strip() for x in title.split("•")] if "•" in title else []
    traits = item.get("traits") or {}
    model = (
        _pick_trait_name(traits.get("model"))
        or str(item.get("model_name") or "").strip()
        or (title_parts[0] if len(title_parts) >= 1 else "")
        or "-"
    )
    background = (
        _pick_trait_name(traits.get("background"))
        or str(item.get("background_name") or "").strip()
        or (title_parts[1] if len(title_parts) >= 2 else "")
        or "-"
    )
    pattern = (
        _pick_trait_name(traits.get("pattern"))
        or str(item.get("pattern_name") or "").strip()
        or (title_parts[2] if len(title_parts) >= 3 else "")
        or "-"
    )
    collection = item.get("base_name") or item.get("group") or item.get("base_id") or "-"
    reasons = item.get("reasons") or []
    risks = item.get("risks") or []
    summary = f"ожидается {fc_bias} (24ч: {fc_range}, оценка {score:.1f}, уверенность {conf}%)"

    lines = [
        "<b>GiftMarketZone: Сигналы :</b>",
        f"<b>{html.escape(action)}</b> | score {score:.1f} | conf {conf}%",
        f"Коллекция: <b>{html.escape(str(collection))}</b>",
        f"Модель: <b>{html.escape(str(model))}</b>",
        f"Фон: <b>{html.escape(str(background))}</b>",
        f"Узор: <b>{html.escape(str(pattern))}</b>",
        "",
        f"<b>{html.escape(action_ru)}:</b> {html.escape(summary)}",
        "",
        f"<b>Прогноз 24ч:</b> {html.escape(fc_bias)}, диапазон {html.escape(fc_range)}",
    ]
    lines.append("<b>Причины:</b>")
    if reasons:
        for r in reasons[:3]:
            txt = str((r or {}).get("text") or "-")
            lines.append(f"- {html.escape(txt)}")
    else:
        lines.append("- -")
    lines.append("<b>Риск:</b>")
    if risks:
        for r in risks[:2]:
            txt = str((r or {}).get("text") or "-")
            lines.append(f"- {html.escape(txt)}")
    else:
        lines.append("- -")
    if signal_ts and signal_ts > 0:
        signal_dt = datetime.fromtimestamp(signal_ts, tz=timezone.utc).astimezone(MSK_TZ).strftime("%Y-%m-%d %H:%M:%S МСК")
    else:
        signal_dt = _now_msk_text()
    lines.extend(["", f"Время сигнала: {signal_dt}"])
    return "\n".join(lines)


def _send_signal_to(chat_id: str | int, item: Dict) -> None:
    text = _format_signal(item, signal_ts=int(item.get("last_sent_ts", 0) or 0))
    preview = str(item.get("preview_url") or "").strip()
    if preview.startswith("http://") or preview.startswith("https://"):
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        # Telegram caption max 1024 chars.
        caption = text[:1000]
        _http_post(url, {"chat_id": str(chat_id), "photo": preview, "caption": caption, "parse_mode": "HTML"})
        return
    send_message_to(chat_id, text, parse_mode="HTML")


def _send_signal(item: Dict) -> None:
    _send_signal_to(CHAT_ID, item)


def _is_dynamic(prev: Dict, curr: Dict) -> bool:
    if not prev:
        return True
    if prev.get("action") != curr.get("action"):
        return True
    if abs(float(curr.get("reco_score", 0) or 0) - float(prev.get("reco_score", 0) or 0)) >= SCORE_DELTA_MIN:
        return True
    if abs(float(curr.get("confidence", 0) or 0) - float(prev.get("confidence", 0) or 0)) >= CONF_DELTA_MIN:
        return True
    try:
        prev_pct = float(prev.get("floor_change_pct_24h", 0))
        curr_pct = float(curr.get("floor_change_pct_24h", 0))
    except Exception:
        return True
    if abs(curr_pct - prev_pct) >= max(DYNAMICS_PCT, CHANGE24H_DELTA_MIN):
        return True
    prev_fc = prev.get("forecast") or {}
    curr_fc = curr.get("forecast") or {}
    if prev_fc.get("bias") != curr_fc.get("bias"):
        return True
    return False


def _signal_fingerprint(item: Dict) -> str:
    fc = item.get("forecast") or {}
    rng = fc.get("range_pct") if isinstance(fc, dict) else []
    lo = float(rng[0]) if isinstance(rng, list) and len(rng) >= 1 else 0.0
    hi = float(rng[1]) if isinstance(rng, list) and len(rng) >= 2 else 0.0
    parts = [
        str(item.get("variant_id") or ""),
        str(item.get("action") or ""),
        str(int(round(float(item.get("reco_score", 0) or 0)))),
        str(int(round(float(item.get("confidence", 0) or 0)))),
        str(fc.get("bias") or "flat"),
        f"{lo:.1f}",
        f"{hi:.1f}",
    ]
    return "|".join(parts)


def _wait_api_ready() -> None:
    started = time.time()
    while True:
        try:
            _http_get(f"{API_BASE_URL}/healthz")
            return
        except Exception:
            if time.time() - started >= API_WARMUP_MAX_SEC:
                return
            time.sleep(2)


def cycle(cache: Dict) -> None:
    _wait_api_ready()
    _handle_commands(cache)
    try:
        resp = _http_get(f"{API_BASE_URL}/api/recommendations?scope=all&entity=variant&ai=1")
    except Exception as e:
        # Fallback path for Render cold starts / heavy AI pipeline windows.
        if isinstance(e, TimeoutError) or (
            isinstance(e, urllib.error.HTTPError) and e.code in {502, 503, 504}
        ):
            resp = _http_get(f"{API_BASE_URL}/api/recommendations?scope=all&entity=variant&ai=0")
        else:
            raise
    items = sorted(resp.get("items") or [], key=lambda x: float(x.get("confidence", 0) or 0), reverse=True)
    now_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_ts = int(time.time())
    sent_count = 0
    stat_total = len(items)
    stat_conf = 0
    stat_action = 0
    stat_cooldown = 0
    stat_fp = 0
    stat_dyn = 0

    if FORCE_SEND_TOP1 and items:
        _send_signal(items[0])
        sent_count += 1
        key = f"{items[0].get('variant_id')}"
        fp = _signal_fingerprint(items[0])
        cache[key] = {**items[0], "last_sent": now_tag, "last_sent_ts": now_ts, "last_fp": fp}
        if DEBUG:
            print(f"[bot] force-send top1 variant={key}")
        return

    for item in items:
        if sent_count >= MAX_MESSAGES_PER_CYCLE:
            break
        if item.get("confidence", 0) < MIN_CONFIDENCE:
            continue
        stat_conf += 1
        if str(item.get("action") or "").upper() not in {"BUY", "SELL", "WATCH", "AVOID"}:
            continue
        stat_action += 1
        key = f"{item.get('variant_id')}"
        prev = cache.get(key, {})
        fp = _signal_fingerprint(item)
        last_fp = str(prev.get("last_fp") or "")
        last_sent_ts = int(prev.get("last_sent_ts", 0) or 0)
        # Ограничение частоты: не чаще 1 раза в час по одному варианту.
        if last_sent_ts and (now_ts - last_sent_ts) < MIN_REPEAT_SEC:
            stat_cooldown += 1
            continue
        # Даже после cooldown повторяем только при существенном изменении.
        if fp == last_fp:
            stat_fp += 1
            continue
        if not _is_dynamic(prev, item):
            stat_dyn += 1
            continue
        _send_signal(item)
        sent_count += 1
        cache[key] = {**item, "last_sent": now_tag, "last_sent_ts": now_ts, "last_fp": fp}
    if DEBUG:
        print(
            f"[bot] total={stat_total} pass_conf={stat_conf} pass_action={stat_action} "
            f"skip_cooldown={stat_cooldown} skip_fp={stat_fp} skip_not_dynamic={stat_dyn} sent={sent_count}"
        )


def command_cycle(cache: Dict) -> None:
    _wait_api_ready()
    _handle_commands(cache)


def main() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise SystemExit("Set TG_BOT_TOKEN and TG_CHAT_ID before running bot.py")

    os.makedirs(os.path.dirname(LOCK_FILE) or ".", exist_ok=True)
    lock_fh = open(LOCK_FILE, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another bot sender process is already running")

    cache = _load_cache()
    while True:
        try:
            cycle(cache)
            _save_cache(cache)
        except urllib.error.URLError as e:
            print(f"Network error: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"Unexpected error: {e}")
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import queue
import hashlib
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _bool_env(value: Any, default: bool = False) -> bool:
    raw = str(value if value is not None else "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{int(time.time() * 1000)}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _deep_merge(base, patch):
    if isinstance(base, dict) and isinstance(patch, dict):
        out = dict(base)
        for key, value in patch.items():
            out[key] = _deep_merge(out.get(key), value)
        return out
    return patch


class GateEngine:
    def __init__(self, gates: dict | None, signal_profiles: dict | None = None) -> None:
        self.gates = gates if isinstance(gates, dict) else {}
        self.signal_profiles = signal_profiles if isinstance(signal_profiles, dict) else {}

    def evaluate(self, gate_name: str, payload: dict | None) -> dict:
        gate = self.gates.get(gate_name) if isinstance(self.gates.get(gate_name), dict) else {}
        rules = gate.get("all") if isinstance(gate.get("all"), list) else []
        row = payload if isinstance(payload, dict) else {}
        checks: list[dict] = []
        passed = True
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            metric = str(rule.get("metric") or "").strip()
            op = str(rule.get("op") or "").strip()
            target = _safe_float(rule.get("value"), 0.0)
            current = _safe_float(row.get(metric), 0.0)
            if op == ">=":
                ok = current >= target
            elif op == ">":
                ok = current > target
            elif op == "<=":
                ok = current <= target
            elif op == "<":
                ok = current < target
            elif op == "==":
                ok = abs(current - target) <= 1e-9
            else:
                ok = False
            checks.append({"metric": metric, "op": op, "value": target, "current": current, "ok": ok})
            if not ok:
                passed = False
        row = payload if isinstance(payload, dict) else {}
        exception = None
        if gate_name == "gift_signal_channel":
            action = str(row.get("action") or row.get("type") or "").upper()
            conf = _safe_float(row.get("conf_pct"), 0.0)
            pressure = _safe_float(row.get("listing_pressure"), 0.0)
            absorption = _safe_float(row.get("absorption_30m"), 0.0)
            strength_tag = str(row.get("strength_tag") or "").upper()
            strong_sell = action == "SELL" and conf >= 40.0 and (pressure >= 6.0 or absorption <= 0.6)
            if strong_sell or strength_tag == "STRONG_SELL":
                passed = True
                exception = "strong_sell_override"
        return {"ok": passed, "checks": checks, "exception": exception}


class MessageRenderer:
    def __init__(self, profile: dict, rules_text: str, signal_profiles: dict | None = None, edgerank_weights: dict | None = None) -> None:
        self.profile = profile if isinstance(profile, dict) else {}
        self.rules_text = str(rules_text or "")
        self.signal_profiles = signal_profiles if isinstance(signal_profiles, dict) else {}
        self.edgerank_weights = edgerank_weights if isinstance(edgerank_weights, dict) else {}
        self.locale = str(self.profile.get("locale") or "ru-RU")
        self.time_format = str(self.profile.get("time_format") or "YYYY-MM-DD HH:mm:ss z")
        money = self.profile.get("money") if isinstance(self.profile.get("money"), dict) else {}
        self.money_unit = str(money.get("unit") or "TON")
        self.money_decimals = max(0, _safe_int(money.get("decimals"), 2))
        rendering = self.profile.get("rendering") if isinstance(self.profile.get("rendering"), dict) else {}
        self.line_break = str(rendering.get("line_break") or "\n")
        self.bullet = str(rendering.get("bullet") or "• ")
        self.max_reasons = max(1, _safe_int(rendering.get("max_reasons"), 3))
        self.max_risks = max(1, _safe_int(rendering.get("max_risks"), 3))
        emojis = rendering.get("emojis") if isinstance(rendering.get("emojis"), dict) else {}
        self.regime_badges = emojis.get("regime_badge") if isinstance(emojis.get("regime_badge"), dict) else {}
        self.action_badges = emojis.get("action_badge") if isinstance(emojis.get("action_badge"), dict) else {}
        rr = self.profile.get("reason_risk_dictionary") if isinstance(self.profile.get("reason_risk_dictionary"), dict) else {}
        self.reason_dict = rr.get("reasons") if isinstance(rr.get("reasons"), dict) else {}
        self.risk_dict = rr.get("risk_flags") if isinstance(rr.get("risk_flags"), dict) else {}
        decision = self.profile.get("decision_engine_render") if isinstance(self.profile.get("decision_engine_render"), dict) else {}
        self.tactics_map = decision.get("regime_tactics_map") if isinstance(decision.get("regime_tactics_map"), dict) else {}

    def render_market_status(self, status: dict) -> str:
        payload = status if isinstance(status, dict) else {}
        templates = self.profile.get("templates") if isinstance(self.profile.get("templates"), dict) else {}
        template = templates.get("market_status") if isinstance(templates.get("market_status"), dict) else {}
        ctx = self._market_context(payload)
        lines = [self._fmt(str(template.get("title") or ""), ctx)]
        for section in template.get("sections") or []:
            if not isinstance(section, dict):
                continue
            title = str(section.get("title") or "").strip()
            if title:
                lines.append(title)
            for row in section.get("lines") or []:
                text = self._fmt(str(row or ""), ctx).strip()
                if text:
                    lines.append(text)
        return self.line_break.join([x for x in lines if str(x).strip()]).strip()

    def render_gift_signal(self, signal: dict) -> str:
        payload = signal if isinstance(signal, dict) else {}
        templates = self.profile.get("templates") if isinstance(self.profile.get("templates"), dict) else {}
        template = templates.get("gift_signal") if isinstance(templates.get("gift_signal"), dict) else {}
        ctx = self._signal_context(payload)
        lines = [self._fmt(str(template.get("title") or ""), ctx)]
        for section in template.get("sections") or []:
            if not isinstance(section, dict):
                continue
            title = str(section.get("title") or "").strip()
            if title:
                lines.append(title)
            for row in section.get("lines") or []:
                text = self._fmt(str(row or ""), ctx).strip()
                if text:
                    lines.append(text)
        return self.line_break.join([x for x in lines if str(x).strip()]).strip()

    def _market_context(self, payload: dict) -> dict[str, str]:
        flow = payload.get("flow") if isinstance(payload.get("flow"), dict) else {}
        liq = payload.get("liquidity") if isinstance(payload.get("liquidity"), dict) else {}
        depth = liq.get("depth_5pct") if isinstance(liq.get("depth_5pct"), dict) else {}
        supply = payload.get("supply") if isinstance(payload.get("supply"), dict) else {}
        whales = payload.get("whales") if isinstance(payload.get("whales"), dict) else {}
        signals_1h = payload.get("signals_1h") if isinstance(payload.get("signals_1h"), dict) else {}
        provider = payload.get("provider_health") if isinstance(payload.get("provider_health"), dict) else {}
        regime = str(payload.get("market_regime") or "MEAN_REVERT").upper()
        tactics = self.tactics_map.get(regime) if isinstance(self.tactics_map.get(regime), list) else []
        tactics = [str(x or "").strip() for x in tactics][:3]
        while len(tactics) < 3:
            tactics.append("")
        delta_lots = _safe_int(supply.get("delta_lots_1h"), 0)
        return {
            "market_regime": regime,
            "regime_emoji": str(self.regime_badges.get(regime) or ""),
            "market_conf_pct": str(_safe_int(payload.get("data_conf_pct"), 0)),
            "trend": str(payload.get("trend") or "флет"),
            "market_velocity_score": str(_safe_int(payload.get("velocity_score"), 0)),
            "market_volatility_bucket": str(payload.get("vol_level") or "MED"),
            "volume_velocity_x": self._fmt_num(flow.get("volume_velocity"), 2),
            "absorption_rate_30m": self._fmt_num(flow.get("absorption"), 2),
            "listing_pressure": self._fmt_num(flow.get("listing_pressure"), 2),
            "liquidity_score": str(_safe_int(liq.get("liquidity_score"), 0)),
            "depth_5pct_lots": str(_safe_int(depth.get("lots"), 0)),
            "depth_5pct_ton": self._fmt_num(depth.get("ton"), 2),
            "active_lots_market": str(_safe_int(supply.get("active_lots"), 0)),
            "delta_lots_1h_sign": "+" if delta_lots >= 0 else "-",
            "delta_lots_1h": str(abs(delta_lots)),
            "new_listings_10m": str(_safe_int(supply.get("listing_velocity_10m"), 0)),
            "new_listings_10m_norm": self._fmt_num(supply.get("listing_velocity_norm"), 2),
            "whale_share_pct": self._fmt_num(whales.get("whale_ratio_pct"), 2),
            "whale_impulse": self._fmt_num(whales.get("whale_impulse"), 2),
            "signals_1h_buy": str(_safe_int(signals_1h.get("buy"), 0)),
            "signals_1h_sell": str(_safe_int(signals_1h.get("sell"), 0)),
            "signals_1h_skipwatch": str(_safe_int(signals_1h.get("watch"), 0) + _safe_int(signals_1h.get("skip"), 0)),
            "data_health": str(payload.get("data_health") or "OK"),
            "data_health_note": str(payload.get("data_health_note") or ""),
            "updated_at": self._fmt_time(payload.get("updated_at") or payload.get("ts") or ""),
            "p95_ms": str(_safe_int(provider.get("p95_ms"), 0)),
            "err_pct": self._fmt_num(provider.get("err_pct"), 2),
            "tactic_line1": tactics[0],
            "tactic_line2": tactics[1],
            "tactic_line3": tactics[2],
        }

    def _signal_context(self, payload: dict) -> dict[str, str]:
        regime = str(payload.get("market_regime") or "MEAN_REVERT").upper()
        edge = self._resolved_edge(payload, regime)
        reasons = self._reasons(payload, regime)
        risks = self._risks(payload)
        plan_entry, plan_exit = self._plan_lines(payload, regime)
        price = _safe_float(payload.get("price_ton"), 0.0)
        fair = _safe_float(payload.get("fair_ton"), 0.0)
        delta = 0.0
        if price > 0 and fair > 0:
            delta = ((fair - price) / price) * 100.0
        action = str(payload.get("action") or payload.get("type") or "WATCH").upper()
        return {
            "action": action,
            "edgeRank100": self._fmt_num(edge.get("edgeRank100"), 0),
            "score100": self._fmt_num(payload.get("score100"), 0),
            "conf_pct": self._fmt_num(payload.get("conf_pct"), 0),
            "horizon": str(payload.get("horizon") or "30m"),
            "market_regime": regime,
            "collection": str(payload.get("collection") or "Unknown"),
            "model": str(payload.get("model") or "Unknown"),
            "background": str(payload.get("background") or "Unknown"),
            "pattern": str(payload.get("pattern") or "Unknown"),
            "price_ton": self._fmt_money(payload.get("price_ton")),
            "floor_ton": self._fmt_money(payload.get("floor_ton")),
            "fair_ton": self._fmt_money(payload.get("fair_ton")),
            "delta_fair_pct_sign": "+" if delta >= 0 else "-",
            "delta_fair_pct": self._fmt_num(abs(delta), 2),
            "plan_entry_line": plan_entry,
            "plan_exit_line": plan_exit,
            "liquidity_score": self._fmt_num(payload.get("liquidity_score"), 0),
            "absorption_rate_30m": self._fmt_num(payload.get("absorption_30m"), 2),
            "depth_5pct_lots": str(_safe_int(payload.get("depth_5pct_count"), 0)),
            "depth_5pct_ton": self._fmt_money(payload.get("depth_5pct_ton")),
            "listing_pressure": self._fmt_num(payload.get("listing_pressure"), 2),
            "volume_velocity_x": self._fmt_num(payload.get("volume_velocity"), 2),
            "reasons_block": self.line_break.join([f"{self.bullet}{x}" for x in reasons]) if reasons else f"{self.bullet}—",
            "risks_block": self.line_break.join([f"{self.bullet}{x}" for x in risks]) if risks else f"{self.bullet}—",
            "ts": self._fmt_time(payload.get("ts") or _utcnow_iso()),
            "score100_raw": self._fmt_num(payload.get("score100"), 0),
            "undervalue_pct": self._fmt_num(payload.get("undervalue_pct"), 2),
            "conf_pct_raw": self._fmt_num(payload.get("conf_pct"), 0),
        }

    def _reasons(self, payload: dict, regime: str) -> list[str]:
        raw = [self._render_reason_token(str(x).strip(), payload) for x in (payload.get("reasons") or []) if str(x).strip()]
        if raw:
            return raw[: self.max_reasons]
        out: list[str] = []
        undervalue_pct = _safe_float(payload.get("undervalue_pct"), 0.0)
        absorption = _safe_float(payload.get("absorption_30m"), 0.0)
        liq = _safe_float(payload.get("liquidity_score"), 0.0)
        action = str(payload.get("action") or payload.get("type") or "WATCH").upper()
        buy_all = (((self.signal_profiles.get("profiles") or {}).get(regime) or {}).get("buy_all") or {}) if isinstance(self.signal_profiles.get("profiles"), dict) else {}
        min_u = _safe_float(buy_all.get("undervalue_gte"), 0.0) * 100.0
        if action == "WATCH" and undervalue_pct < min_u and "NEAR_ENTRY" in self.reason_dict:
            out.append(self._fmt(str(self.reason_dict.get("NEAR_ENTRY") or ""), {"score100": self._fmt_num(payload.get("score100"), 0), "missing_metric": "недооценки"}))
        if 0.85 <= absorption <= 1.10 and "GOOD_ABSORPTION" in self.reason_dict:
            out.append(self._fmt(str(self.reason_dict.get("GOOD_ABSORPTION") or ""), {"absorption_rate_30m": self._fmt_num(absorption, 2)}))
        if liq >= 50.0 and "STRONG_LIQ" in self.reason_dict:
            out.append(self._fmt(str(self.reason_dict.get("STRONG_LIQ") or ""), {"liquidity_score": self._fmt_num(liq, 0)}))
        if undervalue_pct > 0 and "UNDERVALUED" in self.reason_dict:
            out.append(self._fmt(str(self.reason_dict.get("UNDERVALUED") or ""), {"undervalue_pct": self._fmt_num(undervalue_pct, 2)}))
        return out[: self.max_reasons]

    def _risks(self, payload: dict) -> list[str]:
        raw = [self._render_risk_token(str(x).strip(), payload) for x in (payload.get("risk_flags") or []) if str(x).strip()]
        if raw:
            return raw[: self.max_risks]
        out: list[str] = []
        depth = _safe_int(payload.get("depth_5pct_count"), 0)
        pressure = _safe_float(payload.get("listing_pressure"), 0.0)
        conf = _safe_float(payload.get("conf_pct"), 0.0)
        data_health = str(payload.get("data_health") or "OK").upper()
        if depth <= 3 and "LOW_DEPTH_5PCT" in self.risk_dict:
            out.append(self._fmt(str(self.risk_dict.get("LOW_DEPTH_5PCT") or ""), {"depth_5pct_lots": str(depth)}))
        if pressure >= 4.0 and "HIGH_PRESSURE" in self.risk_dict:
            out.append(self._fmt(str(self.risk_dict.get("HIGH_PRESSURE") or ""), {"listing_pressure": self._fmt_num(pressure, 2)}))
        if conf < 35.0 and "LOW_CONF" in self.risk_dict:
            out.append(self._fmt(str(self.risk_dict.get("LOW_CONF") or ""), {"conf_pct": self._fmt_num(conf, 0)}))
        if data_health != "OK" and "DATA_DEGRADED" in self.risk_dict:
            out.append(self._fmt(str(self.risk_dict.get("DATA_DEGRADED") or ""), {"data_health_note": str(payload.get("data_health_note") or data_health)}))
        return out[: self.max_risks]

    def _render_reason_token(self, token: str, payload: dict) -> str:
        key = str(token or "").strip().upper()
        if key in self.reason_dict:
            price = _safe_float(payload.get("price_ton"), 0.0)
            fair = _safe_float(payload.get("fair_ton"), 0.0)
            delta = ((price - fair) / fair) * 100.0 if fair > 0 else 0.0
            return self._fmt(
                str(self.reason_dict.get(key) or token),
                {
                    "score100": self._fmt_num(payload.get("score100"), 0),
                    "missing_metric": "недооценки",
                    "absorption_rate_30m": self._fmt_num(payload.get("absorption_30m"), 2),
                    "liquidity_score": self._fmt_num(payload.get("liquidity_score"), 0),
                    "undervalue_pct": self._fmt_num(payload.get("undervalue_pct"), 2),
                    "delta_fair_pct": self._fmt_num(abs(delta), 2),
                },
            )
        return token

    def _render_risk_token(self, token: str, payload: dict) -> str:
        key = str(token or "").strip().upper()
        if key in self.risk_dict:
            return self._fmt(
                str(self.risk_dict.get(key) or token),
                {
                    "depth_5pct_lots": str(_safe_int(payload.get("depth_5pct_count"), 0)),
                    "listing_pressure": self._fmt_num(payload.get("listing_pressure"), 2),
                    "conf_pct": self._fmt_num(payload.get("conf_pct"), 0),
                    "data_health_note": str(payload.get("data_health_note") or payload.get("data_health") or "DEGRADED"),
                },
            )
        return token

    def _resolved_edge(self, payload: dict, regime: str) -> dict[str, float]:
        edge100 = _safe_float(payload.get("edgeRank100"), -1.0)
        edge_raw = _safe_float(payload.get("edgeRank_raw"), -1.0)
        if edge100 >= 0.0 and edge_raw >= 0.0:
            return {"edgeRank100": edge100, "edgeRank_raw": edge_raw}
        profiles = self.edgerank_weights.get("profiles") if isinstance(self.edgerank_weights.get("profiles"), dict) else {}
        weights = profiles.get(regime) if isinstance(profiles.get(regime), dict) else profiles.get("MEAN_REVERT", {})
        s = _clamp(_safe_float(payload.get("score100"), 0.0) / 100.0, 0.0, 1.0)
        c = _clamp(_safe_float(payload.get("conf_pct"), 0.0) / 100.0, 0.0, 1.0)
        ep = _clamp(_safe_float(payload.get("expected_profit_pct"), 0.0) / 30.0, 0.0, 1.0)
        l = _clamp(_safe_float(payload.get("liquidity_score"), 0.0) / 100.0, 0.0, 1.0)
        ar = _clamp(_safe_float(payload.get("absorption_30m"), 0.0) / 2.0, 0.0, 1.0)
        d = _clamp(_safe_float(payload.get("depth_score"), _safe_float(payload.get("depth_5pct_count"), 0.0) / 25.0), 0.0, 1.0)
        lp = _clamp(_safe_float(payload.get("listing_pressure"), 0.0) / 6.0, 0.0, 1.0)
        vv_norm = _clamp((_safe_float(payload.get("volume_velocity"), 0.0) - 0.8) / 1.0, 0.0, 1.0)
        raw = (
            _safe_float(weights.get("EP"), 0.35) * ep
            + _safe_float(weights.get("S"), 0.25) * s
            + _safe_float(weights.get("L"), 0.15) * l
            + _safe_float(weights.get("AR"), 0.10) * ar
            + _safe_float(weights.get("D"), 0.10) * d
            + _safe_float(weights.get("LP"), -0.15) * lp
            + (_safe_float(weights.get("VV_bonus"), 0.0) * vv_norm if regime == "PANIC" else 0.0)
        )
        edge = _clamp(raw, 0.0, 1.0) * c
        return {"edgeRank100": round(edge * 100.0), "edgeRank_raw": round(raw, 6)}

    def _plan_lines(self, payload: dict, regime: str) -> tuple[str, str]:
        profiles = self.signal_profiles.get("profiles") if isinstance(self.signal_profiles.get("profiles"), dict) else {}
        regime_profile = profiles.get(regime) if isinstance(profiles.get(regime), dict) else {}
        buy_all = regime_profile.get("buy_all") if isinstance(regime_profile.get("buy_all"), dict) else {}
        parts: list[str] = []
        if "score100_gte" in buy_all:
            parts.append(f"score≥{self._fmt_num(buy_all.get('score100_gte'), 0)}")
        if "undervalue_gte" in buy_all:
            parts.append(f"U≥{self._fmt_num(_safe_float(buy_all.get('undervalue_gte')) * 100.0, 0)}%")
        if "expected_profit_pct_gte" in buy_all:
            parts.append(f"EP≥{self._fmt_num(buy_all.get('expected_profit_pct_gte'), 0)}%")
        if "liquidity_norm_gte" in buy_all:
            parts.append(f"L≥{self._fmt_num(_safe_float(buy_all.get('liquidity_norm_gte')) * 100.0, 0)}")
        if "absorption_gte" in buy_all:
            parts.append(f"AR≥{self._fmt_num(buy_all.get('absorption_gte'), 2)}")
        if "listing_pressure_lte" in buy_all:
            parts.append(f"LP≤{self._fmt_num(buy_all.get('listing_pressure_lte'), 2)}")
        if "depth_score_gte" in buy_all:
            parts.append(f"Depth≥{self._fmt_num(buy_all.get('depth_score_gte'), 2)}")
        if "volume_velocity_gte" in buy_all:
            parts.append(f"VV≥{self._fmt_num(buy_all.get('volume_velocity_gte'), 2)}")

        missing_tokens: list[str] = []
        score = _safe_float(payload.get("score100"), 0.0)
        undervalue = _safe_float(payload.get("undervalue_pct"), 0.0) / 100.0
        profit = _safe_float(payload.get("expected_profit_pct"), 0.0)
        liq = _safe_float(payload.get("liquidity_score"), 0.0) / 100.0
        absorption = _safe_float(payload.get("absorption_30m"), 0.0)
        pressure = _safe_float(payload.get("listing_pressure"), 0.0)
        depth = _safe_float(payload.get("depth_score"), _safe_float(payload.get("depth_5pct_count"), 0.0) / 25.0)
        vv = _safe_float(payload.get("volume_velocity"), 0.0)
        if score < _safe_float(buy_all.get("score100_gte"), 0.0):
            missing_tokens.append("score")
        if undervalue < _safe_float(buy_all.get("undervalue_gte"), 0.0):
            missing_tokens.append("undervalue")
        if profit < _safe_float(buy_all.get("expected_profit_pct_gte"), 0.0):
            missing_tokens.append("profit")
        if liq < _safe_float(buy_all.get("liquidity_norm_gte"), 0.0):
            missing_tokens.append("liquidity")
        if absorption < _safe_float(buy_all.get("absorption_gte"), 0.0):
            missing_tokens.append("absorption")
        if pressure > _safe_float(buy_all.get("listing_pressure_lte"), 10.0):
            missing_tokens.append("listing_pressure")
        if depth < _safe_float(buy_all.get("depth_score_gte"), 0.0):
            missing_tokens.append("depth")
        if vv < _safe_float(buy_all.get("volume_velocity_gte"), 0.0):
            missing_tokens.append("volume_velocity")
        priority_order = ["undervalue", "absorption", "liquidity"] + (["volume_velocity"] if regime == "PANIC" else []) + ["score", "profit", "listing_pressure", "depth"]
        missing_tokens = [token for token in priority_order if token in missing_tokens][:2]
        entry = f"• BUY-триггер ({regime}): " + ", ".join(parts)
        exit_line = self._watch_trigger_line(regime, buy_all, missing_tokens) if missing_tokens else "• BUY-гейт выполнен: следим за LP/AR и планом выхода"
        return entry, exit_line

    def _watch_trigger_line(self, regime: str, buy_all: dict, missing_tokens: list[str]) -> str:
        post_rules = self.signal_profiles.get("post_rules") if isinstance(self.signal_profiles.get("post_rules"), dict) else {}
        watch_triggers = post_rules.get("watch_triggers") if isinstance(post_rules.get("watch_triggers"), list) else []
        rendered: list[str] = []
        labels = {
            "undervalue": "недооценка",
            "absorption": "absorption",
            "liquidity": "ликвидность",
            "volume_velocity": "VV",
            "score": "score",
            "profit": "profit",
            "listing_pressure": "LP",
            "depth": "depth",
        }
        for token in missing_tokens:
            if token in {"score", "profit", "listing_pressure", "depth"}:
                rendered.append(labels.get(token, token))
                continue
            template = next((x for x in watch_triggers if isinstance(x, dict) and str(x.get("if_missing") or "") == token), None)
            if not isinstance(template, dict):
                rendered.append(labels.get(token, token))
                continue
            trigger = str(template.get("trigger") or "")
            trigger = trigger.replace("threshold_undervalue", self._fmt_num(_safe_float(buy_all.get("undervalue_gte"), 0.0), 2))
            trigger = trigger.replace("threshold_absorption", self._fmt_num(_safe_float(buy_all.get("absorption_gte"), 0.0), 2))
            trigger = trigger.replace("threshold_liquidity", self._fmt_num(_safe_float(buy_all.get("liquidity_norm_gte"), 0.0), 2))
            trigger = trigger.replace("threshold_vv", self._fmt_num(_safe_float(buy_all.get("volume_velocity_gte"), 0.0), 2))
            rendered.append(trigger)
        return f"• Не хватает до BUY: {'; '.join(rendered)}"

    def _fmt(self, template: str, ctx: dict[str, Any]) -> str:
        text = str(template or "")
        for key, value in ctx.items():
            text = text.replace("{" + str(key) + "}", str(value))
        return text

    def _fmt_num(self, value: Any, digits: int) -> str:
        num = _safe_float(value, 0.0)
        fmt = f"{{:.{max(0, int(digits))}f}}"
        return fmt.format(num)

    def _fmt_money(self, value: Any) -> str:
        return self._fmt_num(value, self.money_decimals)

    def _fmt_time(self, value: Any) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return raw
        return dt.astimezone(timezone.utc).strftime("%d.%m.%Y/%H:%M:%S")


class TelegramNotifier:
    def __init__(
        self,
        *,
        profile_path: Path,
        rules_path: Path,
        signal_profiles_path: Path,
        edgerank_weights_path: Path,
        settings_path: Path,
        journal_path: Path,
        bot_token: str,
        default_chat_id: str,
    ) -> None:
        self.profile = _load_json(profile_path, {})
        self.rules_text = rules_path.read_text(encoding="utf-8") if rules_path.exists() else ""
        self.signal_profiles = _load_json(signal_profiles_path, {})
        self.edgerank_weights = _load_json(edgerank_weights_path, {})
        self.renderer = MessageRenderer(self.profile, self.rules_text, self.signal_profiles, self.edgerank_weights)
        self.gates = GateEngine((self.profile.get("publish_gates") if isinstance(self.profile.get("publish_gates"), dict) else {}), self.signal_profiles)
        self.settings_path = settings_path
        self.journal_path = journal_path
        self.bot_token = str(bot_token or "").strip()
        self.default_chat_id = str(default_chat_id or "").strip()
        self._lock = threading.RLock()
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=1024)
        self._stop = threading.Event()
        self._rate_lock = threading.Lock()
        self._rate_state: dict[str, list[float]] = {}
        self._settings_overrides = _load_json(settings_path, {})
        self._journal = _load_json(journal_path, {"sent": {}, "failed": [], "stats": {}})
        self._worker = threading.Thread(target=self._worker_loop, name="telegram-notifier", daemon=True)
        self._worker.start()

    def defaults(self) -> dict:
        gate = ((self.profile.get("publish_gates") or {}).get("gift_signal_channel") or {}) if isinstance(self.profile.get("publish_gates"), dict) else {}
        all_rules = gate.get("all") if isinstance(gate.get("all"), list) else []
        thresholds = {str(r.get("metric") or ""): _safe_float(r.get("value"), 0.0) for r in all_rules if isinstance(r, dict)}
        enabled_default = bool(self.bot_token and self.default_chat_id and _bool_env(None, True))
        return {
            "enabled": enabled_default,
            "market_status": {
                "enabled": True,
                "channel_id": self.default_chat_id,
                "min_interval_sec": 900,
            },
            "gift_signal": {
                "enabled": True,
                "channel_id": self.default_chat_id,
                "include_image": True,
            },
            "publish_gates": {
                "gift_signal_channel": {
                    "edgeRank100_gte": thresholds.get("edgeRank100", 55.0),
                    "conf_pct_gte": thresholds.get("conf_pct", 35.0),
                    "expected_profit_pct_gte": thresholds.get("expected_profit_pct", 8.0),
                    "adaptive_sparse_fallback": True,
                    "adaptive_sparse_edgeRank100_gte": 1.0,
                    "adaptive_sparse_conf_pct_gte": 10.0,
                    "adaptive_sparse_expected_profit_pct_gte": 0.0,
                }
            },
            "transport": {
                "timeout_sec": 12,
                "max_retries": 3,
                "retry_backoff_sec": 1.5,
                "rate_limit_per_minute": 20,
                "dedupe_ttl_sec": 600,
            },
        }

    def effective_settings(self) -> dict:
        with self._lock:
            return _deep_merge(self.defaults(), self._settings_overrides if isinstance(self._settings_overrides, dict) else {})

    def update_settings(self, patch: dict) -> dict:
        sanitized = self._sanitize_patch(patch)
        with self._lock:
            self._settings_overrides = _deep_merge(self._settings_overrides if isinstance(self._settings_overrides, dict) else {}, sanitized)
            _save_json_atomic(self.settings_path, self._settings_overrides)
        return self.effective_settings()

    def reset_settings(self) -> dict:
        with self._lock:
            self._settings_overrides = {}
            _save_json_atomic(self.settings_path, self._settings_overrides)
        return self.effective_settings()

    def status(self) -> dict:
        settings = self.effective_settings()
        stats = self._journal.get("stats") if isinstance(self._journal.get("stats"), dict) else {}
        return {
            "ok": True,
            "configured": bool(self.bot_token),
            "worker_alive": self._worker.is_alive(),
            "queue_size": self._queue.qsize(),
            "effective": settings,
            "stats": {
                "sent_total": _safe_int(stats.get("sent_total"), 0),
                "failed_total": _safe_int(stats.get("failed_total"), 0),
                "dropped_total": _safe_int(stats.get("dropped_total"), 0),
                "last_sent_at": stats.get("last_sent_at"),
                "last_error": stats.get("last_error"),
            },
        }

    def journal_snapshot(self, limit: int = 50) -> dict:
        lim = max(1, min(_safe_int(limit, 50), 200))
        sent = self._journal.get("sent") if isinstance(self._journal.get("sent"), dict) else {}
        failed = self._journal.get("failed") if isinstance(self._journal.get("failed"), list) else []
        sent_items = []
        for key, value in sent.items():
            if not isinstance(value, dict):
                continue
            sent_items.append({"key": str(key), **value})
        sent_items.sort(key=lambda row: str(row.get("sent_at") or ""), reverse=True)
        failed_items = [row for row in failed if isinstance(row, dict)]
        failed_items.sort(key=lambda row: str(row.get("ts") or ""), reverse=True)
        return {"ok": True, "sent": sent_items[:lim], "failed": failed_items[:lim]}

    def close(self, timeout_sec: float = 2.0) -> None:
        self._stop.set()
        try:
            self._worker.join(timeout=max(0.1, float(timeout_sec)))
        except Exception:
            pass

    def enqueue_market_status(self, status: dict) -> bool:
        effective = self.effective_settings()
        if not bool(effective.get("enabled")):
            return False
        market_cfg = effective.get("market_status") if isinstance(effective.get("market_status"), dict) else {}
        if not bool(market_cfg.get("enabled")):
            return False
        payload = status.get("payload") if isinstance(status.get("payload"), dict) else status
        stable_payload = dict(payload or {})
        stable_payload.pop("ts", None)
        stable_payload.pop("updated_at", None)
        digest = hashlib.sha1(json.dumps(stable_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
        regime = str((payload or {}).get("market_regime") or "MEAN_REVERT")
        dedupe_key = f"market:{regime}:{digest}"
        item = {"kind": "market_status", "payload": payload, "channel_id": str(market_cfg.get("channel_id") or self.default_chat_id), "dedupe_key": dedupe_key}
        return self._enqueue(item)

    def enqueue_gift_signal(self, signal_event: dict) -> bool:
        effective = self.effective_settings()
        if not bool(effective.get("enabled")):
            return False
        signal_cfg = effective.get("gift_signal") if isinstance(effective.get("gift_signal"), dict) else {}
        if not bool(signal_cfg.get("enabled")):
            return False
        payload = signal_event.get("payload") if isinstance(signal_event.get("payload"), dict) else signal_event
        gate_cfg = (((effective.get("publish_gates") or {}).get("gift_signal_channel") or {}) if isinstance(effective.get("publish_gates"), dict) else {})
        gate_values = {
            "gift_signal_channel": {
                "all": [
                    {"metric": "edgeRank100", "op": ">=", "value": _safe_float(gate_cfg.get("edgeRank100_gte"), 55.0)},
                    {"metric": "conf_pct", "op": ">=", "value": _safe_float(gate_cfg.get("conf_pct_gte"), 35.0)},
                    {"metric": "expected_profit_pct", "op": ">=", "value": _safe_float(gate_cfg.get("expected_profit_pct_gte"), 8.0)},
                ]
            }
        }
        gate_result = GateEngine(gate_values).evaluate("gift_signal_channel", payload)
        if not bool(gate_result.get("ok")):
            adaptive_sparse = bool(gate_cfg.get("adaptive_sparse_fallback", True))
            action = str((payload or {}).get("action") or (payload or {}).get("type") or "").upper()
            data_quality = str((payload or {}).get("data_quality") or "").lower()
            if not (adaptive_sparse and data_quality == "sparse" and action == "SELL"):
                return False
            # In sparse production mode, SELL is already produced by the backend decision engine
            # after regime/risk evaluation, while score/conf/profit can collapse to near-zero due to
            # degraded analytics coverage. Allow those SELL signals through as a dedicated fallback.
            return self._enqueue(
                {
                    "kind": "gift_signal",
                    "payload": payload,
                    "channel_id": str(signal_cfg.get("channel_id") or self.default_chat_id),
                    "include_image": bool(signal_cfg.get("include_image", True)),
                    "dedupe_key": f"signal:{str((payload or {}).get('signal_id') or '')}:{str((payload or {}).get('ts') or signal_event.get('ts') or '')}",
                }
            )
        signal_id = str((payload or {}).get("signal_id") or "")
        ts = str((payload or {}).get("ts") or signal_event.get("ts") or "")
        dedupe_key = f"signal:{signal_id}:{ts}"
        item = {
            "kind": "gift_signal",
            "payload": payload,
            "channel_id": str(signal_cfg.get("channel_id") or self.default_chat_id),
            "include_image": bool(signal_cfg.get("include_image", True)),
            "dedupe_key": dedupe_key,
        }
        return self._enqueue(item)

    def send_test(self, kind: str, payload: dict) -> dict:
        effective = self.effective_settings()
        target_kind = str(kind or "gift_signal").strip().lower()
        if target_kind == "market_status":
            text = self.renderer.render_market_status(payload)
            channel_id = str((((effective.get("market_status") or {}).get("channel_id")) or self.default_chat_id))
            include_image = False
        else:
            text = self.renderer.render_gift_signal(payload)
            channel_id = str((((effective.get("gift_signal") or {}).get("channel_id")) or self.default_chat_id))
            include_image = bool((((effective.get("gift_signal") or {}).get("include_image")) if isinstance(effective.get("gift_signal"), dict) else True))
        try:
            self._deliver_message(channel_id=channel_id, text=text, preview_url=str(payload.get("preview_url") or "") if include_image else "", include_image=include_image, settings=effective)
            return {"ok": True, "kind": target_kind, "preview": text, "sent": True}
        except Exception as exc:
            return {"ok": False, "kind": target_kind, "preview": text, "sent": False, "error": f"{exc.__class__.__name__}:{exc}"}

    def send_now(self, *, kind: str, payload: dict, channel_id: str, include_image: bool | None = None, bypass_gates: bool = False) -> dict:
        effective = self.effective_settings()
        target_kind = str(kind or "gift_signal").strip().lower()
        if target_kind == "gift_signal" and not bypass_gates:
            gate_values = {
                "gift_signal_channel": {
                    "all": [
                        {"metric": "edgeRank100", "op": ">=", "value": _safe_float((((effective.get("publish_gates") or {}).get("gift_signal_channel") or {}).get("edgeRank100_gte")), 55.0)},
                        {"metric": "conf_pct", "op": ">=", "value": _safe_float((((effective.get("publish_gates") or {}).get("gift_signal_channel") or {}).get("conf_pct_gte")), 35.0)},
                        {"metric": "expected_profit_pct", "op": ">=", "value": _safe_float((((effective.get("publish_gates") or {}).get("gift_signal_channel") or {}).get("expected_profit_pct_gte")), 8.0)},
                    ]
                }
            }
            gate_result = GateEngine(gate_values).evaluate("gift_signal_channel", payload)
            if not bool(gate_result.get("ok")):
                return {"ok": False, "kind": target_kind, "sent": False, "error": "publish_gate_blocked", "preview": self.renderer.render_gift_signal(payload)}
        if target_kind == "market_status":
            text = self.renderer.render_market_status(payload)
            with_image = False
        else:
            text = self.renderer.render_gift_signal(payload)
            with_image = bool(include_image if include_image is not None else True)
        try:
            self._deliver_message(channel_id=str(channel_id or self.default_chat_id), text=text, preview_url=str(payload.get("preview_url") or "") if with_image else "", include_image=with_image, settings=effective)
            return {"ok": True, "kind": target_kind, "sent": True, "preview": text}
        except Exception as exc:
            return {"ok": False, "kind": target_kind, "sent": False, "error": f"{exc.__class__.__name__}:{exc}", "preview": text}

    def _sanitize_patch(self, patch: dict) -> dict:
        src = patch if isinstance(patch, dict) else {}
        out: dict[str, Any] = {}
        if "enabled" in src:
            out["enabled"] = bool(src.get("enabled"))
        for key in ("market_status", "gift_signal"):
            row = src.get(key) if isinstance(src.get(key), dict) else None
            if not isinstance(row, dict):
                continue
            item: dict[str, Any] = {}
            if "enabled" in row:
                item["enabled"] = bool(row.get("enabled"))
            if "channel_id" in row:
                item["channel_id"] = str(row.get("channel_id") or "").strip()
            if key == "market_status" and "min_interval_sec" in row:
                item["min_interval_sec"] = max(60, min(_safe_int(row.get("min_interval_sec"), 900), 86400))
            if key == "gift_signal" and "include_image" in row:
                item["include_image"] = bool(row.get("include_image"))
            if item:
                out[key] = item
        gates = src.get("publish_gates") if isinstance(src.get("publish_gates"), dict) else None
        if isinstance(gates, dict):
            signal_gate = gates.get("gift_signal_channel") if isinstance(gates.get("gift_signal_channel"), dict) else {}
            out["publish_gates"] = {
                "gift_signal_channel": {
                    "edgeRank100_gte": _clamp(_safe_float(signal_gate.get("edgeRank100_gte"), 55.0), 0.0, 100.0),
                    "conf_pct_gte": _clamp(_safe_float(signal_gate.get("conf_pct_gte"), 35.0), 0.0, 100.0),
                    "expected_profit_pct_gte": _clamp(_safe_float(signal_gate.get("expected_profit_pct_gte"), 8.0), 0.0, 1000.0),
                    "adaptive_sparse_fallback": bool(signal_gate.get("adaptive_sparse_fallback", True)),
                    "adaptive_sparse_edgeRank100_gte": _clamp(_safe_float(signal_gate.get("adaptive_sparse_edgeRank100_gte"), 1.0), 0.0, 100.0),
                    "adaptive_sparse_conf_pct_gte": _clamp(_safe_float(signal_gate.get("adaptive_sparse_conf_pct_gte"), 10.0), 0.0, 100.0),
                    "adaptive_sparse_expected_profit_pct_gte": _clamp(_safe_float(signal_gate.get("adaptive_sparse_expected_profit_pct_gte"), 0.0), 0.0, 1000.0),
                }
            }
        transport = src.get("transport") if isinstance(src.get("transport"), dict) else None
        if isinstance(transport, dict):
            out["transport"] = {
                "timeout_sec": max(3, min(_safe_int(transport.get("timeout_sec"), 12), 120)),
                "max_retries": max(1, min(_safe_int(transport.get("max_retries"), 3), 10)),
                "retry_backoff_sec": _clamp(_safe_float(transport.get("retry_backoff_sec"), 1.5), 0.1, 30.0),
                "rate_limit_per_minute": max(1, min(_safe_int(transport.get("rate_limit_per_minute"), 20), 120)),
                "dedupe_ttl_sec": max(60, min(_safe_int(transport.get("dedupe_ttl_sec"), 600), 86400)),
            }
        return out

    def _enqueue(self, item: dict) -> bool:
        try:
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            self._bump_stat("dropped_total", error="queue_full")
            return False

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._process_item(item)
            except Exception as exc:
                self._record_failure(str(item.get("dedupe_key") or "unknown"), f"{exc.__class__.__name__}:{exc}")
            finally:
                self._queue.task_done()

    def _process_item(self, item: dict) -> None:
        effective = self.effective_settings()
        kind = str(item.get("kind") or "")
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        channel_id = str(item.get("channel_id") or self.default_chat_id)
        dedupe_key = str(item.get("dedupe_key") or "")
        if not dedupe_key or not channel_id:
            return
        if self._is_duplicate(dedupe_key, effective):
            return
        if kind == "market_status":
            market_cfg = effective.get("market_status") if isinstance(effective.get("market_status"), dict) else {}
            min_interval_sec = max(60, min(_safe_int(market_cfg.get("min_interval_sec"), 900), 86400))
            if self._recent_kind_sent(kind, channel_id, min_interval_sec):
                return
        if kind == "market_status":
            text = self.renderer.render_market_status(payload)
            include_image = False
            preview_url = ""
        else:
            text = self.renderer.render_gift_signal(payload)
            include_image = bool(item.get("include_image", True))
            preview_url = str(payload.get("preview_url") or "") if include_image else ""
        self._deliver_message(channel_id=channel_id, text=text, preview_url=preview_url, include_image=include_image, settings=effective)
        self._mark_sent(dedupe_key, kind, channel_id, preview_text=text, payload=payload if kind == "gift_signal" else None)

    def _deliver_message(self, *, channel_id: str, text: str, preview_url: str, include_image: bool, settings: dict) -> None:
        if not self.bot_token:
            raise RuntimeError("telegram_bot_token_not_configured")
        transport = settings.get("transport") if isinstance(settings.get("transport"), dict) else {}
        timeout_sec = max(3, min(_safe_int(transport.get("timeout_sec"), 12), 120))
        max_retries = max(1, min(_safe_int(transport.get("max_retries"), 3), 10))
        backoff = _clamp(_safe_float(transport.get("retry_backoff_sec"), 1.5), 0.1, 30.0)
        self._apply_rate_limit(channel_id, settings)
        message_text = str(text or "").strip()
        if not message_text:
            raise RuntimeError("empty_message")
        last_error: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                if include_image and preview_url:
                    self._telegram_post("sendPhoto", {"chat_id": channel_id, "photo": preview_url, "caption": message_text[:1024]}, timeout_sec=timeout_sec)
                else:
                    self._telegram_post("sendMessage", {"chat_id": channel_id, "text": message_text[:4096]}, timeout_sec=timeout_sec)
                return
            except Exception as exc:
                last_error = exc
                if attempt >= max_retries:
                    break
                time.sleep(backoff * attempt)
        raise last_error if last_error is not None else RuntimeError("telegram_delivery_failed")

    def _telegram_post(self, method: str, payload: dict[str, Any], *, timeout_sec: int) -> dict:
        url = f"https://api.telegram.org/bot{self.bot_token}/{method}"
        body = urllib.parse.urlencode({k: str(v) for k, v in payload.items()}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        if not bool(raw.get("ok")):
            raise RuntimeError(f"telegram_api_error:{raw.get('description')}")
        return raw

    def _apply_rate_limit(self, channel_id: str, settings: dict) -> None:
        transport = settings.get("transport") if isinstance(settings.get("transport"), dict) else {}
        per_minute = max(1, min(_safe_int(transport.get("rate_limit_per_minute"), 20), 120))
        now = time.time()
        with self._rate_lock:
            bucket = self._rate_state.setdefault(channel_id, [])
            bucket[:] = [ts for ts in bucket if now - ts < 60.0]
            if len(bucket) >= per_minute:
                sleep_sec = max(0.0, 60.0 - (now - bucket[0]))
            else:
                sleep_sec = 0.0
            if sleep_sec > 0.0:
                time.sleep(min(sleep_sec, 5.0))
                now = time.time()
                bucket[:] = [ts for ts in bucket if now - ts < 60.0]
            bucket.append(now)

    def _is_duplicate(self, dedupe_key: str, settings: dict) -> bool:
        transport = settings.get("transport") if isinstance(settings.get("transport"), dict) else {}
        ttl = max(60, min(_safe_int(transport.get("dedupe_ttl_sec"), 600), 86400))
        sent = self._journal.get("sent") if isinstance(self._journal.get("sent"), dict) else {}
        entry = sent.get(dedupe_key) if isinstance(sent.get(dedupe_key), dict) else None
        if not isinstance(entry, dict):
            return False
        ts = _safe_float(entry.get("mono_ts"), 0.0)
        return (time.monotonic() - ts) <= ttl

    def _mark_sent(self, dedupe_key: str, kind: str, channel_id: str, *, preview_text: str = "", payload: dict | None = None) -> None:
        with self._lock:
            sent = self._journal.setdefault("sent", {})
            if not isinstance(sent, dict):
                sent = {}
                self._journal["sent"] = sent
            entry = {
                "kind": kind,
                "channel_id": channel_id,
                "sent_at": _utcnow_iso(),
                "mono_ts": time.monotonic(),
            }
            if preview_text:
                entry["preview_text"] = str(preview_text)
            if isinstance(payload, dict) and kind == "gift_signal":
                entry["payload"] = payload
            sent[dedupe_key] = entry
            if len(sent) > 4000:
                items = sorted(sent.items(), key=lambda kv: _safe_float(((kv[1] or {}).get("mono_ts")), 0.0), reverse=True)[:3000]
                self._journal["sent"] = dict(items)
            self._bump_stat("sent_total")
            _save_json_atomic(self.journal_path, self._journal)

    def _recent_kind_sent(self, kind: str, channel_id: str, interval_sec: int) -> bool:
        sent = self._journal.get("sent") if isinstance(self._journal.get("sent"), dict) else {}
        now_mono = time.monotonic()
        for value in sent.values():
            if not isinstance(value, dict):
                continue
            if str(value.get("kind") or "") != kind:
                continue
            if str(value.get("channel_id") or "") != channel_id:
                continue
            mono_ts = _safe_float(value.get("mono_ts"), 0.0)
            if mono_ts > 0 and (now_mono - mono_ts) <= float(interval_sec):
                return True
        return False

    def _record_failure(self, dedupe_key: str, error: str) -> None:
        with self._lock:
            failed = self._journal.setdefault("failed", [])
            if not isinstance(failed, list):
                failed = []
                self._journal["failed"] = failed
            failed.append({"key": dedupe_key, "error": error, "ts": _utcnow_iso()})
            if len(failed) > 200:
                self._journal["failed"] = failed[-200:]
            self._bump_stat("failed_total", error=error)
            _save_json_atomic(self.journal_path, self._journal)

    def _bump_stat(self, field: str, error: str | None = None) -> None:
        stats = self._journal.setdefault("stats", {})
        if not isinstance(stats, dict):
            stats = {}
            self._journal["stats"] = stats
        stats[field] = _safe_int(stats.get(field), 0) + 1
        if field == "sent_total":
            stats["last_sent_at"] = _utcnow_iso()
        if error:
            stats["last_error"] = error

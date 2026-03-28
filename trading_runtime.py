from __future__ import annotations

import base64
from contextlib import closing
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

try:
    import psycopg  # type: ignore
except Exception:  # pragma: no cover
    psycopg = None

try:
    import redis as redis_lib  # type: ignore
except Exception:  # pragma: no cover
    redis_lib = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    target = dt or _now_utc()
    return target.isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{int(time.time() * 1000)}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


class TradeRuntime:
    def __init__(
        self,
        data_dir: Path,
        *,
        quote_secret: str,
        quote_ttl_sec: int = 5,
        db_path: Path | None = None,
        postgres_dsn: str | None = None,
        redis_url: str | None = None,
        tx_verify_url: str | None = None,
        tx_verify_token: str | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.quote_secret = str(quote_secret or "gmz-trade-quote-secret").encode("utf-8")
        self.quote_ttl_sec = max(3, min(int(quote_ttl_sec or 5), 10))
        self.db_path = Path(db_path) if db_path else None
        self.postgres_dsn = str(postgres_dsn or "").strip()
        self.redis_url = str(redis_url or "").strip()
        self.tx_verify_url = str(tx_verify_url or "").strip()
        self.tx_verify_token = str(tx_verify_token or "").strip()
        self.intents_file = data_dir / "trade_intents_store.json"
        self.positions_file = data_dir / "trade_positions_store.json"
        self.holdings_file = data_dir / "trade_holdings_store.json"
        self.autosell_file = data_dir / "trade_autosell_rules_store.json"
        self.autosell_state_file = data_dir / "trade_autosell_state_store.json"
        self.wallet_activity_file = data_dir / "trade_wallet_activity_store.json"
        self.events_file = data_dir / "trade_events_store.json"
        self.quotes_file = data_dir / "trade_quotes_store.json"
        self.used_quotes: dict[str, float] = {}
        self._pg_enabled = bool(self.postgres_dsn and psycopg is not None)
        self._redis = None
        if self.db_path:
            self._init_db()
        if self._pg_enabled:
            self._init_postgres()
        if self.redis_url and redis_lib is not None:
            try:
                self._redis = redis_lib.Redis.from_url(self.redis_url, decode_responses=True)
            except Exception:
                self._redis = None

    @property
    def _pg_store_map(self) -> dict[str, tuple[str, str, tuple[str, ...]]]:
        return {
            self.intents_file.name: ("trade_intents", "intent_id", ("wallet_address", "variant_id", "status", "created_at", "expires_at", "source", "intent_type")),
            self.positions_file.name: ("positions", "position_id", ("wallet_address", "variant_id", "updated_at")),
            self.holdings_file.name: ("holdings", "holding_id", ("wallet_address", "variant_id", "status", "updated_at")),
            self.autosell_file.name: ("autosell_rules", "rule_id", ("wallet_address", "enabled", "scope", "trigger_type", "mode", "priority", "updated_at")),
            self.wallet_activity_file.name: ("wallet_activity_runtime", "activity_id", ("wallet_address", "ts")),
            self.quotes_file.name: ("trade_quote_state", "nonce", ("state", "expires_at")),
            self.autosell_state_file.name: ("trade_autosell_state", "state_key", ("updated_at",)),
        }

    def list_trade_intents(self, wallet_address: str, status: str | None = None, limit: int = 100, cursor: str | None = None) -> dict:
        items = [x for x in self._read_list(self.intents_file) if str(x.get("wallet_address") or "") == str(wallet_address or "")]
        self._expire_stale_intents(items)
        self.reconcile_broadcast_intents(wallet_address=wallet_address)
        items = [x for x in self._read_list(self.intents_file) if str(x.get("wallet_address") or "") == str(wallet_address or "")]
        if status:
            items = [x for x in items if str(x.get("status") or "") == str(status)]
        items.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
        start = int(cursor or 0) if str(cursor or "").isdigit() else 0
        end = start + max(1, min(int(limit or 100), 500))
        next_cursor = str(end) if end < len(items) else None
        return {"items": items[start:end], "next_cursor": next_cursor}

    def get_trade_intent(self, intent_id: str) -> dict | None:
        rows = self._read_list(self.intents_file)
        self._expire_stale_intents(rows)
        self.reconcile_broadcast_intents()
        for row in rows:
            if str(row.get("intent_id") or "") == str(intent_id or ""):
                return row
        return None

    def create_trade_intent(self, payload: dict, *, market_regime: str, variant_snapshot: dict | None) -> dict:
        intent_type = str(payload.get("intent_type") or "").upper()
        wallet_address = str(payload.get("wallet_address") or "").strip()
        variant_id = str(payload.get("variant_id") or "").strip()
        if intent_type not in {"BUY", "BUY_AND_LIST", "SELL", "LIST", "CANCEL_LISTING", "TRANSFER"}:
            raise ValueError("unsupported_intent_type")
        if not wallet_address or not variant_id:
            raise ValueError("missing_required_fields")
        idem = str(payload.get("idempotency_key") or "").strip()
        intents = self._read_list(self.intents_file)
        if idem:
            for row in intents:
                if str(row.get("idempotency_key") or "") == idem:
                    return {"intent": row, "wallet_tx": self._wallet_tx_for_intent(row)}
        now = _now_utc()
        item = {
            "intent_id": f"ti_{secrets.token_hex(8)}",
            "intent_type": intent_type,
            "variant_id": variant_id,
            "wallet_address": wallet_address,
            "listing_id": payload.get("listing_id"),
            "gift_unique_id": payload.get("gift_unique_id"),
            "price_ton": payload.get("price_ton"),
            "max_spend_ton": payload.get("max_spend_ton"),
            "fee_budget_ton": payload.get("fee_budget_ton"),
            "status": "PENDING_SIGNATURE",
            "source": "STANDARD",
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(minutes=10)),
            "tx_hash": None,
            "chain_id": payload.get("chain_id") or (f"chain_{secrets.token_hex(6)}" if intent_type == "BUY_AND_LIST" else None),
            "parent_intent_id": payload.get("parent_intent_id"),
            "step_index": payload.get("step_index"),
            "chain_policy": payload.get("chain_policy"),
            "post_action": payload.get("post_action"),
            "reasons": list((variant_snapshot or {}).get("reasons") or []),
            "risk_flags": list((variant_snapshot or {}).get("risk_flags") or []),
            "decision_trace": {
                "market_regime": market_regime,
                "variant_label": (variant_snapshot or {}).get("variant_label"),
                "requested_intent_type": intent_type,
            },
            "idempotency_key": idem or None,
        }
        intents.append(item)
        self._write_list(self.intents_file, intents)
        self._append_event("trade.intent.created", item)
        return {"intent": item, "wallet_tx": self._wallet_tx_for_intent(item)}

    def confirm_intent_signature(self, intent_id: str, payload: dict, *, market_regime: str, variant_snapshot: dict | None) -> dict:
        intents = self._read_list(self.intents_file)
        target = None
        for row in intents:
            if str(row.get("intent_id") or "") == str(intent_id or ""):
                target = row
                break
        if not isinstance(target, dict):
            raise KeyError("intent_not_found")
        if str(target.get("status") or "") in {"CONFIRMED", "BROADCAST", "SIGNED"} and str(target.get("tx_hash") or "") == str(payload.get("tx_hash") or ""):
            return target
        target["tx_hash"] = str(payload.get("tx_hash") or "").strip() or target.get("tx_hash")
        target["status"] = "SIGNED"
        target.setdefault("status_timeline", []).append({"status": "SIGNED", "ts": _iso()})
        self._append_event("trade.intent.signed", target)
        target["status"] = "BROADCAST"
        target.setdefault("status_timeline", []).append({"status": "BROADCAST", "ts": _iso()})
        self._append_event("trade.intent.broadcast", target)
        target["status"] = "CONFIRMED"
        target.setdefault("status_timeline", []).append({"status": "CONFIRMED", "ts": _iso()})
        self._write_list(self.intents_file, intents)
        self._apply_confirmed_intent(target, market_regime=market_regime, variant_snapshot=variant_snapshot)
        self._append_event("trade.intent.confirmed", target)
        return target

    def issue_buy_quote(self, *, variant_id: str, max_price_ton: float, slippage_bps: int, wallet_address: str | None, variant_snapshot: dict | None) -> dict:
        snapshot = variant_snapshot or {}
        nonce = secrets.token_hex(10)
        now = _now_utc()
        fee_budget = max(0.03, round(max_price_ton * 0.01, 4))
        quote = {
            "variant_id": variant_id,
            "listing_id": snapshot.get("listing_id"),
            "max_price_ton": round(float(max_price_ton), 6),
            "slippage_bps": int(slippage_bps),
            "fee_budget_ton": fee_budget,
            "wallet_address_hash": hashlib.sha256(str(wallet_address or "").encode("utf-8")).hexdigest() if wallet_address else None,
            "nonce": nonce,
            "issued_at": int(now.timestamp()),
        }
        body = json.dumps(quote, sort_keys=True, separators=(",", ":")).encode("utf-8")
        sig = hmac.new(self.quote_secret, body, hashlib.sha256).hexdigest()
        token = base64.urlsafe_b64encode(json.dumps({"quote": quote, "sig": sig}).encode("utf-8")).decode("utf-8")
        payload = {"buy_quote_token": token, "expires_at": _iso(now + timedelta(seconds=self.quote_ttl_sec)), "quote": {k: v for k, v in quote.items() if k != "issued_at"}}
        self._upsert_quote_state(nonce, {
            "nonce": nonce,
            "state": "ISSUED",
            "variant_id": variant_id,
            "wallet_address_hash": quote.get("wallet_address_hash"),
            "issued_at": _iso(now),
            "expires_at": payload["expires_at"],
            "buy_quote_token": token,
        })
        self._append_event("trade.quote.issued", payload)
        return payload

    def confirm_fast_buy(self, payload: dict, *, market_regime: str, variant_snapshot: dict | None) -> dict:
        token = str(payload.get("buy_quote_token") or "").strip()
        tx_hash = str(payload.get("tx_hash") or "").strip()
        wallet_address = str(payload.get("wallet_address") or "").strip()
        if not token or not tx_hash or not wallet_address:
            raise ValueError("missing_fast_confirm_fields")
        quote = self._decode_quote(token)
        nonce = str(((quote or {}).get("quote") or {}).get("nonce") or "")
        if not nonce:
            raise ValueError("invalid_quote")
        quote_state = self._get_quote_state(nonce)
        if isinstance(quote_state, dict) and str(quote_state.get("state") or "") in {"LOCKED", "USED"}:
            raise RuntimeError("quote_nonce_already_used")
        if self._redis is not None:
            try:
                if self._redis.exists(f"used_quote:{nonce}"):
                    raise RuntimeError("quote_nonce_already_used")
            except RuntimeError:
                raise
            except Exception:
                pass
        if nonce in self.used_quotes and self.used_quotes[nonce] > time.time():
            raise RuntimeError("quote_nonce_already_used")
        issued_at = _as_int(((quote or {}).get("quote") or {}).get("issued_at"), 0)
        if issued_at <= 0 or (time.time() - issued_at) > self.quote_ttl_sec:
            self._upsert_quote_state(nonce, {"state": "EXPIRED", "last_checked_at": _iso()})
            raise TimeoutError("quote_expired")
        wallet_hash = ((quote or {}).get("quote") or {}).get("wallet_address_hash")
        if wallet_hash and wallet_hash != hashlib.sha256(wallet_address.encode("utf-8")).hexdigest():
            raise ValueError("wallet_address_mismatch")
        self._upsert_quote_state(nonce, {"state": "LOCKED", "locked_at": _iso(), "wallet_address": wallet_address, "tx_hash": tx_hash})
        self.used_quotes[nonce] = time.time() + 30.0
        if self._redis is not None:
            try:
                self._redis.setex(f"used_quote:{nonce}", 30, "LOCKED")
            except Exception:
                pass
        quote_payload = (quote or {}).get("quote") or {}
        item = self.create_trade_intent(
            {
                "intent_type": "BUY",
                "variant_id": quote_payload.get("variant_id"),
                "wallet_address": wallet_address,
                "max_spend_ton": quote_payload.get("max_price_ton"),
                "fee_budget_ton": quote_payload.get("fee_budget_ton"),
                "idempotency_key": f"fast:{nonce}",
            },
            market_regime=market_regime,
            variant_snapshot=variant_snapshot,
        )["intent"]
        item["source"] = "FAST_BUY"
        item["status"] = "BROADCAST"
        item["tx_hash"] = tx_hash
        item.setdefault("status_timeline", []).append({"status": "BROADCAST", "ts": _iso()})
        intents = self._read_list(self.intents_file)
        for idx, row in enumerate(intents):
            if str(row.get("intent_id") or "") == str(item.get("intent_id") or ""):
                intents[idx] = item
                break
        self._write_list(self.intents_file, intents)
        self._append_event("trade.quote.used", {"nonce": nonce, "wallet_address": wallet_address, "tx_hash": tx_hash})
        self._upsert_quote_state(nonce, {"state": "USED", "used_at": _iso(), "intent_id": item.get("intent_id")})
        self._append_event("trade.intent.broadcast", item)
        item["status"] = "CONFIRMED"
        item.setdefault("status_timeline", []).append({"status": "CONFIRMED", "ts": _iso()})
        intents = self._read_list(self.intents_file)
        for idx, row in enumerate(intents):
            if str(row.get("intent_id") or "") == str(item.get("intent_id") or ""):
                intents[idx] = item
                break
        self._write_list(self.intents_file, intents)
        self._apply_confirmed_intent(item, market_regime=market_regime, variant_snapshot=variant_snapshot)
        self._append_event("trade.intent.confirmed", item)
        return item

    def list_positions(self, wallet_address: str) -> dict:
        items = [x for x in self._read_list(self.positions_file) if str(x.get("wallet_address") or "") == str(wallet_address or "")]
        items.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
        return {"items": items}

    def list_holdings(self, wallet_address: str) -> dict:
        items = [x for x in self._read_list(self.holdings_file) if str(x.get("wallet_address") or "") == str(wallet_address or "")]
        items.sort(key=lambda x: str(x.get("updated_at") or x.get("acquired_at") or ""), reverse=True)
        return {"items": items}

    def get_pnl_summary(self, wallet_address: str, *, market_regime: str) -> dict:
        positions = self.list_positions(wallet_address).get("items") or []
        realized_ton = sum(_as_float(x.get("realized_pnl_ton"), 0.0) for x in positions)
        unrealized_ton = sum(_as_float(x.get("unrealized_pnl_ton"), 0.0) for x in positions)
        exposure_ton = sum(_as_float(x.get("mark_price_ton"), 0.0) * _as_float(x.get("qty"), 0.0) for x in positions)
        return {
            "pnl_today_ton": round(realized_ton + unrealized_ton, 6),
            "pnl_today_pct": round(((realized_ton + unrealized_ton) / exposure_ton) * 100.0, 2) if exposure_ton > 0 else 0.0,
            "pnl_7d_ton": round(realized_ton, 6),
            "pnl_30d_ton": round(realized_ton, 6),
            "win_rate": 100.0 if realized_ton >= 0 and positions else 0.0,
            "avg_hold_min": 0.0,
            "best_trade_ton": max([0.0] + [_as_float(x.get("realized_pnl_ton"), 0.0) for x in positions]),
            "worst_trade_ton": min([0.0] + [_as_float(x.get("realized_pnl_ton"), 0.0) for x in positions]),
            "exposure_ton": round(exposure_ton, 6),
            "market_regime": market_regime,
        }

    def list_autosell_rules(self, wallet_address: str) -> dict:
        items = [x for x in self._read_list(self.autosell_file) if str(x.get("wallet_address") or "") == str(wallet_address or "")]
        items.sort(key=lambda x: (int(x.get("priority") or 0), str(x.get("updated_at") or "")))
        return {"items": items}

    def upsert_autosell_rule(self, payload: dict) -> dict:
        wallet_address = str(payload.get("wallet_address") or "").strip()
        if not wallet_address:
            raise ValueError("wallet_address_required")
        rules = self._read_list(self.autosell_file)
        rule_id = str(payload.get("rule_id") or "").strip() or f"asr_{secrets.token_hex(6)}"
        item = {
            "rule_id": rule_id,
            "wallet_address": wallet_address,
            "enabled": bool(payload.get("enabled", True)),
            "scope": str(payload.get("scope") or "*"),
            "trigger_type": str(payload.get("trigger_type") or "TAKE_PROFIT"),
            "params": payload.get("params") if isinstance(payload.get("params"), dict) else {},
            "mode": str(payload.get("mode") or "NOTIFY_ONLY"),
            "list_price_strategy": payload.get("list_price_strategy"),
            "cooldown_sec": max(0, _as_int(payload.get("cooldown_sec"), 0)),
            "priority": max(0, _as_int(payload.get("priority"), 100)),
            "updated_at": _iso(),
        }
        updated = False
        for idx, row in enumerate(rules):
            if str(row.get("rule_id") or "") == rule_id:
                rules[idx] = item
                updated = True
                break
        if not updated:
            rules.append(item)
        self._write_list(self.autosell_file, rules)
        return item

    def wallet_activity(self, wallet_address: str, limit: int = 50, cursor: str | None = None) -> dict:
        items = [x for x in self._read_list(self.wallet_activity_file) if str(x.get("wallet_address") or "") == str(wallet_address or "")]
        items.sort(key=lambda x: str(x.get("ts") or ""), reverse=True)
        start = int(cursor or 0) if str(cursor or "").isdigit() else 0
        end = start + max(1, min(int(limit or 50), 200))
        return {"items": items[start:end], "next_cursor": str(end) if end < len(items) else None}

    def stream_events(self, wallet_address: str, kinds: set[str] | None = None, limit: int = 100) -> list[dict]:
        if self.db_path:
            return self._db_stream_events(wallet_address, kinds=kinds, limit=limit)
        rows = self._read_list(self.events_file)
        out = []
        wanted = kinds or set()
        for row in reversed(rows[-max(1, min(limit, 500)):]):
            if not isinstance(row, dict):
                continue
            ev = str(row.get("event") or "")
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            candidate_wallet = str(payload.get("wallet_address") or "")
            if wallet_address and candidate_wallet and candidate_wallet != wallet_address:
                continue
            if wanted and ev not in wanted:
                continue
            out.append(row)
        return out

    def retry_chain_list_intent(self, parent_intent_id: str) -> dict:
        intents = self._read_list(self.intents_file)
        parent = next((x for x in intents if str(x.get("intent_id") or "") == str(parent_intent_id or "")), None)
        if not isinstance(parent, dict):
            raise KeyError("parent_intent_not_found")
        if str(parent.get("chain_policy") or "") != "BUY_THEN_LIST":
            raise ValueError("retry_not_allowed")
        current_children = [x for x in intents if str(x.get("parent_intent_id") or "") == str(parent_intent_id)]
        active_child = next((x for x in current_children if str(x.get("status") or "") in {"PENDING_SIGNATURE", "SIGNED", "BROADCAST"}), None)
        if isinstance(active_child, dict):
            return active_child
        post_action = parent.get("post_action") if isinstance(parent.get("post_action"), dict) else {}
        listing_params = post_action.get("listing_params") if isinstance(post_action.get("listing_params"), dict) else {"list_price_ton": parent.get("price_ton"), "duration_sec": 86400, "marketplace": "fragment"}
        child = {
            "intent_id": f"ti_{secrets.token_hex(8)}",
            "intent_type": "LIST",
            "variant_id": parent.get("variant_id"),
            "wallet_address": parent.get("wallet_address"),
            "listing_id": None,
            "gift_unique_id": None,
            "price_ton": listing_params.get("list_price_ton"),
            "max_spend_ton": None,
            "fee_budget_ton": None,
            "status": "PENDING_SIGNATURE",
            "source": "STANDARD",
            "created_at": _iso(),
            "expires_at": _iso(_now_utc() + timedelta(minutes=10)),
            "tx_hash": None,
            "chain_id": parent.get("chain_id"),
            "parent_intent_id": parent.get("intent_id"),
            "step_index": 2,
            "chain_policy": "BUY_THEN_LIST",
            "post_action": {"type": "LIST", "listing_params": listing_params},
            "reasons": parent.get("reasons") or [],
            "risk_flags": parent.get("risk_flags") or [],
            "decision_trace": {"retry_from_parent": True},
            "idempotency_key": f"chain:{parent.get('chain_id')}:retry:{secrets.token_hex(4)}",
        }
        intents.append(child)
        self._write_list(self.intents_file, intents)
        self._append_event("trade.intent.created", child)
        return child

    def reconcile_broadcast_intents(self, wallet_address: str | None = None) -> None:
        intents = self._read_list(self.intents_file)
        changed = False
        for row in intents:
            if not isinstance(row, dict):
                continue
            if wallet_address and str(row.get("wallet_address") or "") != str(wallet_address or ""):
                continue
            if str(row.get("status") or "") != "BROADCAST":
                continue
            verdict = self._verify_tx_state(str(row.get("tx_hash") or ""), str(row.get("wallet_address") or ""), str(row.get("intent_id") or ""))
            state = str(verdict.get("status") or "").upper()
            if state == "CONFIRMED":
                row["status"] = "CONFIRMED"
                row.setdefault("status_timeline", []).append({"status": "CONFIRMED", "ts": _iso(), "source": verdict.get("source")})
                self._apply_confirmed_intent(row, market_regime=str(verdict.get("market_regime") or "MEAN_REVERT"), variant_snapshot=verdict.get("variant_snapshot") if isinstance(verdict.get("variant_snapshot"), dict) else None)
                self._append_event("trade.intent.confirmed", row)
                changed = True
            elif state == "FAILED":
                row["status"] = "FAILED"
                row.setdefault("status_timeline", []).append({"status": "FAILED", "ts": _iso(), "reason": verdict.get("reason")})
                self._append_event("trade.intent.failed", row)
                changed = True
        if changed:
            self._write_list(self.intents_file, intents)

    def _decode_quote(self, token: str) -> dict:
        try:
            raw = json.loads(base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8"))
        except Exception as exc:
            raise ValueError("invalid_quote_token") from exc
        quote = raw.get("quote") if isinstance(raw.get("quote"), dict) else {}
        sig = str(raw.get("sig") or "")
        body = json.dumps(quote, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected = hmac.new(self.quote_secret, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("invalid_quote_signature")
        return raw

    def _verify_tx_state(self, tx_hash: str, wallet_address: str, intent_id: str) -> dict:
        if not tx_hash:
            return {"status": "FAILED", "reason": "tx_hash_missing", "source": "runtime"}
        if self.tx_verify_url:
            q = f"tx_hash={urllib.parse.quote(tx_hash, safe='')}&wallet_address={urllib.parse.quote(wallet_address, safe='')}"
            url = self.tx_verify_url + ("&" if "?" in self.tx_verify_url else "?") + q
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            if self.tx_verify_token:
                req.add_header("Authorization", f"Bearer {self.tx_verify_token}")
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                status = str(payload.get("status") or "PENDING").upper()
                return {
                    "status": status,
                    "reason": payload.get("reason"),
                    "source": "provider",
                    "market_regime": payload.get("market_regime") or "MEAN_REVERT",
                    "variant_snapshot": payload.get("variant_snapshot"),
                }
            except urllib.error.HTTPError as exc:
                return {"status": "FAILED" if exc.code in {400, 404, 409} else "PENDING", "reason": f"provider_http_{exc.code}", "source": "provider"}
            except Exception:
                return {"status": "PENDING", "reason": "provider_unavailable", "source": "provider"}
        return {"status": "CONFIRMED", "source": "simulated", "market_regime": "MEAN_REVERT"}

    def _apply_confirmed_intent(self, intent: dict, *, market_regime: str, variant_snapshot: dict | None) -> None:
        intent_type = str(intent.get("intent_type") or "")
        wallet_address = str(intent.get("wallet_address") or "")
        variant_id = str(intent.get("variant_id") or "")
        holdings = self._read_list(self.holdings_file)
        positions = self._read_list(self.positions_file)
        now_iso = _iso()
        price_ton = _as_float(intent.get("price_ton"), _as_float(intent.get("max_spend_ton"), _as_float((variant_snapshot or {}).get("price_ton"), _as_float((variant_snapshot or {}).get("floor_ton"), 0.0))))
        fair_ton = _as_float((variant_snapshot or {}).get("fair_ton"), _as_float((variant_snapshot or {}).get("floor_ton"), price_ton))
        if intent_type in {"BUY", "BUY_AND_LIST"}:
            holding_id = f"hld_{secrets.token_hex(6)}"
            gift_unique_id = str(intent.get("gift_unique_id") or f"{variant_id}:{holding_id}")
            holdings.append({
                "holding_id": holding_id,
                "wallet_address": wallet_address,
                "gift_unique_id": gift_unique_id,
                "variant_id": variant_id,
                "acquired_price_ton": price_ton,
                "acquired_at": now_iso,
                "status": "OWNED",
                "marketplace_listing_id": None,
                "listed_price_ton": None,
                "updated_at": now_iso,
            })
            self._touch_position(positions, wallet_address, variant_id, qty_delta=1.0, buy_price=price_ton, mark_price=fair_ton, variant_snapshot=variant_snapshot)
            self._append_wallet_activity(wallet_address, amount_ton=-price_ton, tx_hash=str(intent.get("tx_hash") or ""), direction="OUT")
            if str(intent.get("chain_policy") or "") == "BUY_THEN_LIST":
                post_action = intent.get("post_action") if isinstance(intent.get("post_action"), dict) else {}
                if str(post_action.get("type") or "") == "LIST":
                    self._create_followup_list_intent(parent_intent=intent, listing_params=post_action.get("listing_params") if isinstance(post_action.get("listing_params"), dict) else {})
        elif intent_type == "LIST":
            for row in holdings:
                if str(row.get("wallet_address") or "") == wallet_address and str(row.get("variant_id") or "") == variant_id and str(row.get("status") or "") == "OWNED":
                    row["status"] = "LISTED"
                    row["marketplace_listing_id"] = str(intent.get("listing_id") or f"ml_{secrets.token_hex(5)}")
                    row["listed_price_ton"] = _as_float((intent.get("post_action") or {}).get("listing_params", {}).get("list_price_ton"), _as_float(intent.get("price_ton"), fair_ton))
                    row["updated_at"] = now_iso
                    break
        elif intent_type == "CANCEL_LISTING":
            for row in holdings:
                if str(row.get("wallet_address") or "") == wallet_address and str(row.get("variant_id") or "") == variant_id and str(row.get("status") or "") == "LISTED":
                    row["status"] = "OWNED"
                    row["marketplace_listing_id"] = None
                    row["listed_price_ton"] = None
                    row["updated_at"] = now_iso
                    break
        elif intent_type in {"SELL", "TRANSFER"}:
            for row in holdings:
                if str(row.get("wallet_address") or "") == wallet_address and str(row.get("variant_id") or "") == variant_id and str(row.get("status") or "") in {"OWNED", "LISTED"}:
                    row["status"] = "SOLD"
                    row["updated_at"] = now_iso
                    break
            self._touch_position(positions, wallet_address, variant_id, qty_delta=-1.0, buy_price=price_ton, mark_price=fair_ton, variant_snapshot=variant_snapshot)
            self._append_wallet_activity(wallet_address, amount_ton=price_ton, tx_hash=str(intent.get("tx_hash") or ""), direction="IN")
        self._write_list(self.holdings_file, holdings)
        self._write_list(self.positions_file, positions)
        pnl = self.get_pnl_summary(wallet_address, market_regime=market_regime)
        self._append_event("position.updated", {**self._latest_position_for_wallet(positions, wallet_address, variant_id), "wallet_address": wallet_address})
        self._append_event("holding.updated", {**self._latest_holding_for_wallet(holdings, wallet_address, variant_id), "wallet_address": wallet_address})
        self._append_event("pnl.updated", {**pnl, "wallet_address": wallet_address})
        self._evaluate_autosell(wallet_address=wallet_address, variant_id=variant_id, market_regime=market_regime, positions=positions, holdings=holdings, variant_snapshot=variant_snapshot)

    def _create_followup_list_intent(self, *, parent_intent: dict, listing_params: dict) -> None:
        intents = self._read_list(self.intents_file)
        idem = f"chain:{parent_intent.get('chain_id')}:step:2"
        for row in intents:
            if str(row.get("idempotency_key") or "") == idem:
                return
        now = _now_utc()
        child = {
            "intent_id": f"ti_{secrets.token_hex(8)}",
            "intent_type": "LIST",
            "variant_id": parent_intent.get("variant_id"),
            "wallet_address": parent_intent.get("wallet_address"),
            "listing_id": None,
            "gift_unique_id": None,
            "price_ton": listing_params.get("list_price_ton"),
            "max_spend_ton": None,
            "fee_budget_ton": None,
            "status": "PENDING_SIGNATURE",
            "source": "STANDARD",
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(minutes=10)),
            "tx_hash": None,
            "chain_id": parent_intent.get("chain_id"),
            "parent_intent_id": parent_intent.get("intent_id"),
            "step_index": 2,
            "chain_policy": "BUY_THEN_LIST",
            "post_action": {"type": "LIST", "listing_params": listing_params},
            "reasons": parent_intent.get("reasons") or [],
            "risk_flags": parent_intent.get("risk_flags") or [],
            "decision_trace": {"generated_from_buy_confirm": True},
            "idempotency_key": idem,
        }
        intents.append(child)
        self._write_list(self.intents_file, intents)
        self._append_event("trade.intent.created", child)

    def _touch_position(self, positions: list[dict], wallet_address: str, variant_id: str, *, qty_delta: float, buy_price: float, mark_price: float, variant_snapshot: dict | None) -> None:
        target = None
        for row in positions:
            if str(row.get("wallet_address") or "") == wallet_address and str(row.get("variant_id") or "") == variant_id:
                target = row
                break
        now_iso = _iso()
        if target is None:
            if qty_delta <= 0:
                return
            positions.append({
                "position_id": f"pos_{secrets.token_hex(6)}",
                "wallet_address": wallet_address,
                "variant_id": variant_id,
                "qty": qty_delta,
                "avg_buy_price_ton": buy_price,
                "mark_price_ton": mark_price,
                "fees_paid_ton": 0.0,
                "realized_pnl_ton": 0.0,
                "realized_pnl_pct": 0.0,
                "unrealized_pnl_ton": round((mark_price - buy_price) * qty_delta, 6),
                "unrealized_pnl_pct": round(((mark_price - buy_price) / buy_price) * 100.0, 2) if buy_price > 0 else 0.0,
                "edgeRank100": (variant_snapshot or {}).get("edgeRank100"),
                "conf_pct": (variant_snapshot or {}).get("conf_pct"),
                "action": (variant_snapshot or {}).get("action"),
                "risk_flags": list((variant_snapshot or {}).get("risk_flags") or []),
                "opened_at": now_iso,
                "updated_at": now_iso,
            })
            return
        qty_before = _as_float(target.get("qty"), 0.0)
        avg_buy = _as_float(target.get("avg_buy_price_ton"), buy_price)
        qty_after = qty_before + qty_delta
        if qty_delta > 0:
            total_cost = (qty_before * avg_buy) + (qty_delta * buy_price)
            target["qty"] = qty_after
            target["avg_buy_price_ton"] = round(total_cost / qty_after, 6) if qty_after > 0 else avg_buy
        else:
            realized = (mark_price - avg_buy) * abs(qty_delta)
            target["qty"] = max(0.0, qty_after)
            target["realized_pnl_ton"] = round(_as_float(target.get("realized_pnl_ton"), 0.0) + realized, 6)
            target["realized_pnl_pct"] = round((target["realized_pnl_ton"] / (avg_buy * max(1.0, qty_before))) * 100.0, 2) if avg_buy > 0 and qty_before > 0 else 0.0
        target["mark_price_ton"] = mark_price
        target["unrealized_pnl_ton"] = round((mark_price - _as_float(target.get("avg_buy_price_ton"), avg_buy)) * _as_float(target.get("qty"), 0.0), 6)
        target["unrealized_pnl_pct"] = round(((mark_price - _as_float(target.get("avg_buy_price_ton"), avg_buy)) / _as_float(target.get("avg_buy_price_ton"), avg_buy)) * 100.0, 2) if _as_float(target.get("avg_buy_price_ton"), avg_buy) > 0 else 0.0
        target["edgeRank100"] = (variant_snapshot or {}).get("edgeRank100")
        target["conf_pct"] = (variant_snapshot or {}).get("conf_pct")
        target["action"] = (variant_snapshot or {}).get("action")
        target["risk_flags"] = list((variant_snapshot or {}).get("risk_flags") or [])
        target["updated_at"] = now_iso
        if _as_float(target.get("qty"), 0.0) <= 0:
            positions[:] = [x for x in positions if x is not target]

    def _wallet_tx_for_intent(self, intent: dict) -> dict:
        amount = _as_float(intent.get("max_spend_ton"), _as_float(intent.get("price_ton"), 0.0))
        return {
            "validUntil": int(time.time()) + 600,
            "messages": [
                {
                    "address": "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c",
                    "amount": str(int(max(amount, 0.01) * 1_000_000_000)),
                    "payload": f"gmz:{intent.get('intent_type')}:{intent.get('intent_id')}",
                }
            ],
        }

    def _append_wallet_activity(self, wallet_address: str, *, amount_ton: float, tx_hash: str, direction: str) -> None:
        items = self._read_list(self.wallet_activity_file)
        items.append({
            "wallet_address": wallet_address,
            "ts": _iso(),
            "direction": direction,
            "amount_ton": round(amount_ton, 6),
            "counterparty": "marketplace",
            "tx_hash": tx_hash or f"tx_{secrets.token_hex(6)}",
        })
        self._write_list(self.wallet_activity_file, items[-1000:])
        self._append_event("wallet.activity.updated", {"wallet_address": wallet_address, "items": [items[-1]]})

    def _append_event(self, event: str, payload: dict) -> None:
        if self.db_path:
            self._db_append_event(event, payload)
            return
        items = self._read_list(self.events_file)
        items.append({"event": event, "ts": _iso(), "payload": payload})
        self._write_list(self.events_file, items[-2000:])
        self._redis_publish_event(event, payload)

    def _evaluate_autosell(self, *, wallet_address: str, variant_id: str, market_regime: str, positions: list[dict], holdings: list[dict], variant_snapshot: dict | None) -> None:
        rules = [x for x in self._read_list(self.autosell_file) if str(x.get("wallet_address") or "") == wallet_address and bool(x.get("enabled", True))]
        if not rules:
            return
        rules.sort(key=lambda x: (int(x.get("priority") or 0), str(x.get("updated_at") or "")))
        pos = self._latest_position_for_wallet(positions, wallet_address, variant_id)
        hold = self._latest_holding_for_wallet(holdings, wallet_address, variant_id)
        if not pos or not hold:
            return
        state = _load_json(self.autosell_state_file, {})
        if not isinstance(state, dict):
            state = {}
        state_rows = self._read_list(self.autosell_state_file)
        if isinstance(state_rows, list) and state_rows:
            state = {str((x or {}).get("state_key") or ""): x for x in state_rows if isinstance(x, dict) and str((x or {}).get("state_key") or "")}
        now_ts = time.time()
        for rule in rules:
            scope = str(rule.get("scope") or "*")
            if scope not in {"*", variant_id}:
                continue
            rule_key = f"{wallet_address}:{scope}:{rule.get('rule_id')}"
            row_state = state.get(rule_key) if isinstance(state.get(rule_key), dict) else {}
            last_trigger_ts = _as_float(row_state.get("last_trigger_ts"), 0.0)
            cooldown = max(0, _as_int(rule.get("cooldown_sec"), 0))
            if last_trigger_ts and (now_ts - last_trigger_ts) < cooldown:
                continue
            if self._pending_intent_exists(wallet_address, variant_id, kinds={"SELL", "LIST"}):
                continue
            matched, details = self._autosell_matches(rule, pos, hold, market_regime=market_regime, variant_snapshot=variant_snapshot, state=row_state)
            if not matched:
                if details.get("trailing_peak") is not None:
                    row_state["trailing_peak"] = details.get("trailing_peak")
                    row_state["state_key"] = rule_key
                    row_state["updated_at"] = _iso()
                    state[rule_key] = row_state
                    self._write_list(self.autosell_state_file, list(state.values()))
                continue
            row_state["last_trigger_ts"] = now_ts
            if details.get("trailing_peak") is not None:
                row_state["trailing_peak"] = details.get("trailing_peak")
            row_state["state_key"] = rule_key
            row_state["updated_at"] = _iso()
            state[rule_key] = row_state
            self._write_list(self.autosell_state_file, list(state.values()))
            payload = {
                "wallet_address": wallet_address,
                "variant_id": variant_id,
                "rule_id": rule.get("rule_id"),
                "trigger_type": rule.get("trigger_type"),
                "mode": rule.get("mode"),
                "details": details,
            }
            self._append_event("autosell.triggered", payload)
            mode = str(rule.get("mode") or "NOTIFY_ONLY")
            if mode == "AUTO_LIST":
                self.create_trade_intent({
                    "intent_type": "LIST",
                    "variant_id": variant_id,
                    "wallet_address": wallet_address,
                    "gift_unique_id": hold.get("gift_unique_id"),
                    "post_action": {"type": "LIST", "listing_params": {"list_price_ton": _as_float(pos.get("mark_price_ton"), 0.0), "duration_sec": 86400, "marketplace": "fragment"}},
                    "idempotency_key": f"autosell:list:{rule.get('rule_id')}:{variant_id}",
                }, market_regime=market_regime, variant_snapshot=variant_snapshot)
            elif mode == "AUTO_SELL_NOW":
                self.create_trade_intent({
                    "intent_type": "SELL",
                    "variant_id": variant_id,
                    "wallet_address": wallet_address,
                    "gift_unique_id": hold.get("gift_unique_id"),
                    "price_ton": _as_float(pos.get("mark_price_ton"), 0.0),
                    "idempotency_key": f"autosell:sell:{rule.get('rule_id')}:{variant_id}",
                }, market_regime=market_regime, variant_snapshot=variant_snapshot)
            break

    def _autosell_matches(self, rule: dict, pos: dict, hold: dict, *, market_regime: str, variant_snapshot: dict | None, state: dict) -> tuple[bool, dict]:
        trigger = str(rule.get("trigger_type") or "")
        params = rule.get("params") if isinstance(rule.get("params"), dict) else {}
        avg_buy = _as_float(pos.get("avg_buy_price_ton"), 0.0)
        mark = _as_float(pos.get("mark_price_ton"), 0.0)
        now = _now_utc()
        opened_at = str(pos.get("opened_at") or hold.get("acquired_at") or "")
        trailing_peak = max(_as_float(state.get("trailing_peak"), 0.0), mark)
        if trigger == "TAKE_PROFIT":
            tp_pct = _as_float(params.get("tp_pct"), 0.10)
            return (mark >= avg_buy * (1 + tp_pct), {"threshold": avg_buy * (1 + tp_pct)})
        if trigger == "STOP_LOSS":
            sl_pct = _as_float(params.get("sl_pct"), 0.05)
            return (mark <= avg_buy * (1 - sl_pct), {"threshold": avg_buy * (1 - sl_pct)})
        if trigger == "TRAILING_STOP":
            trailing_pct = _as_float(params.get("trailing_pct"), 0.05)
            return (mark <= trailing_peak * (1 - trailing_pct), {"trailing_peak": trailing_peak, "threshold": trailing_peak * (1 - trailing_pct)})
        if trigger == "TIME_EXIT":
            try:
                opened_dt = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
            except Exception:
                opened_dt = now
            max_hold_minutes = _as_float(params.get("max_hold_minutes"), 60.0)
            return (((now - opened_dt).total_seconds() / 60.0) >= max_hold_minutes, {"held_minutes": (now - opened_dt).total_seconds() / 60.0})
        if trigger == "REGIME_EXIT":
            regimes = {str(x) for x in (params.get("regimes") or [])} if isinstance(params.get("regimes"), list) else set()
            return (market_regime in regimes, {"market_regime": market_regime})
        if trigger == "SIGNAL_EXIT":
            snap = variant_snapshot or {}
            edge_min = _as_float(params.get("edgeRank100_min"), 55.0)
            conf_min = _as_float(params.get("conf_pct_min"), 35.0)
            profit_min = _as_float(params.get("expected_profit_pct_min"), 8.0)
            signal_action = str(snap.get("action") or "")
            matched = signal_action == "SELL" or _as_float(snap.get("edgeRank100"), 0.0) < edge_min or _as_float(snap.get("conf_pct"), 0.0) < conf_min or _as_float(snap.get("expected_profit_pct"), 0.0) < profit_min
            return (matched, {"signal_action": signal_action, "edgeRank100": snap.get("edgeRank100"), "conf_pct": snap.get("conf_pct")})
        return False, {"trailing_peak": trailing_peak}

    def _expire_stale_intents(self, intents: list[dict]) -> None:
        changed = False
        now_ts = time.time()
        for row in intents:
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "")
            if status not in {"PENDING_SIGNATURE", "SIGNED", "BROADCAST"}:
                continue
            expires_at = str(row.get("expires_at") or "")
            try:
                exp_ts = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            if exp_ts <= now_ts:
                row["status"] = "EXPIRED"
                row.setdefault("status_timeline", []).append({"status": "EXPIRED", "ts": _iso()})
                self._append_event("trade.intent.failed", row)
                changed = True
        if changed:
            self._write_list(self.intents_file, intents)

    def _pending_intent_exists(self, wallet_address: str, variant_id: str, *, kinds: set[str]) -> bool:
        for row in self._read_list(self.intents_file):
            if str(row.get("wallet_address") or "") != wallet_address:
                continue
            if str(row.get("variant_id") or "") != variant_id:
                continue
            if str(row.get("intent_type") or "") not in kinds:
                continue
            if str(row.get("status") or "") in {"PENDING_SIGNATURE", "SIGNED", "BROADCAST"}:
                return True
        return False

    def _latest_position_for_wallet(self, positions: list[dict], wallet_address: str, variant_id: str) -> dict:
        for row in reversed(positions):
            if str(row.get("wallet_address") or "") == wallet_address and str(row.get("variant_id") or "") == variant_id:
                return row
        return {"wallet_address": wallet_address, "variant_id": variant_id}

    def _latest_holding_for_wallet(self, holdings: list[dict], wallet_address: str, variant_id: str) -> dict:
        for row in reversed(holdings):
            if str(row.get("wallet_address") or "") == wallet_address and str(row.get("variant_id") or "") == variant_id:
                return row
        return {"wallet_address": wallet_address, "variant_id": variant_id}

    def _read_list(self, path: Path) -> list[dict]:
        if self._pg_enabled:
            return self._pg_read_snapshot(path.name)
        if self.db_path:
            return self._db_read_snapshot(path.name)
        data = _load_json(path, [])
        return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []

    def _write_list(self, path: Path, rows: list[dict]) -> None:
        if self._pg_enabled:
            self._pg_write_snapshot(path.name, rows)
            return
        if self.db_path:
            self._db_write_snapshot(path.name, rows)
            return
        _save_json(path, rows)

    def _init_db(self) -> None:
        assert self.db_path is not None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS trade_runtime_snapshots (store_name TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS trade_runtime_events (id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL, ts TEXT NOT NULL, payload_json TEXT NOT NULL)"
            )
            conn.commit()

    def _db_read_snapshot(self, store_name: str) -> list[dict]:
        assert self.db_path is not None
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT payload_json FROM trade_runtime_snapshots WHERE store_name = ?",
                (str(store_name),),
            ).fetchone()
        if not row:
            return []
        try:
            data = json.loads(str(row[0] or "[]"))
        except Exception:
            return []
        return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []

    def _db_write_snapshot(self, store_name: str, rows: list[dict]) -> None:
        assert self.db_path is not None
        payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
        ts = _iso()
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO trade_runtime_snapshots(store_name, payload_json, updated_at) VALUES(?,?,?) ON CONFLICT(store_name) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (str(store_name), payload, ts),
            )
            conn.commit()

    def _db_append_event(self, event: str, payload: dict) -> None:
        assert self.db_path is not None
        ts = _iso()
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO trade_runtime_events(event, ts, payload_json) VALUES(?,?,?)",
                (str(event), ts, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
            )
            conn.execute(
                "DELETE FROM trade_runtime_events WHERE id NOT IN (SELECT id FROM trade_runtime_events ORDER BY id DESC LIMIT 4000)"
            )
            conn.commit()
        self._redis_publish_event(event, payload)

    def _db_stream_events(self, wallet_address: str, kinds: set[str] | None = None, limit: int = 100) -> list[dict]:
        assert self.db_path is not None
        wanted = kinds or set()
        with closing(sqlite3.connect(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT event, ts, payload_json FROM trade_runtime_events ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        out: list[dict] = []
        for event, ts, payload_json in rows:
            try:
                payload = json.loads(str(payload_json or "{}"))
            except Exception:
                payload = {}
            candidate_wallet = str((payload or {}).get("wallet_address") or "")
            if wallet_address and candidate_wallet and candidate_wallet != wallet_address:
                continue
            if wanted and str(event or "") not in wanted:
                continue
            out.append({"event": str(event or ""), "ts": str(ts or ""), "payload": payload})
        out.reverse()
        return out

    def _redis_publish_event(self, event: str, payload: dict) -> None:
        if self._redis is None:
            return
        stream = self._stream_name_for_event(event)
        if not stream:
            return
        env = {"event": event, "ts": _iso(), "payload": payload}
        try:
            self._redis.xadd(stream, {"payload": json.dumps(env, ensure_ascii=False, separators=(",", ":"))}, maxlen=self._stream_retention(stream), approximate=True)
        except Exception:
            return

    def _stream_name_for_event(self, event: str) -> str:
        if event.startswith("trade.quote"):
            return "stream:trade_quotes"
        if event.startswith("trade.intent"):
            return "stream:trade_intents"
        if event.startswith("position."):
            return "stream:positions"
        if event.startswith("holding."):
            return "stream:holdings"
        if event.startswith("pnl."):
            return "stream:pnl"
        if event.startswith("wallet.activity"):
            return "stream:wallet_activity"
        return ""

    def _stream_retention(self, stream: str) -> int:
        mapping = {
            "stream:trade_quotes": 1000,
            "stream:trade_intents": 5000,
            "stream:positions": 3000,
            "stream:holdings": 3000,
            "stream:pnl": 3000,
            "stream:wallet_activity": 3000,
        }
        return mapping.get(stream, 2000)

    def _init_postgres(self) -> None:
        if not self._pg_enabled:
            return
        with closing(psycopg.connect(self.postgres_dsn)) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS trade_intents (
                        intent_id TEXT PRIMARY KEY,
                        wallet_address TEXT NOT NULL,
                        variant_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL,
                        source TEXT NOT NULL,
                        intent_type TEXT NOT NULL,
                        payload_json JSONB NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_trade_intents_wallet ON trade_intents(wallet_address, created_at DESC);

                    CREATE TABLE IF NOT EXISTS positions (
                        position_id TEXT PRIMARY KEY,
                        wallet_address TEXT NOT NULL,
                        variant_id TEXT NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        payload_json JSONB NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_positions_wallet ON positions(wallet_address, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS holdings (
                        holding_id TEXT PRIMARY KEY,
                        wallet_address TEXT NOT NULL,
                        variant_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        updated_at TIMESTAMPTZ,
                        payload_json JSONB NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_holdings_wallet ON holdings(wallet_address, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS autosell_rules (
                        rule_id TEXT PRIMARY KEY,
                        wallet_address TEXT NOT NULL,
                        enabled BOOLEAN NOT NULL,
                        scope TEXT NOT NULL,
                        trigger_type TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        priority INT NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL,
                        payload_json JSONB NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_autosell_rules_wallet ON autosell_rules(wallet_address, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS wallet_activity_runtime (
                        activity_id TEXT PRIMARY KEY,
                        wallet_address TEXT NOT NULL,
                        ts TIMESTAMPTZ NOT NULL,
                        payload_json JSONB NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_wallet_activity_runtime_wallet ON wallet_activity_runtime(wallet_address, ts DESC);

                    CREATE TABLE IF NOT EXISTS trade_quote_state (
                        nonce TEXT PRIMARY KEY,
                        state TEXT NOT NULL,
                        expires_at TIMESTAMPTZ,
                        payload_json JSONB NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS trade_autosell_state (
                        state_key TEXT PRIMARY KEY,
                        updated_at TIMESTAMPTZ NOT NULL,
                        payload_json JSONB NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS pnl_snapshots (
                        wallet_address TEXT NOT NULL,
                        ts TIMESTAMPTZ NOT NULL,
                        payload_json JSONB NOT NULL,
                        PRIMARY KEY(wallet_address, ts)
                    );

                    CREATE TABLE IF NOT EXISTS audit_log (
                        id BIGSERIAL PRIMARY KEY,
                        entity TEXT NOT NULL,
                        entity_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        payload JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    );

                    CREATE TABLE IF NOT EXISTS trade_runtime_events_pg (
                        id BIGSERIAL PRIMARY KEY,
                        event TEXT NOT NULL,
                        ts TIMESTAMPTZ NOT NULL,
                        payload_json JSONB NOT NULL
                    );
                    """
                )
            conn.commit()

    def _pg_read_snapshot(self, store_name: str) -> list[dict]:
        if not self._pg_enabled:
            return []
        meta = self._pg_store_map.get(str(store_name))
        if not meta:
            return []
        table, _key_field, sort_fields = meta
        order_by = sort_fields[0] if sort_fields else _key_field
        try:
            with closing(psycopg.connect(self.postgres_dsn)) as conn:  # type: ignore[arg-type]
                with conn.cursor() as cur:
                    cur.execute(f"SELECT payload_json FROM {table} ORDER BY {order_by} DESC")
                    rows = cur.fetchall()
        except Exception:
            return []
        out: list[dict] = []
        for row in rows:
            payload = row[0] if row else None
            if isinstance(payload, dict):
                out.append(payload)
            elif isinstance(payload, str):
                try:
                    parsed = json.loads(payload)
                    if isinstance(parsed, dict):
                        out.append(parsed)
                except Exception:
                    continue
        return out

    def _pg_write_snapshot(self, store_name: str, rows: list[dict]) -> None:
        if not self._pg_enabled:
            return
        meta = self._pg_store_map.get(str(store_name))
        if not meta:
            return
        table, key_field, field_order = meta
        try:
            with closing(psycopg.connect(self.postgres_dsn)) as conn:  # type: ignore[arg-type]
                with conn.cursor() as cur:
                    cur.execute(f"DELETE FROM {table}")
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        key_val = row.get(key_field)
                        if key_val is None:
                            continue
                        cols = [key_field] + list(field_order) + ["payload_json"]
                        values = [key_val]
                        for field in field_order:
                            values.append(row.get(field))
                        values.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
                        placeholders = ", ".join(["%s"] * len(values))
                        cur.execute(
                            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
                            tuple(values),
                        )
                conn.commit()
        except Exception:
            return

    def _get_quote_state(self, nonce: str) -> dict | None:
        if not nonce:
            return None
        for row in self._read_list(self.quotes_file):
            if str(row.get("nonce") or "") == str(nonce):
                return row
        return None

    def _upsert_quote_state(self, nonce: str, patch: dict) -> None:
        if not nonce:
            return
        rows = self._read_list(self.quotes_file)
        target = None
        for row in rows:
            if str(row.get("nonce") or "") == str(nonce):
                target = row
                break
        if target is None:
            target = {"nonce": nonce}
            rows.append(target)
        for key, value in (patch or {}).items():
            target[key] = value
        target.setdefault("updated_at", _iso())
        self._write_list(self.quotes_file, rows)

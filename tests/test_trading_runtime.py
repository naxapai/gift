import base64
import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path

from trading_runtime import TradeRuntime


class TestTradingRuntime(unittest.TestCase):
    def test_variant_a_buy_then_list_creates_child_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5)
            created = rt.create_trade_intent({
                'intent_type': 'BUY_AND_LIST',
                'variant_id': 'v1',
                'wallet_address': 'EQTEST',
                'max_spend_ton': 8.0,
                'chain_policy': 'BUY_THEN_LIST',
                'post_action': {'type': 'LIST', 'listing_params': {'list_price_ton': 9.1, 'duration_sec': 86400, 'marketplace': 'fragment'}},
            }, market_regime='MEAN_REVERT', variant_snapshot={'variant_label': 'Variant 1', 'floor_ton': 8.0, 'fair_ton': 8.8})
            parent = created['intent']
            confirmed = rt.confirm_intent_signature(parent['intent_id'], {'tx_hash': 'tx1'}, market_regime='MEAN_REVERT', variant_snapshot={'variant_label': 'Variant 1', 'floor_ton': 8.0, 'fair_ton': 8.8})
            self.assertEqual(confirmed['status'], 'CONFIRMED')
            all_items = rt.list_trade_intents('EQTEST')['items']
            child = next((x for x in all_items if x.get('parent_intent_id') == parent['intent_id']), None)
            self.assertTrue(isinstance(child, dict))
            self.assertEqual(child.get('intent_type'), 'LIST')
            self.assertEqual(child.get('step_index'), 2)

    def test_autosell_take_profit_auto_list_creates_pending_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5)
            rt.upsert_autosell_rule({
                'rule_id': 'tp-list',
                'wallet_address': 'EQTEST',
                'enabled': True,
                'scope': '*',
                'trigger_type': 'TAKE_PROFIT',
                'params': {'tp_pct': 0.0},
                'mode': 'AUTO_LIST',
                'cooldown_sec': 0,
                'priority': 1,
            })
            created = rt.create_trade_intent({'intent_type': 'BUY', 'variant_id': 'v2', 'wallet_address': 'EQTEST', 'max_spend_ton': 5.0}, market_regime='RISK_ON', variant_snapshot={'variant_label': 'Variant 2', 'floor_ton': 5.0, 'fair_ton': 6.0})
            rt.confirm_intent_signature(created['intent']['intent_id'], {'tx_hash': 'tx2'}, market_regime='RISK_ON', variant_snapshot={'variant_label': 'Variant 2', 'floor_ton': 5.0, 'fair_ton': 6.0})
            intents = rt.list_trade_intents('EQTEST')['items']
            auto_list = next((x for x in intents if x.get('intent_type') == 'LIST'), None)
            self.assertTrue(isinstance(auto_list, dict))
            self.assertEqual(auto_list.get('status'), 'PENDING_SIGNATURE')
            events = rt.stream_events('EQTEST', kinds={'autosell.triggered'}, limit=20)
            self.assertTrue(events)

    def test_fast_confirm_emits_quote_used_and_confirmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5)
            quote = rt.issue_buy_quote(variant_id='v3', max_price_ton=4.5, slippage_bps=100, wallet_address='EQTEST', variant_snapshot={'floor_ton': 4.0, 'fair_ton': 4.6})
            item = rt.confirm_fast_buy({'buy_quote_token': quote['buy_quote_token'], 'tx_hash': 'tx3', 'wallet_address': 'EQTEST'}, market_regime='MEAN_REVERT', variant_snapshot={'floor_ton': 4.0, 'fair_ton': 4.6})
            self.assertEqual(item['status'], 'CONFIRMED')
            events = rt.stream_events('EQTEST', kinds={'trade.quote.used', 'trade.intent.broadcast', 'trade.intent.confirmed'}, limit=20)
            names = [x.get('event') for x in events]
            self.assertIn('trade.quote.used', names)
            self.assertIn('trade.intent.broadcast', names)
            self.assertIn('trade.intent.confirmed', names)

    def test_sqlite_backed_runtime_persists_snapshots_and_stream(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / 'trades.sqlite3'
            rt = TradeRuntime(root, quote_secret='secret', quote_ttl_sec=5, db_path=db_path)
            created = rt.create_trade_intent({'intent_type': 'BUY', 'variant_id': 'v4', 'wallet_address': 'EQSQL', 'max_spend_ton': 7.0}, market_regime='RISK_ON', variant_snapshot={'floor_ton': 7.0, 'fair_ton': 7.8})
            rt.confirm_intent_signature(created['intent']['intent_id'], {'tx_hash': 'tx4'}, market_regime='RISK_ON', variant_snapshot={'floor_ton': 7.0, 'fair_ton': 7.8})
            rt2 = TradeRuntime(root, quote_secret='secret', quote_ttl_sec=5, db_path=db_path)
            intents = rt2.list_trade_intents('EQSQL')['items']
            self.assertTrue(intents)
            events = rt2.stream_events('EQSQL', kinds={'trade.intent.confirmed'}, limit=20)
            self.assertTrue(events)

    def test_quote_nonce_lifecycle_persists_used_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5)
            quote = rt.issue_buy_quote(variant_id='v5', max_price_ton=3.5, slippage_bps=100, wallet_address='EQTEST', variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.8})
            raw = rt._decode_quote(quote['buy_quote_token'])
            nonce = raw['quote']['nonce']
            state_before = rt._get_quote_state(nonce)
            self.assertEqual(state_before.get('state'), 'ISSUED')
            rt.confirm_fast_buy({'buy_quote_token': quote['buy_quote_token'], 'tx_hash': 'tx5', 'wallet_address': 'EQTEST'}, market_regime='MEAN_REVERT', variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.8})
            state_after = rt._get_quote_state(nonce)
            self.assertEqual(state_after.get('state'), 'USED')
            with self.assertRaises(RuntimeError):
                rt.confirm_fast_buy({'buy_quote_token': quote['buy_quote_token'], 'tx_hash': 'tx5b', 'wallet_address': 'EQTEST'}, market_regime='MEAN_REVERT', variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.8})

    def test_retry_chain_list_intent_creates_new_child_when_previous_not_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5)
            created = rt.create_trade_intent({
                'intent_type': 'BUY_AND_LIST',
                'variant_id': 'v6',
                'wallet_address': 'EQTEST',
                'max_spend_ton': 8.0,
                'chain_policy': 'BUY_THEN_LIST',
                'post_action': {'type': 'LIST', 'listing_params': {'list_price_ton': 9.1, 'duration_sec': 86400, 'marketplace': 'fragment'}},
            }, market_regime='MEAN_REVERT', variant_snapshot={'variant_label': 'Variant 6', 'floor_ton': 8.0, 'fair_ton': 8.8})
            parent = created['intent']
            rt.confirm_intent_signature(parent['intent_id'], {'tx_hash': 'tx6'}, market_regime='MEAN_REVERT', variant_snapshot={'variant_label': 'Variant 6', 'floor_ton': 8.0, 'fair_ton': 8.8})
            items = rt.list_trade_intents('EQTEST')['items']
            child = next((x for x in items if x.get('parent_intent_id') == parent['intent_id']), None)
            self.assertTrue(isinstance(child, dict))
            child['status'] = 'FAILED'
            rt._write_list(rt.intents_file, items)
            retry = rt.retry_chain_list_intent(parent['intent_id'])
            self.assertEqual(retry.get('intent_type'), 'LIST')
            self.assertNotEqual(retry.get('intent_id'), child.get('intent_id'))

    def test_quote_expiry_marks_state_expired(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=3)
            quote = rt.issue_buy_quote(variant_id='v7', max_price_ton=2.5, slippage_bps=100, wallet_address='EQTEST', variant_snapshot={'floor_ton': 2.0, 'fair_ton': 2.7})
            raw = rt._decode_quote(quote['buy_quote_token'])
            raw['quote']['issued_at'] = int(time.time()) - 10
            tampered = base64.urlsafe_b64encode(json.dumps({'quote': raw['quote'], 'sig': hmac.new(b'secret', json.dumps(raw['quote'], sort_keys=True, separators=(',', ':')).encode('utf-8'), hashlib.sha256).hexdigest()}).encode('utf-8')).decode('utf-8')
            with self.assertRaises(TimeoutError):
                rt.confirm_fast_buy({'buy_quote_token': tampered, 'tx_hash': 'tx7', 'wallet_address': 'EQTEST'}, market_regime='MEAN_REVERT', variant_snapshot={'floor_ton': 2.0, 'fair_ton': 2.7})
            state = rt._get_quote_state(raw['quote']['nonce'])
            self.assertEqual(state.get('state'), 'EXPIRED')


if __name__ == '__main__':
    unittest.main()

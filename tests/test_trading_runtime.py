import base64
import hashlib
import hmac
import json
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from trading_runtime import TradeRuntime


class TestTradingRuntime(unittest.TestCase):
    def test_sandbox_standard_buy_confirms_via_stubbed_marketplace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(
                Path(tmpdir),
                quote_secret='secret',
                quote_ttl_sec=5,
                environment='sandbox',
                marketplace_wallet_address='EQSANDBOXMARKETPLACE',
            )
            created = rt.create_trade_intent(
                {
                    'intent_type': 'BUY',
                    'variant_id': 'sbx1',
                    'wallet_address': 'EQTEST',
                    'max_spend_ton': 4.0,
                },
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 4.0, 'fair_ton': 4.4},
            )
            self.assertEqual(created['wallet_tx']['messages'][0]['address'], 'EQSANDBOXMARKETPLACE')
            confirmed = rt.confirm_intent_signature(
                created['intent']['intent_id'],
                {'tx_hash': 'sim_buy_ok'},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 4.0, 'fair_ton': 4.4},
            )
            self.assertEqual(confirmed['status'], 'CONFIRMED')
            self.assertEqual(confirmed['status_timeline'][-1]['source'], 'sandbox_mock_marketplace')

    def test_fast_buy_quote_validates_price_slippage_and_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5, environment='sandbox')
            with self.assertRaises(ValueError) as missing_variant:
                rt.issue_buy_quote(variant_id='', max_price_ton=3.3, slippage_bps=100, wallet_address='EQTEST', variant_snapshot={'floor_ton': 3.0})
            self.assertEqual(str(missing_variant.exception), 'variant_id_required')
            with self.assertRaises(ValueError) as bad_price:
                rt.issue_buy_quote(variant_id='sbx2', max_price_ton=0.0, slippage_bps=100, wallet_address='EQTEST', variant_snapshot={'floor_ton': 3.0})
            self.assertEqual(str(bad_price.exception), 'max_price_ton_required')
            with self.assertRaises(ValueError) as bad_slippage:
                rt.issue_buy_quote(variant_id='sbx2', max_price_ton=3.3, slippage_bps=10001, wallet_address='EQTEST', variant_snapshot={'floor_ton': 3.0})
            self.assertEqual(str(bad_slippage.exception), 'slippage_bps_out_of_range')

    def test_sandbox_fast_buy_confirms_via_stubbed_marketplace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5, environment='sandbox')
            quote = rt.issue_buy_quote(
                variant_id='sbx2',
                max_price_ton=3.3,
                slippage_bps=100,
                wallet_address='EQTEST',
                variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.5},
            )
            item = rt.confirm_fast_buy(
                {'buy_quote_token': quote['buy_quote_token'], 'tx_hash': 'sim_fast_ok', 'wallet_address': 'EQTEST'},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.5},
            )
            self.assertEqual(item['status'], 'CONFIRMED')
            self.assertEqual(item['source'], 'FAST_BUY')

    def test_sandbox_wallet_reject_marks_intent_failed_without_holding(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5, environment='sandbox')
            created = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'sbx_reject', 'wallet_address': 'EQTEST', 'max_spend_ton': 2.5},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 2.5, 'fair_ton': 2.7},
            )
            item = rt.confirm_intent_signature(
                created['intent']['intent_id'],
                {'tx_hash': 'rejected_wallet_001'},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 2.5, 'fair_ton': 2.7},
            )
            self.assertEqual(item['status'], 'FAILED')
            self.assertEqual(str(item.get('error_code') or ''), 'sandbox_tx_rejected')
            self.assertEqual(rt.list_holdings('EQTEST')['items'], [])

    def test_sandbox_pending_tx_stays_broadcast(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5, environment='sandbox')
            created = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'sbx3', 'wallet_address': 'EQTEST', 'max_spend_ton': 2.5},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 2.5, 'fair_ton': 2.7},
            )
            item = rt.confirm_intent_signature(
                created['intent']['intent_id'],
                {'tx_hash': 'pending_wait_001'},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 2.5, 'fair_ton': 2.7},
            )
            self.assertEqual(item['status'], 'BROADCAST')

    def test_production_without_verifier_does_not_auto_confirm(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5, environment='production')
            created = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'prd1', 'wallet_address': 'EQTEST', 'max_spend_ton': 6.0},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 6.0, 'fair_ton': 6.5},
            )
            item = rt.confirm_intent_signature(
                created['intent']['intent_id'],
                {'tx_hash': 'real_tx_hash'},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 6.0, 'fair_ton': 6.5},
            )
            self.assertEqual(item['status'], 'BROADCAST')
            self.assertIsNone(rt.list_holdings('EQTEST')['items'][0:1] or None)

    def test_tx_hash_replay_is_rejected_for_standard_and_fast_buy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5, environment='sandbox')
            first = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'replay1', 'wallet_address': 'EQTEST', 'max_spend_ton': 3.0},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.3},
            )
            rt.confirm_intent_signature(
                first['intent']['intent_id'],
                {'tx_hash': 'tx_replay_1'},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.3},
            )
            second = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'replay2', 'wallet_address': 'EQTEST', 'max_spend_ton': 4.0},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 4.0, 'fair_ton': 4.3},
            )
            with self.assertRaises(RuntimeError) as standard_replay:
                rt.confirm_intent_signature(
                    second['intent']['intent_id'],
                    {'tx_hash': 'tx_replay_1'},
                    market_regime='MEAN_REVERT',
                    variant_snapshot={'floor_ton': 4.0, 'fair_ton': 4.3},
                )
            self.assertEqual(str(standard_replay.exception), 'tx_hash_already_used')

            quote = rt.issue_buy_quote(variant_id='replay3', max_price_ton=5.0, slippage_bps=100, wallet_address='EQTEST', variant_snapshot={'floor_ton': 5.0})
            with self.assertRaises(RuntimeError) as fast_replay:
                rt.confirm_fast_buy(
                    {'buy_quote_token': quote['buy_quote_token'], 'tx_hash': 'tx_replay_1', 'wallet_address': 'EQTEST'},
                    market_regime='MEAN_REVERT',
                    variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.3},
                )
            self.assertEqual(str(fast_replay.exception), 'tx_hash_already_used')

    def test_duplicate_confirm_request_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5, environment='sandbox')
            created = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'dup1', 'wallet_address': 'EQTEST', 'max_spend_ton': 3.0},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.3},
            )
            first = rt.confirm_intent_signature(
                created['intent']['intent_id'],
                {'tx_hash': 'sim_dup_ok'},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.3},
            )
            second = rt.confirm_intent_signature(
                created['intent']['intent_id'],
                {'tx_hash': 'sim_dup_ok'},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.3},
            )
            self.assertEqual(first['intent_id'], second['intent_id'])
            self.assertEqual(len(rt.list_holdings('EQTEST')['items']), 1)

    def test_standard_confirm_rejects_wallet_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5, environment='sandbox')
            created = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'wallet_mismatch', 'wallet_address': 'EQTEST', 'max_spend_ton': 3.0},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.3},
            )
            with self.assertRaises(ValueError) as exc:
                rt.confirm_intent_signature(
                    created['intent']['intent_id'],
                    {'tx_hash': 'sim_wallet_mismatch', 'wallet_address': 'EQOTHER'},
                    market_regime='MEAN_REVERT',
                    variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.3},
                )
            self.assertEqual(str(exc.exception), 'wallet_address_mismatch')
            self.assertEqual(rt.list_holdings('EQTEST')['items'], [])

    def test_standard_confirm_rejects_second_different_tx_after_finalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5, environment='sandbox')
            created = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'dup_final', 'wallet_address': 'EQTEST', 'max_spend_ton': 3.0},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.3},
            )
            rt.confirm_intent_signature(
                created['intent']['intent_id'],
                {'tx_hash': 'sim_dup_final_ok', 'wallet_address': 'EQTEST'},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.3},
            )
            with self.assertRaises(RuntimeError) as exc:
                rt.confirm_intent_signature(
                    created['intent']['intent_id'],
                    {'tx_hash': 'sim_dup_final_other', 'wallet_address': 'EQTEST'},
                    market_regime='MEAN_REVERT',
                    variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.3},
                )
            self.assertEqual(str(exc.exception), 'intent_already_finalized')
            self.assertEqual(len(rt.list_holdings('EQTEST')['items']), 1)

    def test_standard_confirm_rejects_tx_replacement_while_broadcast(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5, environment='sandbox')
            created = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'broadcast_replace', 'wallet_address': 'EQTEST', 'max_spend_ton': 3.0},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.3},
            )
            rt.confirm_intent_signature(
                created['intent']['intent_id'],
                {'tx_hash': 'pending_replace_1', 'wallet_address': 'EQTEST'},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.3},
            )
            with self.assertRaises(RuntimeError) as exc:
                rt.confirm_intent_signature(
                    created['intent']['intent_id'],
                    {'tx_hash': 'pending_replace_2', 'wallet_address': 'EQTEST'},
                    market_regime='MEAN_REVERT',
                    variant_snapshot={'floor_ton': 3.0, 'fair_ton': 3.3},
                )
            self.assertEqual(str(exc.exception), 'intent_tx_hash_mismatch')
            self.assertEqual(rt.list_holdings('EQTEST')['items'], [])

    def test_broadcast_timeout_marks_failed_not_expired(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5, environment='sandbox')
            created = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'timeout1', 'wallet_address': 'EQTEST', 'max_spend_ton': 2.0},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 2.0, 'fair_ton': 2.2},
            )
            item = rt.confirm_intent_signature(
                created['intent']['intent_id'],
                {'tx_hash': 'pending_timeout_001'},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 2.0, 'fair_ton': 2.2},
            )
            self.assertEqual(item['status'], 'BROADCAST')
            intents = rt._read_list(rt.intents_file)
            intents[0]['expires_at'] = '2000-01-01T00:00:00Z'
            rt._write_list(rt.intents_file, intents)
            rows = rt.list_trade_intents('EQTEST')['items']
            self.assertEqual(rows[0]['status'], 'FAILED')
            self.assertEqual(str(rows[0].get('error_code') or ''), 'broadcast_timeout')

    def test_pending_signature_expires_after_ttl_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5, environment='sandbox')
            created = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'exp1', 'wallet_address': 'EQTEST', 'max_spend_ton': 2.0},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 2.0, 'fair_ton': 2.2},
            )
            intents = rt._read_list(rt.intents_file)
            intents[0]['expires_at'] = '2000-01-01T00:00:00Z'
            rt._write_list(rt.intents_file, intents)
            rows = rt.list_trade_intents('EQTEST')['items']
            self.assertEqual(rows[0]['status'], 'EXPIRED')

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

    def test_file_audit_log_records_intent_and_autosell_generated_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5)
            rt.upsert_autosell_rule({
                'rule_id': 'audit-signal-exit',
                'wallet_address': 'EQTEST',
                'enabled': True,
                'scope': '*',
                'trigger_type': 'SIGNAL_EXIT',
                'params': {'edgeRank100_min': 55, 'conf_pct_min': 35, 'expected_profit_pct_min': 8},
                'mode': 'AUTO_SELL_NOW',
                'cooldown_sec': 0,
                'priority': 1,
            })
            created = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'audit_variant', 'wallet_address': 'EQTEST', 'max_spend_ton': 5.0},
                market_regime='RISK_OFF',
                variant_snapshot={'floor_ton': 5.0, 'fair_ton': 4.2, 'action': 'SELL', 'edgeRank100': 22, 'conf_pct': 18, 'expected_profit_pct': -4.5},
            )
            rt.confirm_intent_signature(
                created['intent']['intent_id'],
                {'tx_hash': 'tx_audit_signal_exit'},
                market_regime='RISK_OFF',
                variant_snapshot={'floor_ton': 5.0, 'fair_ton': 4.2, 'action': 'SELL', 'edgeRank100': 22, 'conf_pct': 18, 'expected_profit_pct': -4.5},
            )
            rows = rt._read_list(rt.audit_file)
            self.assertTrue(rows)
            self.assertTrue(all({'entity', 'entity_id', 'action', 'payload', 'created_at'} <= set(row.keys()) for row in rows))
            self.assertTrue(any(row.get('entity') == 'autosell_rule' and row.get('action') == 'upserted' for row in rows))
            self.assertTrue(any(row.get('entity') == 'trade_intent' and row.get('action') == 'created' and (row.get('payload') or {}).get('intent_type') == 'SELL' for row in rows))

    def test_autosell_signal_exit_auto_sell_now_creates_pending_sell(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5)
            rt.upsert_autosell_rule({
                'rule_id': 'signal-exit-sell',
                'wallet_address': 'EQTEST',
                'enabled': True,
                'scope': '*',
                'trigger_type': 'SIGNAL_EXIT',
                'params': {'edgeRank100_min': 55, 'conf_pct_min': 35, 'expected_profit_pct_min': 8},
                'mode': 'AUTO_SELL_NOW',
                'cooldown_sec': 0,
                'priority': 1,
            })
            created = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'v_signal_exit', 'wallet_address': 'EQTEST', 'max_spend_ton': 5.0},
                market_regime='RISK_OFF',
                variant_snapshot={'variant_label': 'Variant Signal Exit', 'floor_ton': 5.0, 'fair_ton': 4.2, 'action': 'SELL', 'edgeRank100': 22, 'conf_pct': 18, 'expected_profit_pct': -4.5},
            )
            rt.confirm_intent_signature(
                created['intent']['intent_id'],
                {'tx_hash': 'tx_signal_exit'},
                market_regime='RISK_OFF',
                variant_snapshot={'variant_label': 'Variant Signal Exit', 'floor_ton': 5.0, 'fair_ton': 4.2, 'action': 'SELL', 'edgeRank100': 22, 'conf_pct': 18, 'expected_profit_pct': -4.5},
            )
            intents = rt.list_trade_intents('EQTEST')['items']
            auto_sell = next((x for x in intents if x.get('intent_type') == 'SELL'), None)
            self.assertTrue(isinstance(auto_sell, dict))
            self.assertEqual(auto_sell.get('status'), 'PENDING_SIGNATURE')
            events = rt.stream_events('EQTEST', kinds={'autosell.triggered'}, limit=20)
            self.assertTrue(events)
            payload = (events[0] or {}).get('payload') if isinstance((events[0] or {}).get('payload'), dict) else (events[0] or {})
            self.assertEqual(str((payload or {}).get('mode') or ''), 'AUTO_SELL_NOW')

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
            events = rt.stream_events('EQTEST', kinds={'trade.quote.used', 'trade.intent.broadcast', 'trade.intent.confirmed', 'trade.execution.confirmed'}, limit=20)
            names = [x.get('event') for x in events]
            self.assertIn('trade.quote.used', names)
            self.assertIn('trade.intent.broadcast', names)
            self.assertIn('trade.intent.confirmed', names)
            self.assertIn('trade.execution.confirmed', names)
            execution = next(x for x in events if x.get('event') == 'trade.execution.confirmed')
            self.assertEqual(execution.get('payload', {}).get('wallet_address'), 'EQTEST')
            self.assertEqual(execution.get('payload', {}).get('variant_id'), 'v3')
            self.assertEqual(rt._stream_name_for_event('trade.execution.confirmed'), 'stream:trade_executions')

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
            events = rt2.stream_events('EQSQL', kinds={'trade.intent.confirmed', 'trade.execution.confirmed'}, limit=20)
            names = [x.get('event') for x in events]
            self.assertIn('trade.intent.confirmed', names)
            self.assertIn('trade.execution.confirmed', names)

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

    def test_provider_unavailable_keeps_intent_in_broadcast(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5, tx_verify_url='https://provider/tx')
            created = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'v_provider_timeout', 'wallet_address': 'EQTEST', 'max_spend_ton': 5.0},
                market_regime='MEAN_REVERT',
                variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5},
            )
            with patch('urllib.request.urlopen', side_effect=RuntimeError('provider timeout')):
                item = rt.confirm_intent_signature(
                    created['intent']['intent_id'],
                    {'tx_hash': 'tx_provider_timeout'},
                    market_regime='MEAN_REVERT',
                    variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5},
                )
            self.assertEqual(item.get('status'), 'BROADCAST')
            self.assertEqual(str(item.get('tx_hash') or ''), 'tx_provider_timeout')
            self.assertEqual(rt.list_holdings('EQTEST')['items'], [])

    def test_provider_pending_keeps_intent_in_broadcast(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5, tx_verify_url='https://provider/tx')
            created = rt.create_trade_intent({'intent_type': 'BUY', 'variant_id': 'v8', 'wallet_address': 'EQTEST', 'max_spend_ton': 5.0}, market_regime='MEAN_REVERT', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            with patch.object(rt, '_verify_tx_state', return_value={'status': 'PENDING', 'source': 'provider'}):
                item = rt.confirm_intent_signature(created['intent']['intent_id'], {'tx_hash': 'tx8'}, market_regime='MEAN_REVERT', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            self.assertEqual(item.get('status'), 'BROADCAST')

    def test_signature_payload_hash_validation_rejects_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5)
            created = rt.create_trade_intent({'intent_type': 'BUY', 'variant_id': 'v9', 'wallet_address': 'EQTEST', 'max_spend_ton': 5.0}, market_regime='MEAN_REVERT', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            with self.assertRaises(ValueError):
                rt.confirm_intent_signature(created['intent']['intent_id'], {'tx_hash': 'tx9', 'signature_meta': {'payload_hash': 'bad_hash'}}, market_regime='MEAN_REVERT', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})

    def test_list_requires_owned_holding_and_price(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5)
            with self.assertRaises(ValueError):
                rt.create_trade_intent({'intent_type': 'LIST', 'variant_id': 'v10', 'wallet_address': 'EQTEST'}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            created = rt.create_trade_intent({'intent_type': 'BUY', 'variant_id': 'v10', 'wallet_address': 'EQTEST', 'max_spend_ton': 5.0}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            rt.confirm_intent_signature(created['intent']['intent_id'], {'tx_hash': 'tx10'}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            with self.assertRaises(ValueError):
                rt.create_trade_intent({'intent_type': 'LIST', 'variant_id': 'v10', 'wallet_address': 'EQTEST', 'post_action': {'type': 'LIST', 'listing_params': {'duration_sec': 86400, 'marketplace': 'fragment'}}}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            listed = rt.create_trade_intent({'intent_type': 'LIST', 'variant_id': 'v10', 'wallet_address': 'EQTEST', 'post_action': {'type': 'LIST', 'listing_params': {'list_price_ton': 6.0, 'duration_sec': 86400, 'marketplace': 'fragment'}}}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            self.assertEqual(listed['intent']['intent_type'], 'LIST')

    def test_cancel_sell_transfer_require_correct_holding_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5)
            created = rt.create_trade_intent({'intent_type': 'BUY', 'variant_id': 'v11', 'wallet_address': 'EQTEST', 'max_spend_ton': 5.0}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            rt.confirm_intent_signature(created['intent']['intent_id'], {'tx_hash': 'tx11'}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            sell = rt.create_trade_intent({'intent_type': 'SELL', 'variant_id': 'v11', 'wallet_address': 'EQTEST'}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            self.assertEqual(sell['intent']['intent_type'], 'SELL')
            with self.assertRaises(ValueError):
                rt.create_trade_intent({'intent_type': 'TRANSFER', 'variant_id': 'v11', 'wallet_address': 'EQTEST'}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            transfer = rt.create_trade_intent({'intent_type': 'TRANSFER', 'variant_id': 'v11', 'wallet_address': 'EQTEST', 'transfer_params': {'telegram_user_id': '144832201'}}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            self.assertEqual(transfer['intent']['intent_type'], 'TRANSFER')
            list_intent = rt.create_trade_intent({'intent_type': 'LIST', 'variant_id': 'v11', 'wallet_address': 'EQTEST', 'post_action': {'type': 'LIST', 'listing_params': {'list_price_ton': 6.0, 'duration_sec': 86400, 'marketplace': 'fragment'}}}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            rt.confirm_intent_signature(list_intent['intent']['intent_id'], {'tx_hash': 'tx11-list'}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            cancel = rt.create_trade_intent({'intent_type': 'CANCEL_LISTING', 'variant_id': 'v11', 'wallet_address': 'EQTEST'}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            self.assertEqual(cancel['intent']['intent_type'], 'CANCEL_LISTING')

    def test_cancel_listing_duplicate_pending_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5)
            created = rt.create_trade_intent({'intent_type': 'BUY', 'variant_id': 'v12', 'wallet_address': 'EQTEST', 'max_spend_ton': 5.0}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            rt.confirm_intent_signature(created['intent']['intent_id'], {'tx_hash': 'tx12'}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            list_intent = rt.create_trade_intent({'intent_type': 'LIST', 'variant_id': 'v12', 'wallet_address': 'EQTEST', 'post_action': {'type': 'LIST', 'listing_params': {'list_price_ton': 6.0, 'duration_sec': 86400, 'marketplace': 'fragment'}}}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            rt.confirm_intent_signature(list_intent['intent']['intent_id'], {'tx_hash': 'tx12-list'}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            first = rt.create_trade_intent({'intent_type': 'CANCEL_LISTING', 'variant_id': 'v12', 'wallet_address': 'EQTEST'}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            self.assertEqual(first['intent']['status'], 'PENDING_SIGNATURE')
            with self.assertRaises(ValueError):
                rt.create_trade_intent({'intent_type': 'CANCEL_LISTING', 'variant_id': 'v12', 'wallet_address': 'EQTEST'}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})

    def test_transfer_marks_holding_terminal_and_preserves_transfer_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5)
            created = rt.create_trade_intent({'intent_type': 'BUY', 'variant_id': 'v13', 'wallet_address': 'EQTEST', 'max_spend_ton': 5.0}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            rt.confirm_intent_signature(created['intent']['intent_id'], {'tx_hash': 'tx13'}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            transfer = rt.create_trade_intent({'intent_type': 'TRANSFER', 'variant_id': 'v13', 'wallet_address': 'EQTEST', 'transfer_params': {'telegram_user_id': '144832201'}}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            rt.confirm_intent_signature(transfer['intent']['intent_id'], {'tx_hash': 'tx13-transfer'}, market_regime='RISK_OFF', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            holding = rt.list_holdings('EQTEST')['items'][0]
            self.assertEqual(holding.get('status'), 'SOLD')
            self.assertEqual(str((holding.get('transfer_meta') or {}).get('result') or ''), 'TRANSFERRED')

    def test_pnl_mark_price_precedence_uses_market_mark_before_fair_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5)
            created = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'v_mark', 'wallet_address': 'EQTEST', 'max_spend_ton': 5.0},
                market_regime='RISK_OFF',
                variant_snapshot={'floor_ton': 6.0, 'fair_ton': 9.0, 'mark_price_ton': 7.0},
            )
            rt.confirm_intent_signature(
                created['intent']['intent_id'],
                {'tx_hash': 'tx-mark-buy'},
                market_regime='RISK_OFF',
                variant_snapshot={'floor_ton': 6.0, 'fair_ton': 9.0, 'mark_price_ton': 7.0},
            )
            position = rt.list_positions('EQTEST')['items'][0]
            self.assertEqual(position.get('mark_price_ton'), 7.0)
            self.assertEqual(position.get('unrealized_pnl_ton'), 2.0)

            created_floor = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'v_floor_mark', 'wallet_address': 'EQTEST', 'max_spend_ton': 5.0},
                market_regime='RISK_OFF',
                variant_snapshot={'floor_ton': 6.0, 'fair_ton': 10.0},
            )
            rt.confirm_intent_signature(
                created_floor['intent']['intent_id'],
                {'tx_hash': 'tx-floor-mark-buy'},
                market_regime='RISK_OFF',
                variant_snapshot={'floor_ton': 6.0, 'fair_ton': 10.0},
            )
            floor_position = next(x for x in rt.list_positions('EQTEST')['items'] if x.get('variant_id') == 'v_floor_mark')
            self.assertEqual(floor_position.get('mark_price_ton'), 6.0)
            self.assertEqual(floor_position.get('unrealized_pnl_ton'), 1.0)

    def test_sell_realizes_pnl_at_execution_price_not_fair_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5)
            buy = rt.create_trade_intent(
                {'intent_type': 'BUY', 'variant_id': 'v_sell_mark', 'wallet_address': 'EQTEST', 'max_spend_ton': 5.0},
                market_regime='RISK_OFF',
                variant_snapshot={'floor_ton': 5.0, 'fair_ton': 10.0},
            )
            rt.confirm_intent_signature(
                buy['intent']['intent_id'],
                {'tx_hash': 'tx-sell-mark-buy'},
                market_regime='RISK_OFF',
                variant_snapshot={'floor_ton': 5.0, 'fair_ton': 10.0},
            )
            sell = rt.create_trade_intent(
                {'intent_type': 'SELL', 'variant_id': 'v_sell_mark', 'wallet_address': 'EQTEST', 'price_ton': 6.0},
                market_regime='RISK_OFF',
                variant_snapshot={'floor_ton': 9.0, 'fair_ton': 12.0},
            )
            rt.confirm_intent_signature(
                sell['intent']['intent_id'],
                {'tx_hash': 'tx-sell-mark-sell'},
                market_regime='RISK_OFF',
                variant_snapshot={'floor_ton': 9.0, 'fair_ton': 12.0},
            )
            history = rt.list_trade_intents('EQTEST')['items']
            confirmed_sell = next(x for x in history if x.get('intent_type') == 'SELL')
            self.assertEqual(confirmed_sell.get('status'), 'CONFIRMED')
            self.assertEqual(rt.list_positions('EQTEST')['items'], [])
            pnl = rt.get_pnl_summary('EQTEST', market_regime='RISK_OFF')
            self.assertEqual(pnl.get('pnl_7d_ton'), 1.0)

    def test_failed_intent_keeps_error_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rt = TradeRuntime(Path(tmpdir), quote_secret='secret', quote_ttl_sec=5, tx_verify_url='https://provider/tx')
            created = rt.create_trade_intent({'intent_type': 'BUY', 'variant_id': 'v14', 'wallet_address': 'EQTEST', 'max_spend_ton': 5.0}, market_regime='MEAN_REVERT', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            with patch.object(rt, '_verify_tx_state', return_value={'status': 'FAILED', 'reason': 'provider_http_404', 'source': 'provider'}):
                item = rt.confirm_intent_signature(created['intent']['intent_id'], {'tx_hash': 'tx14'}, market_regime='MEAN_REVERT', variant_snapshot={'floor_ton': 5.0, 'fair_ton': 5.5})
            self.assertEqual(item.get('status'), 'FAILED')
            self.assertEqual(item.get('error_code'), 'provider_http_404')


if __name__ == '__main__':
    unittest.main()

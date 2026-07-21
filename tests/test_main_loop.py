import unittest
import tempfile
import os
from types import SimpleNamespace
from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd

import Config
from main import (
    _persist_daily_entry_counts_to_config,
    _run_signal_check_with_timeout,
    check_entry_signals,
    evaluate_trailing_stop_loss,
    get_next_check_time,
    initialize_runtime_state,
    is_trading_time,
    main_trading_loop,
    square_off_tracked_positions,
    should_log_pivot_this_cycle,
)


class MainLoopTests(unittest.TestCase):
    def test_next_check_time_aligns_to_boundary_with_buffer(self):
        now = Config.TIME_ZONE.localize(datetime(2026, 7, 7, 9, 22, 10))
        with patch('main.Config.STRATEGY_CONFIG', {'TIMEFRAME': 5, 'CANDLE_CLOSE_BUFFER_SECONDS': 1}):
            next_time = get_next_check_time(now)
        self.assertEqual(next_time, Config.TIME_ZONE.localize(datetime(2026, 7, 7, 9, 25, 1)))

    def test_next_check_time_uses_same_boundary_if_before_buffer(self):
        now = Config.TIME_ZONE.localize(datetime(2026, 7, 7, 9, 20, 0, 500000))
        with patch('main.Config.STRATEGY_CONFIG', {'TIMEFRAME': 5, 'CANDLE_CLOSE_BUFFER_SECONDS': 1}):
            next_time = get_next_check_time(now)
        self.assertEqual(next_time, Config.TIME_ZONE.localize(datetime(2026, 7, 7, 9, 20, 1)))

    def test_next_check_time_from_916_is_92001(self):
        now = Config.TIME_ZONE.localize(datetime(2026, 7, 7, 9, 16, 0))
        with patch('main.Config.STRATEGY_CONFIG', {'TIMEFRAME': 5, 'CANDLE_CLOSE_BUFFER_SECONDS': 1}):
            next_time = get_next_check_time(now)
        self.assertEqual(next_time, Config.TIME_ZONE.localize(datetime(2026, 7, 7, 9, 20, 1)))

    def test_check_entry_signals_skips_empty_candle_data(self):
        class EmptyUplink:
            def customCandleData(self, *_args, **_kwargs):
                return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'oi'])

        with patch('main.Config.NIFTY_CONFIG', {'enable': True, 'index_instrument': 'test', 'lot_size': 75}), \
             patch('main.Config.STRATEGY_CONFIG', {'LOTS': 1, 'MAX_ENTRIES': 3}), \
             patch('main.Config.POSITION_CONFIG', {}):
            check_entry_signals(EmptyUplink())

    def test_main_trading_loop_runs_multiple_cycles_in_test_mode(self):
        with patch('main.Config.STRATEGY_CONFIG', {'TEST_MODE': True, 'TIMEFRAME': 5, 'CANDLE_CLOSE_BUFFER_SECONDS': 1}), \
             patch('main.check_entry_signals') as mock_check, \
             patch('main.sleep', side_effect=[None, KeyboardInterrupt]):
            with self.assertRaises(KeyboardInterrupt):
                main_trading_loop(object())

        self.assertEqual(mock_check.call_count, 1)

    def test_is_trading_time_true_when_test_mode_enabled_outside_hours(self):
        off_hours = Config.TIME_ZONE.localize(datetime(2026, 7, 7, 2, 0, 0))
        with patch('main.Config.STRATEGY_CONFIG', {'TEST_MODE': True}), \
             patch('main.datetime') as mock_datetime:
            mock_datetime.now.return_value = off_hours
            self.assertTrue(is_trading_time())

    def test_initialize_runtime_state_loads_entry_counts_once(self):
        uplink = SimpleNamespace(getPositionBook=lambda: {'data': []})
        with patch('main.Config.PERSISTED_DAILY_ENTRY_COUNTS', {'2026-07-10': {'NIFTY': 2}}, create=True), \
             patch('main.Config.DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config._DAILY_ENTRY_COUNTS_LOADED', False, create=True), \
             patch('main.Config.POSITION_CONFIG', {}, create=True):
            initialize_runtime_state(uplink)
            self.assertEqual(Config.DAILY_ENTRY_COUNTS.get('2026-07-10', {}).get('NIFTY'), 2)

            Config.PERSISTED_DAILY_ENTRY_COUNTS = {'2026-07-10': {'NIFTY': 7}}
            initialize_runtime_state(uplink)
            self.assertEqual(Config.DAILY_ENTRY_COUNTS.get('2026-07-10', {}).get('NIFTY'), 2)

    def test_initialize_runtime_state_syncs_open_short_nifty_option(self):
        uplink = SimpleNamespace(
            getPositionBook=lambda: {
                'data': [
                    {
                        'instrument_token': 'NFO_OPT|NIFTY25JUL24500PE',
                        'trading_symbol': 'NIFTY25JUL24500PE',
                        'quantity': -75,
                        'average_price': 120.5,
                    }
                ]
            }
        )

        with patch('main.Config.PERSISTED_DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config.DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config._DAILY_ENTRY_COUNTS_LOADED', False, create=True), \
             patch('main.Config.POSITION_CONFIG', {}, create=True), \
             patch('main.Config.NIFTY_CONFIG', {'index_instrument': 'NSE_INDEX|Nifty 50', 'lot_size': 75, 'enable': True}, create=True):
            initialize_runtime_state(uplink)
            self.assertIn('NIFTY', Config.POSITION_CONFIG)
            self.assertEqual(Config.POSITION_CONFIG['NIFTY']['option_type'], 'PE')
            self.assertEqual(Config.POSITION_CONFIG['NIFTY']['qty'], 75)
            self.assertEqual(Config.POSITION_CONFIG['NIFTY']['entry_price'], 120.5)

    def test_initialize_runtime_state_preserves_existing_position_on_endpoint_error(self):
        uplink = SimpleNamespace(
            getPositionBook=lambda: {
                'status': 'error',
                'data': [],
                'errors': [
                    {
                        'errorCode': 'UDAPI100060',
                        'message': 'Resource not Found.',
                    }
                ],
            }
        )

        existing_position = {
            'option_instrument': 'NFO_OPT|NIFTY25JUL24500PE',
            'index_instrument': 'NSE_INDEX|Nifty 50',
            'qty': 75,
            'entry_price': 120.5,
            'option_type': 'PE',
            'lots': 1,
            'source': 'manual',
        }

        with patch('main.Config.PERSISTED_DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config.DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config._DAILY_ENTRY_COUNTS_LOADED', False, create=True), \
             patch('main.Config.POSITION_CONFIG', {'NIFTY': dict(existing_position)}, create=True), \
             patch('main.Config.NIFTY_CONFIG', {'index_instrument': 'NSE_INDEX|Nifty 50', 'lot_size': 75, 'enable': True}, create=True):
            initialize_runtime_state(uplink)
            self.assertEqual(Config.POSITION_CONFIG.get('NIFTY'), existing_position)

    def test_initialize_runtime_state_prefers_strategy_tagged_order_token(self):
        uplink = SimpleNamespace(
            getPositionBook=lambda: {
                'data': [
                    {
                        'instrument_token': 'NFO_OPT|NIFTY25JUL24450CE',
                        'trading_symbol': 'NIFTY25JUL24450CE',
                        'quantity': -150,
                        'average_price': 180.0,
                        'product': 'I',
                    },
                    {
                        'instrument_token': 'NFO_OPT|NIFTY25JUL24500PE',
                        'trading_symbol': 'NIFTY25JUL24500PE',
                        'quantity': -75,
                        'average_price': 120.5,
                        'product': 'I',
                    },
                ]
            },
            getOrderBook=lambda: {
                'data': [
                    {
                        'instrument_token': 'NFO_OPT|NIFTY25JUL24500PE',
                        'status': 'complete',
                        'transaction_type': 'SELL',
                        'product': 'I',
                        'tag': 'STRATEGY_NIFTY_INTRADAY',
                    }
                ]
            },
        )

        with patch('main.Config.PERSISTED_DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config.DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config._DAILY_ENTRY_COUNTS_LOADED', False, create=True), \
             patch('main.Config.POSITION_CONFIG', {}, create=True), \
             patch('main.Config.ORDER_TAG', 'STRATEGY_NIFTY_INTRADAY', create=True), \
             patch('main.Config.ORDER_TYPE', 'I', create=True), \
             patch('main.Config.NIFTY_CONFIG', {'index_instrument': 'NSE_INDEX|Nifty 50', 'lot_size': 75, 'enable': True}, create=True):
            initialize_runtime_state(uplink)
            self.assertIn('NIFTY', Config.POSITION_CONFIG)
            self.assertEqual(Config.POSITION_CONFIG['NIFTY']['option_instrument'], 'NFO_OPT|NIFTY25JUL24500PE')
            self.assertEqual(Config.POSITION_CONFIG['NIFTY']['qty'], 75)

    def test_initialize_runtime_state_filters_delivery_when_strategy_is_intraday(self):
        uplink = SimpleNamespace(
            getPositionBook=lambda: {
                'data': [
                    {
                        'instrument_token': 'NFO_OPT|NIFTY25JUL24450CE',
                        'trading_symbol': 'NIFTY25JUL24450CE',
                        'quantity': -150,
                        'average_price': 180.0,
                        'product': 'D',
                    },
                    {
                        'instrument_token': 'NFO_OPT|NIFTY25JUL24500PE',
                        'trading_symbol': 'NIFTY25JUL24500PE',
                        'quantity': -75,
                        'average_price': 120.5,
                        'product': 'I',
                    },
                ]
            }
        )

        with patch('main.Config.PERSISTED_DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config.DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config._DAILY_ENTRY_COUNTS_LOADED', False, create=True), \
             patch('main.Config.POSITION_CONFIG', {}, create=True), \
             patch('main.Config.ORDER_TAG', 'STRATEGY_NIFTY_INTRADAY', create=True), \
             patch('main.Config.ORDER_TYPE', 'I', create=True), \
             patch('main.Config.NIFTY_CONFIG', {'index_instrument': 'NSE_INDEX|Nifty 50', 'lot_size': 75, 'enable': True}, create=True):
            initialize_runtime_state(uplink)
            self.assertIn('NIFTY', Config.POSITION_CONFIG)
            self.assertEqual(Config.POSITION_CONFIG['NIFTY']['option_instrument'], 'NFO_OPT|NIFTY25JUL24500PE')
            self.assertEqual(Config.POSITION_CONFIG['NIFTY']['qty'], 75)

    def test_initialize_runtime_state_derives_entry_price_from_sell_value(self):
        uplink = SimpleNamespace(
            getPositionBook=lambda: {
                'data': [
                    {
                        'instrument_token': 'NFO_OPT|NIFTY25JUL24500PE',
                        'trading_symbol': 'NIFTY25JUL24500PE',
                        'quantity': -75,
                        'average_price': 0,
                        'sell_price': 0,
                        'sell_value': 9150,
                        'product': 'I',
                    }
                ]
            },
            getLTP=lambda _instrument: 130.0,
        )

        with patch('main.Config.PERSISTED_DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config.DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config._DAILY_ENTRY_COUNTS_LOADED', False, create=True), \
             patch('main.Config.POSITION_CONFIG', {}, create=True), \
             patch('main.Config.ORDER_TAG', 'STRATEGY_NIFTY_INTRADAY', create=True), \
             patch('main.Config.ORDER_TYPE', 'I', create=True), \
             patch('main.Config.NIFTY_CONFIG', {'index_instrument': 'NSE_INDEX|Nifty 50', 'lot_size': 75, 'enable': True}, create=True):
            initialize_runtime_state(uplink)
            self.assertIn('NIFTY', Config.POSITION_CONFIG)
            self.assertAlmostEqual(Config.POSITION_CONFIG['NIFTY']['entry_price'], 122.0)

    def test_initialize_runtime_state_restores_trailing_mode_on_restart(self):
        class TrailingUplink:
            def getPositionBook(self):
                return {
                    'data': [
                        {
                            'instrument_token': 'NFO_OPT|NIFTY25JUL24500PE',
                            'trading_symbol': 'NIFTY25JUL24500PE',
                            'quantity': -75,
                            'average_price': 500.0,
                            'product': 'I',
                        }
                    ]
                }

            def getRequiredMargin(self, **_kwargs):
                return 1_000_000

            def getLTP(self, _instrument):
                return 366.0

        with patch('main.Config.PERSISTED_DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config.DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config._DAILY_ENTRY_COUNTS_LOADED', False, create=True), \
             patch('main.Config.POSITION_CONFIG', {}, create=True), \
             patch('main.Config.NIFTY_CONFIG', {'index_instrument': 'NSE_INDEX|Nifty 50', 'lot_size': 75, 'enable': True}, create=True), \
             patch('main.Config.STRATEGY_CONFIG', {
                 'ENABLE_TRAILING_STOP_LOSS': True,
                 'TRAILING_ACTIVATION_PROFIT_PERCENT_OF_MARGIN': 1.0,
                 'TRAILING_STOP_LOSS_GAP_PERCENT_OF_MARGIN': 0.5,
                 'TRAILING_STEP_ABSOLUTE_RS': 1000,
             }, create=True):
            initialize_runtime_state(TrailingUplink())
            self.assertIn('NIFTY', Config.POSITION_CONFIG)
            self.assertTrue(Config.POSITION_CONFIG['NIFTY']['trailing_stop_loss']['active'])
            self.assertAlmostEqual(Config.POSITION_CONFIG['NIFTY']['trailing_stop_loss']['stop_loss_pnl'], 5050.0)

    def test_initialize_runtime_state_prefers_seeded_config_position_when_present_in_broker_candidates(self):
        seeded_position = {
            'option_instrument': 'NFO_OPT|NIFTY25JUL24500PE',
            'index_instrument': 'NSE_INDEX|Nifty 50',
            'qty': 75,
            'entry_price': 121.0,
            'option_type': 'PE',
            'lots': 1,
            'entry_order_id': 'seed-order',
            'order_status': 'submitted',
        }

        uplink = SimpleNamespace(
            getPositionBook=lambda: {
                'data': [
                    {
                        'instrument_token': 'NFO_OPT|NIFTY25JUL24450CE',
                        'trading_symbol': 'NIFTY25JUL24450CE',
                        'quantity': -150,
                        'average_price': 180.0,
                        'product': 'I',
                    },
                    {
                        'instrument_token': 'NFO_OPT|NIFTY25JUL24500PE',
                        'trading_symbol': 'NIFTY25JUL24500PE',
                        'quantity': -75,
                        'average_price': 120.5,
                        'product': 'I',
                    },
                ]
            },
            getOrderBook=lambda: {'data': []},
        )

        with patch('main.Config.PERSISTED_DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config.DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config._DAILY_ENTRY_COUNTS_LOADED', False, create=True), \
             patch('main.Config.POSITION_CONFIG', {'NIFTY': dict(seeded_position)}, create=True), \
             patch('main.Config.ORDER_TAG', 'STRATEGY_NIFTY_INTRADAY', create=True), \
             patch('main.Config.ORDER_TYPE', 'I', create=True), \
             patch('main.Config.NIFTY_CONFIG', {'index_instrument': 'NSE_INDEX|Nifty 50', 'lot_size': 75, 'enable': True}, create=True):
            initialize_runtime_state(uplink)
            self.assertEqual(Config.POSITION_CONFIG['NIFTY']['option_instrument'], seeded_position['option_instrument'])
            self.assertEqual(Config.POSITION_CONFIG['NIFTY']['qty'], 75)
            self.assertEqual(Config.POSITION_CONFIG['NIFTY']['entry_order_id'], 'seed-order')

    def test_initialize_runtime_state_retains_seeded_config_position_when_broker_has_no_candidates(self):
        seeded_position = {
            'option_instrument': 'NFO_OPT|NIFTY25JUL24500PE',
            'index_instrument': 'NSE_INDEX|Nifty 50',
            'qty': 75,
            'entry_price': 121.0,
            'option_type': 'PE',
            'lots': 1,
            'entry_order_id': 'seed-order',
            'order_status': 'submitted',
        }

        uplink = SimpleNamespace(
            getPositionBook=lambda: {'data': []},
            getOrderBook=lambda: {'data': []},
        )

        with patch('main.Config.PERSISTED_DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config.DAILY_ENTRY_COUNTS', {}, create=True), \
             patch('main.Config._DAILY_ENTRY_COUNTS_LOADED', False, create=True), \
             patch('main.Config.POSITION_CONFIG', {'NIFTY': dict(seeded_position)}, create=True), \
             patch('main.Config.ORDER_TAG', 'STRATEGY_NIFTY_INTRADAY', create=True), \
             patch('main.Config.ORDER_TYPE', 'I', create=True), \
             patch('main.Config.NIFTY_CONFIG', {'index_instrument': 'NSE_INDEX|Nifty 50', 'lot_size': 75, 'enable': True}, create=True):
            initialize_runtime_state(uplink)
            self.assertEqual(Config.POSITION_CONFIG.get('NIFTY'), seeded_position)

    def test_persist_daily_entry_counts_updates_config_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = os.path.join(tmp_dir, 'Config.py')
            with open(config_path, 'w', encoding='utf-8') as file_obj:
                file_obj.write(
                    "PERSISTED_DAILY_ENTRY_COUNTS = {}\n"
                    "DAILY_ENTRY_COUNTS = {}\n"
                )

            counts = {'2026-07-10': {'NIFTY': 3}}
            with patch('main.Config.__file__', config_path, create=True):
                _persist_daily_entry_counts_to_config(counts)

            with open(config_path, 'r', encoding='utf-8') as file_obj:
                updated = file_obj.read()

            self.assertIn('PERSISTED_DAILY_ENTRY_COUNTS = {"2026-07-10": {"NIFTY": 3}}', updated)

    def test_run_signal_check_with_timeout_returns_false_when_blocked(self):
        def _blocked_check(_uplink):
            import time
            time.sleep(0.2)

        with patch('main.check_entry_signals', side_effect=_blocked_check), \
             patch('main.get_signal_check_timeout_seconds', return_value=0.05):
            self.assertFalse(_run_signal_check_with_timeout(object()))

    def test_main_trading_loop_raises_after_timeout_threshold(self):
        with patch('main.Config.STRATEGY_CONFIG', {
                'TEST_MODE': True,
                'TIMEFRAME': 5,
                'CANDLE_CLOSE_BUFFER_SECONDS': 1,
                'MAX_CONSECUTIVE_SIGNAL_TIMEOUTS': 2,
            }), \
             patch('main._run_signal_check_with_timeout', return_value=False), \
             patch('main.sleep', return_value=None):
            with self.assertRaises(RuntimeError):
                main_trading_loop(object())

    def test_main_trading_loop_squares_off_at_end_time(self):
        before_end_dt = Config.TIME_ZONE.localize(datetime(2026, 7, 10, 15, 10, 1))
        uplink = SimpleNamespace(closePosition=lambda *_args, **_kwargs: 'close-order-id')

        with patch('main.Config.STRATEGY_CONFIG', {'TEST_MODE': False, 'TIMEFRAME': 5, 'CANDLE_CLOSE_BUFFER_SECONDS': 1}), \
             patch('main.Config.POSITION_CONFIG', {'NIFTY': {'option_instrument': 'NFO_OPT|NIFTY25JUL24500PE', 'qty': 75}}, create=True), \
             patch('main.datetime') as mock_datetime, \
             patch('main.get_next_check_time', return_value=before_end_dt + timedelta(minutes=5)), \
             patch('main.has_reached_trading_end', side_effect=[False, True]), \
             patch('main.sleep', return_value=None), \
             patch.object(uplink, 'closePosition') as mock_close_position, \
             patch('main._run_signal_check_with_timeout') as mock_run_check:
            mock_datetime.now.return_value = before_end_dt

            main_trading_loop(uplink)

        mock_close_position.assert_called_once_with('NFO_OPT|NIFTY25JUL24500PE', 75, 'BUY')
        mock_run_check.assert_not_called()

    def test_square_off_tracked_positions_noop_when_empty(self):
        uplink = SimpleNamespace(closePosition=lambda *_args, **_kwargs: 'close-order-id')

        with patch('main.Config.POSITION_CONFIG', {}, create=True), \
             patch.object(uplink, 'closePosition') as mock_close_position:
            closed = square_off_tracked_positions(uplink, 'test-context')

        self.assertEqual(closed, 0)
        mock_close_position.assert_not_called()

    def test_should_log_pivot_every_12th_iteration(self):
        with patch('main.Config.STRATEGY_CONFIG', {'PIVOT_LOG_INTERVAL_ITERATIONS': 12}, create=True), \
             patch('main.Config.SIGNAL_CHECK_ITERATION_COUNT', 0, create=True):
            results = [should_log_pivot_this_cycle() for _ in range(12)]

        self.assertFalse(any(results[:11]))
        self.assertTrue(results[11])

    def test_trailing_stop_loss_activates_at_threshold_and_sets_initial_stop(self):
        class TrailingUplink:
            def getRequiredMargin(self, **_kwargs):
                return 1_000_000

            def getLTP(self, _instrument):
                return 366.0

        position_config = {
            'option_instrument': 'NFO_OPT|NIFTY_TEST_PE',
            'qty': 75,
            'entry_price': 500.0,
            'option_type': 'PE',
        }

        with patch('main.Config.STRATEGY_CONFIG', {
                'ENABLE_TRAILING_STOP_LOSS': True,
                'TRAILING_ACTIVATION_PROFIT_PERCENT_OF_MARGIN': 1.0,
                'TRAILING_STOP_LOSS_GAP_PERCENT_OF_MARGIN': 0.5,
                'TRAILING_STEP_ABSOLUTE_RS': 1000,
            }, create=True):
            result = evaluate_trailing_stop_loss(TrailingUplink(), 'NIFTY', position_config)

        self.assertTrue(result['active'])
        self.assertEqual(result['action'], 'hold')
        self.assertAlmostEqual(position_config['trailing_stop_loss']['stop_loss_pnl'], 5050.0)

    def test_trailing_stop_loss_moves_only_by_configured_step(self):
        class TrailingUplink:
            def __init__(self):
                self._ltps = [366.6666667, 353.3333333]
                self._idx = 0

            def getRequiredMargin(self, **_kwargs):
                return 1_000_000

            def getLTP(self, _instrument):
                ltp = self._ltps[min(self._idx, len(self._ltps) - 1)]
                self._idx += 1
                return ltp

        uplink = TrailingUplink()
        position_config = {
            'option_instrument': 'NFO_OPT|NIFTY_TEST_PE',
            'qty': 75,
            'entry_price': 500.0,
            'option_type': 'PE',
        }

        with patch('main.Config.STRATEGY_CONFIG', {
                'ENABLE_TRAILING_STOP_LOSS': True,
                'TRAILING_ACTIVATION_PROFIT_PERCENT_OF_MARGIN': 1.0,
                'TRAILING_STOP_LOSS_GAP_PERCENT_OF_MARGIN': 0.5,
                'TRAILING_STEP_ABSOLUTE_RS': 1000,
            }, create=True):
            evaluate_trailing_stop_loss(uplink, 'NIFTY', position_config)
            evaluate_trailing_stop_loss(uplink, 'NIFTY', position_config)

        self.assertAlmostEqual(position_config['trailing_stop_loss']['stop_loss_pnl'], 6000.0, places=4)

    def test_trailing_stop_loss_does_not_move_when_profit_drops(self):
        class TrailingUplink:
            def __init__(self):
                self._ltps = [340.0, 346.6666667]
                self._idx = 0

            def getRequiredMargin(self, **_kwargs):
                return 1_000_000

            def getLTP(self, _instrument):
                ltp = self._ltps[min(self._idx, len(self._ltps) - 1)]
                self._idx += 1
                return ltp

        uplink = TrailingUplink()
        position_config = {
            'option_instrument': 'NFO_OPT|NIFTY_TEST_PE',
            'qty': 75,
            'entry_price': 500.0,
            'option_type': 'PE',
        }

        with patch('main.Config.STRATEGY_CONFIG', {
                'ENABLE_TRAILING_STOP_LOSS': True,
                'TRAILING_ACTIVATION_PROFIT_PERCENT_OF_MARGIN': 1.0,
                'TRAILING_STOP_LOSS_GAP_PERCENT_OF_MARGIN': 0.5,
                'TRAILING_STEP_ABSOLUTE_RS': 1000,
            }, create=True):
            evaluate_trailing_stop_loss(uplink, 'NIFTY', position_config)
            evaluate_trailing_stop_loss(uplink, 'NIFTY', position_config)

        self.assertAlmostEqual(position_config['trailing_stop_loss']['stop_loss_pnl'], 7000.0)

    def test_trailing_stop_loss_accepts_dict_like_ltp_payload(self):
        class TrailingUplink:
            def getRequiredMargin(self, **_kwargs):
                return 1_000_000

            def getLTP(self, _instrument):
                return {
                    'data': {
                        'NFO_OPT|NIFTY_TEST_PE': {
                            'last_price': 366.0,
                        }
                    }
                }

        position_config = {
            'option_instrument': 'NFO_OPT|NIFTY_TEST_PE',
            'qty': 75,
            'entry_price': 500.0,
            'option_type': 'PE',
        }

        with patch('main.Config.STRATEGY_CONFIG', {
                'ENABLE_TRAILING_STOP_LOSS': True,
                'TRAILING_ACTIVATION_PROFIT_PERCENT_OF_MARGIN': 1.0,
                'TRAILING_STOP_LOSS_GAP_PERCENT_OF_MARGIN': 0.5,
                'TRAILING_STEP_ABSOLUTE_RS': 1000,
            }, create=True):
            result = evaluate_trailing_stop_loss(TrailingUplink(), 'NIFTY', position_config)

        self.assertEqual(result['action'], 'hold')
        self.assertTrue(result['active'])
        self.assertAlmostEqual(result['running_pnl'], 10050.0)

    def test_trailing_stop_loss_uses_position_row_ltp_fallback_when_get_ltp_unavailable(self):
        class TrailingUplink:
            def getRequiredMargin(self, **_kwargs):
                return 10_000

            def getPositionBook(self):
                return {
                    'data': [
                        {
                            'instrument_token': 'NFO_OPT|NIFTY_TEST_PE',
                            'quantity': -10,
                            'last_price': 90.0,
                            'pnl': None,
                        }
                    ]
                }

        position_config = {
            'option_instrument': 'NFO_OPT|NIFTY_TEST_PE',
            'qty': 10,
            'entry_price': 100.0,
            'option_type': 'PE',
        }

        with patch('main.Config.STRATEGY_CONFIG', {
                'ENABLE_TRAILING_STOP_LOSS': True,
                'TRAILING_ACTIVATION_PROFIT_PERCENT_OF_MARGIN': 1.0,
                'TRAILING_STOP_LOSS_GAP_PERCENT_OF_MARGIN': 0.5,
                'TRAILING_STEP_ABSOLUTE_RS': 1000,
            }, create=True):
            result = evaluate_trailing_stop_loss(TrailingUplink(), 'NIFTY', position_config)

        self.assertEqual(result['action'], 'hold')
        self.assertTrue(result['active'])
        self.assertAlmostEqual(result['running_pnl'], 100.0)

    def test_trailing_stop_loss_matches_position_row_on_numeric_token_suffix(self):
        class TrailingUplink:
            def getRequiredMargin(self, **_kwargs):
                return None

            def getPositionBook(self):
                return {
                    'data': [
                        {
                            'instrument_token': 'NFO_OPT|57346',
                            'quantity': -260,
                            'last_price': 20.0,
                            'used_margin': 50000.0,
                        }
                    ]
                }

        position_config = {
            'option_instrument': 'NSE_FO|57346',
            'qty': 260,
            'entry_price': 25.0,
            'option_type': 'CE',
        }

        with patch('main.Config.STRATEGY_CONFIG', {
                'ENABLE_TRAILING_STOP_LOSS': True,
                'TRAILING_ACTIVATION_PROFIT_PERCENT_OF_MARGIN': 1.0,
                'TRAILING_STOP_LOSS_GAP_PERCENT_OF_MARGIN': 0.5,
                'TRAILING_STEP_ABSOLUTE_RS': 1000,
            }, create=True):
            result = evaluate_trailing_stop_loss(TrailingUplink(), 'NIFTY', position_config)

        self.assertEqual(result['action'], 'hold')
        self.assertTrue(result['active'])
        self.assertAlmostEqual(result['running_pnl'], 1300.0)
        self.assertAlmostEqual(result['used_margin'], 50000.0)

    def test_trailing_stop_loss_exits_when_running_pnl_below_trail(self):
        class TrailingUplink:
            def getRequiredMargin(self, **_kwargs):
                return 1_000_000

            def getLTP(self, _instrument):
                return 394.6666667

        position_config = {
            'option_instrument': 'NFO_OPT|NIFTY_TEST_PE',
            'qty': 75,
            'entry_price': 500.0,
            'option_type': 'PE',
            'trailing_stop_loss': {
                'active': True,
                'stop_loss_pnl': 8000.0,
                'last_peak_pnl': 13000.0,
                'last_trail_anchor_pnl': 12000.0,
            },
        }

        with patch('main.Config.STRATEGY_CONFIG', {
                'ENABLE_TRAILING_STOP_LOSS': True,
                'TRAILING_ACTIVATION_PROFIT_PERCENT_OF_MARGIN': 1.0,
                'TRAILING_STOP_LOSS_GAP_PERCENT_OF_MARGIN': 0.5,
                'TRAILING_STEP_ABSOLUTE_RS': 1000,
            }, create=True):
            result = evaluate_trailing_stop_loss(TrailingUplink(), 'NIFTY', position_config)

        self.assertEqual(result['action'], 'exit')
        self.assertTrue(result['active'])

    def test_check_entry_signals_skips_strategy_logic_once_trailing_active(self):
        class TrailingUplink:
            def customCandleData(self, *_args, **_kwargs):
                return pd.DataFrame([
                    {'date': pd.Timestamp('2026-07-10 09:15:00', tz='Asia/Kolkata'), 'open': 100.0, 'high': 110.0, 'low': 95.0, 'close': 108.0, 'volume': 1000, 'oi': 0},
                    {'date': pd.Timestamp('2026-07-10 09:20:00', tz='Asia/Kolkata'), 'open': 108.0, 'high': 112.0, 'low': 102.0, 'close': 111.0, 'volume': 1000, 'oi': 0},
                ])

            def getRequiredMargin(self, **_kwargs):
                return 1_000_000

            def getLTP(self, _instrument):
                return 360.0

        uplink = TrailingUplink()
        with patch('main.Config.NIFTY_CONFIG', {'enable': True, 'index_instrument': 'NSE_INDEX|Nifty 50', 'lot_size': 75}), \
             patch('main.Config.STRATEGY_CONFIG', {
                 'LOTS': 1,
                 'MAX_ENTRIES': 3,
                 'TIMEFRAME': 5,
                 'ENABLE_TRAILING_STOP_LOSS': True,
                 'TRAILING_ACTIVATION_PROFIT_PERCENT_OF_MARGIN': 1.0,
                 'TRAILING_STOP_LOSS_GAP_PERCENT_OF_MARGIN': 0.5,
                 'TRAILING_STEP_ABSOLUTE_RS': 1000,
             }, create=True), \
             patch('main.Config.POSITION_CONFIG', {
                 'NIFTY': {
                     'option_instrument': 'NFO_OPT|NIFTY_TEST_PE',
                     'qty': 75,
                     'entry_price': 500.0,
                     'option_type': 'PE',
                 }
             }, create=True), \
             patch('main._get_fixed_daily_pivot_levels', return_value={'pivot': 100.0, 'r1': 105.0, 's1': 95.0}), \
             patch('main.evaluate_strategy_signal') as mock_strategy_signal, \
             patch('main.exit_position') as mock_exit:
            check_entry_signals(uplink)

        mock_strategy_signal.assert_not_called()
        mock_exit.assert_not_called()

    def test_get_next_check_time_uses_trailing_interval_when_active(self):
        now = Config.TIME_ZONE.localize(datetime(2026, 7, 7, 9, 22, 10))

        with patch('main.is_trailing_stop_loss_enabled', return_value=True), \
             patch('main._is_any_trailing_mode_active', return_value=True), \
             patch('main.get_trailing_evaluation_interval_seconds', return_value=90.0):
            next_time = get_next_check_time(now)

        self.assertEqual(next_time, now + timedelta(seconds=90))

    def test_get_next_check_time_stays_timeframe_aligned_when_position_open_but_trailing_inactive(self):
        now = Config.TIME_ZONE.localize(datetime(2026, 7, 7, 9, 22, 10))

        with patch('main.is_trailing_stop_loss_enabled', return_value=True), \
             patch('main._is_any_trailing_mode_active', return_value=False), \
             patch('main._has_any_tracked_open_position', return_value=True), \
             patch('main.get_trailing_evaluation_interval_seconds', return_value=90.0):
            next_time = get_next_check_time(now)

        self.assertEqual(next_time, Config.TIME_ZONE.localize(datetime(2026, 7, 7, 9, 25, 1)))

    def test_get_next_check_time_ignores_string_false_trailing_active_state(self):
        now = Config.TIME_ZONE.localize(datetime(2026, 7, 7, 9, 22, 10))

        with patch('main.is_trailing_stop_loss_enabled', return_value=True), \
             patch('main.Config.POSITION_CONFIG', {
                 'NIFTY': {
                     'trailing_stop_loss': {
                         'active': 'False',
                     }
                 }
             }, create=True):
            next_time = get_next_check_time(now)

        self.assertEqual(next_time, Config.TIME_ZONE.localize(datetime(2026, 7, 7, 9, 25, 1)))

    def test_check_entry_signals_continues_strategy_logic_when_trailing_enabled_but_not_armed(self):
        class TrailingUplink:
            def customCandleData(self, *_args, **_kwargs):
                return pd.DataFrame([
                    {'date': pd.Timestamp('2026-07-10 09:15:00', tz='Asia/Kolkata'), 'open': 100.0, 'high': 110.0, 'low': 95.0, 'close': 108.0, 'volume': 1000, 'oi': 0},
                    {'date': pd.Timestamp('2026-07-10 09:20:00', tz='Asia/Kolkata'), 'open': 108.0, 'high': 112.0, 'low': 102.0, 'close': 111.0, 'volume': 1000, 'oi': 0},
                ])

            def getRequiredMargin(self, **_kwargs):
                return 1_000_000

            def getLTP(self, _instrument):
                return 470.0

        uplink = TrailingUplink()
        with patch('main.Config.NIFTY_CONFIG', {'enable': True, 'index_instrument': 'NSE_INDEX|Nifty 50', 'lot_size': 75}), \
             patch('main.Config.STRATEGY_CONFIG', {
                 'LOTS': 1,
                 'MAX_ENTRIES': 3,
                 'TIMEFRAME': 5,
                 'ENABLE_TRAILING_STOP_LOSS': True,
                 'TRAILING_ACTIVATION_PROFIT_PERCENT_OF_MARGIN': 1.0,
                 'TRAILING_STOP_LOSS_GAP_PERCENT_OF_MARGIN': 0.5,
                 'TRAILING_STEP_ABSOLUTE_RS': 1000,
             }, create=True), \
             patch('main.Config.POSITION_CONFIG', {
                 'NIFTY': {
                     'option_instrument': 'NFO_OPT|NIFTY_TEST_PE',
                     'qty': 75,
                     'entry_price': 500.0,
                     'option_type': 'PE',
                     'trailing_stop_loss': {},
                 }
             }, create=True), \
             patch('main._get_fixed_daily_pivot_levels', return_value={'pivot': 100.0, 'r1': 105.0, 's1': 95.0}), \
             patch('main.evaluate_strategy_signal', return_value={'action': 'hold'}) as mock_strategy_signal, \
             patch('main.exit_position') as mock_exit:
            check_entry_signals(uplink)

        mock_strategy_signal.assert_called_once()
        mock_exit.assert_not_called()


if __name__ == '__main__':
    unittest.main()

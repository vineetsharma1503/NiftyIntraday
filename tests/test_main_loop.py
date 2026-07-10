import unittest
import tempfile
import os
from types import SimpleNamespace
from datetime import datetime
from unittest.mock import patch

import pandas as pd

import Config
from main import (
    _persist_daily_entry_counts_to_config,
    _run_signal_check_with_timeout,
    check_entry_signals,
    get_next_check_time,
    initialize_runtime_state,
    is_trading_time,
    main_trading_loop,
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


if __name__ == '__main__':
    unittest.main()

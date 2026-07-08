import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd

import Config
from main import check_entry_signals, get_next_check_time, main_trading_loop, is_trading_time


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


if __name__ == '__main__':
    unittest.main()

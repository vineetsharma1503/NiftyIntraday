import unittest
from unittest.mock import patch

import pandas as pd

from strategy_logic import evaluate_strategy_signal


class StrategyLogicTests(unittest.TestCase):
    def test_uses_provided_daily_pivot_levels(self):
        candle_data = pd.DataFrame([
            {'high': 100, 'low': 90, 'close': 95},
            {'high': 110, 'low': 100, 'close': 105},
        ])

        result = evaluate_strategy_signal(
            candle_data,
            position_open=False,
            entry_count=0,
            pivot_levels={'pivot': 95.0, 'r1': 104.0, 's1': 90.0},
        )

        self.assertEqual(result['action'], 'enter')
        self.assertEqual(result['option_type'], 'PE')

    def test_bullish_entry_signal(self):
        candle_data = pd.DataFrame([
            {'high': 100, 'low': 90, 'close': 95},
            {'high': 103, 'low': 98, 'close': 102},
        ])

        result = evaluate_strategy_signal(candle_data, position_open=False, entry_count=0)

        self.assertEqual(result['action'], 'enter')
        self.assertEqual(result['option_type'], 'PE')
        self.assertEqual(result['lots'], 1)

    def test_bearish_entry_signal(self):
        candle_data = pd.DataFrame([
            {'high': 100, 'low': 90, 'close': 95},
            {'high': 95, 'low': 88, 'close': 89},
        ])

        indicator = candle_data.copy()
        indicator['supertrend'] = [96, 96]
        indicator['supertrend_direction'] = [-1, -1]

        with patch('strategy_logic.create_supertrend_indicator', return_value=indicator):
            result = evaluate_strategy_signal(candle_data, position_open=False, entry_count=0)

        self.assertEqual(result['action'], 'enter')
        self.assertEqual(result['option_type'], 'CE')
        self.assertEqual(result['lots'], 1)

    def test_exit_signal(self):
        candle_data = pd.DataFrame([
            {'high': 100, 'low': 90, 'close': 95},
            {'high': 95, 'low': 88, 'close': 89},
        ])

        result = evaluate_strategy_signal(candle_data, position_open=True, position_option_type='PE')

        self.assertEqual(result['action'], 'exit')
        self.assertEqual(result['option_type'], 'PE')

    def test_hold_signal_when_position_open_and_exit_not_met(self):
        candle_data = pd.DataFrame([
            {'high': 100, 'low': 90, 'close': 95},
            {'high': 104, 'low': 96, 'close': 102},
        ])

        result = evaluate_strategy_signal(candle_data, position_open=True, position_option_type='PE')

        self.assertEqual(result['action'], 'hold')
        self.assertEqual(result['option_type'], 'PE')

    def test_logs_strategy_decision_details(self):
        candle_data = pd.DataFrame([
            {'high': 100, 'low': 90, 'close': 95},
            {'high': 103, 'low': 98, 'close': 102},
        ])

        with self.assertLogs(level='INFO') as captured:
            evaluate_strategy_signal(candle_data, position_open=False, entry_count=0)

        logs = '\n'.join(captured.output)
        self.assertIn('pivot', logs.lower())
        self.assertIn('supertrend', logs.lower())
        self.assertIn('decision', logs.lower())


if __name__ == '__main__':
    unittest.main()

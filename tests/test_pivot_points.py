import unittest

import pandas as pd

from pivot_points import (
    calculate_daily_pivot_levels,
    calculate_daily_pivot_levels_from_candles,
    create_supertrend_indicator,
    has_price_crossed_r1,
    has_price_crossed_s1,
)


class PivotPointTests(unittest.TestCase):
    def test_standard_daily_pivot_levels(self):
        levels = calculate_daily_pivot_levels(high=100, low=90, close=95)
        self.assertAlmostEqual(levels['pivot'], 95.0)
        self.assertAlmostEqual(levels['r1'], 100.0)
        self.assertAlmostEqual(levels['s1'], 90.0)

    def test_calculate_from_candles_dataframe(self):
        candle_data = pd.DataFrame([
            {'high': 100, 'low': 90, 'close': 95}
        ])
        levels = calculate_daily_pivot_levels_from_candles(candle_data)
        self.assertAlmostEqual(levels['pivot'], 95.0)
        self.assertAlmostEqual(levels['r1'], 100.0)
        self.assertAlmostEqual(levels['s1'], 90.0)

    def test_cross_signal_helpers(self):
        self.assertTrue(has_price_crossed_r1(101, 100))
        self.assertFalse(has_price_crossed_r1(99, 100))
        self.assertTrue(has_price_crossed_s1(89, 90))
        self.assertFalse(has_price_crossed_s1(91, 90))

    def test_create_supertrend_indicator(self):
        candle_data = pd.DataFrame([
            {'high': 100, 'low': 95, 'close': 98},
            {'high': 102, 'low': 97, 'close': 101},
            {'high': 103, 'low': 99, 'close': 100},
            {'high': 104, 'low': 100, 'close': 103},
        ])

        indicator = create_supertrend_indicator(candle_data)

        self.assertIn('supertrend', indicator.columns)
        self.assertIn('supertrend_direction', indicator.columns)
        self.assertEqual(len(indicator), len(candle_data))
        self.assertTrue(indicator['supertrend_direction'].isin([1, -1]).all())

    def test_supertrend_direction_matches_line_side(self):
        candle_data = pd.DataFrame([
            {'high': 100, 'low': 95, 'close': 99},
            {'high': 103, 'low': 98, 'close': 102},
            {'high': 105, 'low': 101, 'close': 104},
            {'high': 106, 'low': 102, 'close': 103},
            {'high': 104, 'low': 99, 'close': 100},
            {'high': 101, 'low': 96, 'close': 97},
            {'high': 99, 'low': 94, 'close': 95},
            {'high': 98, 'low': 93, 'close': 94},
        ])

        indicator = create_supertrend_indicator(candle_data, length=3, multiplier=2.0)

        for _, row in indicator.iterrows():
            if int(row['supertrend_direction']) == 1:
                self.assertGreaterEqual(float(row['close']), float(row['supertrend']))
            else:
                self.assertLessEqual(float(row['close']), float(row['supertrend']))


if __name__ == '__main__':
    unittest.main()

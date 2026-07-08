"""Pivot point helpers for intraday NIFTY analysis.

This module implements the classic Standard Pivot Point calculation using the
previous day's high, low, and close values. It also exposes helpers that can
be used to check whether the current price has crossed the R1 or S1 levels.
"""

from __future__ import annotations

from typing import Dict, Union

import pandas as pd


def calculate_daily_pivot_levels(high: float, low: float, close: float) -> Dict[str, float]:
    """Calculate daily pivot, R1 and S1 using the standard formula.

    Standard pivot point formulas:
        Pivot = (High + Low + Close) / 3
        R1 = (2 * Pivot) - Low
        S1 = (2 * Pivot) - High
    """
    high_value = float(high)
    low_value = float(low)
    close_value = float(close)

    pivot = (high_value + low_value + close_value) / 3.0
    r1 = (2 * pivot) - low_value
    s1 = (2 * pivot) - high_value

    return {
        'pivot': pivot,
        'r1': r1,
        's1': s1,
    }


def calculate_daily_pivot_levels_from_candles(candle_data: Union[pd.DataFrame, pd.Series, dict], candle_index: int = -1) -> Dict[str, float]:
    """Calculate pivot levels from candle data.

    The function accepts either a pandas DataFrame/Series or a mapping containing
    HLC values. When a DataFrame is provided, the last candle is used by default.
    """
    if isinstance(candle_data, pd.DataFrame):
        if candle_data.empty:
            raise ValueError('Candle data is empty')
        row = candle_data.iloc[candle_index]
    elif isinstance(candle_data, pd.Series):
        row = candle_data
    elif isinstance(candle_data, dict):
        row = candle_data
    else:
        raise TypeError('Expected pandas DataFrame/Series or dict for candle data')

    if not isinstance(row, dict):
        row = row.to_dict()

    return calculate_daily_pivot_levels(
        row.get('high'),
        row.get('low'),
        row.get('close'),
    )


def create_supertrend_indicator(candle_data: Union[pd.DataFrame, pd.Series, dict], length: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """Create a Supertrend indicator from OHLC candle data.

    The helper returns the original candle data with two additional columns:
    - supertrend: the calculated trend line value.
    - supertrend_direction: 1 for an uptrend and -1 for a downtrend.

    The calculation follows TradingView-style Supertrend behavior:
    - ATR uses Wilder's RMA smoothing.
    - Final upper/lower bands are carried forward conditionally.
    - Direction is 1 for bullish (line below price) and -1 for bearish.
    """
    if isinstance(candle_data, pd.DataFrame):
        dataframe = candle_data.copy()
    elif isinstance(candle_data, pd.Series):
        dataframe = pd.DataFrame([candle_data.to_dict()])
    elif isinstance(candle_data, dict):
        dataframe = pd.DataFrame([candle_data])
    else:
        raise TypeError('Expected pandas DataFrame/Series or dict for candle data')

    if dataframe.empty:
        raise ValueError('Candle data is empty')

    required_columns = {'high', 'low', 'close'}
    missing_columns = required_columns.difference(dataframe.columns)
    if missing_columns:
        raise KeyError(f'Missing required columns: {sorted(missing_columns)}')

    dataframe = dataframe.copy()
    dataframe['high'] = pd.to_numeric(dataframe['high'], errors='coerce')
    dataframe['low'] = pd.to_numeric(dataframe['low'], errors='coerce')
    dataframe['close'] = pd.to_numeric(dataframe['close'], errors='coerce')

    if dataframe[['high', 'low', 'close']].isna().any().any():
        raise ValueError('Candle data contains non-numeric values')

    length_value = int(length)
    if length_value <= 0:
        raise ValueError('length must be greater than 0')

    high = dataframe['high']
    low = dataframe['low']
    close = dataframe['close']

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Wilder's RMA for ATR to align with TradingView's ta.atr/ta.rma behavior.
    atr = pd.Series([float('nan')] * len(dataframe), index=dataframe.index, dtype='float64')
    if len(dataframe) > 0:
        atr.iloc[0] = float(tr.iloc[0])
        for index in range(1, len(dataframe)):
            atr.iloc[index] = ((atr.iloc[index - 1] * (length_value - 1)) + tr.iloc[index]) / length_value

    hl_average = (high + low) / 2.0
    basic_upper = hl_average + (multiplier * atr)
    basic_lower = hl_average - (multiplier * atr)

    final_upper = pd.Series([float('nan')] * len(dataframe), index=dataframe.index, dtype='float64')
    final_lower = pd.Series([float('nan')] * len(dataframe), index=dataframe.index, dtype='float64')
    supertrend = pd.Series([float('nan')] * len(dataframe), index=dataframe.index, dtype='float64')
    direction = pd.Series([0] * len(dataframe), index=dataframe.index, dtype='int64')

    for index in range(len(dataframe)):
        if index == 0:
            final_upper.iloc[index] = basic_upper.iloc[index]
            final_lower.iloc[index] = basic_lower.iloc[index]
            if close.iloc[index] >= hl_average.iloc[index]:
                supertrend.iloc[index] = final_lower.iloc[index]
                direction.iloc[index] = 1
            else:
                supertrend.iloc[index] = final_upper.iloc[index]
                direction.iloc[index] = -1
            continue

        prev_upper = final_upper.iloc[index - 1]
        prev_lower = final_lower.iloc[index - 1]
        prev_close_value = close.iloc[index - 1]
        current_upper = basic_upper.iloc[index]
        current_lower = basic_lower.iloc[index]

        final_upper.iloc[index] = current_upper if (current_upper < prev_upper) or (prev_close_value > prev_upper) else prev_upper
        final_lower.iloc[index] = current_lower if (current_lower > prev_lower) or (prev_close_value < prev_lower) else prev_lower

        previous_supertrend = supertrend.iloc[index - 1]
        previous_final_upper = final_upper.iloc[index - 1]

        # If previous supertrend used upper band, we're in bearish mode until close breaks above upper band.
        if previous_supertrend == previous_final_upper:
            if close.iloc[index] <= final_upper.iloc[index]:
                supertrend.iloc[index] = final_upper.iloc[index]
                direction.iloc[index] = -1
            else:
                supertrend.iloc[index] = final_lower.iloc[index]
                direction.iloc[index] = 1
        else:
            if close.iloc[index] >= final_lower.iloc[index]:
                supertrend.iloc[index] = final_lower.iloc[index]
                direction.iloc[index] = 1
            else:
                supertrend.iloc[index] = final_upper.iloc[index]
                direction.iloc[index] = -1

    dataframe['supertrend'] = supertrend.ffill().fillna(hl_average)
    dataframe['supertrend_direction'] = direction.replace(0, pd.NA).ffill().fillna(1).astype(int)
    return dataframe


def has_price_crossed_r1(price: float, r1: float, inclusive: bool = True) -> bool:
    """Return True when the price is at or above R1."""
    price_value = float(price)
    r1_value = float(r1)
    return price_value >= r1_value if inclusive else price_value > r1_value


def has_price_crossed_s1(price: float, s1: float, inclusive: bool = True) -> bool:
    """Return True when the price is at or below S1."""
    price_value = float(price)
    s1_value = float(s1)
    return price_value <= s1_value if inclusive else price_value < s1_value

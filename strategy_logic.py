"""Pure strategy helpers for the NIFTY pivot-and-Supertrend option logic."""

from __future__ import annotations

from typing import Optional

import pandas as pd

import Config
from logger import logger
from pivot_points import calculate_daily_pivot_levels_from_candles, create_supertrend_indicator


def evaluate_strategy_signal(
    candle_data: pd.DataFrame,
    position_open: bool = False,
    position_option_type: Optional[str] = None,
    pivot_levels: Optional[dict] = None,
    entry_count: int = 0,
    lots: int = 1,
    max_entries: int = 3,
    log_pivot_details: bool = True,
) -> dict:
    """Evaluate the entry/exit signal for the configured strategy.

    The strategy uses the latest 5-minute candle (or the latest row in the
    provided frame) and evaluates:
    - bullish entry: close above R1 and Supertrend is bullish
    - bearish entry: close below S1 and Supertrend is bearish
    - bullish exit: close below S1 or Supertrend flips bearish
    - bearish exit: close above R1 or Supertrend flips bullish
    """
    if candle_data is None or len(candle_data) == 0:
        logger.info('Strategy evaluation skipped: no candle data provided')
        decision = {'action': 'none', 'option_type': None, 'lots': lots}
        logger.info(
            'Strategy decision | latest_close=%s | r1=%s | s1=%s | supertrend_direction=%s | decision=%s',
            None,
            None,
            None,
            None,
            decision,
        )
        return decision

    frame = candle_data.copy()
    if 'close' not in frame.columns or 'high' not in frame.columns or 'low' not in frame.columns:
        raise KeyError('candle_data must contain high, low, and close columns')

    latest_row = frame.iloc[-1]
    latest_close = float(latest_row['close'])

    if pivot_levels is None:
        pivot_row = frame.iloc[-2] if len(frame) > 1 else latest_row
        pivot_levels = calculate_daily_pivot_levels_from_candles(pd.DataFrame([pivot_row.to_dict()]))
        if log_pivot_details:
            logger.info(
                'Strategy pivot calculation | source=intraday_fallback | latest_close=%.2f | pivot_row=%s | r1=%.2f | s1=%.2f',
                latest_close,
                pivot_row.to_dict(),
                pivot_levels['r1'],
                pivot_levels['s1'],
            )
    else:
        if log_pivot_details:
            logger.info(
                'Strategy pivot calculation | source=daily_previous_session | latest_close=%.2f | pivot_levels=%s',
                latest_close,
                pivot_levels,
            )

    r1 = float(pivot_levels['r1'])
    s1 = float(pivot_levels['s1'])

    st_length = int(Config.STRATEGY_CONFIG.get('SUPERTREND_LENGTH', 10))
    st_multiplier = float(Config.STRATEGY_CONFIG.get('SUPERTREND_MULTIPLIER', 3.0))
    indicator = create_supertrend_indicator(frame, length=st_length, multiplier=st_multiplier)
    latest_direction = int(indicator.iloc[-1]['supertrend_direction'])
    latest_supertrend = float(indicator.iloc[-1]['supertrend'])
    logger.info(
        'Strategy supertrend calculation | length=%s | multiplier=%s | latest_direction=%s | latest_supertrend=%.2f',
        st_length,
        st_multiplier,
        latest_direction,
        latest_supertrend,
    )

    decision = {'action': 'none', 'option_type': None, 'lots': lots}

    if position_open and position_option_type:
        if position_option_type == 'PE':
            should_exit = latest_close < s1 or latest_direction == -1
            if should_exit:
                decision = {'action': 'exit', 'option_type': 'PE', 'lots': lots}
                logger.info(
                    'Strategy decision | latest_close=%.2f | r1=%.2f | s1=%.2f | supertrend_direction=%s | decision=%s',
                    latest_close,
                    r1,
                    s1,
                    latest_direction,
                    decision,
                )
                return decision
        elif position_option_type == 'CE':
            should_exit = latest_close > r1 or latest_direction == 1
            if should_exit:
                decision = {'action': 'exit', 'option_type': 'CE', 'lots': lots}
                logger.info(
                    'Strategy decision | latest_close=%.2f | r1=%.2f | s1=%.2f | supertrend_direction=%s | decision=%s',
                    latest_close,
                    r1,
                    s1,
                    latest_direction,
                    decision,
                )
                return decision

        decision = {'action': 'hold', 'option_type': position_option_type, 'lots': lots}
        logger.info(
            'Strategy decision | latest_close=%.2f | r1=%.2f | s1=%.2f | supertrend_direction=%s | decision=%s',
            latest_close,
            r1,
            s1,
            latest_direction,
            decision,
        )
        return decision

    if entry_count >= max_entries:
        logger.info(
            'Strategy decision | latest_close=%.2f | r1=%.2f | s1=%.2f | supertrend_direction=%s | decision=%s',
            latest_close,
            r1,
            s1,
            latest_direction,
            decision,
        )
        return decision

    bullish_entry = latest_close > r1 and latest_direction == 1
    bearish_entry = latest_close < s1 and latest_direction == -1

    if bullish_entry:
        decision = {'action': 'enter', 'option_type': 'PE', 'lots': lots}
        logger.info(
            'Strategy decision | latest_close=%.2f | r1=%.2f | s1=%.2f | supertrend_direction=%s | decision=%s',
            latest_close,
            r1,
            s1,
            latest_direction,
            decision,
        )
        return decision
    if bearish_entry:
        decision = {'action': 'enter', 'option_type': 'CE', 'lots': lots}
        logger.info(
            'Strategy decision | latest_close=%.2f | r1=%.2f | s1=%.2f | supertrend_direction=%s | decision=%s',
            latest_close,
            r1,
            s1,
            latest_direction,
            decision,
        )
        return decision

    logger.info(
        'Strategy decision | latest_close=%.2f | r1=%.2f | s1=%.2f | supertrend_direction=%s | decision=%s',
        latest_close,
        r1,
        s1,
        latest_direction,
        decision,
    )
    return decision

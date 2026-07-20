# ============================================================================
# STRATEGY2 - NIFTY CANDLE BREAKOUT OPTIONS TRADING
# ============================================================================

from datetime import datetime, time, timedelta
from time import sleep 
import warnings
import json
import os
import re
import math
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np
from upstoxapi import UpstoxApi
import Config
from logger import logger
import Utility
from pivot_points import calculate_daily_pivot_levels_from_candles
from strategy_logic import evaluate_strategy_signal


class MockUplink:
    """Lightweight fallback used when running locally in test mode."""

    def __init__(self):
        self._candle_data = pd.DataFrame([
            {'date': pd.Timestamp('2026-07-06 09:15:00', tz='Asia/Kolkata'), 'open': 22300.0, 'high': 22320.0, 'low': 22280.0, 'close': 22310.0, 'volume': 1000, 'oi': 0},
            {'date': pd.Timestamp('2026-07-06 09:16:00', tz='Asia/Kolkata'), 'open': 22310.0, 'high': 22340.0, 'low': 22300.0, 'close': 22335.0, 'volume': 1000, 'oi': 0},
            {'date': pd.Timestamp('2026-07-06 09:17:00', tz='Asia/Kolkata'), 'open': 22335.0, 'high': 22360.0, 'low': 22320.0, 'close': 22350.0, 'volume': 1000, 'oi': 0},
        ])

    def customCandleData(self, instrument_key, timeframe):
        return self._candle_data.copy()

    def getLTP(self, instrument_key):
        return 22350.0

    def placeMultipleOrder(self, instrument_key, qty, trans_type, order_type):
        logger.info('Mock order placed')
        return 'mock-order-id'

    def isAllOrderTraded(self, order_list):
        return True, pd.DataFrame([{'average_price': 22350.0}])

    def closePosition(self, instrument_key, qty, trans_type=None):
        logger.info('Mock position close')
        return 'mock-close-id'

    def exit_all(self):
        logger.info('Mock exit_all called')


def check_candle_breakout(candle_data, candle_count=2, direction='LONG'):
    """
    Check for candle breakout pattern
    
    Args:
        candle_data: DataFrame with OHLC data
        candle_count: Number of candles to check for breakout
        direction: 'LONG' for breakout of highs, 'SHORT' for breakdown of lows
    
    Returns:
        bool: True if breakout detected, False otherwise
    """
    try:
        if len(candle_data) < candle_count + 1:
            return False
        
        # Get the last few candles
        recent_candles = candle_data.tail(candle_count + 1)
        
        if direction == 'LONG':
            # Check if the latest candle breaks above the high of previous candles
            previous_candles = recent_candles.iloc[:-1]  # All except the last candle
            current_candle = recent_candles.iloc[-1]     # Last candle
            
            # Find the highest high of previous candles
            previous_high = previous_candles['high'].max()
            
            # Check if current candle closes above the previous high
            breakout = current_candle['close'] > previous_high
            
            logger.info(f"LONG Breakout Check - Previous High: {previous_high}, "
                       f"Current Close: {current_candle['close']}, Breakout: {breakout}")
            
            return breakout
            
        elif direction == 'SHORT':
            # Check if the latest candle breaks below the low of previous candles
            previous_candles = recent_candles.iloc[:-1]  # All except the last candle
            current_candle = recent_candles.iloc[-1]     # Last candle
            
            # Find the lowest low of previous candles
            previous_low = previous_candles['low'].min()
            
            # Check if current candle closes below the previous low
            breakdown = current_candle['close'] < previous_low
            
            logger.info(f"SHORT Breakdown Check - Previous Low: {previous_low}, "
                       f"Current Close: {current_candle['close']}, Breakdown: {breakdown}")
            
            return breakdown
            
        return False
        
    except Exception as e:
        logger.error(f"Error in breakout check: {e}")
        return False


def is_test_mode_enabled():
    """Return normalized TEST_MODE flag from strategy config."""
    value = Config.STRATEGY_CONFIG.get('TEST_MODE', False)
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def _normalize_bool(value):
    """Normalize strategy config values to bool."""
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def _to_float_or_none(value):
    """Safely parse numeric values and return None when parsing fails."""
    try:
        return float(value)
    except Exception:
        return None


def _extract_quote_numeric(value):
    """Extract a numeric quote value from a scalar, dict, or nested payload."""
    scalar_value = _to_float_or_none(value)
    if scalar_value is not None:
        return scalar_value

    if isinstance(value, dict):
        for key in ('last_price', 'ltp', 'last_traded_price', 'close', 'price', 'value'):
            scalar_value = _to_float_or_none(value.get(key))
            if scalar_value is not None:
                return scalar_value

        for nested_value in value.values():
            scalar_value = _extract_quote_numeric(nested_value)
            if scalar_value is not None:
                return scalar_value

    if isinstance(value, (list, tuple)):
        for nested_value in value:
            scalar_value = _extract_quote_numeric(nested_value)
            if scalar_value is not None:
                return scalar_value

    return None


def is_trailing_stop_loss_enabled():
    """Return True when trailing stop-loss management is globally enabled."""
    return _normalize_bool(Config.STRATEGY_CONFIG.get('ENABLE_TRAILING_STOP_LOSS', False))


def get_trailing_activation_profit_percent_of_margin():
    """Return the profit threshold % of used margin that activates trailing mode."""
    value = _to_float_or_none(Config.STRATEGY_CONFIG.get('TRAILING_ACTIVATION_PROFIT_PERCENT_OF_MARGIN', 1.0))
    return max(0.0, value if value is not None else 1.0)


def get_trailing_gap_percent_of_margin():
    """Return trailing gap as % of used margin."""
    value = _to_float_or_none(Config.STRATEGY_CONFIG.get('TRAILING_STOP_LOSS_GAP_PERCENT_OF_MARGIN', 0.5))
    return max(0.0, value if value is not None else 0.5)


def get_trailing_step_absolute_rs():
    """Return minimum profit increase needed before trailing SL is moved."""
    value = _to_float_or_none(Config.STRATEGY_CONFIG.get('TRAILING_STEP_ABSOLUTE_RS', 1000.0))
    return max(1.0, value if value is not None else 1000.0)


def get_trailing_evaluation_interval_seconds():
    """Return evaluation interval in seconds while trailing mode is active."""
    value = _to_float_or_none(Config.STRATEGY_CONFIG.get('TRAILING_EVALUATION_INTERVAL_SECONDS', 60))
    return max(1.0, value if value is not None else 60.0)


def _is_any_trailing_mode_active():
    """Return True when any tracked symbol currently has trailing mode active."""
    tracked_positions = getattr(Config, 'POSITION_CONFIG', {})
    if not isinstance(tracked_positions, dict):
        return False

    for position in tracked_positions.values():
        if not isinstance(position, dict):
            continue
        trailing_state = position.get('trailing_stop_loss')
        if isinstance(trailing_state, dict) and _normalize_bool(trailing_state.get('active', False)):
            return True
    return False


def _has_any_tracked_open_position():
    """Return True when the runtime has at least one tracked open position."""
    tracked_positions = getattr(Config, 'POSITION_CONFIG', {})
    return isinstance(tracked_positions, dict) and bool(tracked_positions)


def _extract_row_numeric(row, keys, positive_only=False):
    """Pick the first usable numeric value from candidate payload keys."""
    if not isinstance(row, dict):
        return None

    for key in keys:
        value = _to_float_or_none(row.get(key))
        if value is None:
            continue
        if positive_only and value <= 0:
            continue
        return value
    return None


def _get_position_row_for_instrument(uplink_obj, option_instrument):
    """Return broker position row matching the open option instrument."""
    if not hasattr(uplink_obj, 'getPositionBook'):
        return None

    try:
        position_book = uplink_obj.getPositionBook()
    except Exception as exc:
        logger.warning('Trailing stop-loss position book fetch failed: %s', exc)
        return None

    if not isinstance(position_book, dict):
        return None

    positions = position_book.get('data', [])
    if not isinstance(positions, list):
        return None

    instrument_key = str(option_instrument or '').strip()
    for row in positions:
        if not isinstance(row, dict):
            continue
        token = str(row.get('instrument_token', row.get('instrument_key', '')) or '').strip()
        if token and token == instrument_key:
            return row
    return None


def _compute_short_pnl_from_ltp(uplink_obj, position_config):
    """Compute running PnL for short option positions using LTP fallback."""
    option_instrument = str(position_config.get('option_instrument', '') or '').strip()
    if not option_instrument or not hasattr(uplink_obj, 'getLTP'):
        return None, None

    entry_price = _to_float_or_none(position_config.get('entry_price'))
    qty = int(position_config.get('qty', 0) or 0)
    if entry_price is None or qty <= 0:
        return None, None

    try:
        ltp = _extract_quote_numeric(uplink_obj.getLTP(option_instrument))
    except Exception as exc:
        logger.warning('Trailing stop-loss LTP fetch failed for %s: %s', option_instrument, exc)
        return None, None

    if ltp is None:
        return None, None

    # Strategy takes short option entries, so PnL improves as option premium falls.
    pnl = (entry_price - ltp) * qty
    return pnl, ltp


def _resolve_margin_via_margin_api(uplink_obj, position_config):
    """Resolve required margin for the open position via Upstox POST /v2/charges/margin."""
    if not hasattr(uplink_obj, 'getRequiredMargin'):
        return None

    option_instrument = str(position_config.get('option_instrument', '') or '').strip()
    qty = int(position_config.get('qty', 0) or 0)
    if not option_instrument or qty <= 0:
        return None

    transaction_type = str(position_config.get('transaction_type', 'SELL') or 'SELL').upper()
    product = str(position_config.get('product', getattr(Config, 'ORDER_TYPE', 'I')) or getattr(Config, 'ORDER_TYPE', 'I')).upper()

    try:
        margin = uplink_obj.getRequiredMargin(
            instrument_key=option_instrument,
            quantity=qty,
            transaction_type=transaction_type,
            product=product,
        )
    except Exception as exc:
        logger.warning('Trailing stop-loss margin API call failed for %s: %s', option_instrument, exc)
        return None

    margin_value = _to_float_or_none(margin)
    if margin_value is None or margin_value <= 0:
        return None
    return margin_value


def _resolve_trailing_runtime_metrics(uplink_obj, position_config):
    """Resolve used margin and running PnL needed by trailing stop-loss logic."""
    option_instrument = str(position_config.get('option_instrument', '') or '').strip()
    entry_price = _to_float_or_none(position_config.get('entry_price'))
    qty = int(position_config.get('qty', 0) or 0)

    used_margin = _resolve_margin_via_margin_api(uplink_obj, position_config)

    row = _get_position_row_for_instrument(uplink_obj, option_instrument)
    if used_margin is None:
        used_margin = _extract_row_numeric(
            row,
            [
                'used_margin',
                'margin_used',
                'required_margin',
                'span_margin',
                'exposure_margin',
                'margin',
            ],
            positive_only=True,
        )

    ltp_pnl, _ = _compute_short_pnl_from_ltp(uplink_obj, position_config)
    running_pnl = ltp_pnl

    if running_pnl is None and entry_price is not None and qty > 0:
        row_ltp = _extract_row_numeric(
            row,
            [
                'last_price',
                'ltp',
                'close',
                'average_price',
            ],
            positive_only=True,
        )
        if row_ltp is not None:
            running_pnl = (entry_price - row_ltp) * qty

    if running_pnl is None:
        running_pnl = _extract_row_numeric(
            row,
            [
                'pnl',
                'day_pnl',
                'mtm',
                'unrealized_pnl',
                'unrealised_pnl',
                'realized_pnl',
                'realised_pnl',
            ],
            positive_only=False,
        )
        if running_pnl is not None:
            logger.warning(
                'Trailing stop-loss using broker-reported PnL fallback because fresh LTP was unavailable | instrument=%s',
                option_instrument,
            )

    if used_margin is None and entry_price is not None and qty > 0:
        used_margin = abs(entry_price * qty)

    return used_margin, running_pnl


def evaluate_trailing_stop_loss(uplink_obj, symbol, position_config):
    """Evaluate trailing stop-loss for one open position and return action state."""
    trailing_state = position_config.setdefault('trailing_stop_loss', {})
    if not isinstance(trailing_state, dict):
        trailing_state = {}
        position_config['trailing_stop_loss'] = trailing_state

    current_active = _normalize_bool(trailing_state.get('active', False))

    if not is_trailing_stop_loss_enabled():
        return {'active': current_active, 'action': 'none'}

    used_margin, running_pnl = _resolve_trailing_runtime_metrics(uplink_obj, position_config)
    if used_margin is None or used_margin <= 0 or running_pnl is None:
        logger.warning(
            'Trailing stop-loss skipped for %s due to missing metrics | used_margin=%s | running_pnl=%s',
            symbol,
            used_margin,
            running_pnl,
        )
        return {
            'active': current_active,
            'action': 'none',
            'running_pnl': float(running_pnl) if running_pnl is not None else None,
            'used_margin': float(used_margin) if used_margin is not None else None,
        }

    activation_percent = get_trailing_activation_profit_percent_of_margin()
    gap_percent = get_trailing_gap_percent_of_margin()
    step_amount = get_trailing_step_absolute_rs()

    activation_threshold = used_margin * (activation_percent / 100.0)
    gap_amount = used_margin * (gap_percent / 100.0)

    if not current_active:
        if running_pnl < activation_threshold:
            return {'active': False, 'action': 'none'}

        trailing_state.update({
            'active': True,
            'used_margin': float(used_margin),
            'activation_threshold_pnl': float(activation_threshold),
            'gap_amount': float(gap_amount),
            'last_peak_pnl': float(running_pnl),
            'last_trail_anchor_pnl': float(running_pnl),
            'stop_loss_pnl': float(running_pnl - gap_amount),
            'activated_at': datetime.now(Config.TIME_ZONE).isoformat(),
        })
        logger.info(
            '%s trailing stop-loss activated | running_pnl=%.2f | activation_threshold=%.2f | initial_stop_loss_pnl=%.2f | step=%.2f',
            symbol,
            running_pnl,
            activation_threshold,
            trailing_state['stop_loss_pnl'],
            step_amount,
        )
    else:
        trailing_state['used_margin'] = float(used_margin)
        trailing_state['activation_threshold_pnl'] = float(activation_threshold)
        trailing_state['gap_amount'] = float(gap_amount)

        stop_loss_pnl = _to_float_or_none(trailing_state.get('stop_loss_pnl'))
        if stop_loss_pnl is None:
            stop_loss_pnl = float(running_pnl - gap_amount)
            trailing_state['stop_loss_pnl'] = stop_loss_pnl

        last_peak_pnl = _to_float_or_none(trailing_state.get('last_peak_pnl'))
        if last_peak_pnl is None:
            last_peak_pnl = float(running_pnl)
        if running_pnl > last_peak_pnl:
            last_peak_pnl = float(running_pnl)
        trailing_state['last_peak_pnl'] = last_peak_pnl

        anchor_pnl = _to_float_or_none(trailing_state.get('last_trail_anchor_pnl'))
        if anchor_pnl is None:
            anchor_pnl = float(last_peak_pnl)

        if running_pnl >= anchor_pnl + step_amount:
            step_count = int(math.floor((running_pnl - anchor_pnl) / step_amount))
            if step_count > 0:
                trail_move = float(step_count * step_amount)
                trailing_state['stop_loss_pnl'] = float(stop_loss_pnl + trail_move)
                trailing_state['last_trail_anchor_pnl'] = float(anchor_pnl + trail_move)
                logger.info(
                    '%s trailing stop-loss moved | running_pnl=%.2f | stop_loss_pnl=%.2f | move=%.2f',
                    symbol,
                    running_pnl,
                    trailing_state['stop_loss_pnl'],
                    trail_move,
                )

    active_stop_loss = _to_float_or_none(trailing_state.get('stop_loss_pnl'))
    if active_stop_loss is not None and running_pnl < active_stop_loss:
        logger.info(
            '%s trailing stop-loss breached | running_pnl=%.2f | stop_loss_pnl=%.2f',
            symbol,
            running_pnl,
            active_stop_loss,
        )
        return {
            'active': True,
            'action': 'exit',
            'running_pnl': float(running_pnl),
            'stop_loss_pnl': float(active_stop_loss),
        }

    final_active = _normalize_bool(trailing_state.get('active', False))
    return {
        'active': final_active,
        'action': 'hold' if final_active else 'none',
        'running_pnl': float(running_pnl),
        'stop_loss_pnl': _to_float_or_none(trailing_state.get('stop_loss_pnl')),
    }


def is_trading_time():
    """Check if current time is within trading hours"""
    if is_test_mode_enabled():
        return True  # Always return True in test mode
        
    current_time = datetime.now(Config.TIME_ZONE)
    start_time = current_time.replace(hour=Config.TRADING_HOURS['START'][0], minute=Config.TRADING_HOURS['START'][1], second=0)
    exit_time = current_time.replace(hour=Config.TRADING_HOURS['END'][0], minute=Config.TRADING_HOURS['END'][1], second=0)
    return start_time <= current_time < exit_time


def has_reached_trading_end(current_time=None):
    """Return True once local clock reaches configured trading end time."""
    now = current_time or datetime.now(Config.TIME_ZONE)
    exit_time = now.replace(
        hour=Config.TRADING_HOURS['END'][0],
        minute=Config.TRADING_HOURS['END'][1],
        second=0,
        microsecond=0,
    )
    return now >= exit_time


def check_stop_loss_target(uplink_obj, symbol, position_config):
    """Check if stop loss or target is hit"""
    try:
        current_ltp = uplink_obj.getLTP(position_config['option_instrument'])
        if current_ltp is None:
            return False
            
        entry_price = position_config['entry_price']
        pnl_percent = ((current_ltp - entry_price) / entry_price) * 100
        
        logger.info(f'{symbol} LTP: {current_ltp}, Entry: {entry_price}, PnL: {pnl_percent:.2f}%')
        
        # Check exit conditions
        stop_loss = Config.STRATEGY_CONFIG['STOP_LOSS_PERCENT']
        target = Config.STRATEGY_CONFIG['TARGET_PERCENT']
        
        if pnl_percent <= -stop_loss:
            logger.info(f'{symbol} Stop loss hit! PnL: {pnl_percent:.2f}%')
            return True
        elif pnl_percent >= target:
            logger.info(f'{symbol} Target hit! PnL: {pnl_percent:.2f}%')
            return True
            
        return False
        
    except Exception as e:
        logger.exception(f'Error in stop loss/target check: {e}')
        return False


def _get_daily_entry_count(symbol):
    """Return the number of entries already taken for the current day."""
    today = datetime.now(Config.TIME_ZONE).strftime('%Y-%m-%d')
    entry_counts = getattr(Config, 'DAILY_ENTRY_COUNTS', {})
    if today not in entry_counts:
        entry_counts[today] = {}
        setattr(Config, 'DAILY_ENTRY_COUNTS', entry_counts)
    return int(entry_counts[today].get(symbol, 0))


def _increment_daily_entry_count(symbol):
    """Increment the daily entry count for a symbol."""
    today = datetime.now(Config.TIME_ZONE).strftime('%Y-%m-%d')
    entry_counts = getattr(Config, 'DAILY_ENTRY_COUNTS', {})
    if today not in entry_counts:
        entry_counts[today] = {}
    entry_counts[today][symbol] = _get_daily_entry_count(symbol) + 1
    setattr(Config, 'DAILY_ENTRY_COUNTS', entry_counts)
    setattr(Config, 'PERSISTED_DAILY_ENTRY_COUNTS', dict(entry_counts))
    _persist_daily_entry_counts_to_config(entry_counts)


def _persist_daily_entry_counts_to_config(entry_counts):
    """Persist daily entry counters directly into Config.py."""
    try:
        config_path = getattr(Config, '__file__', None)
        if not config_path:
            logger.warning('Skipping entry-count persistence: Config.__file__ unavailable')
            return

        config_path = str(config_path)
        if config_path.endswith('.pyc'):
            config_path = config_path[:-1]
        config_path = os.path.abspath(config_path)

        with open(config_path, 'r', encoding='utf-8') as file_obj:
            content = file_obj.read()

        serialized_counts = json.dumps(entry_counts, sort_keys=True)
        replacement_line = f'PERSISTED_DAILY_ENTRY_COUNTS = {serialized_counts}'
        assignment_pattern = r'(?m)^PERSISTED_DAILY_ENTRY_COUNTS\s*=\s*.*$'

        if re.search(assignment_pattern, content):
            updated_content = re.sub(assignment_pattern, replacement_line, content, count=1)
        else:
            anchor_pattern = r'(?m)^DAILY_ENTRY_COUNTS\s*=\s*.*$'
            anchor_match = re.search(anchor_pattern, content)
            if anchor_match:
                insert_pos = anchor_match.start()
                updated_content = content[:insert_pos] + replacement_line + '\n' + content[insert_pos:]
            else:
                updated_content = content.rstrip() + f'\n{replacement_line}\n'

        if updated_content != content:
            with open(config_path, 'w', encoding='utf-8') as file_obj:
                file_obj.write(updated_content)
            logger.info('Persisted daily entry counts to Config.py: %s', serialized_counts)
    except Exception as exc:
        logger.exception('Failed to persist daily entry counts into Config.py: %s', exc)


def _load_daily_entry_counts_once():
    """Initialize runtime daily entry counts from Config once per process start."""
    if getattr(Config, '_DAILY_ENTRY_COUNTS_LOADED', False):
        return

    persisted = getattr(Config, 'PERSISTED_DAILY_ENTRY_COUNTS', {})
    runtime_counts = getattr(Config, 'DAILY_ENTRY_COUNTS', {})
    merged = dict(persisted) if isinstance(persisted, dict) else {}
    if isinstance(runtime_counts, dict):
        for date_key, symbol_counts in runtime_counts.items():
            if date_key not in merged or not isinstance(merged.get(date_key), dict):
                merged[date_key] = {}
            if isinstance(symbol_counts, dict):
                merged[date_key].update(symbol_counts)

    setattr(Config, 'DAILY_ENTRY_COUNTS', merged)
    setattr(Config, '_DAILY_ENTRY_COUNTS_LOADED', True)
    logger.info('Daily entry counts initialized once at startup: %s', merged)


def _infer_option_type(position_row):
    """Infer CE/PE from broker position row fields."""
    tokens = [
        str(position_row.get('trading_symbol', '')).upper(),
        str(position_row.get('tradingsymbol', '')).upper(),
        str(position_row.get('instrument_token', '')).upper(),
        str(position_row.get('instrument_key', '')).upper(),
    ]
    if any('PE' in token for token in tokens):
        return 'PE'
    if any('CE' in token for token in tokens):
        return 'CE'
    return None


def _normalize_product_code(product_value):
    """Normalize broker product value to strategy-style short codes."""
    value = str(product_value or '').strip().upper()
    if value in {'I', 'INTRADAY', 'MIS'}:
        return 'I'
    if value in {'D', 'DELIVERY', 'CNC'}:
        return 'D'
    return value


def _row_has_expected_tag(row, expected_tag):
    """Return True when a broker row carries the configured strategy tag."""
    if not expected_tag or not isinstance(row, dict):
        return False

    normalized_expected = str(expected_tag).strip().upper()
    tag_fields = [row.get('tag'), row.get('order_tag')]
    for value in tag_fields:
        if str(value or '').strip().upper() == normalized_expected:
            return True

    tags = row.get('tags')
    if isinstance(tags, list):
        return any(str(tag or '').strip().upper() == normalized_expected for tag in tags)

    return False


def _get_strategy_order_tokens(uplink_obj):
    """Collect instrument tokens from completed strategy-tagged entry orders."""
    if not hasattr(uplink_obj, 'getOrderBook'):
        return set()

    try:
        order_book = uplink_obj.getOrderBook()
    except Exception as exc:
        logger.exception('Order book fetch failed during startup position sync: %s', exc)
        return set()

    if not isinstance(order_book, dict):
        return set()

    orders = order_book.get('data', [])
    if not isinstance(orders, list):
        return set()

    expected_tag = str(getattr(Config, 'ORDER_TAG', '') or '').strip().upper()
    expected_product = _normalize_product_code(getattr(Config, 'ORDER_TYPE', ''))
    completed_statuses = {'COMPLETE', 'COMPLETED', 'TRADED', 'FILLED'}
    tokens = set()

    for row in orders:
        if not isinstance(row, dict):
            continue

        if expected_tag and not _row_has_expected_tag(row, expected_tag):
            continue

        status = str(row.get('status', '') or '').strip().upper()
        if status and status not in completed_statuses:
            continue

        trans_type = str(row.get('transaction_type', '') or '').strip().upper()
        if trans_type and trans_type != 'SELL':
            continue

        order_product = _normalize_product_code(row.get('product', row.get('product_type', '')))
        if expected_product and order_product and order_product != expected_product:
            continue

        token = str(row.get('instrument_token', row.get('instrument_key', '')) or '').strip()
        if token:
            tokens.add(token)

    return tokens


def _to_positive_float(value):
    """Convert value to a positive float, or None when not usable."""
    try:
        parsed = float(value)
    except Exception:
        return None
    if parsed > 0:
        return parsed
    return None


def _get_seeded_position_config(symbol):
    """Return a normalized, valid seeded position from Config.POSITION_CONFIG."""
    tracked_positions = getattr(Config, 'POSITION_CONFIG', {})
    if not isinstance(tracked_positions, dict):
        return None

    seeded = tracked_positions.get(symbol)
    if not isinstance(seeded, dict):
        return None

    option_instrument = str(seeded.get('option_instrument', '') or '').strip()
    qty = int(seeded.get('qty', 0) or 0)
    option_type = str(seeded.get('option_type', '') or '').upper()
    if not option_instrument or qty <= 0 or option_type not in {'CE', 'PE'}:
        return None
    return dict(seeded)


def _resolve_entry_price_from_position(uplink_obj, row, qty, option_instrument):
    """Resolve entry price from broker position fields with practical fallbacks."""
    direct_price_fields = [
        'average_price',
        'avg_price',
        'sell_price',
        'day_sell_price',
        'overnight_sell_price',
        'last_price',
        'ltp',
    ]
    for field in direct_price_fields:
        value = _to_positive_float(row.get(field))
        if value is not None:
            return value

    if qty > 0:
        # Some position payloads expose only value fields, not average_price.
        value_fields = ['sell_value', 'day_sell_value', 'overnight_sell_value']
        for field in value_fields:
            value = _to_positive_float(row.get(field))
            if value is not None:
                return value / float(qty)

    if hasattr(uplink_obj, 'getLTP'):
        try:
            ltp = _to_positive_float(uplink_obj.getLTP(option_instrument))
            if ltp is not None:
                logger.info('Startup position sync entry price fallback used LTP for %s: %.2f', option_instrument, ltp)
                return ltp
        except Exception as exc:
            logger.warning('Startup position sync could not fetch LTP fallback for %s: %s', option_instrument, exc)

    return 0.0


def _sync_position_config_from_broker(uplink_obj):
    """Populate runtime POSITION_CONFIG from existing broker positions."""
    symbol = 'NIFTY'
    seeded_position = _get_seeded_position_config(symbol)

    if seeded_position:
        logger.info(
            'Startup position seed detected in Config for %s | instrument=%s | qty=%s | entry_price=%s',
            symbol,
            seeded_position.get('option_instrument'),
            seeded_position.get('qty'),
            seeded_position.get('entry_price'),
        )

    if not hasattr(uplink_obj, 'getPositionBook'):
        logger.warning('Position sync skipped: uplink has no getPositionBook method')
        return

    try:
        position_book = uplink_obj.getPositionBook()
    except Exception as exc:
        logger.exception('Position sync failed while fetching position book: %s', exc)
        return

    if not isinstance(position_book, dict):
        logger.warning('Position sync skipped: unexpected position book payload type')
        return

    if str(position_book.get('status', '')).lower() == 'error':
        if Config.is_sandbox_mode() or is_test_mode_enabled():
            logger.info(
                'Position sync skipped in sandbox/test mode: broker positions endpoint is unavailable; errors=%s',
                position_book.get('errors', []),
            )
        else:
            logger.warning('Position sync skipped: broker positions endpoint returned error payload: %s', position_book.get('errors', []))
        return

    positions = position_book.get('data', [])
    if not isinstance(positions, list):
        logger.warning('Position sync skipped: unexpected data in position book payload')
        return

    expected_product = _normalize_product_code(getattr(Config, 'ORDER_TYPE', ''))
    expected_tag = str(getattr(Config, 'ORDER_TAG', '') or '').strip().upper()
    strategy_order_tokens = _get_strategy_order_tokens(uplink_obj)

    candidates = []
    for row in positions:
        if not isinstance(row, dict):
            continue

        token = str(row.get('instrument_token', row.get('instrument_key', '')))
        trading_symbol = str(row.get('trading_symbol', row.get('tradingsymbol', '')))
        haystack = f'{token} {trading_symbol}'.upper()
        if 'NIFTY' not in haystack:
            continue

        option_type = _infer_option_type(row)
        if option_type not in {'CE', 'PE'}:
            continue

        position_product = _normalize_product_code(row.get('product', row.get('product_type', '')))
        if expected_product and position_product and position_product != expected_product:
            # Avoid matching unrelated delivery positions when strategy is intraday.
            continue

        try:
            net_qty = int(float(row.get('quantity', 0)))
        except Exception:
            net_qty = 0
        if net_qty >= 0:
            # Strategy entries are short-option sells; only map short legs.
            continue

        candidates.append((row, option_type, abs(net_qty)))

    if not candidates:
        if seeded_position:
            Config.POSITION_CONFIG[symbol] = seeded_position
            logger.warning(
                'No open short NIFTY option found in broker book during startup sync; retaining seeded Config position for %s',
                symbol,
            )
            return

        Config.POSITION_CONFIG.pop(symbol, None)
        logger.info('No open short NIFTY option position found in broker book during startup sync')
        return

    tagged_position_candidates = [
        candidate for candidate in candidates
        if _row_has_expected_tag(candidate[0], expected_tag)
    ]

    order_token_candidates = []
    if strategy_order_tokens:
        order_token_candidates = [
            candidate
            for candidate in candidates
            if str(candidate[0].get('instrument_token', candidate[0].get('instrument_key', '')) or '').strip() in strategy_order_tokens
        ]

    selection_pool = candidates
    selection_reason = 'largest_short_position'

    seeded_token = str(seeded_position.get('option_instrument', '')).strip() if seeded_position else ''
    seeded_match_candidates = []
    if seeded_token:
        seeded_match_candidates = [
            candidate
            for candidate in candidates
            if str(candidate[0].get('instrument_token', candidate[0].get('instrument_key', '')) or '').strip() == seeded_token
        ]

    if seeded_match_candidates:
        selection_pool = seeded_match_candidates
        selection_reason = 'config_seed_match'
    if tagged_position_candidates:
        selection_pool = tagged_position_candidates
        selection_reason = 'position_tag_match'
    elif order_token_candidates:
        selection_pool = order_token_candidates
        selection_reason = 'order_tag_token_match'

    logger.info(
        'Startup position sync candidate selection | total=%s | tag_matches=%s | order_token_matches=%s | reason=%s',
        len(candidates),
        len(tagged_position_candidates),
        len(order_token_candidates),
        selection_reason,
    )

    selected_row, option_type, qty = max(selection_pool, key=lambda item: item[2])

    option_instrument = str(selected_row.get('instrument_token', selected_row.get('instrument_key', '')))
    entry_price = _resolve_entry_price_from_position(uplink_obj, selected_row, int(qty), option_instrument)
    if entry_price <= 0 and seeded_position:
        seeded_entry_price = _to_positive_float(seeded_position.get('entry_price'))
        if seeded_entry_price is not None:
            entry_price = seeded_entry_price
    lots = max(1, int(round(qty / max(1, int(Config.NIFTY_CONFIG.get('lot_size', 1))))))

    Config.POSITION_CONFIG[symbol] = {
        'option_instrument': option_instrument,
        'index_instrument': Config.NIFTY_CONFIG['index_instrument'],
        'qty': int(qty),
        'entry_price': entry_price,
        'option_type': option_type,
        'lots': lots,
        'source': 'broker_sync',
    }

    if seeded_position:
        if seeded_position.get('entry_order_id'):
            Config.POSITION_CONFIG[symbol]['entry_order_id'] = seeded_position.get('entry_order_id')
        if seeded_position.get('order_status'):
            Config.POSITION_CONFIG[symbol]['order_status'] = seeded_position.get('order_status')
        if isinstance(seeded_position.get('trailing_stop_loss'), dict):
            Config.POSITION_CONFIG[symbol]['trailing_stop_loss'] = dict(seeded_position.get('trailing_stop_loss'))

    if is_trailing_stop_loss_enabled():
        try:
            evaluate_trailing_stop_loss(uplink_obj, symbol, Config.POSITION_CONFIG[symbol])
        except Exception as exc:
            logger.exception('Startup trailing state restore failed for %s: %s', symbol, exc)

    logger.info('Startup position sync complete for %s: %s', symbol, Config.POSITION_CONFIG[symbol])


def initialize_runtime_state(uplink_obj):
    """Load persisted runtime counters and position state once at startup."""
    _load_daily_entry_counts_once()
    _sync_position_config_from_broker(uplink_obj)


def _get_fixed_daily_pivot_levels(uplink_obj, symbol, instrument_key):
    """Fetch previous-session daily pivot once per day and keep it constant intraday."""
    today = datetime.now(Config.TIME_ZONE).strftime('%Y-%m-%d')
    pivot_cache = getattr(Config, 'DAILY_PIVOT_LEVELS', {})
    if today in pivot_cache and symbol in pivot_cache[today]:
        return pivot_cache[today][symbol]

    if not hasattr(uplink_obj, 'getHistoricalData'):
        logger.warning('%s daily pivot unavailable: uplink has no getHistoricalData; using fallback pivot logic', symbol)
        return None

    to_date = (datetime.now(Config.TIME_ZONE).date() - timedelta(days=1)).strftime('%Y-%m-%d')
    from_date = (datetime.now(Config.TIME_ZONE).date() - timedelta(days=14)).strftime('%Y-%m-%d')
    daily_data = uplink_obj.getHistoricalData(instrument_key, to_date, from_date, interval='day')
    if daily_data is None or len(daily_data) == 0:
        logger.warning('%s daily pivot unavailable: no daily candles from Upstox; using fallback pivot logic', symbol)
        return None

    daily_frame = daily_data.copy()
    if 'date' in daily_frame.columns:
        daily_frame['date'] = pd.to_datetime(daily_frame['date'], errors='coerce', utc=True).dt.tz_convert(Config.TIME_ZONE)
        daily_frame = daily_frame.dropna(subset=['date'])
        today_date = datetime.now(Config.TIME_ZONE).date()
        previous_sessions = daily_frame[daily_frame['date'].dt.date < today_date]
        source_frame = previous_sessions if not previous_sessions.empty else daily_frame
    else:
        source_frame = daily_frame

    if source_frame.empty:
        logger.warning('%s daily pivot unavailable: usable daily candles are empty; using fallback pivot logic', symbol)
        return None

    pivot_row = source_frame.iloc[-1]
    levels = calculate_daily_pivot_levels_from_candles(pivot_row)
    levels = {
        'pivot': float(levels['pivot']),
        'r1': float(levels['r1']),
        's1': float(levels['s1']),
        'source_date': str(pivot_row.get('date')),
    }

    if today not in pivot_cache:
        pivot_cache[today] = {}
    pivot_cache[today][symbol] = levels
    setattr(Config, 'DAILY_PIVOT_LEVELS', pivot_cache)

    logger.info('%s fixed daily pivot set for %s: %s', symbol, today, levels)
    return levels


def check_entry_signals(uplink_obj):
    """Main signal checking logic based on pivot and Supertrend rules."""
    logger.info(f'Position Config: {Config.POSITION_CONFIG}')
    log_pivot_details = should_log_pivot_this_cycle()

    symbol = 'NIFTY'
    symbol_config = Config.NIFTY_CONFIG
    if not symbol_config['enable']:
        return

    lots = int(Config.STRATEGY_CONFIG.get('LOTS', 1))
    max_entries = int(Config.STRATEGY_CONFIG.get('MAX_ENTRIES', 3))
    timeframe = int(Config.STRATEGY_CONFIG.get('TIMEFRAME', 5))
    is_position_open = symbol in Config.POSITION_CONFIG
    daily_pivot_levels = _get_fixed_daily_pivot_levels(uplink_obj, symbol, symbol_config['index_instrument'])

    candle_data = uplink_obj.customCandleData(symbol_config['index_instrument'], timeframe)
    if candle_data is None or len(candle_data) == 0:
        logger.warning('%s candle data unavailable or empty; skipping signal check', symbol)
        return
    logger.info(f'{symbol} candle data:\n{candle_data.tail(3)}')

    if is_position_open:
        position_config = Config.POSITION_CONFIG[symbol]

        if is_trailing_stop_loss_enabled():
            trailing_status = evaluate_trailing_stop_loss(uplink_obj, symbol, position_config)
            if trailing_status.get('action') == 'exit':
                exit_position(uplink_obj, symbol, int(position_config.get('qty', 0)))
                return
            trailing_active = _normalize_bool(trailing_status.get('active', False))
            if trailing_active:
                logger.info(
                    '%s trailing mode active | running_pnl=%s | stop_loss_pnl=%s | skipping pivot/supertrend checks',
                    symbol,
                    trailing_status.get('running_pnl'),
                    trailing_status.get('stop_loss_pnl'),
                )
                return

            logger.info(
                '%s trailing mode not armed yet | running_pnl=%s | stop_loss_pnl=%s | continuing normal open-position checks',
                symbol,
                trailing_status.get('running_pnl'),
                trailing_status.get('stop_loss_pnl'),
            )

        signal = evaluate_strategy_signal(
            candle_data,
            position_open=True,
            position_option_type=position_config.get('option_type'),
            pivot_levels=daily_pivot_levels,
            entry_count=_get_daily_entry_count(symbol),
            lots=lots,
            max_entries=max_entries,
            log_pivot_details=log_pivot_details,
        )
        if signal.get('action') == 'exit':
            exit_position(uplink_obj, symbol, int(position_config.get('qty', 0)))
            return
        return

    signal = evaluate_strategy_signal(
        candle_data,
        position_open=False,
        pivot_levels=daily_pivot_levels,
        entry_count=_get_daily_entry_count(symbol),
        lots=lots,
        max_entries=max_entries,
        log_pivot_details=log_pivot_details,
    )
    if signal.get('action') == 'enter':
        option_type = signal.get('option_type')
        if option_type:
            if execute_entry(uplink_obj, symbol, symbol_config, candle_data.iloc[-1]['close'], option_type, symbol_config['lot_size'], lots=lots):
                _increment_daily_entry_count(symbol)


def check_new_entry(uplink_obj, symbol, symbol_config, candle_data, qty):
    """Check for new entry opportunities"""
    try:
        # Check for breakout based on strategy direction
        strategy_direction = Config.STRATEGY_CONFIG['DIRECTION']
        candle_count = Config.STRATEGY_CONFIG['CANDLE_COUNT']
        
        entry_signal = False
        option_type = None
        
        if strategy_direction == 'LONG':
            if check_candle_breakout(candle_data, candle_count, 'LONG'):
                entry_signal = True
                option_type = 'CE'
                logger.info(f'{symbol} LONG entry: Candle breakout detected')
                
        elif strategy_direction == 'SHORT':
            if check_candle_breakout(candle_data, candle_count, 'SHORT'):
                entry_signal = True
                option_type = 'PE'
                logger.info(f'{symbol} SHORT entry: Candle breakdown detected')
        
        if entry_signal and option_type:
            # Get current NIFTY price
            current_price = candle_data.iloc[-1]['close']
            execute_entry(uplink_obj, symbol, symbol_config, current_price, option_type, qty)
            
    except Exception as e:
        logger.exception(f'Error in new entry check: {e}')


def execute_entry(uplink_obj, symbol, symbol_config, spot_price, option_type, qty, lots=1):
    """Execute entry order for selling an ATM option."""
    try:
        option_instrument = Utility.get_option_instrument(
            spot_price,
            option_type,
            moneyness='ATM',
            expiry_preference=Config.STRATEGY_CONFIG['EXPIRY_PREFERENCE']
        )

        if not option_instrument:
            logger.error(f'Could not find {option_type} option for {symbol}')
            return False

        base_lot_size = Utility.get_instrument_lot_size(option_instrument, default_lot_size=qty)
        order_qty = int(base_lot_size * lots)
        logger.info(f'{symbol} placing {option_type} sell order for qty: {order_qty}')
        entry_order_id = uplink_obj.placeMultipleOrder(option_instrument, order_qty, 'SELL', 'MARKET')

        if not entry_order_id:
            logger.error('Entry order placement failed for %s', symbol)
            return False

        use_v3_order_flow = hasattr(uplink_obj, '_use_v3_order_api') and uplink_obj._use_v3_order_api()
        if use_v3_order_flow:
            # V3 place-order returns acknowledgment; keep fill tracking separate from entry signal path.
            option_ltp = None
            if hasattr(uplink_obj, 'getLTP'):
                try:
                    option_ltp = uplink_obj.getLTP(option_instrument)
                except Exception as e:
                    logger.warning('Unable to fetch option LTP for entry log | instrument=%s | error=%s', option_instrument, e)

            entry_price = float(option_ltp) if option_ltp is not None else float(spot_price)
            Config.POSITION_CONFIG[symbol] = {
                'option_instrument': option_instrument,
                'index_instrument': symbol_config['index_instrument'],
                'qty': order_qty,
                'entry_price': entry_price,
                'option_type': option_type,
                'lots': lots,
                'entry_order_id': entry_order_id,
                'order_status': 'submitted',
            }
            if option_ltp is not None:
                logger.info('%s entry submitted via V3 order API | order_id=%s | entry_ltp=%s', symbol, entry_order_id, entry_price)
            else:
                logger.info('%s entry submitted via V3 order API | order_id=%s', symbol, entry_order_id)
            return True

        for i in range(10):
            all_traded, order_df = uplink_obj.isAllOrderTraded([entry_order_id])
            if all_traded:
                break
            sleep(i)

        if all_traded:
            entry_price = float(order_df.iloc[0]['average_price'])
            Config.POSITION_CONFIG[symbol] = {
                'option_instrument': option_instrument,
                'index_instrument': symbol_config['index_instrument'],
                'qty': order_qty,
                'entry_price': entry_price,
                'option_type': option_type,
                'lots': lots,
            }
            logger.info(f'{symbol} entry successful at price: {entry_price}')
            return True
        else:
            logger.warning(f'Entry order {entry_order_id} not completed')
            return False

    except Exception as e:
        logger.exception(f'Error in entry execution: {e}')
        return False


def exit_position(uplink_obj, symbol, qty):
    """Exit existing position"""
    try:
        logger.info(f'{symbol} exiting position')
        uplink_obj.closePosition(Config.POSITION_CONFIG[symbol]['option_instrument'], qty, 'BUY')
        Config.POSITION_CONFIG.pop(symbol)
        logger.info(f'{symbol} position closed')
    except Exception as e:
        logger.exception(f'Error in position exit: {e}')


def get_sync_time():
    """Return the sleep time between strategy evaluations."""
    tf = int(Config.STRATEGY_CONFIG.get('TIMEFRAME', 5))
    return max(60, tf * 60)


def get_candle_close_buffer_seconds():
    """Return execution buffer in seconds after each timeframe boundary."""
    return max(0.0, float(Config.STRATEGY_CONFIG.get('CANDLE_CLOSE_BUFFER_SECONDS', 1)))


def get_signal_check_timeout_seconds():
    """Return max allowed runtime for one signal-check cycle before timing out."""
    return max(5.0, float(Config.STRATEGY_CONFIG.get('SIGNAL_CHECK_TIMEOUT_SECONDS', 120)))


def get_max_consecutive_signal_timeouts():
    """Return max consecutive signal-check timeouts before forcing process exit."""
    return max(1, int(Config.STRATEGY_CONFIG.get('MAX_CONSECUTIVE_SIGNAL_TIMEOUTS', 5)))


def should_log_pivot_this_cycle():
    """Return True every configured Nth signal-check cycle to reduce pivot log noise."""
    interval = max(1, int(Config.STRATEGY_CONFIG.get('PIVOT_LOG_INTERVAL_ITERATIONS', 12)))
    current_count = int(getattr(Config, 'SIGNAL_CHECK_ITERATION_COUNT', 0)) + 1
    setattr(Config, 'SIGNAL_CHECK_ITERATION_COUNT', current_count)
    return current_count % interval == 0


def square_off_tracked_positions(uplink_obj, context_message=''):
    """Square off only strategy-tracked open positions and skip when none exist."""
    tracked_positions = getattr(Config, 'POSITION_CONFIG', {})
    if not isinstance(tracked_positions, dict) or not tracked_positions:
        if context_message:
            logger.info('%s | no tracked strategy positions to square off', context_message)
        else:
            logger.info('No tracked strategy positions to square off')
        return 0

    closed_count = 0
    for symbol, position in list(tracked_positions.items()):
        option_instrument = str(position.get('option_instrument', '') or '').strip()
        qty = int(position.get('qty', 0) or 0)
        if not option_instrument or qty <= 0:
            logger.warning(
                'Skipping tracked square-off for %s due to invalid position config: %s',
                symbol,
                position,
            )
            Config.POSITION_CONFIG.pop(symbol, None)
            continue

        try:
            uplink_obj.closePosition(option_instrument, qty, 'BUY')
            Config.POSITION_CONFIG.pop(symbol, None)
            closed_count += 1
            logger.info('Square-off submitted for %s | instrument=%s | qty=%s', symbol, option_instrument, qty)
        except Exception as exc:
            logger.exception('Failed to square off tracked position for %s: %s', symbol, exc)

    if context_message:
        logger.info('%s | tracked strategy square-off complete | closed=%s', context_message, closed_count)
    else:
        logger.info('Tracked strategy square-off complete | closed=%s', closed_count)
    return closed_count


def _run_signal_check_with_timeout(uplink_obj):
    """Execute one signal-check cycle with fail-fast timeout handling."""
    timeout_seconds = get_signal_check_timeout_seconds()
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(check_entry_signals, uplink_obj)
    timed_out = False
    try:
        future.result(timeout=timeout_seconds)
        return True
    except FutureTimeoutError:
        timed_out = True
        future.cancel()
        logger.error('Signal check timed out after %.1fs; skipping this cycle and continuing', timeout_seconds)
        return False
    except Exception as exc:
        logger.exception('Signal check failed with exception: %s', exc)
        return False
    finally:
        # Avoid blocking shutdown on timeout so the main loop can move to the next cycle.
        executor.shutdown(wait=not timed_out, cancel_futures=timed_out)


def get_next_check_time(current_time=None):
    """Return the next timeframe-aligned check time with close-buffer applied."""
    now = current_time or datetime.now(Config.TIME_ZONE)

    if is_trailing_stop_loss_enabled() and _is_any_trailing_mode_active():
        trailing_interval_seconds = get_trailing_evaluation_interval_seconds()
        return now + timedelta(seconds=trailing_interval_seconds)

    timeframe = max(1, int(Config.STRATEGY_CONFIG.get('TIMEFRAME', 5)))
    buffer_seconds = get_candle_close_buffer_seconds()

    rounded = now.replace(second=0, microsecond=0)
    minute_mod = rounded.minute % timeframe
    if minute_mod != 0:
        rounded = rounded + timedelta(minutes=(timeframe - minute_mod))

    scheduled = rounded + timedelta(seconds=buffer_seconds)
    if now >= scheduled:
        scheduled = scheduled + timedelta(minutes=timeframe)
    return scheduled


def main_trading_loop(uplink_obj):
    """Main trading loop."""
    logger.info('Main trading loop started | test_mode=%s', is_test_mode_enabled())
    consecutive_timeouts = 0

    while True:
        test_mode = is_test_mode_enabled()
        current_time = datetime.now(Config.TIME_ZONE)

        if not test_mode and has_reached_trading_end(current_time):
            logger.info('Trading end reached at %s; squaring off all positions and stopping loop', current_time)
            try:
                square_off_tracked_positions(uplink_obj, f'Trading end reached at {current_time}')
            except Exception as exc:
                logger.exception('Failed to square off positions at trading end: %s', exc)
            break

        if not test_mode and not is_trading_time():
            logger.info('Outside trading hours at %s; waiting for next cycle', current_time)
            sleep(get_sync_time())
            continue

        next_check_time = get_next_check_time(current_time)
        wait_seconds = max(0.0, (next_check_time - current_time).total_seconds())
        logger.info('Waiting for next aligned check at %s (sleep %.2fs)', next_check_time, wait_seconds)
        sleep(wait_seconds)

        trigger_time = datetime.now(Config.TIME_ZONE)
        if not test_mode and has_reached_trading_end(trigger_time):
            logger.info('Trading end reached at check trigger %s; squaring off all positions and stopping loop', trigger_time)
            try:
                square_off_tracked_positions(uplink_obj, f'Trading end reached at check trigger {trigger_time}')
            except Exception as exc:
                logger.exception('Failed to square off positions at trading end trigger: %s', exc)
            break

        if not test_mode and not is_trading_time():
            logger.info('Skipped signal check at %s due to trading window', trigger_time)
            continue

        logger.info('Starting signal check at %s (scheduled %s)', trigger_time, next_check_time)
        success = _run_signal_check_with_timeout(uplink_obj)
        if success:
            consecutive_timeouts = 0
            continue

        consecutive_timeouts += 1
        max_timeouts = get_max_consecutive_signal_timeouts()
        logger.warning(
            'Signal-check timeout/failure streak: %s/%s',
            consecutive_timeouts,
            max_timeouts,
        )
        if consecutive_timeouts >= max_timeouts:
            logger.critical(
                'Exceeded maximum consecutive signal-check timeouts (%s). Exiting process for external restart.',
                max_timeouts,
            )
            raise RuntimeError('Signal-check timeout threshold exceeded')


if __name__ == '__main__':
    # Check if in test mode
    if is_test_mode_enabled():
        logger.info('Running in TEST MODE - skipping market timing checks only; API calls remain live/sandbox based on config')
    else:
        # Wait for market start
        start_time = datetime.now(Config.TIME_ZONE)
        market_start = start_time.replace(hour=Config.TRADING_HOURS['START'][0], minute=Config.TRADING_HOURS['START'][1], second=0)
        wait_time = max(0, (market_start - start_time).total_seconds())
        
        if wait_time > 0:
            logger.info(f'Waiting for market start: {wait_time} seconds')
            sleep(wait_time)
    
    logger.info('Starting strategy entrypoint | current_time=%s | test_mode=%s', datetime.now(Config.TIME_ZONE), is_test_mode_enabled())
    logger.info(
        'Configured trading window | start=%02d:%02d:%02d | end=%02d:%02d:%02d | timeframe=%s minutes | pivot_log_interval_iterations=%s',
        Config.TRADING_HOURS['START'][0],
        Config.TRADING_HOURS['START'][1],
        Config.TRADING_HOURS['START'][2],
        Config.TRADING_HOURS['END'][0],
        Config.TRADING_HOURS['END'][1],
        Config.TRADING_HOURS['END'][2],
        Config.STRATEGY_CONFIG.get('TIMEFRAME', 5),
        Config.STRATEGY_CONFIG.get('PIVOT_LOG_INTERVAL_ITERATIONS', 12),
    )

    try:
        Utility.initialize_system()
    except Exception as exc:
        logger.exception('Initialization failed: %s', exc)
        raise

    # Runtime always uses Upstox API; MockUplink is intended for unit tests only.
    Config.UPLINK_OBJ = UpstoxApi(accessToken=Config.ACCESS_TOKEN)
    uplink_obj = Config.UPLINK_OBJ
    initialize_runtime_state(uplink_obj)
    
    logger.info('Starting NIFTY Option Selling Intraday Strategy')
    main_trading_loop(uplink_obj)
    
    logger.info('Market closed - Squaring off all positions')
    square_off_tracked_positions(uplink_obj, 'Post-loop market close handler')

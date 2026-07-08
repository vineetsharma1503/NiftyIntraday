# ============================================================================
# STRATEGY - NIFTY Intraday Option Selling using Pivot Points and Supertrend CONFIGURATION
# ============================================================================

import pytz

# Timezone Configuration
TIME_ZONE = pytz.timezone('Asia/Kolkata')
ORDER_TAG = 'STRATEGY_NIFTY_INTRADAY'

# User API Credentials (REQUIRED - Fill these with your Upstox credentials)
API_KEY = ''
SECRET_KEY = ''
MOBILE_NO = ''
PIN = ''
TOTP_KEY = ''

# Strategy Configuration (Modify these as needed)
STRATEGY_CONFIG = {
    # Breakout Settings
    'TIMEFRAME': 5,              # Candle timeframe in minutes
    'CANDLE_CLOSE_BUFFER_SECONDS': 1,  # Delay after candle boundary before evaluating signals
    'LOTS': 1,                   # Default number of option lots per entry
    'MAX_ENTRIES': 3,            # Maximum number of entries per day
    'SUPERTREND_LENGTH': 7,     # Supertrend ATR period (TradingView default)
    'SUPERTREND_MULTIPLIER': 3.0,  # Supertrend ATR multiplier
    
    
    # Option Selection
    'OPTION_MONEYNESS': 'ATM',   # 'ATM', 'ITM1', 'ITM2', 'OTM1', 'OTM2'
    'EXPIRY_PREFERENCE': 'weekly', # 'weekly' or 'monthly'
    
    
    # System Settings
    'TEST_MODE': False,           # True = skip market timing (for testing only)

    # Upstox API mode
    'UPSTOX_ORDER_API_VERSION': 'v3',
    'UPSTOX_QUOTE_API_VERSION': 'v3',
    'SANDBOX_MODE': False,
    # Optional explicit overrides. Keep None to auto-select by SANDBOX_MODE.
    'UPSTOX_V3_BASE_URL': None,
    'UPSTOX_V3_QUOTE_BASE_URL': None,
}

# NIFTY Configuration
NIFTY_CONFIG = {
    'index_instrument': 'NSE_INDEX|Nifty 50',  # For getting NIFTY spot price
    'lot_size': 75,              # Standard NIFTY option lot size
    'enable': True               # Enable/disable trading
}

# Trading Schedule
TRADING_HOURS = {
    'START': (9, 15, 0),         # Market start: 9:15 AM
    'END': (15, 19, 0),          # Auto exit: 3:25 PM (5 min before close)
}

# Order Configuration
ORDER_TYPE = 'I'                 # 'I' for Intraday, 'D' for Delivery

# ============================================================================
# SYSTEM VARIABLES (DO NOT MODIFY)
# ============================================================================
ACCESS_TOKEN = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiIyMTM2NDEiLCJqdGkiOiI2ODk1N2FlODIyMWFiODUzNWNhZDM0YzIiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlhdCI6MTc1NDYyNjc5MiwiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxNzU0NjkwNDAwfQ.CeFGF5Q80l9CYU9vUd-24sY-wYW9gCDHUQ1j9X5OK0w"
UPLINK_OBJ = None
POSITION_CONFIG = {}
CANDLE_DATA_CACHE = {}

# Legacy variables for backward compatibility (will be removed)
RURL = 'https://127.0.0.1:5000/'
TZ_INFO = TIME_ZONE

API_SECRET= None

REDIRECT_URI = None


def is_sandbox_mode():
    """Return True when strategy should run against Upstox sandbox endpoints."""
    return bool(STRATEGY_CONFIG.get('SANDBOX_MODE', False))


def get_upstox_auth_base_url():
    """Base URL for auth dialog and token exchange endpoints."""
    if is_sandbox_mode():
        return 'https://api-sandbox.upstox.com'
    return 'https://api-v2.upstox.com'


def get_upstox_v2_base_url():
    """Base URL for v2 REST endpoints used in token validation and utility calls."""
    if is_sandbox_mode():
        return 'https://api-sandbox.upstox.com'
    return 'https://api.upstox.com'


def get_upstox_v3_order_base_url():
    """Base URL for v3 order endpoints."""
    configured = STRATEGY_CONFIG.get('UPSTOX_V3_BASE_URL')
    if configured:
        return str(configured).rstrip('/')
    if is_sandbox_mode():
        return 'https://api-sandbox.upstox.com'
    return 'https://api-hft.upstox.com'


def get_upstox_v3_quote_base_url():
    """Base URL for v3 quote endpoints."""
    configured = STRATEGY_CONFIG.get('UPSTOX_V3_QUOTE_BASE_URL')
    if configured:
        return str(configured).rstrip('/')
    if is_sandbox_mode():
        return 'https://api-sandbox.upstox.com'
    return 'https://api.upstox.com'
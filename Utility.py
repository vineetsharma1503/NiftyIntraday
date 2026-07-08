# ============================================================================
# UTILITY FUNCTIONS FOR STRATEGY2 - NIFTY CANDLE BREAKOUT STRATEGY
# ============================================================================

from datetime import datetime, time
import json
import base64
import urllib.parse
import urllib.request
import urllib.error
import pandas as pd
import gzip
import Config 
from logger import logger
import os


# ============================================================================
# TOKEN MANAGEMENT
# ============================================================================

def get_token_path():
    """Get the absolute path to token.json in the same directory as this file."""
    token_file = 'token_sandbox.json' if Config.is_sandbox_mode() else 'token.json'
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), token_file)


def load_token():
    """Load access token from token.json"""
    try:
        token_path = get_token_path()
        with open(token_path, 'r') as f:
            data = json.load(f)
        return data.get('access_token'), data.get('timestamp')
    except Exception as e:
        logger.error(f'Error loading token: {e}')
        return None, None


def save_token(token):
    """Save access token to token.json"""
    try:
        data = {
            'access_token': token,
            'timestamp': datetime.now().strftime('%Y-%m-%d')
        }
        token_path = get_token_path()
        with open(token_path, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info('Token saved successfully')
    except Exception as e:
        logger.error(f'Error saving token: {e}')


def test_token_validity(token):
    """Test if token is valid by making a simple API call"""
    def _is_token_not_expired(token_value):
        """Fallback check when network validation is blocked upstream (e.g., Cloudflare)."""
        try:
            parts = str(token_value).split('.')
            if len(parts) != 3:
                return False

            payload = parts[1]
            # Base64url decode with proper padding.
            padded = payload + ('=' * (-len(payload) % 4))
            decoded = base64.urlsafe_b64decode(padded.encode('utf-8')).decode('utf-8')
            claims = json.loads(decoded)
            exp = int(claims.get('exp', 0))
            if exp <= 0:
                return False

            now_ts = int(datetime.now().timestamp())
            return exp > now_ts
        except Exception:
            return False

    try:
        # Use profile endpoint for token validation to avoid segment-specific input errors.
        url = f"{Config.get_upstox_v2_base_url()}/v2/user/profile"

        req = urllib.request.Request(
            url,
            method='GET',
            headers={
                'accept': 'application/json',
                'Api-Version': '2.0',
                'Authorization': f'Bearer {token}',
                # Cloudflare may block default Python urllib signatures.
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
                'Cache-Control': 'no-cache',
            },
        )

        with urllib.request.urlopen(req, timeout=15):
            logger.info('Token validation successful - API call succeeded')
            return True

    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode('utf-8', errors='replace')
        except Exception:
            body = str(e)

        # If Cloudflare blocks request signature, fall back to local JWT expiry check.
        if e.code == 403 and ('browser_signature_banned' in body or 'Error 1010' in body):
            if _is_token_not_expired(token):
                logger.warning('Token validation request blocked by Cloudflare (1010). Token expiry check passed locally; proceeding with token.')
                return True
            logger.error('Token validation blocked by Cloudflare and local token expiry check failed.')
            return False

        if e.code == 401:
            logger.error('Token validation failed - Invalid or expired token (401 Unauthorized)')
        else:
            logger.error('Token validation failed - API error: %s - %s', e.code, body)
        return False
    except urllib.error.URLError as e:
        logger.error(f'Token validation failed - Connection error: {e}')
        return False
    except Exception as e:
        logger.error(f'Token validation failed - Unexpected error: {e}')
        return False


def is_token_valid():
    """Check if stored token exists, is for today, AND is actually valid with API"""
    token, timestamp = load_token()
    if not token or not timestamp:
        logger.info('No stored token found')
        return False
    
    try:
        # Check if token is for today
        token_date = datetime.strptime(timestamp, '%Y-%m-%d').date()
        today = datetime.now().date()
        
        if token_date != today:
            logger.info(f'Stored token is from {token_date}, but today is {today} - token expired')
            return False
            
        # Check if token actually works with API
        logger.info('Found stored token for today - testing validity with API call...')
        return test_token_validity(token)
        
    except ValueError as e:
        logger.error(f'Invalid timestamp format in token file: {e}')
        return False


def initialize_system():
    """Initialize the trading system"""
    logger.info('Initializing Strategy - NIFTY Intraday Option Selling using Pivot Points and Supertrend')
    logger.info('Upstox mode: %s', 'SANDBOX' if Config.is_sandbox_mode() else 'LIVE')
    logger.info('Resolved Upstox auth base URL: %s', Config.get_upstox_auth_base_url())
    logger.info('Resolved Upstox v2 base URL: %s', Config.get_upstox_v2_base_url())
    logger.info('Resolved Upstox v3 order base URL: %s', Config.get_upstox_v3_order_base_url())
    logger.info('Resolved Upstox v3 quote base URL: %s', Config.get_upstox_v3_quote_base_url())

    if Config.STRATEGY_CONFIG.get('TEST_MODE', False):
        logger.info('TEST MODE enabled - market-hour checks are bypassed; API authentication setup will still run')

    if Config.is_sandbox_mode():
        token, _ = load_token()
        if token:
            Config.ACCESS_TOKEN = token
            logger.info('Sandbox mode: using stored token without validity check')
        elif Config.ACCESS_TOKEN:
            save_token(Config.ACCESS_TOKEN)
            logger.info('Sandbox mode: using Config.ACCESS_TOKEN without validity check')
        else:
            logger.error('No ACCESS_TOKEN found for sandbox mode')
            logger.error('Set ACCESS_TOKEN in Config.py or generate one with Upstox login helper')
            raise ValueError('ACCESS_TOKEN is required for sandbox mode')

        logger.info(f'Timeframe: {Config.STRATEGY_CONFIG["TIMEFRAME"]} minutes')
        logger.info(f'Option: {Config.STRATEGY_CONFIG["OPTION_MONEYNESS"]} {Config.STRATEGY_CONFIG["EXPIRY_PREFERENCE"]}')
        logger.info(f'Max Entries: {Config.STRATEGY_CONFIG["MAX_ENTRIES"]}')
        logger.info(f'Lots per Entry: {Config.STRATEGY_CONFIG["LOTS"]}')
        return
    
    # Check for stored valid token
    if is_token_valid():
        token, _ = load_token()
        Config.ACCESS_TOKEN = token
        logger.info('✅ Using stored valid token - API authentication confirmed')
    else:
        # Check if there's a token in Config.py
        if not Config.ACCESS_TOKEN:
            logger.error('❌ No valid ACCESS_TOKEN found!')
            logger.error('Please either:')
            logger.error('1. Set ACCESS_TOKEN in Config.py with a valid token, OR')
            logger.error('2. Use UpstoxDirectLogin.py to generate a new token')
            raise ValueError('ACCESS_TOKEN is required for trading operations')
        
        # Test the token from Config.py
        logger.info('Testing ACCESS_TOKEN from Config.py...')
        if test_token_validity(Config.ACCESS_TOKEN):
            save_token(Config.ACCESS_TOKEN)
            logger.info('✅ Config.py token is valid - saved for future use')
        else:
            logger.error('❌ ACCESS_TOKEN in Config.py is invalid!')
            logger.error('Please update Config.py with a valid token or use UpstoxDirectLogin.py')
            raise ValueError('Invalid ACCESS_TOKEN provided')
    
    # Log configuration

    logger.info(f'Timeframe: {Config.STRATEGY_CONFIG["TIMEFRAME"]} minutes')
    logger.info(f'Option: {Config.STRATEGY_CONFIG["OPTION_MONEYNESS"]} {Config.STRATEGY_CONFIG["EXPIRY_PREFERENCE"]}')
    logger.info(f'Max Entries: {Config.STRATEGY_CONFIG["MAX_ENTRIES"]}')
    logger.info(f'Lots per Entry: {Config.STRATEGY_CONFIG["LOTS"]}')


# ============================================================================
# OPTION SELECTION FOR NIFTY
# ============================================================================

def get_option_instrument(spot_price, option_type, moneyness='ATM', expiry_preference='weekly'):
    """
    Get NIFTY option instrument for trading
    
    Args:
        spot_price: Current NIFTY spot price
        option_type: 'CE' or 'PE'
        moneyness: 'ATM', 'ITM1', 'ITM2', 'OTM1', 'OTM2'
        expiry_preference: 'weekly' or 'monthly'
    
    Returns:
        instrument_token for the option
    """
    try:
        instrument_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'NSE.json.gz')
        with gzip.open(instrument_file, 'rt') as f:
            df = pd.read_json(f)

        # Keep only requested NIFTY option side.
        nifty_options = df[
            (df['name'] == 'NIFTY') &
            (df['trading_symbol'].str.contains('NIFTY', na=False)) &
            (df['instrument_type'] == option_type) &
            (df['exchange'] == 'NSE')
        ].copy()

        if nifty_options.empty:
            logger.error("No NIFTY options found in NSE.csv.gz")
            return None

        nifty_options['strike_price'] = pd.to_numeric(nifty_options['strike_price'], errors='coerce')
        nifty_options['expiry'] = pd.to_numeric(nifty_options['expiry'], errors='coerce')
        nifty_options = nifty_options.dropna(subset=['strike_price', 'expiry'])

        if nifty_options.empty:
            logger.error('No valid NIFTY %s rows after strike/expiry normalization', option_type)
            return None

        nifty_options['expiry_date'] = pd.to_datetime(nifty_options['expiry'], unit='ms', utc=True).dt.tz_convert(Config.TIME_ZONE)
        current_date = datetime.now(Config.TIME_ZONE).date()
        nifty_options['days_to_expiry'] = (nifty_options['expiry_date'].dt.date - current_date).apply(lambda x: x.days)

        # Use active or same-day expiries; avoid selecting stale expired strikes.
        future_options = nifty_options[nifty_options['days_to_expiry'] >= 0].copy()
        if future_options.empty:
            logger.error('No future %s options found for NIFTY', option_type)
            return None

        if 'weekly' in future_options.columns:
            future_options['weekly_flag'] = future_options['weekly'].astype(str).str.lower().isin({'true', '1'})
        else:
            future_options['weekly_flag'] = False

        # Calculate ATM strike (NIFTY strikes are in 50-point intervals)
        atm_strike = int(round(float(spot_price) / 50) * 50)

        # Calculate target strike based on moneyness
        strike_map = {
            'ATM': 0,
            'ITM1': -50 if option_type == 'CE' else 50,
            'ITM2': -100 if option_type == 'CE' else 100,
            'OTM1': 50 if option_type == 'CE' else -50,
            'OTM2': 100 if option_type == 'CE' else -100
        }

        target_strike = atm_strike + strike_map.get(moneyness, 0)

        # Select expiry universe based on preference and fallback gracefully.
        if expiry_preference == 'weekly':
            weekly_universe = future_options[future_options['weekly_flag'] == True]
            current_week_universe = weekly_universe[weekly_universe['days_to_expiry'] <= 7]
            if not current_week_universe.empty:
                option_universe = current_week_universe
            elif not weekly_universe.empty:
                option_universe = weekly_universe
            else:
                option_universe = future_options
        elif expiry_preference == 'monthly':
            preferred_universe = future_options[future_options['weekly_flag'] == False]
            option_universe = preferred_universe if not preferred_universe.empty else future_options
        else:
            option_universe = future_options

        # First lock the closest expiry (today included), then pick nearest strike inside that expiry.
        selected_expiry = option_universe.sort_values(['days_to_expiry', 'expiry_date']).iloc[0]['expiry_date']
        expiry_options = option_universe[option_universe['expiry_date'] == selected_expiry].copy()

        strikes = expiry_options['strike_price'].dropna().unique()
        if len(strikes) == 0:
            logger.error('No valid strikes available after expiry filtering for %s %s', option_type, expiry_preference)
            return None

        selected_strike = float(min(strikes, key=lambda strike: abs(float(strike) - float(target_strike))))
        strike_options = expiry_options[expiry_options['strike_price'] == selected_strike].copy()
        if strike_options.empty:
            logger.error('Unable to resolve strike options for selected strike %s', selected_strike)
            return None

        selected_option = strike_options.sort_values(['days_to_expiry', 'expiry_date']).iloc[0]

        logger.info(f"Selected {option_type} option: {selected_option['trading_symbol']} "
                   f"Strike: {selected_option['strike_price']} Target Strike: {target_strike} "
                   f"Expiry: {selected_option['expiry_date']} Days to expiry: {selected_option['days_to_expiry']}")

        return selected_option['instrument_key']

    except Exception as e:
        logger.error(f"Error finding option instrument: {e}")
        return None


def get_instrument_lot_size(instrument_key, default_lot_size=1):
    """Return lot size for an instrument key from NSE.json.gz."""
    try:
        instrument_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'NSE.json.gz')
        with gzip.open(instrument_file, 'rt') as f:
            df = pd.read_json(f)

        matched = df[df['instrument_key'] == instrument_key]
        if matched.empty or 'lot_size' not in matched.columns:
            return int(default_lot_size)

        lot_size = pd.to_numeric(matched.iloc[0]['lot_size'], errors='coerce')
        if pd.isna(lot_size) or int(lot_size) <= 0:
            return int(default_lot_size)
        return int(lot_size)
    except Exception as e:
        logger.warning('Could not resolve lot size for %s: %s. Falling back to %s', instrument_key, e, default_lot_size)
        return int(default_lot_size)


# ============================================================================
# LEGACY FUNCTIONS (FOR BACKWARD COMPATIBILITY)
# ============================================================================

def getConfig():
    """Legacy function - use load_token() instead"""
    token, timestamp = load_token()
    if token and timestamp:
        return {'access_token': token, 'timestamp': timestamp}
    return {}


def setConfig(updateDict):
    """Legacy function - use save_token() instead"""
    if 'access_token' in updateDict:
        save_token(updateDict['access_token'])


def isTokenValid():
    """Legacy function - use is_token_valid() instead"""
    if is_token_valid():
        token, _ = load_token()
        return token
    return None


def initializer():
    """Legacy function - use initialize_system() instead"""
    initialize_system()


def get_nifty_option_instrument(nifty_price, option_type, expiry_date=None):
    """Legacy function - use get_option_instrument() instead"""
    return get_option_instrument(nifty_price, option_type, 'ATM', 'weekly')


def find_nifty_atm_option(current_price, option_type):
    """Legacy function - use get_option_instrument() instead"""
    return get_option_instrument(current_price, option_type, 'ATM', 'weekly')

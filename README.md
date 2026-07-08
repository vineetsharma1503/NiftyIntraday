# Strategy2 - NIFTY Candle Breakout Options Trading

## Overview
A clean and robust candle breakout strategy for trading NIFTY options. This strategy monitors NIFTY 50 index price movements and executes option trades based on candle breakout patterns with comprehensive risk management.

## Strategy Logic

### Entry Conditions
1. **LONG Direction**: 
   - Current candle closes above the highest high of previous N candles
   - → Buy Call Option (CE)

2. **SHORT Direction**: 
   - Current candle closes below the lowest low of previous N candles  
   - → Buy Put Option (PE)

### Exit Conditions
- **Stop Loss**: Configurable percentage loss (default: 2%)
- **Target**: Configurable percentage profit (default: 4%)
- **Auto Exit**: 5 minutes before market close (3:25 PM)

## Configuration

Edit `Config.py` to customize the strategy:

```python
STRATEGY_CONFIG = {
    'TIMEFRAME': 1,              # Candle timeframe in minutes 
    'CANDLE_COUNT': 2,           # Number of candles to check for breakout
    'DIRECTION': 'LONG',         # 'LONG' or 'SHORT'
    'STOP_LOSS_PERCENT': 2.0,    # Stop loss percentage
    'TARGET_PERCENT': 4.0,       # Target percentage
    'OPTION_MONEYNESS': 'ATM',   # ATM, ITM1, ITM2, OTM1, OTM2
    'EXPIRY_PREFERENCE': 'weekly', # weekly or monthly
    'TEST_MODE': False           # Skip market timing for testing
}
```

### Option Selection
- **ATM**: At The Money (closest to spot price)
- **ITM1/ITM2**: In The Money (1-2 strikes inside)
- **OTM1/OTM2**: Out of The Money (1-2 strikes outside)

### Strike Logic
- NIFTY strikes are in 50-point intervals
- ATM: Rounded to nearest 50 (24,550 → 24,550)
- ITM Call: Lower strikes (24,550 → 24,500 for ITM1)
- OTM Call: Higher strikes (24,550 → 24,600 for OTM1)

## Authentication & Setup

### 🔐 **Step 1: Get Upstox Access Token**

**Option A - Manual Token (Recommended for testing):**
1. Login to Upstox and get your access token
2. Update `Config.py`:
   ```python
   ACCESS_TOKEN = "your_actual_upstox_access_token_here"
   ```

**Option B - Auto-login (Advanced):**
1. Fill your credentials in `Config.py`:
   ```python
   API_KEY = 'your_upstox_api_key'
   SECRET_KEY = 'your_upstox_secret'
   MOBILE_NO = 'your_mobile_number'
   PIN = 'your_upstox_pin'
   ```
2. Run: `python3 UpstoxDirectLogin.py`

### ✅ **Token Validation**
The system now **validates tokens with real API calls**:
- ✅ Tests stored tokens before use
- ❌ Rejects invalid/expired tokens with clear error messages
- 🔄 Automatically saves valid tokens for reuse

## Files Structure (Clean & Organized)

```
strategy2/
├── Config.py              # Strategy configuration (user settings)
├── main.py               # Main strategy logic & candle breakout signals  
├── upstoxapi.py          # Upstox API wrapper (simplified)
├── Utility.py            # Helper functions (token validation, option selection)
├── logger.py             # Logging setup (clean format)
├── UpstoxDirectLogin.py  # Auto-login utility
├── token.json            # Access token storage (auto-managed)
├── NSE.csv.gz            # NSE instrument master file
├── requirements.txt      # Python dependencies
└── README.md             # Documentation
```

## Quick Start

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Setup Authentication** (Choose one option above)

3. **Configure Strategy**
   ```python
   # Edit STRATEGY_CONFIG in Config.py
   'TIMEFRAME': 1,              # 1-minute candles
   'CANDLE_COUNT': 2,           # Check last 2 candles
   'DIRECTION': 'LONG',         # Trade direction
   'STOP_LOSS_PERCENT': 2.0,    # 2% stop loss
   'TARGET_PERCENT': 4.0,       # 4% target
   ```

4. **Run Strategy**
   ```bash
   python3 main.py
   ```

## Key Features

✅ **Clean Architecture**: Refactored code with clear separation of concerns  
✅ **Candle Breakout**: Reliable breakout/breakdown detection logic  
✅ **Smart Option Selection**: Automatic ATM/ITM/OTM selection from NSE data  
✅ **Robust Risk Management**: Built-in stop loss and target with real-time P&L  
✅ **Flexible Configuration**: User-friendly settings in Config.py  
✅ **Test Mode**: Skip market timing for development and testing  
✅ **Comprehensive Logging**: Clean logs with strategy performance tracking  
✅ **Token Validation**: Real API call validation for authentication
- `Utility.py`: Helper functions including option selection
- `logger.py`: Logging configuration
- `UpstoxDirectLogin.py`: Authentication helper
- `NSE.csv.gz`: Symbol database for option instrument lookup
- `token.json`: Access token storage

## Usage

1. Configure your strategy parameters in `Config.py`
2. Set your Upstox API credentials
3. Run: `python main.py`

## Example Configuration

For a 5-minute, 2-candle breakout strategy:
- `TIMEFRAME`: 5 (minutes)
- `CANDLE_COUNT`: 2 (check last 2 candles)
- If LONG: Buy CE when price breaks above 2-candle high
- If SHORT: Buy PE when price breaks below 2-candle low

## Risk Management

- **Stop Loss**: Automatic exit when option price moves against position by configured percentage
- **Target**: Automatic exit when option price reaches profit target
- **Time-based Exit**: All positions squared off before market close (3:25 PM)

## Requirements

- upstox_client
- pandas
- numpy
- Valid Upstox trading account and API access

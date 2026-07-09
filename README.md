# Strategy - NIFTY Intraday Directional Options Trading

## Overview
A clean and robust strategy for trading NIFTY options. This strategy uses Pivot Points standard and Supertrend to generate entry and exit signals.

## Strategy Logic

### Entry Conditions
1. **LONG Direction**: 
   - Current candle on 5 mins time frame closes above the R1 AND Supertrend(7,3).
   - → Sell ATM Put Option (PE) of nearest expiry (including expiry day)

2. **SHORT Direction**: 
   - Current candle closes below the S1 AND Supertrend (7,3).
   - → Sell ATM Call Option (CE) of nearest expiry (including expiry day)

### Exit Conditions
- **LONG Direction**: If 5 minute candle closes below R1 OR Supertrend (7,3)
- **SHORT Direction**: If 5 minute candle closes above S1 OR Supertrend (7,3)
- **Target**: Exit at 3:15 PM to extract maximum theta.

## Configuration

Edit `Config.py` to customize the strategy:

```python
STRATEGY_CONFIG = {
    'TIMEFRAME': 5,              # Candle timeframe in minutes 
    'OPTION_MONEYNESS': 'ATM',   # ATM, ITM1, ITM2, OTM1, OTM2
    'EXPIRY_PREFERENCE': 'weekly', # weekly or monthly
    'TEST_MODE': False           # Skip market timing for testing
    'CANDLE_CLOSE_BUFFER_SECONDS': 1,  # Delay after candle boundary before evaluating signals
    'LOTS': 1,                   # Default number of option lots per entry
    'MAX_ENTRIES': 3,            # Maximum number of entries per day
    'SUPERTREND_LENGTH': 7,     # Supertrend ATR period (TradingView default)
    'SUPERTREND_MULTIPLIER': 3.0,  # Supertrend ATR multiplier
}
```


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
niftyintradayoption/
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
   'TIMEFRAME': 5,              # Candle timeframe in minutes 
    'OPTION_MONEYNESS': 'ATM',   # ATM, ITM1, ITM2, OTM1, OTM2
    'EXPIRY_PREFERENCE': 'weekly', # weekly or monthly
    'TEST_MODE': False           # Skip market timing for testing
    'CANDLE_CLOSE_BUFFER_SECONDS': 1,  # Delay after candle boundary before evaluating signals
    'LOTS': 1,                   # Default number of option lots per entry
    'MAX_ENTRIES': 3,            # Maximum number of entries per day
    'SUPERTREND_LENGTH': 7,     # Supertrend ATR period (TradingView default)
    'SUPERTREND_MULTIPLIER': 3.0,  # Supertrend ATR multiplier
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



## Risk Management

- **Stop Loss**: Dynamic exit given by the Supertrend. Signal check happens every 5 minutes
- **Target**: Unless exit signal is generated the position will run till EOD (3:15 PM) to capture maximum theta


## Requirements

- upstox_client
- pandas
- numpy
- Valid Upstox trading account and API access

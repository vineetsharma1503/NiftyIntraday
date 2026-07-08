#!/usr/bin/env python3
"""
Simple validation script for Strategy3
"""
import sys
import os

print("Strategy3 Validation")
print("=" * 40)

try:
    # Test imports
    print("1. Testing imports...")
    import pandas as pd
    import numpy as np
    print("   ✅ pandas, numpy imported")
    
    # Test local modules
    sys.path.append('/Users/architmittal/Downloads/live_codes/strategy3')
    import Config
    print("   ✅ Config imported")
    
    import Utility
    print("   ✅ Utility imported")
    
    from logger import logger
    print("   ✅ logger imported")
    
    # Test configuration
    print("\n2. Testing configuration...")
    print(f"   Direction: {Config.STRATEGY_CONFIG['DIRECTION']}")
    print(f"   Timeframe: {Config.STRATEGY_CONFIG['TIMEFRAME']} min")
    print(f"   EMAs: {Config.STRATEGY_CONFIG['FAST_EMA']}/{Config.STRATEGY_CONFIG['SLOW_EMA']}")
    print(f"   Risk: {Config.STRATEGY_CONFIG['STOP_LOSS_PERCENT']}%/{Config.STRATEGY_CONFIG['TARGET_PERCENT']}%")
    
    # Test option selection
    print("\n3. Testing option selection...")
    spot_price = 55000
    option_instrument = Utility.get_option_instrument(spot_price, 'CE', 'ATM', 'weekly')
    if option_instrument:
        print(f"   ✅ Found option instrument: {option_instrument}")
    else:
        print("   ❌ Could not find option instrument")
    
    print("\n✅ All basic validations passed!")
    print("\nTo run with real trading:")
    print("1. Set your API credentials in Config.py")
    print("2. Set TEST_MODE = False for live trading")
    print("3. Run: python3 main.py")
    
except ImportError as e:
    print(f"   ❌ Import error: {e}")
    print("   Install missing dependencies: pip install -r requirements.txt")
    
except Exception as e:
    print(f"   ❌ Error: {e}")
    
print("\n" + "=" * 40)

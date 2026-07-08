import unittest
from unittest.mock import patch

import pandas as pd

import Utility


class UtilityOptionSelectionTests(unittest.TestCase):
    @staticmethod
    def _expiry_ms(days_offset):
        ts = pd.Timestamp.now(tz='Asia/Kolkata').normalize() + pd.Timedelta(days=days_offset)
        return int(ts.tz_convert('UTC').value // 10**6)

    @patch('Utility.gzip.open')
    @patch('Utility.pd.read_json')
    def test_selects_nearest_future_strike_when_target_strike_is_expired(self, mock_read_json, _mock_gzip_open):
        mock_read_json.return_value = pd.DataFrame([
            {
                'name': 'NIFTY',
                'exchange': 'NSE',
                'instrument_type': 'CE',
                'trading_symbol': 'NIFTY 24400 CE EXP',
                'strike_price': 24400,
                'expiry': self._expiry_ms(-1),
                'weekly': True,
                'instrument_key': 'NSE_FO|EXPIRED',
            },
            {
                'name': 'NIFTY',
                'exchange': 'NSE',
                'instrument_type': 'CE',
                'trading_symbol': 'NIFTY 24500 CE FUT',
                'strike_price': 24500,
                'expiry': self._expiry_ms(2),
                'weekly': True,
                'instrument_key': 'NSE_FO|FUT24500',
            },
            {
                'name': 'NIFTY',
                'exchange': 'NSE',
                'instrument_type': 'CE',
                'trading_symbol': 'NIFTY 24000 CE FUT',
                'strike_price': 24000,
                'expiry': self._expiry_ms(2),
                'weekly': True,
                'instrument_key': 'NSE_FO|FUT24000',
            },
        ])

        instrument = Utility.get_option_instrument(spot_price=24420, option_type='CE', moneyness='ATM', expiry_preference='weekly')

        self.assertEqual(instrument, 'NSE_FO|FUT24500')

    @patch('Utility.gzip.open')
    @patch('Utility.pd.read_json')
    def test_monthly_preference_prefers_non_weekly_contract(self, mock_read_json, _mock_gzip_open):
        mock_read_json.return_value = pd.DataFrame([
            {
                'name': 'NIFTY',
                'exchange': 'NSE',
                'instrument_type': 'PE',
                'trading_symbol': 'NIFTY 24400 PE WEEKLY',
                'strike_price': 24400,
                'expiry': self._expiry_ms(2),
                'weekly': True,
                'instrument_key': 'NSE_FO|WEEKLY',
            },
            {
                'name': 'NIFTY',
                'exchange': 'NSE',
                'instrument_type': 'PE',
                'trading_symbol': 'NIFTY 24400 PE MONTHLY',
                'strike_price': 24400,
                'expiry': self._expiry_ms(25),
                'weekly': False,
                'instrument_key': 'NSE_FO|MONTHLY',
            },
        ])

        instrument = Utility.get_option_instrument(spot_price=24420, option_type='PE', moneyness='ATM', expiry_preference='monthly')

        self.assertEqual(instrument, 'NSE_FO|MONTHLY')

    @patch('Utility.gzip.open')
    @patch('Utility.pd.read_json')
    def test_weekly_preference_uses_same_day_expiry_when_available(self, mock_read_json, _mock_gzip_open):
        mock_read_json.return_value = pd.DataFrame([
            {
                'name': 'NIFTY',
                'exchange': 'NSE',
                'instrument_type': 'CE',
                'trading_symbol': 'NIFTY 24400 CE TODAY',
                'strike_price': 24400,
                'expiry': self._expiry_ms(0),
                'weekly': True,
                'instrument_key': 'NSE_FO|TODAY',
            },
            {
                'name': 'NIFTY',
                'exchange': 'NSE',
                'instrument_type': 'CE',
                'trading_symbol': 'NIFTY 24400 CE NEXTWEEK',
                'strike_price': 24400,
                'expiry': self._expiry_ms(7),
                'weekly': True,
                'instrument_key': 'NSE_FO|NEXTWEEK',
            },
        ])

        instrument = Utility.get_option_instrument(spot_price=24420, option_type='CE', moneyness='ATM', expiry_preference='weekly')

        self.assertEqual(instrument, 'NSE_FO|TODAY')

    @patch('Utility.gzip.open')
    @patch('Utility.pd.read_json')
    def test_weekly_preference_prioritizes_closest_expiry_before_strike(self, mock_read_json, _mock_gzip_open):
        mock_read_json.return_value = pd.DataFrame([
            {
                'name': 'NIFTY',
                'exchange': 'NSE',
                'instrument_type': 'PE',
                'trading_symbol': 'NIFTY 24500 PE CLOSEST_EXPIRY',
                'strike_price': 24500,
                'expiry': self._expiry_ms(1),
                'weekly': True,
                'instrument_key': 'NSE_FO|D1',
            },
            {
                'name': 'NIFTY',
                'exchange': 'NSE',
                'instrument_type': 'PE',
                'trading_symbol': 'NIFTY 24400 PE FAR_EXPIRY',
                'strike_price': 24400,
                'expiry': self._expiry_ms(3),
                'weekly': True,
                'instrument_key': 'NSE_FO|D3',
            },
        ])

        instrument = Utility.get_option_instrument(spot_price=24420, option_type='PE', moneyness='ATM', expiry_preference='weekly')

        self.assertEqual(instrument, 'NSE_FO|D1')


if __name__ == '__main__':
    unittest.main()

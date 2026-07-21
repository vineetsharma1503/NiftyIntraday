import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd

from upstoxapi import UpstoxApi


class _DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def to_dict(self):
        return self._payload


class _DummyOrderInstance:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def place_order(self, order_payload, api_version):
        self.calls.append((order_payload, api_version))
        return _DummyResponse(self.payload)

    def get_order_book(self, api_version):
        self.calls.append(('get_order_book', api_version))
        return _DummyResponse(self.payload)


class _DummyPositionInstance:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def get_positions(self, api_version):
        self.calls.append(('get_positions', api_version))
        if self.error is not None:
            raise self.error
        return _DummyResponse(self.payload)


class UpstoxApiOrderFallbackTests(unittest.TestCase):
    def _make_api(self):
        api = UpstoxApi.__new__(UpstoxApi)
        api.accessToken = 'test-token'
        api.api_version = '2.0'
        api._force_v2_order_api = False
        return api

    def test_use_v3_order_api_respects_force_v2_runtime_flag(self):
        api = self._make_api()
        with patch('upstoxapi.Config.STRATEGY_CONFIG', {'UPSTOX_ORDER_API_VERSION': 'v3'}):
            self.assertTrue(api._use_v3_order_api())
            api._force_v2_order_api = True
            self.assertFalse(api._use_v3_order_api())

    def test_place_order_falls_back_to_v2_on_static_ip_block(self):
        api = self._make_api()
        api.order_instance = _DummyOrderInstance({'status': 'success', 'data': {'order_id': 'v2-order-123'}})
        api._v3_request = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError('V3 API HTTP 403 Forbidden: {"errors":[{"errorCode":"UDAPI1154","message":"No static IP has been configured"}]}')
        )

        with patch('upstoxapi.Config.STRATEGY_CONFIG', {'UPSTOX_ORDER_API_VERSION': 'v3'}), \
             patch('upstoxapi.Config.ORDER_TYPE', 'I'), \
             patch('upstoxapi.Config.ORDER_TAG', 'TEST_TAG'):
            order_id = api.placeOrder(
                instrument_token='NFO_OPT|TEST',
                quantity=75,
                order_type='MARKET',
                transaction_type='SELL',
            )

        self.assertEqual(order_id, 'v2-order-123')
        self.assertTrue(api._force_v2_order_api)
        self.assertEqual(len(api.order_instance.calls), 1)

    def test_get_order_book_falls_back_to_v2_when_v3_route_missing(self):
        api = self._make_api()
        api.order_instance = _DummyOrderInstance({'status': 'success', 'data': [{'order_id': 'abc'}]})
        api._v3_request = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError('V3 API HTTP 404 Not Found: {"errors":[{"errorCode":"UDAPI100060","message":"Resource not Found."}]}')
        )

        with patch('upstoxapi.Config.STRATEGY_CONFIG', {'UPSTOX_ORDER_API_VERSION': 'v3'}):
            payload = api.getOrderBook()

        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get('status'), 'success')
        self.assertEqual(payload.get('data', [{}])[0].get('order_id'), 'abc')

    def test_init_points_sdk_clients_to_configured_v2_host(self):
        with patch('upstoxapi.Config.STRATEGY_CONFIG', {'SANDBOX_MODE': True}):
            api = UpstoxApi('test-token')

        self.assertEqual(api.order_instance.api_client.configuration.host, 'https://api-sandbox.upstox.com')
        self.assertEqual(api.position_instance.api_client.configuration.host, 'https://api-sandbox.upstox.com')
        self.assertEqual(api.quote_instance.api_client.configuration.host, 'https://api.upstox.com')
        self.assertEqual(api.histdata_instance.api_client.configuration.host, 'https://api.upstox.com')

    def test_quote_base_url_ignores_sandbox_mode(self):
        with patch('upstoxapi.Config.STRATEGY_CONFIG', {'SANDBOX_MODE': True}):
            api = self._make_api()

        self.assertEqual(api._get_v3_quote_base_url(), 'https://api.upstox.com')

    def test_get_position_book_uses_direct_v2_request_in_sandbox(self):
        api = self._make_api()
        api.position_instance = _DummyPositionInstance(error=AssertionError('SDK path should not be used in sandbox'))
        api._v2_request = lambda *_args, **_kwargs: {'status': 'success', 'data': [{'instrument_token': 'NFO_OPT|TEST'}]}

        with patch('upstoxapi.Config.is_sandbox_mode', return_value=True):
            payload = api.getPositionBook()

        self.assertEqual(payload.get('status'), 'success')
        self.assertEqual(payload.get('data', [{}])[0].get('instrument_token'), 'NFO_OPT|TEST')
        self.assertEqual(api.position_instance.calls, [])

    def test_get_position_book_falls_back_to_direct_v2_after_sdk_error(self):
        api = self._make_api()
        api.position_instance = _DummyPositionInstance(error=RuntimeError('invalid token on wrong host'))
        api._v2_request = lambda *_args, **_kwargs: {'status': 'success', 'data': [{'instrument_token': 'NFO_OPT|FALLBACK'}]}

        with patch('upstoxapi.Config.is_sandbox_mode', return_value=False):
            payload = api.getPositionBook()

        self.assertEqual(len(api.position_instance.calls), 1)
        self.assertEqual(payload.get('status'), 'success')
        self.assertEqual(payload.get('data', [{}])[0].get('instrument_token'), 'NFO_OPT|FALLBACK')

    def test_get_required_margin_prefers_required_margin_field(self):
        api = self._make_api()
        api.getMarginDetails = lambda _instruments: {
            'status': 'success',
            'data': {
                'required_margin': 123456.78,
                'final_margin': 120000.0,
                'margins': [{'total_margin': 119000.0}],
            },
        }

        with patch('upstoxapi.Config.ORDER_TYPE', 'I'):
            margin = api.getRequiredMargin('NFO_OPT|TEST', 75, transaction_type='SELL')

        self.assertAlmostEqual(margin, 123456.78)

    def test_custom_candle_data_uses_latest_wall_clock_closed_bucket(self):
        api = self._make_api()
        historical = pd.DataFrame([
            {'date': '2026-07-17 15:25:00+05:30', 'open': 24341.55, 'high': 24352.65, 'low': 24339.20, 'close': 24346.70, 'volume': 0, 'oi': 0},
        ])
        intraday = pd.DataFrame([
            {'date': '2026-07-20 13:00:00+05:30', 'open': 24186.70, 'high': 24189.35, 'low': 24179.90, 'close': 24185.20, 'volume': 0, 'oi': 0},
            {'date': '2026-07-20 13:01:00+05:30', 'open': 24185.55, 'high': 24186.55, 'low': 24175.80, 'close': 24179.85, 'volume': 0, 'oi': 0},
            {'date': '2026-07-20 13:02:00+05:30', 'open': 24180.15, 'high': 24196.45, 'low': 24178.05, 'close': 24194.30, 'volume': 0, 'oi': 0},
            {'date': '2026-07-20 13:05:00+05:30', 'open': 24185.55, 'high': 24186.55, 'low': 24175.80, 'close': 24179.85, 'volume': 0, 'oi': 0},
            {'date': '2026-07-20 13:06:00+05:30', 'open': 24180.15, 'high': 24190.00, 'low': 24178.05, 'close': 24188.00, 'volume': 0, 'oi': 0},
            {'date': '2026-07-20 13:07:00+05:30', 'open': 24188.00, 'high': 24196.45, 'low': 24185.00, 'close': 24194.30, 'volume': 0, 'oi': 0},
            {'date': '2026-07-20 13:10:00+05:30', 'open': 24180.15, 'high': 24210.00, 'low': 24178.05, 'close': 24200.00, 'volume': 0, 'oi': 0},
            {'date': '2026-07-20 13:11:00+05:30', 'open': 24200.00, 'high': 24226.00, 'low': 24199.50, 'close': 24225.00, 'volume': 0, 'oi': 0},
        ])

        api.getHistoricalData = lambda *_args, **_kwargs: historical.copy()
        api.getIntraData = lambda *_args, **_kwargs: intraday.copy()

        with patch('upstoxapi.Config.CANDLE_DATA_CACHE', {}, create=True), \
             patch('upstoxapi.datetime') as mock_datetime:
            mock_datetime.now.return_value = pd.Timestamp('2026-07-20 13:15:01', tz='Asia/Kolkata').to_pydatetime()
            candles = api.customCandleData('NSE_INDEX|Nifty 50', 5)

        self.assertEqual(candles.iloc[-1]['date'], pd.Timestamp('2026-07-20 13:10:00', tz='Asia/Kolkata'))

    def test_resample_data_stays_aligned_to_915_even_if_first_tick_is_916(self):
        api = self._make_api()
        source = pd.DataFrame([
            {'date': '2026-07-20 09:16:00+05:30', 'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.5, 'volume': 1, 'oi': 0},
            {'date': '2026-07-20 09:17:00+05:30', 'open': 100.5, 'high': 102.0, 'low': 100.0, 'close': 101.5, 'volume': 1, 'oi': 0},
            {'date': '2026-07-20 09:18:00+05:30', 'open': 101.5, 'high': 103.0, 'low': 101.0, 'close': 102.5, 'volume': 1, 'oi': 0},
            {'date': '2026-07-20 09:19:00+05:30', 'open': 102.5, 'high': 104.0, 'low': 102.0, 'close': 103.5, 'volume': 1, 'oi': 0},
        ])

        resampled = api._resample_data(source, 5)

        self.assertEqual(resampled.iloc[0]['date'], pd.Timestamp('2026-07-20 09:15:00', tz='Asia/Kolkata'))


if __name__ == '__main__':
    unittest.main()

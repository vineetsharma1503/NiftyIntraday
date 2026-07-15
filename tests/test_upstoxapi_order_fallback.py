import unittest
from unittest.mock import patch

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
        with patch('upstoxapi.Config.get_upstox_v2_base_url', return_value='https://api-sandbox.upstox.com'):
            api = UpstoxApi('test-token')

        self.assertEqual(api.position_instance.api_client.configuration.host, 'https://api-sandbox.upstox.com')

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


if __name__ == '__main__':
    unittest.main()

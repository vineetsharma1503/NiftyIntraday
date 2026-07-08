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


if __name__ == '__main__':
    unittest.main()

# ============================================================================
# UPSTOX API WRAPPER FOR STRATEGY3 - EMA CROSSOVER STRATEGY
# ============================================================================

import math
import json
from datetime import datetime, time, timedelta
from time import sleep
from urllib import parse, request
from urllib.error import HTTPError, URLError
import pandas as pd
import upstox_client
from upstox_client.rest import ApiException
from logger import logger
import Config


class UpstoxApi:
    """Simplified Upstox API wrapper for options trading"""
    
    def __init__(self, accessToken, api_version='2.0'):
        self.accessToken = accessToken
        self.api_version = api_version
        self._force_v2_order_api = False
        configuration = upstox_client.Configuration()
        configuration.access_token = accessToken
        configuration.host = Config.get_upstox_v2_base_url()

        self.order_instance = upstox_client.OrderApi(upstox_client.ApiClient(configuration))
        self.position_instance = upstox_client.PortfolioApi(upstox_client.ApiClient(configuration))
        self.quote_instance = upstox_client.MarketQuoteApi(upstox_client.ApiClient(configuration))
        self.histdata_instance = upstox_client.HistoryApi(upstox_client.ApiClient(configuration))

    def _use_v3_order_api(self):
        """Return True when order APIs should be called via Upstox V3 endpoints."""
        if self._force_v2_order_api:
            return False
        version = str(Config.STRATEGY_CONFIG.get('UPSTOX_ORDER_API_VERSION', 'v2')).lower()
        return version == 'v3'

    def _is_v3_static_ip_restriction(self, err):
        """Return True when v3 order call is blocked by static IP restriction policy."""
        message = str(err).lower()
        return 'udapi1154' in message or 'static ip restriction' in message or 'no static ip has been configured' in message

    def _use_v3_quote_api(self):
        """Return True when quote APIs should be called via Upstox V3 endpoints."""
        version = str(Config.STRATEGY_CONFIG.get('UPSTOX_QUOTE_API_VERSION', 'v2')).lower()
        return version == 'v3'

    def _get_v3_base_url(self):
        """Resolve V3 order API base URL for sandbox/live usage."""
        return Config.get_upstox_v3_order_base_url()

    def _get_v2_base_url(self):
        """Resolve V2 REST API base URL for sandbox/live usage."""
        return Config.get_upstox_v2_base_url()

    def _get_v3_quote_base_url(self):
        """Resolve V3 quote API base URL."""
        return Config.get_upstox_v3_quote_base_url()

    def _v3_request(self, method, path, payload=None, query_params=None, base_url=None):
        """Perform an authenticated HTTP call to the Upstox V3 API."""
        resolved_base_url = base_url or self._get_v3_base_url()
        url = f"{resolved_base_url}{path}"
        if query_params:
            url = f"{url}?{parse.urlencode(query_params)}"

        body = None
        if payload is not None:
            body = json.dumps(payload).encode('utf-8')

        req = request.Request(
            url,
            data=body,
            method=method,
            headers={
                'Authorization': f'Bearer {self.accessToken}',
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
                'Connection': 'keep-alive',
                'Cache-Control': 'no-cache',
            },
        )

        try:
            with request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode('utf-8')
                return json.loads(raw) if raw else {}
        except HTTPError as err:
            error_body = err.read().decode('utf-8', errors='replace')
            raise RuntimeError(f'V3 API HTTP {err.code} {err.reason}: {error_body}') from err
        except URLError as err:
            raise RuntimeError(f'V3 API connection error: {err}') from err

    def _v2_request(self, method, path, payload=None, query_params=None, base_url=None):
        """Perform an authenticated HTTP call to the Upstox V2 API."""
        resolved_base_url = base_url or self._get_v2_base_url()
        url = f"{resolved_base_url}{path}"
        if query_params:
            url = f"{url}?{parse.urlencode(query_params)}"

        body = None
        if payload is not None:
            body = json.dumps(payload).encode('utf-8')

        req = request.Request(
            url,
            data=body,
            method=method,
            headers={
                'Authorization': f'Bearer {self.accessToken}',
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Api-Version': self.api_version,
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
                'Connection': 'keep-alive',
                'Cache-Control': 'no-cache',
            },
        )

        try:
            with request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode('utf-8')
                return json.loads(raw) if raw else {}
        except HTTPError as err:
            error_body = err.read().decode('utf-8', errors='replace')
            try:
                parsed = json.loads(error_body) if error_body else {}
            except Exception:
                parsed = {}

            if not isinstance(parsed, dict):
                parsed = {}

            parsed.setdefault('status', 'error')
            parsed.setdefault('data', [])
            parsed.setdefault('errors', [{
                'errorCode': f'HTTP_{err.code}',
                'message': error_body or err.reason,
            }])
            parsed['http_status'] = err.code
            parsed['source'] = 'v2_rest'
            return parsed
        except URLError as err:
            raise RuntimeError(f'V2 API connection error: {err}') from err

    
    def truncate(self, price):
        """Truncate price to valid tick size (0.05)"""
        if price is None or price == 0:
            return price
        price = round(price / 0.05) * 0.05
        return round(price, 2)

    
    def placeOrder(self, instrument_token, quantity, order_type, transaction_type, 
                   product=None, price=0, trigger_price=0):
        """Place order with Upstox"""
        try:
            if product is None:
                product = Config.ORDER_TYPE
                
            order_payload = {
                "quantity": quantity,
                "product": product,
                "price": self.truncate(price),
                "instrument_token": instrument_token,
                "order_type": order_type,
                "transaction_type": transaction_type,
                "trigger_price": self.truncate(trigger_price),
                "tag": Config.ORDER_TAG,
                "disclosed_quantity": 0,
                "validity": "DAY",
                "is_amo": False
            }

            if self._use_v3_order_api():
                v3_payload = dict(order_payload)
                v3_payload['slice'] = False
                v3_payload['market_protection'] = -1
                try:
                    order_response = self._v3_request('POST', '/v3/order/place', payload=v3_payload)
                    logger.info(f"V3 order request: {v3_payload} | Response: {order_response}")
                    if order_response.get('status') == 'success':
                        order_ids = order_response.get('data', {}).get('order_ids', [])
                        if order_ids:
                            return order_ids[0]
                except RuntimeError as v3_err:
                    if self._is_v3_static_ip_restriction(v3_err):
                        self._force_v2_order_api = True
                        logger.warning(
                            'V3 order API blocked by static IP policy; falling back to v2 order API for this session. Error: %s',
                            v3_err,
                        )
                    else:
                        raise

            if not self._use_v3_order_api():
                order_response = self.order_instance.place_order(order_payload, self.api_version).to_dict()
                logger.info(f"Order placed: {order_payload} | Response: {order_response}")

                if order_response['status'] == 'success':
                    return order_response['data']['order_id']
            else:
                logger.error('Order placement failed: v3 enabled but no order_id returned from Upstox response')
                
        except ApiException as e:
            logger.exception(f"API Exception in order placement: {e}")
        except Exception as e:
            logger.exception(f"Error in order placement: {e}")
        return None

    # ============================================================================
    # ORDER & POSITION MANAGEMENT
    # ============================================================================
    
    def getOrderBook(self):
        """Get order book"""
        try:
            if self._use_v3_order_api():
                try:
                    return self._v3_request('GET', '/v3/order/retrieve-all')
                except RuntimeError as v3_err:
                    # Some accounts/environments do not expose this v3 route.
                    msg = str(v3_err).lower()
                    if '404' in msg or 'resource not found' in msg or 'udapi100060' in msg:
                        logger.warning('V3 order book endpoint unavailable; falling back to v2 order book API. Error: %s', v3_err)
                    else:
                        raise
            order_book_response = self.order_instance.get_order_book(self.api_version)
            return order_book_response.to_dict()
        except Exception as e:
            logger.exception(f'Error fetching order book: {e}')
        return None

    
    def getPositionBook(self):
        """Get position book"""
        try:
            if Config.is_sandbox_mode():
                position_book = self._v2_request('GET', '/v2/portfolio/short-term-positions')
                if isinstance(position_book, dict) and str(position_book.get('status', '')).lower() == 'error':
                    logger.warning('Sandbox positions endpoint returned error payload: %s', position_book)
                return position_book

            position_book = self.position_instance.get_positions(self.api_version)
            return position_book.to_dict()
        except Exception as e:
            logger.warning('SDK positions fetch failed; retrying via direct v2 REST call. Error: %s', e)
            try:
                position_book = self._v2_request('GET', '/v2/portfolio/short-term-positions')
                if isinstance(position_book, dict) and str(position_book.get('status', '')).lower() == 'error':
                    logger.warning('V2 REST positions fallback returned error payload: %s', position_book)
                return position_book
            except Exception as fallback_exc:
                logger.exception(f'Error fetching positions: {fallback_exc}')
        return None

    
    def isAllOrderTraded(self, order_list):
        """Check if all orders are executed"""
        try:
            order_book = self.getOrderBook()
            if not order_book:
                return False, None

            data = order_book.get('data', []) if isinstance(order_book, dict) else []
            order_df = pd.DataFrame(data)
            if order_df.empty:
                return False, order_df

            if 'order_id' not in order_df.columns:
                return False, order_df

            filtered_orders = order_df[order_df['order_id'].isin(order_list)]

            if len(filtered_orders) == 0:
                return False, filtered_orders

            status_col = filtered_orders['status'].astype(str).str.upper() if 'status' in filtered_orders.columns else pd.Series([], dtype=str)
            if not status_col.empty and status_col.isin({'COMPLETE', 'COMPLETED', 'TRADED', 'FILLED'}).all():
                return True, filtered_orders

            if {'filled_quantity', 'quantity'}.issubset(filtered_orders.columns):
                filled = pd.to_numeric(filtered_orders['filled_quantity'], errors='coerce').fillna(0)
                qty = pd.to_numeric(filtered_orders['quantity'], errors='coerce').fillna(0)
                return bool((filled >= qty).all()), filtered_orders

            return False, filtered_orders
            
        except Exception as e:
            logger.exception(f'Error checking order status: {e}')
        return False, None

    
    def placeMultipleOrder(self, instrument_key, qty, trans_type, order_type):
        """Place order (wrapper for placeOrder)"""
        return self.placeOrder(instrument_key, qty, order_type, trans_type)

    
    def closePosition(self, instrument_key, qty, trans_type=None):
        """Close existing position"""
        try:
            pos_info = self.getPositionBook()
            if not pos_info:
                return None
                
            for position in pos_info['data']:
                token = position['instrument_token']
                net_qty = int(position['quantity'])
                
                if token == instrument_key and net_qty != 0:
                    transaction_type = 'SELL' if net_qty > 0 else 'BUY'
                    return self.placeMultipleOrder(token, abs(net_qty), transaction_type, 'MARKET')
                    
        except Exception as e:
            logger.exception(f'Error closing position: {e}')
        return None

    
    def exit_all(self):
        """Exit all positions"""
        try:
            pos_info = self.getPositionBook()
            if not pos_info:
                return
                
            for position in pos_info['data']:
                try:
                    token = position['instrument_token']
                    net_qty = int(position['quantity'])
                    
                    if net_qty != 0:
                        transaction_type = 'SELL' if net_qty > 0 else 'BUY'
                        self.placeMultipleOrder(token, abs(net_qty), transaction_type, 'MARKET')
                        
                except Exception as e:
                    logger.exception(f'Error closing position for {token}: {e}')
                    
        except Exception as e:
            logger.exception(f'Error in exit_all: {e}')

    # ============================================================================
    # MARKET DATA & QUOTES
    # ============================================================================

    
    def getLTP(self, instrument_key):
        """Get Last Traded Price"""
        try:
            if self._use_v3_quote_api():
                quote_data = self._v3_request(
                    'GET',
                    '/v3/market-quote/ohlc',
                    query_params={
                        'instrument_key': instrument_key,
                        'interval': 'I1',
                    },
                    base_url=self._get_v3_quote_base_url(),
                )
                logger.debug(f"V3 quote_data for {instrument_key}: {quote_data}")

                data = quote_data.get('data', {}) if isinstance(quote_data, dict) else {}
                if not isinstance(data, dict) or not data:
                    logger.error('No quote data returned for %s from V3 quote API', instrument_key)
                    return None

                if instrument_key in data and isinstance(data[instrument_key], dict) and 'last_price' in data[instrument_key]:
                    return float(data[instrument_key]['last_price'])

                colon_key = instrument_key.replace('|', ':')
                if colon_key in data and isinstance(data[colon_key], dict) and 'last_price' in data[colon_key]:
                    return float(data[colon_key]['last_price'])

                for entry in data.values():
                    if not isinstance(entry, dict):
                        continue
                    if str(entry.get('instrument_token')) == instrument_key and 'last_price' in entry:
                        return float(entry['last_price'])

                for entry in data.values():
                    if isinstance(entry, dict) and 'last_price' in entry:
                        return float(entry['last_price'])

                logger.error('Instrument key %s not found in V3 quote response data keys=%s', instrument_key, list(data.keys()))
                return None

            quote_response = self.quote_instance.get_full_market_quote(instrument_key, self.api_version)
            quote_data = quote_response.to_dict()
            logger.debug(f"Full quote_data for {instrument_key}: {quote_data}")
            if 'data' in quote_data and instrument_key in quote_data['data']:
                return float(quote_data['data'][instrument_key]['last_price'])
            elif 'data' in quote_data:
                for entry in quote_data['data'].values():
                    if str(entry.get('instrument_token')) == instrument_key:
                        return float(entry['last_price'])
                logger.error(f"Instrument token {instrument_key} not found in quote_data['data'].")
            else:
                logger.error(f"Instrument key {instrument_key} not found in quote_data['data'].")
        except Exception as e:
            logger.exception(f'Error fetching LTP: {e}')
        return None

    
    @staticmethod
    def _coerce_candle_frame(payload):
        """Normalize candle payloads from the Upstox API into a DataFrame."""
        if payload is None:
            return None

        if isinstance(payload, pd.DataFrame):
            candle_data = payload.copy()
        elif isinstance(payload, dict):
            data = payload.get('data', payload)
            if isinstance(data, dict) and 'candles' in data:
                data = data['candles']
            elif isinstance(data, dict) and 'data' in data:
                data = data['data']
            candle_data = pd.DataFrame(data)
        else:
            candle_data = pd.DataFrame(payload)

        if candle_data.empty:
            return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'oi'])

        if len(candle_data.columns) >= 7:
            candle_data.columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'oi']
        elif len(candle_data.columns) == 6:
            candle_data.columns = ['date', 'open', 'high', 'low', 'close', 'volume']
            candle_data['oi'] = 0
        else:
            return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'oi'])

        if 'date' in candle_data.columns:
            candle_data['date'] = pd.to_datetime(candle_data['date'], errors='coerce')
            candle_data = candle_data.dropna(subset=['date'])
            if not candle_data.empty:
                candle_data = candle_data.sort_values(by='date')
                candle_data['date'] = candle_data['date'].dt.tz_convert('Asia/Kolkata') if candle_data['date'].dt.tz is not None else candle_data['date'].dt.tz_localize('Asia/Kolkata')
        return candle_data

    def getIntraData(self, instrument_key, interval='1minute'):
        """Get intraday candle data"""
        try:
            intra_data_response = self.histdata_instance.get_intra_day_candle_data(
                instrument_key, interval, self.api_version)
            if intra_data_response is None:
                return None
            payload = intra_data_response.to_dict() if hasattr(intra_data_response, 'to_dict') else intra_data_response
            candle_data = self._coerce_candle_frame(payload)
            if candle_data is None or candle_data.empty:
                return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'oi'])
            return candle_data
            
        except Exception as e:
            logger.exception(f'Error fetching intraday data: {e}')
        return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'oi'])

    
    def getHistoricalData(self, instrument_key, to_date, from_date, interval='minutes'):
        """Get historical candle data"""
        try:
            hist_data_response = self.histdata_instance.get_historical_candle_data1(
                instrument_key, interval, to_date, from_date, self.api_version)
            if hist_data_response is None:
                return None
            payload = hist_data_response.to_dict() if hasattr(hist_data_response, 'to_dict') else hist_data_response
            candle_data = self._coerce_candle_frame(payload)
            if candle_data is None or candle_data.empty:
                return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'oi'])
            return candle_data
            
        except Exception as e:
            logger.exception(f'Error fetching historical data: {e}')
        return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'oi'])

    
    @staticmethod
    def _normalize_timeframe(timeframe):
        """Convert a timeframe value to a pandas-compatible frequency string."""
        if timeframe is None:
            return '1min'

        if isinstance(timeframe, str):
            value = timeframe.strip().lower()
            if value in {'t', 'min', 'minute', 'minutes', '1min', '1minute'}:
                return 'min'
            if value.endswith('t') and value[:-1].isdigit():
                return f"{value[:-1]}min"
            if value.endswith('min') or value.endswith('minute') or value.endswith('minutes'):
                return value
            return value

        if isinstance(timeframe, int):
            return 'min' if timeframe == 1 else f'{timeframe}min'

        return str(timeframe)

    def customCandleData(self, instrument_key, timeframe):
        """Get custom timeframe candle data for strategy"""
        try:
            # Get cached or fresh historical data
            if instrument_key in Config.CANDLE_DATA_CACHE:
                hist_df = Config.CANDLE_DATA_CACHE[instrument_key]
            else:
                today = datetime.now(Config.TIME_ZONE).date()
                to_date = (today - timedelta(days=1)).strftime('%Y-%m-%d')
                from_date = (today - timedelta(days=5)).strftime('%Y-%m-%d')
                
                # Upstox historical candles only support 1minute/30minute/day/week/month.
                hist_data = self.getHistoricalData(instrument_key, to_date, from_date, interval='1minute')
                if hist_data is None:
                    hist_data = pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'oi'])

                hist_df = hist_data if timeframe == 1 else self._resample_data(hist_data, timeframe)
                Config.CANDLE_DATA_CACHE[instrument_key] = hist_df

            # Get today's intraday data
            # Upstox intraday candles only support 1minute/30minute.
            intra_data = self.getIntraData(instrument_key, '1minute')
            if intra_data is not None and not intra_data.empty:
                intra_df = intra_data if timeframe == 1 else self._resample_data(intra_data, timeframe)
                final_data = pd.concat([hist_df, intra_df], ignore_index=True)
            else:
                final_data = hist_df

            if 'date' not in final_data.columns:
                if final_data.index.name == 'date':
                    final_data = final_data.reset_index()
                else:
                    logger.error('Custom candle data is missing a date column after resampling')
                    return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'oi'])

            final_data['date'] = pd.to_datetime(final_data['date'], errors='coerce', utc=True).dt.tz_convert('Asia/Kolkata')
            final_data = final_data.dropna(subset=['date'])

            # Filter to last complete candle
            current_time = datetime.now(Config.TIME_ZONE)
            start_time = current_time.replace(hour=9, minute=15, second=0)
            min_from_start = math.floor((current_time - start_time).seconds / 60)
            last_tf = int(min_from_start / timeframe) * timeframe - timeframe
            last_timestamp = start_time + timedelta(minutes=last_tf)
            
            final_data = final_data[final_data['date'] <= last_timestamp]
            return final_data.sort_values(by='date').reset_index(drop=True)
            
        except Exception as e:
            logger.exception(f'Error in custom candle data: {e}')
        return pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'oi'])

    
    def _resample_data(self, data, timeframe):
        """Resample data to specified timeframe"""
        try:
            data = data.copy()
            if 'date' not in data.columns:
                if data.index.name == 'date':
                    data = data.reset_index()
                else:
                    logger.error('Resample input is missing a date column')
                    return data

            data['date'] = pd.to_datetime(data['date'])
            data = data.dropna(subset=['date'])

            # Filter market hours
            data = data[(data['date'].dt.time > time(9, 14)) & (data['date'].dt.time < time(15, 30))]
            if data.empty:
                return data

            data.set_index('date', inplace=True)

            # Resample data
            freq = self._normalize_timeframe(timeframe)
            resampled = data.resample(freq, origin='start').agg({
                'open': 'first', 
                'high': 'max', 
                'low': 'min', 
                'close': 'last',
                'volume': 'sum',
                'oi': 'last'
            })
            
            resampled.reset_index(inplace=True)
            return resampled.dropna()
            
        except Exception as e:
            logger.exception(f'Error resampling data: {e}')
        return data

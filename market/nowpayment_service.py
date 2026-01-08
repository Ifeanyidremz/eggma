from django.conf import settings
import requests
import logging
import json
import hmac
import hashlib

logger = logging.getLogger(__name__)

class NowPaymentsService:
    def __init__(self):
        self.api_key = settings.NOWPAYMENTS_API_KEY
        self.api_url = settings.NOWPAYMENTS_API_URL
        self.ipn_secret = settings.NOWPAYMENTS_IPN_SECRET
        
        if not self.api_key:
            raise ValueError("NOWPAYMENTS_API_KEY not found in environment variables")
        
        self.headers = {
            'x-api-key': self.api_key,
            'Content-Type': 'application/json'
        }

    def get_available_currencies(self):
        try:
            url = f"{self.api_url}/currencies"
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting currencies: {str(e)}")
            return {'currencies': ['btc', 'eth', 'usdt', 'ltc', 'trx']}

    def get_minimum_payment_amount(self, currency_from, currency_to='usd'):
        try:
            url = f"{self.api_url}/min-amount"
            params = {
                'currency_from': currency_from,
                'currency_to': currency_to
            }
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting min amount: {str(e)}")
            return {'min_amount': 5}

    def create_payment(self, price_amount, price_currency, pay_currency, order_id, ipn_callback_url):
        """
        Create payment with enhanced error handling
        """
        try:
            url = f"{self.api_url}/payment"
            
            # FIXED: Ensure all fields are correct types and format
            data = {
                'price_amount': float(price_amount),
                'price_currency': str(price_currency).lower(),
                'pay_currency': str(pay_currency).lower(),
                'order_id': str(order_id),
                'ipn_callback_url': str(ipn_callback_url),
            }
            
            # Log the request (without exposing API key)
            logger.info(f"Creating NowPayments payment: {data}")
            logger.info(f"API URL: {url}")
            
            response = requests.post(url, headers=self.headers, json=data, timeout=30)
            
            # CRITICAL: Log the response BEFORE raising exception
            logger.info(f"NowPayments response status: {response.status_code}")
            logger.info(f"NowPayments response headers: {dict(response.headers)}")
            logger.info(f"NowPayments response body: {response.text}")
            
            # Try to parse error from response body
            if response.status_code != 200:
                try:
                    error_data = response.json()
                    error_message = error_data.get('message', error_data.get('error', 'Unknown error'))
                    logger.error(f"NowPayments API error details: {error_message}")
                    logger.error(f"Full error response: {json.dumps(error_data, indent=2)}")
                    
                    # Return error instead of raising
                    return {
                        'success': False,
                        'error': error_message,
                        'status_code': response.status_code,
                        'details': error_data
                    }
                except json.JSONDecodeError:
                    logger.error(f"Could not parse error response: {response.text}")
                    return {
                        'success': False,
                        'error': f'HTTP {response.status_code}: {response.text}',
                        'status_code': response.status_code
                    }
            
            # Success - parse and return
            result = response.json()
            logger.info(f"Payment created successfully: {result.get('payment_id')}")
            return result
            
        except requests.exceptions.Timeout:
            logger.error("NowPayments API timeout")
            return {
                'success': False,
                'error': 'Request timeout - NowPayments API is not responding'
            }
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error: {str(e)}")
            return {
                'success': False,
                'error': 'Cannot connect to NowPayments API'
            }
        except Exception as e:
            logger.error(f"Unexpected error creating payment: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def create_payout(self, address, amount, currency, ipn_callback_url=None):
        try:
            url = f"{self.api_url}/payout"
            data = {
                'withdrawals': [{
                    'address': address,
                    'currency': currency,
                    'amount': float(amount),
                    'ipn_callback_url': ipn_callback_url
                }]
            }
            
            logger.info(f"Creating NowPayments payout: {data}")
            response = requests.post(url, headers=self.headers, json=data, timeout=30)
            
            # Log response before raising
            logger.info(f"Payout response status: {response.status_code}")
            logger.info(f"Payout response body: {response.text}")
            
            if response.status_code != 200:
                try:
                    error_data = response.json()
                    logger.error(f"Payout error: {error_data}")
                    return {
                        'success': False,
                        'error': error_data.get('message', 'Payout failed')
                    }
                except:
                    return {
                        'success': False,
                        'error': f'HTTP {response.status_code}: {response.text}'
                    }
            
            result = response.json()
            return result
            
        except Exception as e:
            logger.error(f"Error creating payout: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def get_payment_status(self, payment_id):
        try:
            url = f"{self.api_url}/payment/{payment_id}"
            response = requests.get(url, headers=self.headers, timeout=10)
            
            logger.info(f"Payment status response: {response.status_code}")
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get payment status: {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting payment status: {str(e)}")
            return None

    def verify_ipn(self, request_data, signature):
        if not self.ipn_secret:
            raise ValueError("NOWPAYMENTS_IPN_SECRET not found")
        
        sorted_data = json.dumps(request_data, sort_keys=True, separators=(',', ':'))
        expected_signature = hmac.new(
            self.ipn_secret.encode('utf-8'),
            sorted_data.encode('utf-8'),
            hashlib.sha512
        ).hexdigest()
        
        return hmac.compare_digest(expected_signature, signature)

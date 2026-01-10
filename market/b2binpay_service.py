import requests
import logging
import hmac
import hashlib
import time
from decimal import Decimal
from django.conf import settings
from typing import Dict, Optional
import json

logger = logging.getLogger(__name__)


class B2BinPayService:
    """
    B2BinPay API v3 integration for crypto payments
    Supports deposits and wallet management
    """
    
    def __init__(self):
        # API Configuration
        self.base_url = getattr(settings, 'B2BINPAY_BASE_URL', 'https://v3.api-sandbox.b2binpay.com/')
        self.client_id = getattr(settings, 'B2BINPAY_CLIENT_ID', '')
        self.client_secret = getattr(settings, 'B2BINPAY_CLIENT_SECRET', '')
        self.callback_secret = getattr(settings, 'B2BINPAY_CALLBACK_SECRET', '')
        
        if not self.client_id or not self.client_secret:
            raise ValueError("B2BinPay credentials not configured in settings")
        
        # Token management
        self._access_token = None
        self._token_expires_at = 0
    
    def _get_access_token(self) -> str:
        """
        Get OAuth 2.0 access token (cached for ~1 hour)
        """
        current_time = time.time()
        
        # Return cached token if still valid
        if self._access_token and current_time < self._token_expires_at:
            return self._access_token
        
        # Request new token
        try:
            url = f"{self.base_url}/token/"
            headers = {
                'Content-Type': 'application/vnd.api+json'
            }
            
            payload = {
                "data": {
                    "type": "auth-token",
                    "attributes": {
                        "client_id": self.client_id,
                        "client_secret": self.client_secret
                    }
                }
            }
            
            logger.info("Requesting B2BinPay access token...")
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"Token request failed: {response.status_code} - {response.text}")
                raise Exception(f"Failed to get access token: {response.status_code}")
            
            result = response.json()
            token_data = result.get('data', {}).get('attributes', {})
            
            self._access_token = token_data.get('access')
            expires_in = token_data.get('expires_in', 3599)
            
            # Cache token (subtract 60s as safety margin)
            self._token_expires_at = current_time + expires_in - 60
            
            logger.info("Successfully obtained B2BinPay access token")
            return self._access_token
            
        except Exception as e:
            logger.error(f"Error getting B2BinPay token: {e}", exc_info=True)
            raise
    
    def _make_request(self, method: str, endpoint: str, data: dict = None) -> dict:
        """
        Make authenticated API request
        """
        try:
            token = self._get_access_token()
            url = f"{self.base_url}/{endpoint.lstrip('/')}"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/vnd.api+json'
            }
            
            logger.info(f"B2BinPay API Request: {method} {endpoint}")
            
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, params=data, timeout=30)
            elif method.upper() == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=30)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            logger.info(f"B2BinPay Response Status: {response.status_code}")
            
            if response.status_code not in [200, 201]:
                logger.error(f"API Error: {response.text}")
                return {
                    'success': False,
                    'error': f'API returned status {response.status_code}',
                    'details': response.text
                }
            
            return response.json()
            
        except requests.exceptions.Timeout:
            logger.error("B2BinPay API timeout")
            return {'success': False, 'error': 'Request timeout'}
        except Exception as e:
            logger.error(f"B2BinPay API error: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    def get_wallets(self, wallet_type: Optional[int] = None, currency_id: Optional[str] = None) -> Dict:
        """
        Get list of wallets
        wallet_type: 1=Merchant, 2=Enterprise, 3=Custody, 4=NFT, 5=Swap
        """
        try:
            params = {}
            
            if wallet_type:
                params['filter[wallet_type]'] = wallet_type
            
            if currency_id:
                params['filter[currency]'] = currency_id
            
            result = self._make_request('GET', '/wallet/', params)
            
            if result.get('data'):
                wallets = result.get('data', [])
                return {
                    'success': True,
                    'wallets': wallets,
                    'count': len(wallets) if isinstance(wallets, list) else 1
                }
            
            return {
                'success': False,
                'error': 'No wallets found or API error',
                'details': result
            }
            
        except Exception as e:
            logger.error(f"Error fetching wallets: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_wallet_by_id(self, wallet_id: str) -> Dict:
        """
        Get specific wallet details
        """
        try:
            result = self._make_request('GET', f'/wallet/{wallet_id}')
            
            if result.get('data'):
                wallet_data = result['data']
                attributes = wallet_data.get('attributes', {})
                
                return {
                    'success': True,
                    'wallet_id': wallet_data.get('id'),
                    'label': attributes.get('label'),
                    'balance_confirmed': Decimal(attributes.get('balance_confirmed', '0')),
                    'balance_pending': Decimal(attributes.get('balance_pending', '0')),
                    'status': attributes.get('status'),
                    'type': attributes.get('type'),
                    'destination': attributes.get('destination', {})
                }
            
            return {'success': False, 'error': 'Wallet not found'}
            
        except Exception as e:
            logger.error(f"Error fetching wallet {wallet_id}: {e}")
            return {'success': False, 'error': str(e)}
    
    def create_deposit(
        self,
        wallet_id: str,
        amount: Decimal,
        user_id: str,
        callback_url: str,
        tracking_id: Optional[str] = None
    ) -> Dict:
        """
        Create a deposit (generates unique payment address)
        
        NOTE: This creates a deposit address for users to send crypto to.
        The actual wallet must be created via B2BinPay Web UI.
        """
        try:
            if not tracking_id:
                tracking_id = f"user_{user_id}_{int(time.time())}"
            
            payload = {
                "data": {
                    "type": "deposit",
                    "attributes": {
                        "label": f"Deposit for user {user_id}",
                        "tracking_id": tracking_id,
                        "callback_url": callback_url,
                        "confirmations_needed": 2
                    },
                    "relationships": {
                        "wallet": {
                            "data": {
                                "type": "wallet",
                                "id": str(wallet_id)
                            }
                        }
                    }
                }
            }
            
            logger.info(f"Creating deposit for wallet {wallet_id}, tracking_id: {tracking_id}")
            
            result = self._make_request('POST', '/deposit/', payload)
            
            if result.get('data'):
                deposit_data = result['data']
                attributes = deposit_data.get('attributes', {})
                
                return {
                    'success': True,
                    'deposit_id': deposit_data.get('id'),
                    'address': attributes.get('address'),
                    'currency': attributes.get('currency'),
                    'tracking_id': tracking_id,
                    'status': attributes.get('status'),
                    'callback_url': callback_url
                }
            
            return {
                'success': False,
                'error': result.get('error', 'Failed to create deposit'),
                'details': result
            }
            
        except Exception as e:
            logger.error(f"Error creating deposit: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    def get_deposit_status(self, deposit_id: str) -> Dict:
        """
        Check deposit status
        """
        try:
            result = self._make_request('GET', f'/deposit/{deposit_id}')
            
            if result.get('data'):
                deposit_data = result['data']
                attributes = deposit_data.get('attributes', {})
                
                return {
                    'success': True,
                    'deposit_id': deposit_data.get('id'),
                    'status': attributes.get('status'),
                    'amount': attributes.get('amount'),
                    'tracking_id': attributes.get('tracking_id'),
                    'address': attributes.get('address')
                }
            
            return {'success': False, 'error': 'Deposit not found'}
            
        except Exception as e:
            logger.error(f"Error checking deposit {deposit_id}: {e}")
            return {'success': False, 'error': str(e)}
    
    def verify_callback(self, callback_data: dict, signature: str) -> bool:
        """
        Verify B2BinPay callback signature using HMAC-SHA256
        
        For deposit callbacks, concatenate:
        transfer.status + transfer.amount + deposit.tracking_id + meta.time
        """
        try:
            if not self.callback_secret:
                logger.error("Callback secret not configured")
                return False
            
            # Extract callback components
            included = callback_data.get('included', [])
            meta = callback_data.get('meta', {})
            deposit = callback_data.get('data', {}).get('attributes', {})
            
            # Find transfer in included array
            transfer = None
            for item in included:
                if item.get('type') == 'transfer':
                    transfer = item.get('attributes', {})
                    break
            
            if not transfer:
                logger.error("Transfer data not found in callback")
                return False
            
            # Build verification string
            status = str(transfer.get('status', ''))
            amount = str(transfer.get('amount', ''))
            tracking_id = str(deposit.get('tracking_id', ''))
            callback_time = str(meta.get('time', ''))
            
            message = status + amount + tracking_id + callback_time
            
            logger.info(f"Verification message: {message}")
            
            # Calculate HMAC-SHA256
            expected_signature = hmac.new(
                self.callback_secret.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            is_valid = hmac.compare_digest(expected_signature, signature)
            
            if not is_valid:
                logger.error(f"Signature mismatch. Expected: {expected_signature}, Got: {signature}")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error verifying callback: {e}", exc_info=True)
            return False
    
    def get_supported_currencies(self) -> Dict:
        """
        Get list of supported cryptocurrencies
        """
        try:
            result = self._make_request('GET', '/currency/')
            
            if result.get('data'):
                currencies = []
                for currency in result['data']:
                    attributes = currency.get('attributes', {})
                    currencies.append({
                        'id': currency.get('id'),
                        'code': attributes.get('code'),
                        'name': attributes.get('name'),
                        'precision': attributes.get('precision'),
                        'min_deposit': attributes.get('min_deposit_amount'),
                        'min_withdrawal': attributes.get('min_withdrawal_amount')
                    })
                
                return {
                    'success': True,
                    'currencies': currencies
                }
            
            return {'success': False, 'error': 'No currencies found'}
            
        except Exception as e:
            logger.error(f"Error fetching currencies: {e}")
            return {'success': False, 'error': str(e)}


class VirtualWalletService:
    """
    Virtual wallet management service
    Manages user internal balances separate from blockchain wallets
    """
    
    @staticmethod
    def create_user_wallet(user):
        """
        Create virtual wallet for user (happens automatically on signup)
        The 'balance' field on CustomUser IS the virtual wallet
        """
        from acounts.models import CustomUser
        
        if not hasattr(user, 'balance'):
            user.balance = Decimal('0.00')
            user.save(update_fields=['balance'])
        
        logger.info(f"Virtual wallet initialized for user {user.username}")
        return {'success': True, 'balance': user.balance}
    
    @staticmethod
    def get_wallet_balance(user) -> Decimal:
        """Get user's virtual wallet balance"""
        return user.balance
    
    @staticmethod
    def credit_wallet(user, amount: Decimal, description: str, transaction_type: str = 'deposit') -> Dict:
        """
        Add funds to user's virtual wallet
        """
        from predict.models import Transaction
        from django.db import transaction as db_transaction
        
        try:
            with db_transaction.atomic():
                user_locked = type(user).objects.select_for_update().get(id=user.id)
                
                old_balance = user_locked.balance
                user_locked.balance += amount
                user_locked.save(update_fields=['balance'])
                
                # Create transaction record
                txn = Transaction.objects.create(
                    user=user_locked,
                    transaction_type=transaction_type,
                    amount=amount,
                    balance_before=old_balance,
                    balance_after=user_locked.balance,
                    status='completed',
                    description=description,
                    metadata={
                        'wallet_operation': 'credit',
                        'timestamp': time.time()
                    }
                )
                
                logger.info(f"Credited ${amount} to {user.username}, new balance: ${user_locked.balance}")
                
                return {
                    'success': True,
                    'transaction_id': str(txn.id),
                    'new_balance': user_locked.balance,
                    'amount_credited': amount
                }
                
        except Exception as e:
            logger.error(f"Error crediting wallet: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def debit_wallet(user, amount: Decimal, description: str, transaction_type: str = 'withdrawal') -> Dict:
        """
        Deduct funds from user's virtual wallet
        """
        from predict.models import Transaction
        from django.db import transaction as db_transaction
        
        try:
            with db_transaction.atomic():
                user_locked = type(user).objects.select_for_update().get(id=user.id)
                
                if user_locked.balance < amount:
                    return {
                        'success': False,
                        'error': f'Insufficient balance. Available: ${user_locked.balance}'
                    }
                
                old_balance = user_locked.balance
                user_locked.balance -= amount
                user_locked.save(update_fields=['balance'])
                
                # Create transaction record
                txn = Transaction.objects.create(
                    user=user_locked,
                    transaction_type=transaction_type,
                    amount=-amount,
                    balance_before=old_balance,
                    balance_after=user_locked.balance,
                    status='completed',
                    description=description,
                    metadata={
                        'wallet_operation': 'debit',
                        'timestamp': time.time()
                    }
                )
                
                logger.info(f"Debited ${amount} from {user.username}, new balance: ${user_locked.balance}")
                
                return {
                    'success': True,
                    'transaction_id': str(txn.id),
                    'new_balance': user_locked.balance,
                    'amount_debited': amount
                }
                
        except Exception as e:
            logger.error(f"Error debiting wallet: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def transfer_between_users(sender, recipient_identifier: str, amount: Decimal, description: str = '') -> Dict:
        """
        P2P transfer between users' virtual wallets
        """
        from acounts.models import CustomUser
        from predict.models import Transaction
        from django.db import transaction as db_transaction
        from django.db.models import Q
        
        try:
            amount = Decimal(str(amount))
            
            # Validation
            if amount <= 0:
                return {'success': False, 'error': 'Invalid amount'}
            
            if sender.balance < amount:
                return {'success': False, 'error': f'Insufficient balance. Available: ${sender.balance}'}
            
            # Find recipient
            try:
                recipient = CustomUser.objects.get(
                    Q(username=recipient_identifier) | Q(email=recipient_identifier)
                )
            except CustomUser.DoesNotExist:
                return {'success': False, 'error': 'Recipient not found'}
            
            if sender.id == recipient.id:
                return {'success': False, 'error': 'Cannot transfer to yourself'}
            
            # Perform atomic transfer
            with db_transaction.atomic():
                sender_locked = CustomUser.objects.select_for_update().get(id=sender.id)
                recipient_locked = CustomUser.objects.select_for_update().get(id=recipient.id)
                
                # Check balance again after lock
                if sender_locked.balance < amount:
                    return {'success': False, 'error': 'Insufficient balance'}
                
                sender_old = sender_locked.balance
                recipient_old = recipient_locked.balance
                
                sender_locked.balance -= amount
                recipient_locked.balance += amount
                
                sender_locked.save(update_fields=['balance'])
                recipient_locked.save(update_fields=['balance'])
                
                # Create transaction records
                Transaction.objects.create(
                    user=sender_locked,
                    transaction_type='transfer',
                    amount=-amount,
                    balance_before=sender_old,
                    balance_after=sender_locked.balance,
                    status='completed',
                    description=f'P2P transfer to {recipient.username}: {description}',
                    metadata={
                        'recipient_id': recipient.id,
                        'recipient_username': recipient.username,
                        'transfer_type': 'p2p_send'
                    }
                )
                
                Transaction.objects.create(
                    user=recipient_locked,
                    transaction_type='transfer',
                    amount=amount,
                    balance_before=recipient_old,
                    balance_after=recipient_locked.balance,
                    status='completed',
                    description=f'P2P transfer from {sender.username}: {description}',
                    metadata={
                        'sender_id': sender.id,
                        'sender_username': sender.username,
                        'transfer_type': 'p2p_receive'
                    }
                )
                
                logger.info(f"P2P Transfer: {sender.username} -> {recipient.username}: ${amount}")
                
                return {
                    'success': True,
                    'message': f'Successfully transferred ${amount} to {recipient.username}',
                    'sender_new_balance': sender_locked.balance,
                    'recipient_username': recipient.username,
                    'amount': amount
                }
                
        except Exception as e:
            logger.error(f"P2P transfer error: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
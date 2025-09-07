import stripe
import requests
import hashlib
import hmac
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from typing import Dict, Optional, List
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Configure Stripe
stripe.api_key = getattr(settings, 'STRIPE_SECRET_KEY', '')

@dataclass
class PaymentResult:
    success: bool
    data: Optional[Dict] = None
    error: Optional[str] = None
    transaction_id: Optional[str] = None


class StripeIntegration:
    """Enhanced Stripe integration for wallet deposits"""
    
    def __init__(self):
        self.api_key = getattr(settings, 'STRIPE_SECRET_KEY', '')
        self.publishable_key = getattr(settings, 'STRIPE_PUBLISHABLE_KEY', '')
        self.webhook_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '')
        
        if not self.api_key:
            logger.warning("Stripe API key not configured")
    
    def create_payment_intent(self, amount: Decimal, user, currency: str = 'usd') -> PaymentResult:
        """Create a payment intent for deposit"""
        try:
            # Ensure customer exists
            customer_id = self._get_or_create_customer(user)
            if not customer_id:
                return PaymentResult(success=False, error="Failed to create customer")
            
            # Convert to smallest currency unit (cents for USD)
            amount_cents = int(amount * 100)
            
            # Create payment intent
            intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency=currency,
                customer=customer_id,
                automatic_payment_methods={'enabled': True},
                metadata={
                    'user_id': str(user.id),
                    'username': user.username,
                    'type': 'wallet_deposit',
                    'amount_usd': str(amount)
                },
                description=f'EVGxchain wallet deposit - ${amount}',
                receipt_email=user.email,
                statement_descriptor='EVGXCHAIN DEPOSIT'
            )
            
            return PaymentResult(
                success=True,
                data={
                    'client_secret': intent.client_secret,
                    'payment_intent_id': intent.id,
                    'amount': float(amount),
                    'currency': currency
                },
                transaction_id=intent.id
            )
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating payment intent: {e}")
            return PaymentResult(success=False, error=str(e))
        except Exception as e:
            logger.error(f"Unexpected error creating payment intent: {e}")
            return PaymentResult(success=False, error="Payment system temporarily unavailable")
    
    def _get_or_create_customer(self, user) -> Optional[str]:
        """Get existing or create new Stripe customer"""
        try:
            # Check if user already has a customer ID
            if hasattr(user, 'stripe_customer_id') and user.stripe_customer_id:
                try:
                    # Verify customer exists
                    customer = stripe.Customer.retrieve(user.stripe_customer_id)
                    return customer.id
                except stripe.error.InvalidRequestError:
                    # Customer doesn't exist, create new one
                    pass
            
            # Create new customer
            customer = stripe.Customer.create(
                email=user.email,
                name=getattr(user, 'full_name', user.username),
                metadata={
                    'user_id': str(user.id),
                    'username': user.username,
                    'created_at': timezone.now().isoformat()
                }
            )
            
            # Save customer ID to user
            user.stripe_customer_id = customer.id
            user.save(update_fields=['stripe_customer_id'])
            
            return customer.id
            
        except Exception as e:
            logger.error(f"Error creating Stripe customer: {e}")
            return None
    
    def process_webhook(self, payload: bytes, signature: str) -> PaymentResult:
        """Process Stripe webhook events"""
        try:
            if not self.webhook_secret:
                return PaymentResult(success=False, error="Webhook secret not configured")
            
            # Verify webhook signature
            event = stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
            
            # Handle different event types
            if event['type'] == 'payment_intent.succeeded':
                return self._handle_payment_succeeded(event['data']['object'])
            elif event['type'] == 'payment_intent.payment_failed':
                return self._handle_payment_failed(event['data']['object'])
            elif event['type'] == 'payment_intent.canceled':
                return self._handle_payment_canceled(event['data']['object'])
            else:
                logger.info(f"Unhandled webhook event type: {event['type']}")
                return PaymentResult(success=True)
                
        except stripe.error.SignatureVerificationError:
            logger.error("Invalid webhook signature")
            return PaymentResult(success=False, error="Invalid signature")
        except Exception as e:
            logger.error(f"Webhook processing error: {e}")
            return PaymentResult(success=False, error=str(e))
    
    def _handle_payment_succeeded(self, payment_intent: Dict) -> PaymentResult:
        """Handle successful payment"""
        try:
            from predict.models import Transaction
            from acounts.models import CustomUser
            from django.db import transaction
            
            # Get the pending transaction
            tx = Transaction.objects.select_for_update().get(
                stripe_payment_intent_id=payment_intent['id'],
                status='pending'
            )
            
            with transaction.atomic():
                # Update user balance
                user = tx.user
                user.balance += tx.amount
                user.save()
                
                # Update transaction status
                tx.status = 'completed'
                tx.balance_after = user.balance
                tx.metadata.update({
                    'stripe_charge_id': payment_intent.get('latest_charge'),
                    'completed_at': timezone.now().isoformat()
                })
                tx.save()
                
                # Award XP for deposit
                if hasattr(user, 'add_xp'):
                    xp_amount = min(int(tx.amount / 10), 100)  # 1 XP per $10, max 100
                    user.add_xp(xp_amount)
            
            return PaymentResult(
                success=True,
                data={
                    'amount': float(tx.amount),
                    'user_id': str(user.id),
                    'new_balance': float(user.balance)
                },
                transaction_id=str(tx.id)
            )
            
        except Transaction.DoesNotExist:
            logger.error(f"Transaction not found for payment intent: {payment_intent['id']}")
            return PaymentResult(success=False, error="Transaction not found")
        except Exception as e:
            logger.error(f"Error handling payment success: {e}")
            return PaymentResult(success=False, error=str(e))
    
    def _handle_payment_failed(self, payment_intent: Dict) -> PaymentResult:
        """Handle failed payment"""
        try:
            from predict.models import Transaction
            
            tx = Transaction.objects.get(
                stripe_payment_intent_id=payment_intent['id']
            )
            
            tx.status = 'failed'
            tx.metadata.update({
                'failure_reason': payment_intent.get('last_payment_error', {}).get('message', 'Unknown error'),
                'failed_at': timezone.now().isoformat()
            })
            tx.save()
            
            return PaymentResult(success=True, transaction_id=str(tx.id))
            
        except Transaction.DoesNotExist:
            logger.error(f"Transaction not found for failed payment: {payment_intent['id']}")
            return PaymentResult(success=False, error="Transaction not found")
        except Exception as e:
            logger.error(f"Error handling payment failure: {e}")
            return PaymentResult(success=False, error=str(e))
    
    def _handle_payment_canceled(self, payment_intent: Dict) -> PaymentResult:
        """Handle canceled payment"""
        try:
            from predict.models import Transaction
            
            tx = Transaction.objects.get(
                stripe_payment_intent_id=payment_intent['id']
            )
            
            tx.status = 'cancelled'
            tx.metadata.update({
                'canceled_at': timezone.now().isoformat(),
                'cancellation_reason': payment_intent.get('cancellation_reason', 'User canceled')
            })
            tx.save()
            
            return PaymentResult(success=True, transaction_id=str(tx.id))
            
        except Transaction.DoesNotExist:
            logger.error(f"Transaction not found for canceled payment: {payment_intent['id']}")
            return PaymentResult(success=False, error="Transaction not found")
        except Exception as e:
            logger.error(f"Error handling payment cancellation: {e}")
            return PaymentResult(success=False, error=str(e))


class CryptoWithdrawalService:
    """Service for handling cryptocurrency withdrawals"""
    
    def __init__(self):
        # Configuration for different crypto services
        self.coinbase_api_key = getattr(settings, 'COINBASE_API_KEY', '')
        self.coinbase_api_secret = getattr(settings, 'COINBASE_API_SECRET', '')
        self.infura_project_id = getattr(settings, 'INFURA_PROJECT_ID', '')
        
        # Network configurations
        self.networks = {
            'ethereum': {
                'name': 'Ethereum',
                'min_withdrawal': Decimal('20.00'),
                'base_fee': Decimal('5.00'),
                'fee_rate': Decimal('0.02'),  # 2%
                'confirmation_blocks': 12
            },
            'bsc': {
                'name': 'Binance Smart Chain', 
                'min_withdrawal': Decimal('10.00'),
                'base_fee': Decimal('2.00'),
                'fee_rate': Decimal('0.015'),  # 1.5%
                'confirmation_blocks': 15
            },
            'polygon': {
                'name': 'Polygon',
                'min_withdrawal': Decimal('5.00'),
                'base_fee': Decimal('1.00'),
                'fee_rate': Decimal('0.01'),  # 1%
                'confirmation_blocks': 128
            }
        }
    
    def process_withdrawal(self, user, amount: Decimal, wallet_address: str, 
                         network: str = 'ethereum', token: str = 'USDT') -> PaymentResult:
        """Process crypto withdrawal request"""
        try:
            # Validate network
            if network not in self.networks:
                return PaymentResult(success=False, error=f"Unsupported network: {network}")
            
            network_config = self.networks[network]
            
            # Validate amount
            if amount < network_config['min_withdrawal']:
                return PaymentResult(
                    success=False, 
                    error=f"Minimum withdrawal for {network_config['name']} is ${network_config['min_withdrawal']}"
                )
            
            # Validate wallet address
            if not self._validate_wallet_address(wallet_address, network):
                return PaymentResult(success=False, error="Invalid wallet address format")
            
            # Calculate fees
            fee_info = self._calculate_fees(amount, network)
            total_deduction = fee_info['total_fee'] + amount
            
            # Check user balance
            if user.balance < total_deduction:
                return PaymentResult(
                    success=False, 
                    error=f"Insufficient balance. Required: ${total_deduction}, Available: ${user.balance}"
                )
            
            # Create withdrawal transaction
            withdrawal_result = self._create_withdrawal_transaction(
                user, amount, wallet_address, network, token, fee_info
            )
            
            if withdrawal_result.success:
                # Submit to blockchain (simplified - in production use proper crypto APIs)
                blockchain_result = self._submit_to_blockchain(
                    amount, wallet_address, network, token
                )
                
                if blockchain_result.success:
                    return PaymentResult(
                        success=True,
                        data={
                            'transaction_id': withdrawal_result.transaction_id,
                            'blockchain_tx': blockchain_result.data.get('tx_hash'),
                            'network': network_config['name'],
                            'amount': float(amount),
                            'fees': fee_info,
                            'estimated_arrival': '10-30 minutes'
                        },
                        transaction_id=withdrawal_result.transaction_id
                    )
                else:
                    # Rollback the transaction
                    self._rollback_withdrawal(withdrawal_result.transaction_id)
                    return PaymentResult(success=False, error="Blockchain submission failed")
            
            return withdrawal_result
            
        except Exception as e:
            logger.error(f"Error processing withdrawal: {e}")
            return PaymentResult(success=False, error="Withdrawal processing failed")
    
    def _validate_wallet_address(self, address: str, network: str) -> bool:
        """Validate wallet address format"""
        try:
            if network in ['ethereum', 'bsc', 'polygon']:
                # Ethereum-style address validation
                if not address.startswith('0x'):
                    return False
                if len(address) != 42:
                    return False
                # Verify it's valid hex
                int(address[2:], 16)
                return True
            
            return False
            
        except (ValueError, TypeError):
            return False
    
    def _calculate_fees(self, amount: Decimal, network: str) -> Dict:
        """Calculate withdrawal fees"""
        network_config = self.networks[network]
        
        # Percentage fee
        percentage_fee = amount * network_config['fee_rate']
        
        # Base network fee
        base_fee = network_config['base_fee']
        
        # Total fee
        total_fee = percentage_fee + base_fee
        
        return {
            'percentage_fee': percentage_fee,
            'base_fee': base_fee,
            'total_fee': total_fee,
            'net_amount': amount - total_fee,
            'fee_rate': network_config['fee_rate']
        }
    
    def _create_withdrawal_transaction(self, user, amount: Decimal, wallet_address: str,
                                     network: str, token: str, fee_info: Dict) -> PaymentResult:
        """Create withdrawal transaction record"""
        try:
            from predict.models import Transaction
            from django.db import transaction
            
            with transaction.atomic():
                # Deduct from user balance
                user.balance -= (amount + fee_info['total_fee'])
                user.save()
                
                # Create transaction record
                tx = Transaction.objects.create(
                    user=user,
                    transaction_type='withdrawal',
                    amount=-(amount + fee_info['total_fee']),  # Negative for withdrawal
                    balance_before=user.balance + amount + fee_info['total_fee'],
                    balance_after=user.balance,
                    status='pending',
                    description=f'Crypto withdrawal to {wallet_address[:10]}...{wallet_address[-6:]}',
                    metadata={
                        'wallet_address': wallet_address,
                        'network': network,
                        'token': token,
                        'fee_breakdown': fee_info,
                        'withdrawal_amount': str(amount),
                        'net_amount': str(fee_info['net_amount'])
                    }
                )
            
            return PaymentResult(
                success=True,
                transaction_id=str(tx.id),
                data={'transaction': tx}
            )
            
        except Exception as e:
            logger.error(f"Error creating withdrawal transaction: {e}")
            return PaymentResult(success=False, error="Failed to create withdrawal transaction")
    
    def _submit_to_blockchain(self, amount: Decimal, wallet_address: str, 
                            network: str, token: str) -> PaymentResult:
        """Submit transaction to blockchain (simplified implementation)"""
        try:
            # In production, this would integrate with:
            # - Web3.py for Ethereum/BSC/Polygon
            # - Coinbase Commerce API
            # - BitGo API for enterprise
            # - Custom blockchain node
            
            # For demonstration, we'll simulate a blockchain transaction
            import uuid
            import time
            
            # Simulate network delay
            time.sleep(1)
            
            # Generate mock transaction hash
            tx_hash = f"0x{''.join([f'{ord(c):02x}' for c in str(uuid.uuid4())[:32]])}"
            
            # In reality, you would:
            # 1. Connect to blockchain node
            # 2. Create and sign transaction
            # 3. Broadcast to network
            # 4. Wait for confirmation
            
            return PaymentResult(
                success=True,
                data={
                    'tx_hash': tx_hash,
                    'network': network,
                    'confirmations': 0,
                    'status': 'pending'
                }
            )
            
        except Exception as e:
            logger.error(f"Error submitting to blockchain: {e}")
            return PaymentResult(success=False, error="Blockchain submission failed")
    
    def _rollback_withdrawal(self, transaction_id: str):
        """Rollback failed withdrawal"""
        try:
            from predict.models import Transaction
            from django.db import transaction
            
            with transaction.atomic():
                tx = Transaction.objects.select_for_update().get(id=transaction_id)
                
                # Restore user balance
                user = tx.user
                user.balance += abs(tx.amount)  # Add back the deducted amount
                user.save()
                
                # Update transaction status
                tx.status = 'failed'
                tx.balance_after = user.balance
                tx.metadata.update({
                    'rollback_at': timezone.now().isoformat(),
                    'rollback_reason': 'Blockchain submission failed'
                })
                tx.save()
                
        except Exception as e:
            logger.error(f"Error rolling back withdrawal {transaction_id}: {e}")
    
    def get_withdrawal_status(self, transaction_id: str) -> Dict:
        """Get withdrawal status from blockchain"""
        try:
            from predict.models import Transaction
            
            tx = Transaction.objects.get(id=transaction_id, transaction_type='withdrawal')
            
            if not tx.blockchain_tx_hash:
                return {
                    'status': 'pending',
                    'confirmations': 0,
                    'message': 'Transaction submitted to blockchain'
                }
            
            # In production, query blockchain for confirmation status
            # For demo, simulate confirmation progress
            import time
            created_time = tx.created_at.timestamp()
            current_time = time.time()
            elapsed_minutes = (current_time - created_time) / 60
            
            if elapsed_minutes > 30:
                confirmations = 15
                status = 'confirmed'
            elif elapsed_minutes > 10:
                confirmations = int(elapsed_minutes / 2)
                status = 'confirming'
            else:
                confirmations = 0
                status = 'pending'
            
            return {
                'status': status,
                'confirmations': confirmations,
                'tx_hash': tx.blockchain_tx_hash,
                'network': tx.metadata.get('network', 'ethereum'),
                'amount': tx.metadata.get('withdrawal_amount'),
                'estimated_completion': '10-30 minutes' if status == 'pending' else 'Completed'
            }
            
        except Transaction.DoesNotExist:
            return {'status': 'not_found', 'error': 'Transaction not found'}
        except Exception as e:
            logger.error(f"Error getting withdrawal status: {e}")
            return {'status': 'error', 'error': str(e)}


class CoinbaseCommerceIntegration:
    """Integration with Coinbase Commerce for crypto payments"""
    
    def __init__(self):
        self.api_key = getattr(settings, 'COINBASE_COMMERCE_API_KEY', '')
        self.webhook_secret = getattr(settings, 'COINBASE_COMMERCE_WEBHOOK_SECRET', '')
        self.base_url = 'https://api.commerce.coinbase.com'
    
    def create_charge(self, amount: Decimal, user, description: str = None) -> PaymentResult:
        """Create a Coinbase Commerce charge for crypto deposits"""
        try:
            if not self.api_key:
                return PaymentResult(success=False, error="Coinbase Commerce not configured")
            
            headers = {
                'Content-Type': 'application/json',
                'X-CC-Api-Key': self.api_key,
                'X-CC-Version': '2018-03-22'
            }
            
            charge_data = {
                'name': 'EVGxchain Wallet Deposit',
                'description': description or f'Wallet deposit for {user.username}',
                'pricing_type': 'fixed_price',
                'local_price': {
                    'amount': str(amount),
                    'currency': 'USD'
                },
                'metadata': {
                    'user_id': str(user.id),
                    'username': user.username,
                    'type': 'wallet_deposit'
                },
                'redirect_url': f"{settings.SITE_URL}/dashboard/",
                'cancel_url': f"{settings.SITE_URL}/dashboard/"
            }
            
            response = requests.post(
                f"{self.base_url}/charges",
                headers=headers,
                json=charge_data,
                timeout=10
            )
            
            if response.status_code == 201:
                charge = response.json()['data']
                return PaymentResult(
                    success=True,
                    data={
                        'charge_id': charge['id'],
                        'hosted_url': charge['hosted_url'],
                        'addresses': charge['addresses'],
                        'pricing': charge['pricing']
                    },
                    transaction_id=charge['id']
                )
            else:
                logger.error(f"Coinbase Commerce API error: {response.text}")
                return PaymentResult(success=False, error="Failed to create crypto payment")
                
        except Exception as e:
            logger.error(f"Error creating Coinbase Commerce charge: {e}")
            return PaymentResult(success=False, error="Crypto payment system unavailable")
    
    def handle_webhook(self, payload: bytes, signature: str) -> PaymentResult:
        """Handle Coinbase Commerce webhook"""
        try:
            if not self.webhook_secret:
                return PaymentResult(success=False, error="Webhook secret not configured")
            
            # Verify webhook signature
            computed_signature = hmac.new(
                self.webhook_secret.encode(),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(signature, computed_signature):
                return PaymentResult(success=False, error="Invalid webhook signature")
            
            # Parse webhook data
            import json
            event_data = json.loads(payload.decode())
            
            event_type = event_data.get('event', {}).get('type')
            charge_data = event_data.get('event', {}).get('data', {})
            
            if event_type == 'charge:confirmed':
                return self._handle_charge_confirmed(charge_data)
            elif event_type == 'charge:failed':
                return self._handle_charge_failed(charge_data)
            else:
                return PaymentResult(success=True)  # Unhandled event type
                
        except Exception as e:
            logger.error(f"Error handling Coinbase Commerce webhook: {e}")
            return PaymentResult(success=False, error=str(e))
    
    def _handle_charge_confirmed(self, charge_data: Dict) -> PaymentResult:
        """Handle confirmed crypto payment"""
        try:
            from predict.models import Transaction
            from acounts.models import CustomUser
            from django.db import transaction
            
            # Get user from metadata
            user_id = charge_data.get('metadata', {}).get('user_id')
            if not user_id:
                return PaymentResult(success=False, error="User ID not found in charge metadata")
            
            user = CustomUser.objects.get(id=user_id)
            amount = Decimal(charge_data['pricing']['local']['amount'])
            
            with transaction.atomic():
                # Create transaction record
                tx = Transaction.objects.create(
                    user=user,
                    transaction_type='deposit',
                    amount=amount,
                    balance_before=user.balance,
                    balance_after=user.balance + amount,
                    status='completed',
                    external_id=charge_data['id'],
                    description=f"Crypto deposit via Coinbase Commerce - ${amount}",
                    metadata={
                        'coinbase_charge_id': charge_data['id'],
                        'crypto_amount': charge_data['pricing']['bitcoin']['amount'],
                        'crypto_currency': 'BTC',  # Could be dynamic based on payment method
                        'confirmed_at': timezone.now().isoformat()
                    }
                )
                
                # Update user balance
                user.balance += amount
                user.save()
                
                # Award XP
                if hasattr(user, 'add_xp'):
                    xp_amount = min(int(amount / 5), 200)  # 1 XP per $5, max 200
                    user.add_xp(xp_amount)
            
            return PaymentResult(
                success=True,
                data={
                    'amount': float(amount),
                    'user_id': str(user.id),
                    'new_balance': float(user.balance)
                },
                transaction_id=str(tx.id)
            )
            
        except CustomUser.DoesNotExist:
            return PaymentResult(success=False, error="User not found")
        except Exception as e:
            logger.error(f"Error handling confirmed charge: {e}")
            return PaymentResult(success=False, error=str(e))
    
    def _handle_charge_failed(self, charge_data: Dict) -> PaymentResult:
        """Handle failed crypto payment"""
        try:
            # Log the failed payment for monitoring
            logger.warning(f"Coinbase Commerce charge failed: {charge_data.get('id')}")
            
            return PaymentResult(
                success=True,
                data={'charge_id': charge_data.get('id')}
            )
            
        except Exception as e:
            logger.error(f"Error handling failed charge: {e}")
            return PaymentResult(success=False, error=str(e))


class PaymentMethodManager:
    """Manager class to handle multiple payment methods"""
    
    def __init__(self):
        self.stripe = StripeIntegration()
        self.crypto_withdrawal = CryptoWithdrawalService()
        self.coinbase = CoinbaseCommerceIntegration()
    
    def process_deposit(self, method: str, amount: Decimal, user, **kwargs) -> PaymentResult:
        """Process deposit using specified method"""
        try:
            if method == 'stripe':
                return self.stripe.create_payment_intent(amount, user)
            elif method == 'crypto':
                return self.coinbase.create_charge(amount, user, kwargs.get('description'))
            else:
                return PaymentResult(success=False, error=f"Unsupported deposit method: {method}")
                
        except Exception as e:
            logger.error(f"Error processing {method} deposit: {e}")
            return PaymentResult(success=False, error="Payment processing failed")
    
    def process_withdrawal(self, amount: Decimal, user, wallet_address: str, 
                         network: str = 'ethereum', **kwargs) -> PaymentResult:
        """Process crypto withdrawal"""
        return self.crypto_withdrawal.process_withdrawal(
            user, amount, wallet_address, network, kwargs.get('token', 'USDT')
        )
    
    def get_supported_networks(self) -> List[Dict]:
        """Get list of supported withdrawal networks"""
        return [
            {
                'id': 'ethereum',
                'name': 'Ethereum (ERC-20)',
                'min_withdrawal': '20.00',
                'fee': '2.0% + $5.00',
                'estimated_time': '10-30 minutes'
            },
            {
                'id': 'bsc',
                'name': 'Binance Smart Chain (BEP-20)',
                'min_withdrawal': '10.00', 
                'fee': '1.5% + $2.00',
                'estimated_time': '5-15 minutes'
            },
            {
                'id': 'polygon',
                'name': 'Polygon (MATIC)',
                'min_withdrawal': '5.00',
                'fee': '1.0% + $1.00',
                'estimated_time': '2-10 minutes'
            }
        ]
    
    def calculate_withdrawal_fee(self, amount: Decimal, network: str = 'ethereum') -> Dict:
        """Calculate withdrawal fees for given amount and network"""
        return self.crypto_withdrawal._calculate_fees(amount, network)
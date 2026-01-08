import os
import requests
import stripe
from decimal import Decimal
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from django.conf import settings
from predict.models import Bet
from django.db import models
from django.utils import timezone as django_timezone
from typing import Dict, List, Optional
import logging
import time
from market.models import Market, CryptocurrencyCategory
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from dotenv import load_dotenv
load_dotenv()  

stripe.api_key=os.getenv('STRIPE_SECRET_KEY')


logger = logging.getLogger(__name__)

# Configure Stripe


class CryptoPanicNewsService:
    """Service to fetch crypto news from CryptoPanic API"""
    
    BASE_URL = "https://cryptopanic.com/api/v1/posts/"
    
    @staticmethod
    def fetch_and_store_news():
        """Fetch news from CryptoPanic and store in database"""
        try:
            # CryptoPanic API parameters
            params = {
                'auth_token':os.getenv('CRYPTOPANIC_API_KEY'),
                'public': 'true',
                'kind': 'news',
                'filter': 'hot',  # hot, rising, bullish, bearish
                'currencies': 'BTC,ETH',  # Focus on major cryptos
                'regions': 'en',  # English only
            }
            
            response = requests.get(CryptoPanicNewsService.BASE_URL, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            
            if 'results' not in data:
                logger.error("No results in CryptoPanic response")
                return []
            
            from predict.models import NewsArticle
            from market.models import Market
            
            stored_articles = []
            
            for article_data in data['results'][:10]:  # Limit to 10 most recent
                try:
                    # Determine impact level based on votes
                    votes = article_data.get('votes', {})
                    positive_votes = votes.get('positive', 0)
                    negative_votes = votes.get('negative', 0)
                    total_votes = positive_votes + negative_votes
                    
                    if total_votes >= 50:
                        impact_level = 'high'
                    elif total_votes >= 20:
                        impact_level = 'medium'
                    else:
                        impact_level = 'low'
                    
                    # Parse published date
                    published_at = datetime.fromisoformat(
                        article_data['published_at'].replace('Z', '+00:00')
                    )
                    
                    # Create or update article
                    article, created = NewsArticle.objects.get_or_create(
                        url=article_data['url'],
                        defaults={
                            'title': article_data['title'][:500],  # Limit to model field length
                            'summary': article_data.get('summary', article_data['title'])[:1000],
                            'impact_level': impact_level,
                            'source': article_data.get('source', {}).get('title', 'Unknown'),
                            'published_at': published_at,
                            'is_active': True
                        }
                    )
                    
                    if created:
                        # Associate with relevant markets based on currencies mentioned
                        currencies = article_data.get('currencies', [])
                        for currency in currencies:
                            currency_code = currency.get('code', '').upper()
                            if currency_code in ['BTC', 'ETH']:
                                # Find markets related to this currency
                                related_markets = Market.objects.filter(
                                    models.Q(base_currency=currency_code) |
                                    models.Q(quote_currency=currency_code) |
                                    models.Q(title__icontains=currency_code),
                                    status='active'
                                )
                                article.related_markets.add(*related_markets)
                        
                        stored_articles.append(article)
                        logger.info(f"Stored news article: {article.title}")
                
                except Exception as e:
                    logger.error(f"Error processing article: {e}")
                    continue
            
            return stored_articles
            
        except requests.RequestException as e:
            logger.error(f"Error fetching news from CryptoPanic: {e}")
            return CryptoPanicNewsService._create_fallback_news()
        except Exception as e:
            logger.error(f"Unexpected error in fetch_and_store_news: {e}")
            return CryptoPanicNewsService._create_fallback_news()
    
    @staticmethod
    def _create_fallback_news():
        """Create fallback news articles if API fails"""
        from predict.models import NewsArticle
        
        fallback_articles = [
            {
                'title': 'Bitcoin ETF Inflows Surge as Institutional Adoption Grows',
                'summary': 'Major financial institutions continue to allocate significant resources to Bitcoin ETFs, driving unprecedented inflows this week.',
                'impact_level': 'high',
                'source': 'CryptoNews',
                'url': 'https://example.com/news/1',
            },
            {
                'title': 'Ethereum Network Upgrade Shows Promising Gas Fee Reductions',
                'summary': 'The latest Ethereum network improvements demonstrate measurable reductions in transaction costs for users.',
                'impact_level': 'medium',
                'source': 'EthNews',
                'url': 'https://example.com/news/2',
            },
            {
                'title': 'Federal Reserve Minutes Show Continued Crypto Market Monitoring',
                'summary': 'Fed officials discuss digital asset market developments in latest meeting minutes release.',
                'impact_level': 'medium',
                'source': 'FedWatch',
                'url': 'https://example.com/news/3',
            }
        ]
        
        stored_articles = []
        for article_data in fallback_articles:
            article, created = NewsArticle.objects.get_or_create(
                url=article_data['url'],
                defaults={
                    **article_data,
                    'published_at': django_timezone.now() - timedelta(minutes=30),
                    'is_active': True
                }
            )
            if created:
                stored_articles.append(article)
        
        return stored_articles


class CoinremitterWithdrawalService:
    """Production Coinremitter withdrawal service"""
    
    BASE_URL = "https://coinremitter.com/api/v3"
    
    def __init__(self):
        self.api_key = os.getenv("COINREMITTER_API_KEY")
        self.password = os.getenv("COINREMITTER_WALLET_PASSWORD")
        self.coin = settings.COINREMITTER_USDT_COIN
        
    def _make_request(self, endpoint: str, data: dict) -> dict:
        """Make authenticated request to Coinremitter API"""
        url = f"{self.BASE_URL}/{self.coin}/{endpoint}"
        
        # Add API key and password to data
        data.update({
            'api_key': self.api_key,
            'password': self.password
        })
        
        try:
            response = requests.post(url, data=data, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"Coinremitter API response: {result}")
            
            return result
        except requests.RequestException as e:
            logger.error(f"Coinremitter API error: {e}")
            return {'flag': 0, 'msg': f'API request failed: {str(e)}'}
    
    def validate_address(self, address: str) -> bool:
        """Validate USDT wallet address"""
        data = {'address': address}
        
        result = self._make_request('validate-address', data)
        
        return result.get('flag') == 1 and result.get('data', {}).get('valid', False)
    
    def get_wallet_balance(self) -> Optional[Decimal]:
        """Get current wallet balance"""
        result = self._make_request('get-balance', {})
        
        if result.get('flag') == 1:
            balance = result.get('data', {}).get('balance', '0')
            return Decimal(str(balance))
        
        return None
    
    def send_withdrawal(self, address: str, amount: Decimal, user_id: str) -> Dict:
        """Send USDT withdrawal to user address"""
        
        # Validate address first
        if not self.validate_address(address):
            return {
                'success': False,
                'error': 'Invalid wallet address',
                'tx_id': None
            }
        
        # Check wallet balance
        wallet_balance = self.get_wallet_balance()
        if wallet_balance is None:
            return {
                'success': False,
                'error': 'Unable to check wallet balance',
                'tx_id': None
            }
        
        if wallet_balance < amount:
            logger.error(f"Insufficient wallet balance: {wallet_balance} < {amount}")
            return {
                'success': False,
                'error': 'Insufficient funds in hot wallet',
                'tx_id': None
            }
        
        # Prepare withdrawal data
        data = {
            'address': address,
            'amount': str(amount),
            'custom_id': f"withdraw_{user_id}_{int(time.time())}"  # Unique identifier
        }
        
        result = self._make_request('withdraw', data)
        
        if result.get('flag') == 1:
            tx_data = result.get('data', {})
            return {
                'success': True,
                'tx_id': tx_data.get('id'),
                'tx_hash': tx_data.get('txid'),  # Blockchain transaction hash
                'amount': Decimal(str(tx_data.get('amount', amount))),
                'fee': Decimal(str(tx_data.get('fee', 0))),
                'custom_id': data['custom_id']
            }
        else:
            error_msg = result.get('msg', 'Withdrawal failed')
            logger.error(f"Withdrawal failed: {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'tx_id': None
            }
    
    def get_transaction_status(self, tx_id: str) -> Dict:
        """Check transaction status"""
        data = {'id': tx_id}
        
        result = self._make_request('get-transaction', data)
        
        if result.get('flag') == 1:
            tx_data = result.get('data', {})
            return {
                'success': True,
                'status': tx_data.get('status'),  # pending, success, failed
                'confirmations': tx_data.get('confirmations', 0),
                'tx_hash': tx_data.get('txid'),
                'amount': Decimal(str(tx_data.get('amount', 0)))
            }
        
        return {'success': False, 'error': result.get('msg', 'Transaction not found')}

class CryptoPriceService:
    """Service to fetch real-time crypto prices"""
    
    BASE_URL = "https://api.coingecko.com/api/v3"
    
    @staticmethod
    def get_crypto_prices():
        """Fetch current crypto prices from CoinGecko API"""
        try:
            url = f"{CryptoPriceService.BASE_URL}/simple/price"
            params = {
                'ids': 'bitcoin,ethereum,',
                'vs_currencies': 'usd',
                'include_24hr_change': 'true',
                'include_24hr_vol': 'true',
                'include_market_cap': 'true'
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            # Format the data with enhanced information
            formatted_data = {}
            crypto_mapping = {
                'bitcoin': 'BTC',
                'ethereum': 'ETH', 
                # 'solana': 'SOL',
                # 'cardano': 'ADA',
                # 'polygon': 'MATIC',
                # 'chainlink': 'LINK',
                # 'uniswap': 'UNI',
                # 'binancecoin': 'BNB',
                # 'ripple': 'XRP',
                # 'dogecoin': 'DOGE'
            }
            
            for crypto_id, symbol in crypto_mapping.items():
                if crypto_id in data:
                    price_data = data[crypto_id]
                    formatted_data[symbol] = {
                        'price': price_data['usd'],
                        'change_24h': price_data.get('usd_24h_change', 0),
                        'volume_24h': price_data.get('usd_24h_vol', 0),
                        'market_cap': price_data.get('usd_market_cap', 0),
                        'last_updated': datetime.now(dt_timezone.utc).isoformat()
                    }
            
            return formatted_data
            
        except requests.RequestException as e:
            logger.error(f"Error fetching crypto prices from CoinGecko: {e}")
            return CryptoPriceService._get_fallback_prices()
        except Exception as e:
            logger.error(f"Unexpected error in get_crypto_prices: {e}")
            return CryptoPriceService._get_fallback_prices()
    
    @staticmethod
    def _get_fallback_prices():
        """Return mock data if API fails"""
        return {
            'BTC': {
                'price': 67432.50,
                'change_24h': 2.5,
                'volume_24h': 25000000000,
                'market_cap': 1300000000000,
                'last_updated': datetime.now(dt_timezone.utc).isoformat()
            },
            'ETH': {
                'price': 3421.80,
                'change_24h': -1.2,
                'volume_24h': 12000000000,
                'market_cap': 400000000000,
                'last_updated': datetime.now(dt_timezone.utc).isoformat()
            },
            # 'SOL': {
            #     'price': 187.65,
            #     'change_24h': 5.8,
            #     'volume_24h': 800000000,
            #     'market_cap': 85000000000,
            #     'last_updated': datetime.now(dt_timezone.utc).isoformat()
            # },
        }
    
    @staticmethod
    def get_price_history(symbol: str, days: int = 7) -> Dict:
        """Get historical price data for a cryptocurrency"""
        try:
            crypto_id_map = {
                'BTC': 'bitcoin',
                'ETH': 'ethereum',
                # 'SOL': 'solana',
                # 'ADA': 'cardano',
                # 'MATIC': 'polygon',
                # 'LINK': 'chainlink'
            }
            
            crypto_id = crypto_id_map.get(symbol.upper())
            if not crypto_id:
                return {}
            
            url = f"{CryptoPriceService.BASE_URL}/coins/{crypto_id}/market_chart"
            params = {
                'vs_currency': 'usd',
                'days': days,
                'interval': 'hourly' if days <= 7 else 'daily'
            }
            
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            
            return {
                'prices': data.get('prices', []),
                'market_caps': data.get('market_caps', []),
                'total_volumes': data.get('total_volumes', [])
            }
            
        except Exception as e:
            logger.error(f"Error fetching price history for {symbol}: {e}")
            return {}


class EconomicCalendarService:
    """Service to fetch economic events and store in database"""
    
    @staticmethod
    def fetch_and_store_events():
        """Fetch economic events and store in database"""
        try:
            # For production, use services like:
            # - Financial Modeling Prep API
            # - Alpha Vantage Economic Indicators
            # - FRED API (Federal Reserve Economic Data)
            # - FinnHub Economic Calendar
            
            # Mock implementation with realistic upcoming events
            from market.models import EconomicEvent
            
            now = django_timezone.now()
            
            upcoming_events_data = [
                {
                    'name': 'US Consumer Price Index (CPI)',
                    'event_type': 'cpi',
                    'impact_level': 'high',
                    'description': 'Monthly inflation data release. Historical data shows 15-25% crypto volatility during CPI releases.',
                    'scheduled_time': now + timedelta(days=2, hours=8, minutes=30),  # 8:30 AM in 2 days
                    'expected_value': '0.2% m/m',
                    'previous_value': '0.1% m/m',
                    'is_active': True
                },
                {
                    'name': 'Federal Open Market Committee (FOMC) Meeting',
                    'event_type': 'fomc',
                    'impact_level': 'high',
                    'description': 'Federal Reserve interest rate decision and policy statement. Major crypto market mover.',
                    'scheduled_time': now + timedelta(days=7, hours=14, minutes=0),  # 2:00 PM in 7 days
                    'expected_value': '5.25-5.50%',
                    'previous_value': '5.25-5.50%',
                    'is_active': True
                },
                {
                    'name': 'Non-Farm Payrolls (NFP)',
                    'event_type': 'nfp',
                    'impact_level': 'high',
                    'description': 'US employment data release. Strong correlation with risk asset movements including crypto.',
                    'scheduled_time': now + timedelta(days=5, hours=8, minutes=30),  # 8:30 AM in 5 days
                    'expected_value': '+185K',
                    'previous_value': '+199K',
                    'is_active': True
                },
                {
                    'name': 'US GDP Preliminary Release',
                    'event_type': 'gdp',
                    'impact_level': 'medium',
                    'description': 'Quarterly economic growth data affects market sentiment and crypto flows.',
                    'scheduled_time': now + timedelta(days=10, hours=8, minutes=30),
                    'expected_value': '2.1% q/q annualized',
                    'previous_value': '2.4% q/q annualized',
                    'is_active': True
                },
                {
                    'name': 'US Retail Sales',
                    'event_type': 'retail_sales',
                    'impact_level': 'medium',
                    'description': 'Consumer spending data influences market risk sentiment.',
                    'scheduled_time': now + timedelta(days=12, hours=8, minutes=30),
                    'expected_value': '0.3% m/m',
                    'previous_value': '0.7% m/m',
                    'is_active': True
                }
            ]
            
            stored_events = []
            for event_data in upcoming_events_data:
                event, created = EconomicEvent.objects.get_or_create(
                    name=event_data['name'],
                    scheduled_time=event_data['scheduled_time'],
                    defaults=event_data
                )
                if created:
                    stored_events.append(event)
                    logger.info(f"Stored economic event: {event.name}")
            
            return stored_events
            
        except Exception as e:
            logger.error(f"Error in fetch_and_store_events: {e}")
            return []
    
    @staticmethod
    def cleanup_old_events():
        """Remove old economic events"""
        try:
            from market.models import EconomicEvent
            
            cutoff_date = django_timezone.now() - timedelta(days=7)
            deleted_count = EconomicEvent.objects.filter(
                scheduled_time__lt=cutoff_date
            ).delete()[0]
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old economic events")
            
        except Exception as e:
            logger.error(f"Error cleaning up old events: {e}")


class MarketDataManager:
    """Service to manage and update market data"""
    
    @staticmethod
    def create_trending_markets():
        """Create or update trending markets with realistic data"""
        try:
            from market.models import Market, CryptocurrencyCategory
            from acounts.models import CustomUser
            
            # Get or create categories
            btc_category, _ = CryptocurrencyCategory.objects.get_or_create(
                category_type='bitcoin',
                defaults={
                    'display_name': 'Bitcoin (BTC)',
                    'description': 'Bitcoin price prediction markets',
                    'icon': '₿',
                    'color_code': '#F7931A',
                    'is_active': True,
                    'sort_order': 1
                }
            )
            
            eth_category, _ = CryptocurrencyCategory.objects.get_or_create(
                category_type='ethereum',
                defaults={
                    'display_name': 'Ethereum (ETH)',
                    'description': 'Ethereum price prediction markets',
                    'icon': 'Ξ',
                    'color_code': '#627EEA',
                    'is_active': True,
                    'sort_order': 2
                }
            )
            
            # Get or create a default creator (admin user)
            creator, _ = CustomUser.objects.get_or_create(
                username='system_creator',
                defaults={
                    'email': 'system@evgxchain.com',
                    'is_staff': True,
                    'balance': Decimal('1000000.00')
                }
            )
            
            # Create trending markets
            markets_data = [
                {
                    'title': 'BTC/USDT Price Prediction - CPI Event',
                    'description': 'Trade Bitcoin volatility during the upcoming CPI announcement. Historical data shows 15-25% price movements.',
                    'base_currency': 'BTC',
                    'quote_currency': 'USDT',
                    'category': btc_category,
                    'total_volume': Decimal('156780.50'),
                    'up_volume': Decimal('78234.25'),
                    'down_volume': Decimal('52341.75'),
                    'flat_volume': Decimal('26204.50'),
                    'round_duration': 900,  # 15 minutes
                },
                {
                    'title': 'ETH/USDT FOMC Decision Trading',
                    'description': 'Predict Ethereum price movement during Federal Reserve policy announcement.',
                    'base_currency': 'ETH',
                    'quote_currency': 'USDT',
                    'category': eth_category,
                    'total_volume': Decimal('89456.30'),
                    'up_volume': Decimal('45123.15'),
                    'down_volume': Decimal('32187.90'),
                    'flat_volume': Decimal('12145.25'),
                    'round_duration': 1800,  # 30 minutes
                },
                {
                    'title': 'BTC/USDT Non-Farm Payrolls Impact',
                    'description': 'Trade the correlation between US employment data and Bitcoin price action.',
                    'base_currency': 'BTC',
                    'quote_currency': 'USDT',
                    'category': btc_category,
                    'total_volume': Decimal('203458.75'),
                    'up_volume': Decimal('101729.40'),
                    'down_volume': Decimal('67832.60'),
                    'flat_volume': Decimal('33896.75'),
                    'round_duration': 900,
                }
            ]
            
            created_markets = []
            for market_data in markets_data:
                market, created = Market.objects.get_or_create(
                    title=market_data['title'],
                    defaults={
                        **market_data,
                        'creator': creator,
                        'market_type': 'event',
                        'resolution_date': django_timezone.now() + timedelta(days=30),
                        'round_start_time': django_timezone.now(),
                        'round_start_price': Decimal('67432.50') if 'BTC' in market_data['title'] else Decimal('3421.80'),
                        'status': 'active',
                        'current_round': 1,
                    }
                )
                if created:
                    created_markets.append(market)
                    logger.info(f"Created trending market: {market.title}")
                elif market.status == 'active':
                    # Update volume for existing active markets
                    market.total_volume = market_data['total_volume']
                    market.up_volume = market_data['up_volume'] 
                    market.down_volume = market_data['down_volume']
                    market.flat_volume = market_data['flat_volume']
                    market.save()
                    created_markets.append(market)
            
            return created_markets
            
        except Exception as e:
            logger.error(f"Error creating trending markets: {e}")
            return []


class StripePaymentService:
    """Service for handling Stripe payments with improved error handling"""
    
    def __init__(self):
        if not stripe.api_key:
            raise ValueError("Stripe API key not configured")
    
    def create_customer(self, user) -> Optional[str]:
        """Create or retrieve Stripe customer"""
        try:
            if user.stripe_customer_id:
                # Verify customer exists
                try:
                    stripe.Customer.retrieve(user.stripe_customer_id)
                    return user.stripe_customer_id
                except stripe.error.InvalidRequestError:
                    # Customer doesn't exist, create new one
                    logger.warning(f"Stripe customer {user.stripe_customer_id} not found, creating new one")
                    user.stripe_customer_id = None
            
            # Create new customer
            customer = stripe.Customer.create(
                email=user.email,
                name=getattr(user, 'full_name', f"{user.first_name} {user.last_name}".strip()),
                metadata={
                    'user_id': str(user.id),
                    'username': user.username
                }
            )
            
            # Save customer ID
            user.stripe_customer_id = customer.id
            user.save(update_fields=['stripe_customer_id'])
            
            return customer.id
            
        except Exception as e:
            logger.error(f"Error creating Stripe customer for user {user.id}: {e}")
            return None
    
    def create_payment_intent(self, amount: Decimal, user) -> Optional[Dict]:
        """Create payment intent for deposit with proper metadata"""
        try:
            customer_id = self.create_customer(user)
            if not customer_id:
                logger.error(f"Failed to create/retrieve customer for user {user.id}")
                return None
            
            # Convert to cents for Stripe
            amount_cents = int(amount * 100)
            
            # Create payment intent with comprehensive metadata
            intent = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency='usd',
                customer=customer_id,
                automatic_payment_methods={'enabled': True},
                metadata={
                    'user_id': str(user.id),
                    'username': user.username,
                    'type': 'wallet_deposit',
                    'amount_usd': str(amount),
                    'created_at': django_timezone.now().isoformat(),
                    'platform': 'evgxchain'
                },
                description=f'EVGxchain wallet deposit - ${amount} for user {user.username}',
                statement_descriptor_suffix='EVGXCHAIN DEPOSIT'
            )
            
            logger.info(f"Created payment intent {intent.id} for user {user.id}, amount ${amount}")
            
            return {
                'id': intent.id,
                'client_secret': intent.client_secret,
                'amount': amount_cents,
                'status': intent.status
            }
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error creating payment intent: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error creating payment intent for user {user.id}: {e}")
            return None
    
    def retrieve_payment_intent(self, payment_intent_id: str) -> Optional[Dict]:
        """Retrieve and validate payment intent"""
        try:
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            
            return {
                'id': intent.id,
                'status': intent.status,
                'amount': intent.amount,
                'currency': intent.currency,
                'metadata': intent.metadata,
                'created': intent.created
            }
            
        except stripe.error.InvalidRequestError as e:
            logger.error(f"Payment intent {payment_intent_id} not found: {e}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving payment intent {payment_intent_id}: {e}")
            return None


class FlexibleCoinremitterService:
    """
    Flexible Coinremitter service that can switch between TCN (testing) and USDT (production)
    Based on environment settings
    """
    
    def __init__(self):
        self.base_url = "https://coinremitter.com/api/v3"
        self.api_key = settings.COINREMITTER_API_KEY
        self.password = settings.COINREMITTER_PASSWORD
        
        # Environment detection
        self.is_testing = getattr(settings, 'COINREMITTER_TESTING_MODE', True)
        self.debug_mode = getattr(settings, 'DEBUG', True)
        
        # Configuration for different modes
        self.config = self._get_environment_config()
        
    def _get_environment_config(self):
        """Get configuration based on current environment"""
        
        if self.is_testing:
            # Testing mode - Use TCN
            return {
                'mode': 'testing',
                'coin_symbol': 'TCN',
                'display_name': 'TCN (Test Mode)',
                'min_amount': Decimal('0.01'),
                'network_fee': Decimal('0.01'),
                'network_name': 'Test Network',
                'confirmation_time': 'Instant (Test)',
                'supported_networks': {
                    'tcn': {
                        'coin_symbol': 'TCN',
                        'name': 'TCN Test Network',
                        'min_amount': Decimal('0.01'),
                        'network_fee': Decimal('0.01')
                    }
                }
            }
        else:
            # Production mode - Use USDT
            return {
                'mode': 'production',
                'coin_symbol': 'USDTTRC20',  # Default to TRC20 for lower fees
                'display_name': 'USDT',
                'min_amount': Decimal('1.00'),
                'network_fee': Decimal('1.00'),
                'network_name': 'TRC20',
                'confirmation_time': '1-5 minutes',
                'supported_networks': {
                    'trc20': {
                        'coin_symbol': 'USDTTRC20',
                        'name': 'USDT TRC20 (Tron)',
                        'min_amount': Decimal('1.00'),
                        'network_fee': Decimal('1.00')
                    },
                    'erc20': {
                        'coin_symbol': 'USDTERC20',
                        'name': 'USDT ERC20 (Ethereum)',
                        'min_amount': Decimal('10.00'),
                        'network_fee': Decimal('5.00')
                    }
                }
            }
    
    def get_current_mode_info(self) -> Dict:
        """Get information about current operating mode"""
        return {
            'mode': self.config['mode'],
            'coin_symbol': self.config['coin_symbol'],
            'display_name': self.config['display_name'],
            'is_testing': self.is_testing,
            'supported_networks': list(self.config['supported_networks'].keys()),
            'min_amount': self.config['min_amount'],
            'network_fee': self.config['network_fee']
        }
    
    def get_network_config(self, network: Optional[str] = None) -> Dict:
        """Get network configuration for the specified network"""
        if self.is_testing:
            # In testing mode, always use TCN regardless of network parameter
            return self.config['supported_networks']['tcn']
        else:
            # In production mode, use specified network or default to TRC20
            network = network or 'trc20'
            return self.config['supported_networks'].get(network.lower())
    
    def validate_address(self, wallet_address: str, network: Optional[str] = None) -> bool:
        """Validate wallet address based on current mode"""
        try:
            network_config = self.get_network_config(network)
            if not network_config:
                logger.error(f"Unsupported network: {network} in {self.config['mode']} mode")
                return False
            
            coin_symbol = network_config['coin_symbol']
            
            url = f"{self.base_url}/{coin_symbol}/validate-address"
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
            }
            
            data = {
                'api_key': self.api_key,
                'password': self.password,
                'address': wallet_address
            }
            
            mode_info = f"[{self.config['mode'].upper()}]"
            logger.info(f"{mode_info} Validating address with {coin_symbol}")
            
            response = requests.post(url, data=data, headers=headers, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"{mode_info} Address validation response: {result}")
                
                if result.get('flag') == 1:
                    return True
                else:
                    logger.warning(f"{mode_info} Address validation failed: {result.get('msg', 'Unknown error')}")
                    return False
            else:
                logger.error(f"{mode_info} HTTP error {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Address validation error in {self.config['mode']} mode: {e}")
            return False
    
    def send_withdrawal(self, address: str, amount: Decimal, user_id: str, network: Optional[str] = None) -> Dict:
        """Send withdrawal based on current mode"""
        try:
            network_config = self.get_network_config(network)
            if not network_config:
                return {
                    'success': False,
                    'error': f'Network not supported in {self.config["mode"]} mode'
                }
            
            coin_symbol = network_config['coin_symbol']
            mode_info = f"[{self.config['mode'].upper()}]"
            
            # Check minimum amount
            if amount < network_config['min_amount']:
                return {
                    'success': False,
                    'error': f'Minimum withdrawal for {network_config["name"]} is ${network_config["min_amount"]}'
                }
            
            url = f"{self.base_url}/{coin_symbol}/withdraw"
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
            }
            
            custom_id = f"{self.config['mode']}_user_{user_id}_{int(time.time())}"
            
            data = {
                'api_key': self.api_key,
                'password': self.password,
                'address': address,
                'amount': str(amount),
                'custom_id': custom_id
            }
            
            logger.info(f"{mode_info} Sending withdrawal: {amount} {coin_symbol} to {address[:10]}...{address[-6:]}")
            response = requests.post(url, data=data, headers=headers, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"{mode_info} Withdrawal response: {result}")
                
                if result.get('flag') == 1:
                    data_obj = result.get('data', {})
                    
                    success_result = {
                        'success': True,
                        'tx_hash': data_obj.get('txid'),
                        'tx_id': data_obj.get('id'),
                        'custom_id': custom_id,
                        'fee': data_obj.get('transaction_fees', 0),
                        'network': network_config['name'],
                        'explorer_url': data_obj.get('explorer_url'),
                        'mode': self.config['mode'],
                        'coin_symbol': coin_symbol
                    }
                    
                    # Add testing mode specific info
                    if self.is_testing:
                        success_result.update({
                            'testing_notice': 'This is a test transaction using TCN tokens',
                            'production_equivalent': f'In production, this would be {amount} USDT'
                        })
                    
                    return success_result
                else:
                    error_msg = result.get('msg', 'Withdrawal failed')
                    logger.error(f"{mode_info} Withdrawal failed: {error_msg}")
                    return {
                        'success': False,
                        'error': error_msg,
                        'mode': self.config['mode']
                    }
            else:
                logger.error(f"{mode_info} HTTP error {response.status_code}: {response.text}")
                return {
                    'success': False,
                    'error': f'Network error: HTTP {response.status_code}',
                    'mode': self.config['mode']
                }
                
        except Exception as e:
            logger.error(f"Withdrawal error in {self.config['mode']} mode: {e}")
            return {
                'success': False,
                'error': f'Processing error: {str(e)}',
                'mode': self.config['mode']
            }
    
    def get_balance(self, network: Optional[str] = None) -> Dict:
        """Get wallet balance for current mode"""
        try:
            network_config = self.get_network_config(network)
            if not network_config:
                return {
                    'success': False, 
                    'error': f'Network not supported in {self.config["mode"]} mode'
                }
            
            coin_symbol = network_config['coin_symbol']
            url = f"{self.base_url}/{coin_symbol}/get-balance"
            
            data = {
                'api_key': self.api_key,
                'password': self.password
            }
            
            response = requests.post(url, data=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get('flag') == 1:
                    balance_data = result.get('data', {})
                    return {
                        'success': True,
                        'balance': Decimal(str(balance_data.get('balance', 0))),
                        'network': network_config['name'],
                        'coin_symbol': coin_symbol,
                        'mode': self.config['mode']
                    }
                else:
                    return {
                        'success': False,
                        'error': result.get('msg', 'Failed to get balance'),
                        'mode': self.config['mode']
                    }
            else:
                return {
                    'success': False,
                    'error': f'HTTP error: {response.status_code}',
                    'mode': self.config['mode']
                }
                
        except Exception as e:
            logger.error(f"Balance check error in {self.config['mode']} mode: {e}")
            return {
                'success': False,
                'error': f'Balance check failed: {str(e)}',
                'mode': self.config['mode']
            }


class NewsService:
    """Service for fetching and managing crypto/economic news"""
    
    @staticmethod
    def get_market_news(limit: int = 10) -> List[Dict]:
        """Fetch recent market-moving news"""
        try:
            # Mock news data - in production, integrate with news APIs like:
            # - CryptoPanic API
            # - NewsAPI
            # - Coindesk API
            # - Bloomberg API
            
            news_items = [
                {
                    'title': 'Fed Chair Powell Hints at Policy Shift in Jackson Hole Speech',
                    'summary': 'Markets react to unexpected dovish tone regarding future rate decisions. BTC showing increased volatility.',
                    'impact_level': 'high',
                    'source': 'Federal Reserve',
                    'published_at': django_timezone.now() - timedelta(minutes=15),
                    'url': 'https://example.com/news/1',
                    'categories': ['monetary_policy', 'bitcoin']
                },
                {
                    'title': 'US CPI Data Release Scheduled for Tomorrow 8:30 AM EST',
                    'summary': 'Economists expect 0.2% monthly increase. Historical data shows 15-20% crypto volatility spike during CPI releases.',
                    'impact_level': 'medium',
                    'source': 'Bureau of Labor Statistics',
                    'published_at': django_timezone.now() - timedelta(hours=1),
                    'url': 'https://example.com/news/2',
                    'categories': ['economic_data', 'inflation']
                },
                {
                    'title': 'Bitcoin ETF Inflows Reach $2.1B This Week',
                    'summary': 'Institutional demand remains strong despite recent price consolidation. ETH ETF launches gaining momentum.',
                    'impact_level': 'low',
                    'source': 'ETF Analytics',
                    'published_at': django_timezone.now() - timedelta(hours=2),
                    'url': 'https://example.com/news/3',
                    'categories': ['etf', 'institutional']
                }
            ]
            
            return news_items[:limit]
            
        except Exception as e:
            logger.error(f"Error fetching market news: {e}")
            return []
    
    @staticmethod
    def analyze_news_sentiment(text: str) -> Dict:
        """Analyze sentiment of news text"""
        try:
            # Simple sentiment analysis - in production use:
            # - TextBlob
            # - VADER sentiment
            # - Custom ML model
            
            positive_words = ['bull', 'gain', 'rise', 'up', 'positive', 'growth', 'increase', 'rally']
            negative_words = ['bear', 'fall', 'down', 'negative', 'decline', 'crash', 'drop', 'sell']
            
            text_lower = text.lower()
            positive_count = sum(1 for word in positive_words if word in text_lower)
            negative_count = sum(1 for word in negative_words if word in text_lower)
            
            if positive_count > negative_count:
                sentiment = 'bullish'
                score = min(0.8, positive_count / (positive_count + negative_count + 1))
            elif negative_count > positive_count:
                sentiment = 'bearish'  
                score = min(0.8, negative_count / (positive_count + negative_count + 1))
            else:
                sentiment = 'neutral'
                score = 0.5
            
            return {
                'sentiment': sentiment,
                'score': score,
                'confidence': min(1.0, abs(positive_count - negative_count) / 10)
            }
            
        except Exception as e:
            logger.error(f"Error analyzing sentiment: {e}")
            return {'sentiment': 'neutral', 'score': 0.5, 'confidence': 0.1}


class RiskManagementService:
    """Service for managing trading risks and limits"""
    
    @staticmethod
    def calculate_user_risk_score(user) -> float:
        """Calculate user's risk score based on behavior"""
        try:
            from predict.models import Bet, UserStats
            
            # Get user stats
            try:
                stats = user.stats
            except UserStats.DoesNotExist:
                return 0.1  # Low risk for new users
            
            # Risk factors
            risk_factors = []
            
            # Win rate factor (lower win rate = higher risk)
            if stats.win_rate < Decimal('0.3'):
                risk_factors.append(0.3)
            elif stats.win_rate < Decimal('0.5'):
                risk_factors.append(0.2)
            else:
                risk_factors.append(0.1)
            
            # Volume factor (high volume relative to balance = higher risk)
            if user.balance > 0:
                volume_ratio = float(stats.total_wagered) / float(user.balance)
                if volume_ratio > 10:
                    risk_factors.append(0.4)
                elif volume_ratio > 5:
                    risk_factors.append(0.3)
                else:
                    risk_factors.append(0.1)
            
            # Recent activity factor
            recent_bets = Bet.objects.filter(
                user=user,
                placed_at__gte=django_timezone.now() - timedelta(days=7)
            ).count()
            
            if recent_bets > 50:
                risk_factors.append(0.3)
            elif recent_bets > 20:
                risk_factors.append(0.2)
            else:
                risk_factors.append(0.1)
            
            # Calculate final score
            risk_score = sum(risk_factors) / len(risk_factors) if risk_factors else 0.1
            return min(1.0, risk_score)
            
        except Exception as e:
            logger.error(f"Error calculating risk score: {e}")
            return 0.5  # Default moderate risk
    
    @staticmethod
    def check_bet_limits(user, bet_amount: Decimal, market) -> Dict:
        """Check if bet is within user's limits"""
        try:
            risk_score = RiskManagementService.calculate_user_risk_score(user)
            
            # Base limits
            max_bet_percentage = Decimal('0.1')  # 10% of balance
            if risk_score > 0.7:
                max_bet_percentage = Decimal('0.05')  # 5% for high risk users
            elif risk_score < 0.3:
                max_bet_percentage = Decimal('0.2')  # 20% for low risk users
            
            max_allowed = user.balance * max_bet_percentage
            
            # Daily limit check
            daily_volume = Bet.objects.filter(
                user=user,
                placed_at__gte=django_timezone.now() - timedelta(days=1)
            ).aggregate(
                total=models.Sum('amount')
            )['total'] or Decimal('0')
            
            daily_limit = user.balance * Decimal('0.5')  # 50% daily limit
            
            checks = {
                'within_balance': bet_amount <= user.balance,
                'within_single_bet_limit': bet_amount <= max_allowed,
                'within_daily_limit': (daily_volume + bet_amount) <= daily_limit,
                'within_market_limits': market.min_bet <= bet_amount <= market.max_bet,
                'risk_score': risk_score,
                'max_allowed_bet': float(max_allowed),
                'daily_remaining': float(daily_limit - daily_volume)
            }
            
            checks['all_passed'] = all([
                checks['within_balance'],
                checks['within_single_bet_limit'], 
                checks['within_daily_limit'],
                checks['within_market_limits']
            ])
            
            return checks
            
        except Exception as e:
            logger.error(f"Error checking bet limits: {e}")
            return {
                'all_passed': False,
                'error': 'Unable to verify bet limits'
            }


class WebhookService:
    """Service for handling payment webhooks"""
    
    @staticmethod
    def handle_stripe_webhook(payload: str, sig_header: str) -> Dict:
        """Handle Stripe webhook events"""
        try:
            endpoint_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', '')
            if not endpoint_secret:
                return {'success': False, 'error': 'Webhook secret not configured'}
            
            # Verify webhook signature
            event = stripe.Webhook.construct_event(
                payload, sig_header, endpoint_secret
            )
            
            # Handle the event
            if event['type'] == 'payment_intent.succeeded':
                payment_intent = event['data']['object']
                return WebhookService._handle_payment_success(payment_intent)
            
            elif event['type'] == 'payment_intent.payment_failed':
                payment_intent = event['data']['object']
                return WebhookService._handle_payment_failed(payment_intent)
            
            else:
                return {'success': True, 'message': f'Unhandled event type: {event["type"]}'}
            
        except stripe.error.SignatureVerificationError:
            return {'success': False, 'error': 'Invalid signature'}
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def _handle_payment_success(payment_intent: Dict) -> Dict:
        """Handle successful payment"""
        try:
            from predict.models import Transaction
            from acounts.models import CustomUser
            from django.db import transaction as db_transaction
            
            # Get transaction by payment intent ID
            try:
                transaction = Transaction.objects.get(
                    stripe_payment_intent_id=payment_intent['id'],
                    status='pending'
                )
            except Transaction.DoesNotExist:
                logger.error(f"Transaction not found for payment intent: {payment_intent['id']}")
                return {'success': False, 'error': 'Transaction not found'}
            
            # FIXED: Use database transaction to ensure consistency
            with db_transaction.atomic():
                # Update user balance - CRUCIAL FIX
                user = transaction.user
                user.balance += transaction.amount
                user.save(update_fields=['balance'])
                
                # Update transaction record
                transaction.status = 'completed'
                transaction.balance_after = user.balance
                transaction.completed_at = django_timezone.now()
                transaction.save(update_fields=['status', 'balance_after', 'completed_at'])
                
                # Award XP for deposit
                user.add_xp(10)
            
            return {
                'success': True,
                'message': f'Payment processed for user {user.username}',
                'amount': float(transaction.amount),
                'new_balance': float(user.balance)
            }
            
        except Exception as e:
            logger.error(f"Error handling payment success: {e}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def _handle_payment_failed(payment_intent: Dict) -> Dict:
        """Handle failed payment"""
        try:
            from predict.models import Transaction
            
            # Update transaction status
            transaction = Transaction.objects.get(
                stripe_payment_intent_id=payment_intent['id']
            )
            transaction.status = 'failed'
            transaction.save()
            
            return {
                'success': True,
                'message': f'Payment failure recorded for transaction {transaction.id}'
            }
            
        except Transaction.DoesNotExist:
            return {'success': False, 'error': 'Transaction not found'}
        except Exception as e:
            logger.error(f"Error handling payment failure: {e}")
            return {'success': False, 'error': str(e)}


class DataSyncService:
    """Main service to coordinate all data synchronization"""
    
    @staticmethod
    def sync_all_data():
        """Sync all external data - news, events, markets"""
        logger.info("Starting full data sync...")
        
        # Sync news articles
        try:
            news_articles = CryptoPanicNewsService.fetch_and_store_news()
            logger.info(f"Synced {len(news_articles)} news articles")
        except Exception as e:
            logger.error(f"Error syncing news: {e}")
        
        # Sync economic events
        try:
            events = EconomicCalendarService.fetch_and_store_events()
            logger.info(f"Synced {len(events)} economic events")
        except Exception as e:
            logger.error(f"Error syncing events: {e}")
        
        # Create/update trending markets
        try:
            markets = MarketDataManager.create_trending_markets()
            logger.info(f"Synced {len(markets)} trending markets")
        except Exception as e:
            logger.error(f"Error syncing markets: {e}")
        
        # Cleanup old data
        try:
            EconomicCalendarService.cleanup_old_events()
            logger.info("Cleaned up old events")
        except Exception as e:
            logger.error(f"Error cleaning up: {e}")
        
        logger.info("Data sync completed")



class MarketDataService:
    """Service for market-specific calculations and data"""
    
    @staticmethod
    def get_round_time_remaining(market) -> int:
        """Calculate remaining time in current round (seconds)"""
        try:
            if not hasattr(market, 'round_start_time') or not market.round_start_time:
                return getattr(market, 'round_duration', 900)
            
            elapsed = (django_timezone.now() - market.round_start_time).total_seconds()
            remaining = getattr(market, 'round_duration', 900) - elapsed
            
            return max(0, int(remaining))
            
        except Exception:
            return getattr(market, 'round_duration', 900) if hasattr(market, 'round_duration') else 900
    
    @staticmethod
    def get_round_info(market) -> Dict:
        """Get comprehensive round information"""
        try:
            time_remaining = MarketDataService.get_round_time_remaining(market)
            
            return {
                'round_number': getattr(market, 'current_round', 1),
                'time_remaining': time_remaining,
                'total_volume': float(getattr(market, 'total_volume', 0)),
                'participants': market.get_participant_count() if hasattr(market, 'get_participant_count') else 0,
                'duration': getattr(market, 'round_duration', 900),
                'start_price': float(getattr(market, 'round_start_price', 0)) if getattr(market, 'round_start_price', 0) else None,
            }
        except Exception as e:
            logger.error(f"Error calculating round info: {e}")
            return {
                'round_number': 1,
                'time_remaining': 900,
                'total_volume': 0,
                'participants': 0,
                'duration': 900,
                'start_price': None
            }
    
    @staticmethod
    def calculate_volatility(prices: List[float], window: int = 24) -> float:
        """Calculate price volatility over a time window"""
        try:
            if len(prices) < 2:
                return 0.0
            
            # Calculate percentage changes
            changes = []
            for i in range(1, min(len(prices), window + 1)):
                if prices[i-1] != 0:
                    change = (prices[i] - prices[i-1]) / prices[i-1]
                    changes.append(change)
            
            if not changes:
                return 0.0
            
            # Standard deviation of changes
            mean_change = sum(changes) / len(changes)
            variance = sum((x - mean_change) ** 2 for x in changes) / len(changes)
            volatility = variance ** 0.5
            
            return volatility * 100  # Return as percentage
            
        except Exception as e:
            logger.error(f"Error calculating volatility: {e}")
            return 0.0

class PriceTargetMarketService:
    
    @staticmethod
    def create_target_market(
        creator,
        crypto_symbol,
        target_price,
        end_date=None
    ):
        """Create a new price target market with HTML-formatted description"""
        
        try:
            logger.info(f"Creating target market: symbol={crypto_symbol}, target={target_price}")
            
            # Get current price
            crypto_prices = CryptoPriceService.get_crypto_prices()
            current_price = crypto_prices.get(crypto_symbol, {}).get('price', 0)
            
            if not current_price:
                raise ValueError(f"Unable to get current price for {crypto_symbol}")
            
            current_price = Decimal(str(current_price))
            target_price = Decimal(str(target_price))
            
            logger.info(f"Current price: ${current_price}, Target: ${target_price}")
            
            # Calculate end date if not provided
            if not end_date:
                now = timezone.now()
                if now.month == 12:
                    next_month = now.replace(year=now.year + 1, month=1, day=1)
                else:
                    next_month = now.replace(month=now.month + 1, day=1)
                
                end_date = next_month - timedelta(days=1)
                end_date = end_date.replace(hour=23, minute=59, second=59)
            
            logger.info(f"End date: {end_date}")
            
            # Get or create category
            category_type = 'bitcoin' if crypto_symbol == 'BTC' else 'ethereum' if crypto_symbol == 'ETH' else 'altcoins'
            
            try:
                category = CryptocurrencyCategory.objects.get(category_type=category_type)
                logger.info(f"Using existing category: {category.display_name}")
            except CryptocurrencyCategory.DoesNotExist:
                category = CryptocurrencyCategory.objects.create(
                    category_type=category_type,
                    display_name=f'{crypto_symbol} Price Targets',
                    description=f'Binary price target predictions for {crypto_symbol}',
                    icon='🎯',
                    color_code='#F7931A' if crypto_symbol == 'BTC' else '#627EEA',
                    is_active=True
                )
                logger.info(f"Created new category: {category.display_name}")
            
            # Determine if target is above or below current price
            direction = "reach" if target_price > current_price else "fall below"
            percent_change = abs((target_price - current_price) / current_price * 100)
            
            # Create HTML-formatted description (no Markdown asterisks)
            description = f"""
    <div class="market-description">
        <div class="price-info">
            <p><strong>Current Price:</strong> ${current_price:,.2f}</p>
            <p><strong>Target Price:</strong> ${target_price:,.0f}</p>
            <p><strong>Required Change:</strong> {percent_change:.1f}%</p>
            <p><strong>Deadline:</strong> {end_date.strftime('%B %d, %Y at %I:%M %p UTC')}</p>
        </div>

        <div class="how-it-works">
            <h3>How it works:</h3>
            <ul>
                <li>Vote <strong>YES</strong> if you think {crypto_symbol} will {direction} ${target_price:,.0f} before the deadline</li>
                <li>Vote <strong>NO</strong> if you think it won't reach this price</li>
                <li>Market resolves <strong>YES</strong> if {crypto_symbol} touches or exceeds ${target_price:,.0f} at any point before deadline</li>
                <li>Market resolves <strong>NO</strong> if deadline passes without reaching target</li>
            </ul>
        </div>

        <div class="resolution-criteria">
            <h3>Resolution Criteria:</h3>
            <ul>
                <li>Using CoinGecko API price data</li>
                <li>Checked automatically every hour</li>
                <li>First touch of target price wins</li>
                <li>No need to close above target - just needs to reach it</li>
            </ul>
        </div>
    </div>
    """.strip()
            
            # Create market
            market_data = {
                'title': f"Will {crypto_symbol} {direction} ${target_price:,.0f} before {end_date.strftime('%B %d, %Y')}?",
                'description': description,
                'market_type': 'target',
                'creator': creator,
                'category': category,
                'base_currency': crypto_symbol,
                'quote_currency': 'USDT',
                'target_price': target_price,
                'highest_price_reached': current_price,
                'round_start_price': current_price,
                'resolution_date': end_date,
                'round_start_time': timezone.now(),
                'total_volume': Decimal('0'),
                'up_volume': Decimal('0'),
                'down_volume': Decimal('0'),
                'flat_volume': Decimal('0'),
                'min_bet': Decimal('1.00'),
                'max_bet': Decimal('10000.00'),
                'round_duration': 0,
                'current_round': 1,
                'status': 'active'
            }
            
            logger.info(f"Creating Market object with data: title={market_data['title']}")
            
            market = Market.objects.create(**market_data)
            
            logger.info(f"✅ Market created successfully: ID={market.id}")
            
            return market
            
        except Exception as e:
            logger.error(f"❌ Error in create_target_market: {str(e)}", exc_info=True)
            raise  
    
    @staticmethod
    def check_target_reached(market):
        """
        Check if target price has been reached
        Returns: (bool, Decimal) - (reached, current_price)
        """
        from decimal import Decimal
        
        if market.market_type != 'target':
            raise ValueError("Market is not a price target market")
        
        # Get current price
        crypto_prices = CryptoPriceService.get_crypto_prices()
        current_price = crypto_prices.get(market.base_currency, {}).get('price', 0)
        
        if not current_price:
            return False, None
        
        current_price = Decimal(str(current_price))
        
        # Update highest price reached
        if not market.highest_price_reached or current_price > market.highest_price_reached:
            market.highest_price_reached = current_price
            market.save(update_fields=['highest_price_reached'])
        
        # Check if target reached
        target_reached = market.highest_price_reached >= market.target_price
        
        return target_reached, current_price
    
    @staticmethod
    def resolve_target_market(market):
        """
        Resolve a price target market
        Call this when resolution_date is passed OR target is reached early
        """
        from django.utils import timezone
        from decimal import Decimal
        
        if market.status != 'active':
            logger.warning(f"Market {market.id} is not active (status: {market.status})")
            return
        
        if market.market_type != 'target':
            raise ValueError("Market is not a price target market")
        
        # Determine outcome
        target_reached, final_price = PriceTargetMarketService.check_target_reached(market)
        
        winning_outcome = 'UP' if target_reached else 'DOWN'  # UP = YES, DOWN = NO
        
        # Close market
        market.status = 'resolved'
        market.winning_outcome = winning_outcome
        market.resolved_at = timezone.now()
        market.round_end_price = final_price
        market.save()
        
        # Resolve all bets
        from predict.models import Bet, Transaction
        winning_bets = Bet.objects.filter(
            market=market,
            outcome=winning_outcome,
            status='active'
        )
        
        losing_bets = Bet.objects.filter(
            market=market,
            status='active'
        ).exclude(outcome=winning_outcome)
        
        total_pool = market.total_volume
        winning_pool = market.up_volume if winning_outcome == 'UP' else market.down_volume
        
        # Pay winners
        for bet in winning_bets:
            # Recalculate actual payout based on final pool
            if winning_pool > 0:
                bet.actual_payout = (bet.amount / winning_pool) * total_pool
            else:
                bet.actual_payout = bet.potential_payout  # Fallback
            
            bet.status = 'won'
            bet.resolved_at = timezone.now()
            bet.save()
            
            # Credit user
            user = bet.user
            old_balance = user.balance
            user.balance += bet.actual_payout
            user.save()
            
            # Create transaction
            Transaction.objects.create(
                user=user,
                transaction_type='payout',
                amount=bet.actual_payout,
                balance_before=old_balance,
                balance_after=user.balance,
                status='completed',
                bet=bet,
                market=market,
                description=f'Payout for winning {"YES" if winning_outcome == "UP" else "NO"} bet on {market.title[:50]}...'
            )
            
            # Award XP
            user.add_xp(50)
        
        # Mark losers
        for bet in losing_bets:
            bet.status = 'lost'
            bet.actual_payout = Decimal('0')
            bet.resolved_at = timezone.now()
            bet.save()
        
        logger.info(
            f"Resolved target market {market.id}: {winning_outcome} "
            f"({winning_bets.count()} winners, {losing_bets.count()} losers) "
            f"Target: ${market.target_price}, Highest: ${market.highest_price_reached}"
        )
        
        return market
    
    @staticmethod
    def get_active_target_markets():
        """Get all active price target markets"""
        from market.models import Market
        
        return Market.objects.filter(
            market_type='target',
            status='active'
        ).select_related('category', 'creator').order_by('resolution_date')
    
    @staticmethod
    def get_user_target_bets(user):
        """Get user's bets on target markets"""
        from predict.models import Bet
        
        return Bet.objects.filter(
            user=user,
            market__market_type='target'
        ).select_related('market').order_by('-placed_at')
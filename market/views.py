from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, Sum
from django.http import JsonResponse,HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.views.generic import View
from django.utils import timezone
from datetime import timedelta
import os
import json
import stripe
from django.views.decorators.http import require_POST
from .models import Market, CryptocurrencyCategory, EconomicEvent
from acounts.models import CustomUser, ReferralProfile, ReferralTransaction
from acounts.referral_service import ReferralService
from predict.models import NewsArticle
from decimal import Decimal, InvalidOperation
from django.views.decorators.csrf import csrf_protect
from .utils import *
from django.conf import settings
from predict.models import Bet, Transaction, UserStats
from django.db import transaction as db_transaction
from .b2binpay_service import B2BinPayService, VirtualWalletService
from .wallet_service import WalletTransferService
from django.contrib.admin.views.decorators import staff_member_required
import logging
import traceback
from dotenv import load_dotenv
load_dotenv() 

logger = logging.getLogger(__name__)

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

@login_required
def marketPage(request):
    """Main market listing page with filters and real-time data"""
    
    # Trigger data sync if data is empty (for first-time setup)
    _ensure_data_exists()
    
    # Get filter parameters
    category_filter = request.GET.get('category', 'all')
    search_query = request.GET.get('search', '')
    sort_by = request.GET.get('sort', 'popular')
    
    # Base queryset - active markets only
    markets = Market.objects.filter(
        status='active'
    ).select_related('category', 'creator')
    
    # Apply filters
    if category_filter != 'all':
        markets = markets.filter(category__category_type=category_filter)
    
    if search_query:
        markets = markets.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(base_currency__icontains=search_query) |
            Q(quote_currency__icontains=search_query)
        )
    
    # Apply sorting
    if sort_by == 'newest':
        markets = markets.order_by('-created_at')
    elif sort_by == 'ending-soon':
        markets = markets.order_by('resolution_date')
    elif sort_by == 'highest-volume':
        markets = markets.order_by('-total_volume')
    else:  # popular
        markets = markets.order_by('-total_volume', '-created_at')
    
    # Get trending markets (highest volume in last 24h)
    trending_markets = Market.objects.filter(
        status='active',
        created_at__gte=timezone.now() - timedelta(days=1)
    ).order_by('-total_volume')[:3]
    
    # If no trending markets, get top 3 by volume
    if not trending_markets:
        trending_markets = Market.objects.filter(
            status='active'
        ).order_by('-total_volume')[:3]
    
    print(f"Trending markets found: {trending_markets.count()}")
    
    # Get categories for filters
    categories = CryptocurrencyCategory.objects.filter(is_active=True)
    
    # Get real-time crypto prices
    crypto_prices = CryptoPriceService.get_crypto_prices()
    
    # Get recent news articles (active only)
    recent_news = NewsArticle.objects.filter(
        is_active=True,
        published_at__gte=timezone.now() - timedelta(hours=48)  # Extended to 48 hours
    ).order_by('-published_at')[:3]
    
    print(f"Recent news found: {recent_news.count()}")
    
    # Get upcoming economic events
    upcoming_events = EconomicEvent.objects.filter(
        scheduled_time__gt=timezone.now(),
        is_active=True
    ).order_by('scheduled_time')[:5]
    
    print(f"Upcoming events found: {upcoming_events.count()}")
    
    # Enhanced market data calculation
    for market in markets:
        market.participant_count = market.get_participant_count()
        market.time_remaining = max(0, (market.resolution_date - timezone.now()).days)
        
        # Add crypto price data if relevant
        market.crypto_data = None
        trading_pair = market.trading_pair
        for symbol, data in crypto_prices.items():
            if symbol in trading_pair or symbol.lower() in market.title.lower():
                market.crypto_data = data
                break
        
        # Calculate round info
        market.current_round_time_left = MarketDataService.get_round_time_remaining(market)
    
    context = {
        'markets': markets[:8],  # Limit for performance
        'trending_markets': trending_markets,
        'categories': categories,
        'crypto_prices': crypto_prices,
        'recent_news': recent_news,
        'upcoming_events': upcoming_events,
        'current_category': category_filter,
        'search_query': search_query,
        'sort_by': sort_by,
        'total_markets': markets.count(),
    }
    
    return render(request, 'market_list.html', context)


def _ensure_data_exists():
    """Ensure basic data exists, sync if not"""
    try:
        from .utils import DataSyncService
        
        # Check if we have recent news
        recent_news_count = NewsArticle.objects.filter(
            is_active=True,
            published_at__gte=timezone.now() - timedelta(hours=24)
        ).count()
        
        # Check if we have upcoming events
        upcoming_events_count = EconomicEvent.objects.filter(
            scheduled_time__gt=timezone.now(),
            is_active=True
        ).count()
        
        # Check if we have active markets
        active_markets_count = Market.objects.filter(status='active').count()
        
        # If any data is missing, trigger sync
        if recent_news_count == 0 or upcoming_events_count == 0 or active_markets_count == 0:
            print("Data missing, triggering sync...")
            DataSyncService.sync_all_data()
    
    except Exception as e:
        print(f"Error ensuring data exists: {e}")
        # Continue without failing the view

@login_required
def marketDetail(request, market_id=None):
    """Market detail page with betting functionality"""
    
    # Get or create default BTC/USDT market for demo
    try:
        if market_id:
            market = get_object_or_404(Market, id=market_id, status='active')
        else:
            # Try to get an existing BTC market or create one
            market = Market.objects.filter(
                title__icontains="BTC",
                status='active'
            ).first()
            
            if not market:
                # Ensure we have markets
                _ensure_data_exists()
                market = Market.objects.filter(status='active').first()
                
            if not market:
                # Create fallback market
                from acounts.models import CustomUser
                creator, _ = CustomUser.objects.get_or_create(
                    username='system_creator',
                    defaults={
                        'email': 'system@evgxchain.com',
                        'balance': Decimal('1000000.00')
                    }
                )
                
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
                
                market = Market.objects.create(
                    title="BTC/USDT Price Prediction",
                    description="Trade on Bitcoin vs USDT price movements with economic events: CPI, FOMC, NFP releases",
                    market_type='price',
                    creator=creator,
                    category=btc_category,
                    base_currency="BTC",
                    quote_currency="USDT",
                    resolution_date=timezone.now() + timedelta(days=30),
                    round_duration=900,  # 15 minutes
                    total_volume=Decimal('105000.00'),
                    up_volume=Decimal('52000.00'),
                    down_volume=Decimal('26500.00'),
                    flat_volume=Decimal('26500.00'),
                    status='active',
                    current_round=1,
                    round_start_time=timezone.now(),
                    round_start_price=Decimal('67432.50')
                )
                
    except Exception as e:
        print(f"Error getting market: {e}")
        # Fallback market data for display
        class MockMarket:
            id = "demo"
            title = "BTC/USDT Price Prediction"
            description = "Trade on Bitcoin vs USDT price movements with economic events"
            trading_pair = "BTC/USDT"
            total_volume = Decimal('105000')
            up_volume = Decimal('52000')
            down_volume = Decimal('26500')
            flat_volume = Decimal('26500')
            round_duration = 900
            min_bet = Decimal('1.00')
            max_bet = Decimal('10000.00')
            
            def get_participant_count(self):
                return 210
                
            @property
            def up_odds(self):
                return Decimal('2.02')
            @property 
            def down_odds(self):
                return Decimal('3.96')
            @property
            def flat_odds(self):
                return Decimal('3.96')
        
        market = MockMarket()
    
    # Get user's existing bets on this market
    user_bets = []
    if request.user.is_authenticated and hasattr(market, 'bets'):
        user_bets = market.bets.filter(
            user=request.user,
            status='active'
        ).order_by('-placed_at')
    
    # Get market statistics
    total_bets = getattr(market, 'bets', type('obj', (object,), {'filter': lambda *args, **kwargs: type('obj', (object,), {'count': lambda: 156})()})).filter(status='active').count() if hasattr(market, 'bets') else 156
    unique_participants = market.get_participant_count() if hasattr(market, 'get_participant_count') else 210
    
    # Get recent bets (anonymized for privacy)
    recent_bets = []
    if hasattr(market, 'bets'):
        recent_bets = market.bets.filter(status='active').select_related('user')[:10]
    
    # Get real-time crypto prices
    crypto_prices = CryptoPriceService.get_crypto_prices()
    
    # Get market crypto data
    market_crypto_data = None
    trading_pair = getattr(market, 'trading_pair', 'BTC/USDT')
    for symbol, data in crypto_prices.items():
        if symbol.lower() in trading_pair.lower():
            market_crypto_data = data
            break
    
    # Calculate round information
    round_info = MarketDataService.get_round_info(market)
    
    context = {
        'market': market,
        'user_bets': user_bets,
        'total_bets': total_bets,
        'unique_participants': unique_participants, 
        'recent_bets': recent_bets,
        'crypto_prices': crypto_prices,
        'market_crypto_data': market_crypto_data,
        'round_info': round_info,
        'user_balance': request.user.balance if request.user.is_authenticated else Decimal('0'),
    }
    context.update({
        'predict_timeframes': ['1m', '2m', '3m'],
        'predict_multipliers': {
            'UP': Decimal('1.95'),
            'FLAT': Decimal('3.20'), 
            'DOWN': Decimal('1.98')
        },
        'quick_bet_amount': Decimal('1.00'),
    })
    
    return render(request, 'market_detail.html', context)


@login_required 
def userPortfolio(request):
    """User's betting portfolio and statistics dashboard"""
    
    # Get user's active bets
    active_bets = Bet.objects.filter(
        user=request.user,
        status='active'
    ).select_related('market').order_by('-placed_at')[:20]
    
    # Get user's bet history
    bet_history = Bet.objects.filter(
        user=request.user,
        status__in=['won', 'lost']
    ).select_related('market').order_by('-resolved_at')[:20]
    
    # Get or create user stats
    user_stats, created = UserStats.objects.get_or_create(
        user=request.user,
        defaults={
            'total_bets': 0,
            'won_bets': 0,
            'lost_bets': 0,
            'total_wagered': Decimal('0'),
            'total_winnings': Decimal('0'),
            'win_rate': Decimal('0'),
        }
    )
    
    # Update stats if needed
    if created or user_stats.last_updated < timezone.now() - timedelta(hours=1):
        user_stats.update_stats()
    
    # Calculate portfolio metrics
    potential_winnings = sum([bet.potential_payout for bet in active_bets])
    total_active_bets = sum([bet.amount for bet in active_bets])
    
    # Get recent transactions
    recent_transactions = Transaction.objects.filter(
        user=request.user,
        status='completed'
    ).order_by('-created_at')[:10]
    
    deposits = Transaction.objects.filter(
        user=request.user,
        transaction_type='deposit',
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    withdrawals = Transaction.objects.filter(
        user=request.user,
        transaction_type='withdrawal',
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    bets_placed = Transaction.objects.filter(
        user=request.user,
        transaction_type='bet',
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')  # This will be negative
    
    payouts = Transaction.objects.filter(
        user=request.user,
        transaction_type='payout',
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    bonuses = Transaction.objects.filter(
        user=request.user,
        transaction_type='bonus',
        status='completed'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    # Calculate real balance: deposits + payouts + bonuses - withdrawals + bets_placed (bets_placed is negative)
    calculated_balance = deposits + payouts + bonuses - withdrawals + bets_placed
    
    # Update user balance if different
    if abs(request.user.balance - calculated_balance) > Decimal('0.01'):
        request.user.balance = calculated_balance
        request.user.save(update_fields=['balance'])
    
    bet_xp = user_stats.total_bets * 10  # 10 XP per bet
    deposit_xp = deposits // Decimal('10') * 5  # 5 XP per $10 deposited
    win_xp = user_stats.won_bets * 25  # 25 XP per win
    
    calculated_xp = int(bet_xp + deposit_xp + win_xp)
    
    # Update user XP if different
    if request.user.xp != calculated_xp:
        request.user.xp = calculated_xp
        request.user.save(update_fields=['xp'])
    
    # Calculate level progress
    current_xp = request.user.xp
    next_level_xp = request.user.get_xp_for_next_level()
    xp_progress = (current_xp / next_level_xp * 100) if next_level_xp > 0 else 100
    
    # Get trending markets for recommendations
    trending_markets = Market.objects.filter(
        status='active'
    ).order_by('-total_volume')[:3]
    
    context = {
        'user_stats': user_stats,
        'active_bets': active_bets,
        'bet_history': bet_history,
        'recent_transactions': recent_transactions,
        'potential_winnings': potential_winnings,
        'total_active_bets': total_active_bets,
        'xp_progress': min(xp_progress, 100),
        'next_level_xp': next_level_xp,
        'level_title': request.user.get_level_title(),
        'trending_markets': trending_markets,
        'user_balance': request.user.balance,  # FIXED: Use actual user balance instead of deposits
        'user_xp': request.user.xp,
        'calculated_balance': calculated_balance,
        'deposits_total': deposits,
        'withdrawals_total': withdrawals,
        'bets_total': abs(bets_placed),  # Show as positive for display
        'payouts_total': payouts,
        'bonuses_total': bonuses,
        'settings': settings,
    }
    
    return render(request, 'profile.html', context)


@login_required
def get_wallet_balance(request):
    try:
        balance = VirtualWalletService.get_wallet_balance(request.user)
        
        # Get recent transactions
        recent_transactions = Transaction.objects.filter(
            user=request.user
        ).order_by('-created_at')[:10]
        
        transactions_data = [{
            'id': str(txn.id),
            'type': txn.transaction_type,
            'amount': float(txn.amount),
            'status': txn.status,
            'description': txn.description,
            'created_at': txn.created_at.isoformat(),
            'balance_after': float(txn.balance_after)
        } for txn in recent_transactions]
        
        return JsonResponse({
            'success': True,
            'balance': float(balance),
            'currency': 'USD',
            'recent_transactions': transactions_data
        })
        
    except Exception as e:
        logger.error(f"Error fetching wallet balance: {e}")
        return JsonResponse({'success': False, 'error': str(e)})
    

@login_required
def wallet_dashboard(request):
    try:
        # Get wallet balance
        balance = VirtualWalletService.get_wallet_balance(request.user)
        
        # Get transaction history
        transactions = Transaction.objects.filter(
            user=request.user
        ).order_by('-created_at')[:50]
        
        # Calculate statistics
        total_deposits = Transaction.objects.filter(
            user=request.user,
            transaction_type='deposit',
            status='completed'
        ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
        
        total_withdrawals = abs(Transaction.objects.filter(
            user=request.user,
            transaction_type='withdrawal',
            status='completed'
        ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0'))
        
        total_transfers_sent = abs(Transaction.objects.filter(
            user=request.user,
            transaction_type='transfer',
            amount__lt=0,
            status='completed'
        ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0'))
        
        total_transfers_received = Transaction.objects.filter(
            user=request.user,
            transaction_type='transfer',
            amount__gt=0,
            status='completed'
        ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
        
        context = {
            'balance': balance,
            'transactions': transactions,
            'total_deposits': total_deposits,
            'total_withdrawals': total_withdrawals,
            'total_transfers_sent': total_transfers_sent,
            'total_transfers_received': total_transfers_received,
            'pending_deposits': Transaction.objects.filter(
                user=request.user,
                transaction_type='deposit',
                status='pending'
            ).count()
        }
        
        return render(request, 'wallet_dashboard.html', context)
        
    except Exception as e:
        logger.error(f"Wallet dashboard error: {e}")
        messages.error(request, 'Error loading wallet dashboard')
        return redirect('dashboard')
    
    
@login_required 
def place_bet(request):
    """Enhanced bet placement with predict-to-earn support (without model changes)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    
    try:
        data = json.loads(request.body)
        market_id = data.get('market_id')
        outcome = data.get('outcome')  # UP, DOWN, FLAT
        amount = Decimal(str(data.get('amount', 0)))
        bet_type = data.get('bet_type', 'regular')  # regular, quick_predict
        timeframe = data.get('timeframe', '15m')  # For predict-to-earn
        
        # Validation
        if not all([market_id, outcome, amount]):
            return JsonResponse({'success': False, 'error': 'Missing required fields'})
        
        if outcome not in ['UP', 'DOWN', 'FLAT']:
            return JsonResponse({'success': False, 'error': 'Invalid outcome'})
        
        # Predict-to-earn specific validations
        if bet_type == 'quick_predict':
            if amount != Decimal('1.00'):
                return JsonResponse({'success': False, 'error': 'Quick predict bets must be exactly $1.00'})
            
            if timeframe not in ['1m', '2m', '3m']:
                return JsonResponse({'success': False, 'error': 'Invalid predict timeframe'})
        else:
            # Regular bet validations
            if amount < Decimal('1.00'):
                return JsonResponse({'success': False, 'error': 'Minimum bet is $1.00'})
        
        if amount > request.user.balance:
            return JsonResponse({'success': False, 'error': 'Insufficient balance'})
        
        # Get market
        try:
            market = Market.objects.get(id=market_id, status='active')
        except Market.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Market not found'})
        
        # Check if user has active predict-to-earn bet (limit one at a time)
        if bet_type == 'quick_predict':
            # Use existing bet_type field - map quick_predict to 'quick'
            existing_predict_bet = Bet.objects.filter(
                user=request.user,
                market=market,
                bet_type='quick',  # Use existing 'quick' type
                status='active'
            ).exists()
            
            if existing_predict_bet:
                return JsonResponse({
                    'success': False, 
                    'error': 'You already have an active predict-to-earn bet on this market'
                })
        
        # Calculate odds and timeframe-specific multipliers
        if bet_type == 'quick_predict':
            # Special multipliers for predict-to-earn based on timeframe
            multipliers = {
                '1m': {'UP': Decimal('1.85'), 'FLAT': Decimal('4.50'), 'DOWN': Decimal('1.90')},
                '2m': {'UP': Decimal('1.95'), 'FLAT': Decimal('3.20'), 'DOWN': Decimal('1.98')},
                '3m': {'UP': Decimal('2.10'), 'FLAT': Decimal('2.80'), 'DOWN': Decimal('2.05')}
            }
            odds = multipliers.get(timeframe, multipliers['2m']).get(outcome, Decimal('2.00'))
        else:
            # Regular market odds
            if outcome == 'UP':
                odds = market.up_odds
            elif outcome == 'DOWN':
                odds = market.down_odds
            else:  # FLAT
                odds = market.flat_odds
        
        potential_payout = amount * odds
        
        # Calculate resolution time for predict-to-earn (store in description)
        resolution_time = None
        description_suffix = ""
        if bet_type == 'quick_predict':
            timeframe_seconds = {
                '1m': 60,
                '2m': 120,
                '3m': 180
            }
            resolution_time = timezone.now() + timedelta(seconds=timeframe_seconds[timeframe])
            description_suffix = f" (Predict-to-earn {timeframe}, resolves at {resolution_time.strftime('%H:%M:%S')})"
        
        # Create bet within transaction
        with db_transaction.atomic():
            # Store old balance for transaction record
            old_balance = request.user.balance
            
            # Deduct from user balance
            request.user.balance -= amount
            request.user.save(update_fields=['balance'])
            
            bet = Bet.objects.create(
                user=request.user,
                market=market,
                bet_type='quick' if bet_type == 'quick_predict' else 'regular',  # Map to existing choices
                outcome=outcome,
                amount=amount,
                odds_at_bet=odds,
                potential_payout=potential_payout,
                round_number=market.current_round,
                round_start_price=market.round_start_price,
                status='active'
            )
            
            # Update market volume (for regular bets)
            if bet_type != 'quick_predict':
                market.total_volume += amount
                if outcome == 'UP':
                    market.up_volume += amount
                elif outcome == 'DOWN':
                    market.down_volume += amount
                else:  # FLAT
                    market.flat_volume += amount
                market.save()
            
            # Create transaction record with predict-to-earn info in description
            description = f"{'Quick predict' if bet_type == 'quick_predict' else 'Bet'} placed: {outcome} on {market.title}"
            description += description_suffix
            
            Transaction.objects.create(
                user=request.user,
                transaction_type='bet',
                amount=-amount,
                balance_before=old_balance,
                balance_after=request.user.balance,
                status='completed',
                bet=bet,
                market=market,
                description=description,
                # Store predict-to-earn data in metadata (Transaction already has this field)
                metadata={
                    'bet_type': bet_type,
                    'timeframe': timeframe if bet_type == 'quick_predict' else None,
                    'created_price': str(get_current_crypto_price(market)),
                    'is_predict_to_earn': bet_type == 'quick_predict',
                    'resolution_time': resolution_time.isoformat() if resolution_time else None,
                    'predict_odds': str(odds) if bet_type == 'quick_predict' else None
                }
            )
            
            # Award XP
            if bet_type == 'quick_predict':
                xp_earned = 15  # Fixed XP for quick predict
            else:
                xp_earned = min(int(amount), 50)  # Regular bet XP
            
            request.user.xp += xp_earned
            request.user.save(update_fields=['xp'])
            
        
            if bet_type == 'quick_predict':
                from django.core.cache import cache
                cache_key = f"predict_bet_{bet.id}_resolution"
                cache.set(cache_key, {
                    'bet_id': str(bet.id),
                    'resolution_time': resolution_time.isoformat(),
                    'timeframe': timeframe,
                    'starting_price': str(get_current_crypto_price(market)),
                    'outcome': outcome
                }, timeout=60*60*24)  # Store for 24 hours
                
                logger.info(f"Stored predict-to-earn resolution info for bet {bet.id}")
        
        return JsonResponse({
            'success': True,
            'message': f'{"Quick predict" if bet_type == "quick_predict" else "Bet"} placed successfully! {xp_earned} XP earned.',
            'bet_id': str(bet.id),
            'new_balance': float(request.user.balance),
            'new_xp': request.user.xp,
            'xp_earned': xp_earned,
            'resolution_time': resolution_time.isoformat() if resolution_time else None,
            'odds': float(odds),
            'potential_payout': float(potential_payout)
        })
        
    except Exception as e:
        logger.error(f"Bet placement error: {e}")
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@csrf_protect
def wallet_deposit(request):
    """Handle wallet deposit via Stripe with improved error handling"""
    
    if request.method == 'POST':
        try:
            # Handle both JSON and form data
            if request.content_type == 'application/json':
                data = json.loads(request.body)
                amount_str = str(data.get('amount', ''))
            else:
                amount_str = request.POST.get('amount', '')
            
            # Clean and validate the amount string
            amount_str = amount_str.strip()
            if not amount_str:
                return JsonResponse({
                    'success': False,
                    'error': 'Amount is required'
                })
            
            # Remove any currency symbols or commas
            amount_str = amount_str.replace('$', '').replace(',', '')
            
            try:
                amount = Decimal(amount_str)
            except (InvalidOperation, ValueError) as e:
                return JsonResponse({
                    'success': False,
                    'error': f'Invalid amount format: {amount_str}'
                })
            
            # Validation
            if amount < Decimal('5.00'):
                return JsonResponse({
                    'success': False,
                    'error': 'Minimum deposit is $5.00'
                })
            
            if amount > Decimal('10000.00'):
                return JsonResponse({
                    'success': False,
                    'error': 'Maximum deposit is $10,000.00'
                })
            
            # Create Stripe payment intent
            stripe_service = StripePaymentService()
            payment_result = stripe_service.create_payment_intent(
                amount=amount,
                user=request.user
            )
            
            if not payment_result:
                return JsonResponse({
                    'success': False,
                    'error': 'Unable to create payment. Please try again.'
                })
            
            payment_intent_id = payment_result['id']
            
            # FIXED: Create transaction with proper atomic operation and ensure 'pending' status
            try:
                with db_transaction.atomic():
                    # Check if transaction already exists (prevent duplicates)
                    existing_transaction = Transaction.objects.filter(
                        stripe_payment_intent_id=payment_intent_id
                    ).first()
                    
                    if existing_transaction:
                        logger.warning(f"Transaction already exists for payment_intent {payment_intent_id}")
                        return JsonResponse({
                            'success': True,
                            'client_secret': payment_result['client_secret'],
                            'amount': float(amount),
                            'transaction_id': str(existing_transaction.id)
                        })
                    
                    # FIXED: Create new transaction with explicit 'pending' status
                    transaction = Transaction.objects.create(
                        user=request.user,
                        transaction_type='deposit',
                        amount=amount,
                        balance_before=request.user.balance,
                        balance_after=request.user.balance,  # Will update on completion
                        status='pending',  # EXPLICIT: Ensure this is 'pending'
                        stripe_payment_intent_id=payment_intent_id,
                        description=f"Wallet deposit via Stripe - ${amount}",
                        created_at=timezone.now(),
                        metadata={
                            'stripe_payment_intent_id': payment_intent_id,
                            'stripe_amount_cents': int(amount * 100),
                            'created_via': 'wallet_deposit_endpoint'
                        }
                    )
                    
                    logger.info(f"Created transaction {transaction.id} for payment_intent {payment_intent_id} with status '{transaction.status}'")
                    
                    return JsonResponse({
                        'success': True,
                        'client_secret': payment_result['client_secret'],
                        'amount': float(amount),
                        'transaction_id': str(transaction.id)
                    })
                    
            except Exception as e:
                logger.error(f"Error creating transaction for payment_intent {payment_intent_id}: {e}")
                return JsonResponse({
                    'success': False,
                    'error': 'Database error. Please try again.'
                })
                
        except Exception as e:
            logger.error(f"Deposit error for user {request.user.id}: {str(e)}", exc_info=True)
            
            return JsonResponse({
                'success': False,
                'error': f'Payment error: {str(e)}'
            })
    
    return redirect('dashboard')


@csrf_exempt
@require_POST  
def stripe_webhook(request):
    """
    Enhanced webhook with extensive debugging
    """
    # STEP 1: Log that webhook was hit
    logger.info(f"=== STRIPE WEBHOOK HIT at {timezone.now()} ===")
    
    # STEP 2: Log request details
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
    
    logger.info(f"Request Details:")
    logger.info(f"- Method: {request.method}")
    logger.info(f"- Content-Type: {request.content_type}")
    logger.info(f"- Payload size: {len(payload)} bytes")
    logger.info(f"- Has signature header: {bool(sig_header)}")
    logger.info(f"- Webhook secret configured: {bool(STRIPE_WEBHOOK_SECRET)}")
    logger.info(f"- Request IP: {request.META.get('REMOTE_ADDR', 'unknown')}")
    
    # STEP 3: Try to log raw payload (first 500 chars for safety)
    try:
        payload_preview = payload.decode('utf-8')[:500]
        logger.info(f"Payload preview: {payload_preview}")
    except:
        logger.info("Could not decode payload preview")

    if not STRIPE_WEBHOOK_SECRET:
        logger.error("❌ STRIPE_WEBHOOK_SECRET not configured")
        return HttpResponse("Webhook secret not configured", status=500)

    # STEP 4: Try to verify and parse the event
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        logger.info(f"✅ Event verified successfully")
        logger.info(f"- Event ID: {event['id']}")
        logger.info(f"- Event Type: {event['type']}")
        logger.info(f"- Created: {event.get('created')}")
        
        # Log the event data
        event_data = event.get("data", {})
        event_object = event_data.get("object", {})
        logger.info(f"- Object ID: {event_object.get('id', 'N/A')}")
        logger.info(f"- Object Type: {event_object.get('object', 'N/A')}")
        
        if event_object.get('object') == 'payment_intent':
            logger.info(f"Payment Intent Details:")
            logger.info(f"- Status: {event_object.get('status')}")
            logger.info(f"- Amount: {event_object.get('amount')}")
            logger.info(f"- Amount Received: {event_object.get('amount_received')}")
            logger.info(f"- Currency: {event_object.get('currency')}")
        
    except ValueError as e:
        logger.error(f"❌ Invalid payload: {e}")
        return HttpResponse("Invalid payload", status=400)
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"❌ Signature verification failed: {e}")
        logger.error(f"Received signature: {sig_header}")
        if STRIPE_WEBHOOK_SECRET:
            logger.error(f"Expected secret (first 10 chars): {STRIPE_WEBHOOK_SECRET[:10]}...")
        return HttpResponse("Invalid signature", status=400)
    except Exception as e:
        logger.error(f"❌ Event parsing error: {e}", exc_info=True)
        return HttpResponse("Event parsing error", status=400)

    # STEP 5: Process the event
    try:
        logger.info(f"🔄 Processing event: {event['type']}")
        
        if event["type"] == "payment_intent.succeeded":
            logger.info("Handling payment_intent.succeeded")
            payment_intent = event["data"]["object"]
            success = handle_successful_payment(payment_intent)
            
            if success:
                logger.info("✅ Payment processed successfully")
                return HttpResponse("Payment processed successfully", status=200)
            else:
                logger.error("❌ Payment processing failed")
                return HttpResponse("Processing failed", status=400)

        elif event["type"] == "payment_intent.payment_failed":
            logger.info("Handling payment_intent.payment_failed")
            payment_intent = event["data"]["object"]
            handle_failed_payment(payment_intent)
            logger.info("✅ Failed payment processed")
            return HttpResponse("Failed payment processed", status=200)

        elif event["type"] == "payment_intent.canceled":
            logger.info("Handling payment_intent.canceled")
            payment_intent = event["data"]["object"]
            handle_canceled_payment(payment_intent)
            logger.info("✅ Canceled payment processed")
            return HttpResponse("Canceled payment processed", status=200)

        else:
            logger.info(f"ℹ️ Unhandled event type: {event['type']} - ignoring")
            return HttpResponse("Event received", status=200)

    except Exception as e:
        logger.error(f"❌ Critical error processing event {event.get('id')}: {e}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return HttpResponse("Event processing error", status=500)



def handle_successful_payment(payment_intent):
    """
    Simplified version with extensive logging for debugging
    """
    pid = payment_intent.get("id")
    logger.info(f"🔄 handle_successful_payment called for: {pid}")
    
    if not pid:
        logger.error("❌ No payment_intent ID")
        return False
    
    try:
        # Log payment intent details
        logger.info(f"Payment Intent Analysis:")
        logger.info(f"- ID: {pid}")
        logger.info(f"- Status: {payment_intent.get('status')}")
        logger.info(f"- Amount (cents): {payment_intent.get('amount')}")
        logger.info(f"- Amount Received (cents): {payment_intent.get('amount_received')}")
        logger.info(f"- Currency: {payment_intent.get('currency')}")
        
        # Calculate amount
        stripe_amount_cents = payment_intent.get("amount_received") or payment_intent.get("amount", 0)
        stripe_amount = Decimal(stripe_amount_cents) / 100
        logger.info(f"- Calculated amount: ${stripe_amount}")
        
        # Search for transactions
        logger.info(f"🔍 Searching for transactions with payment_intent_id: {pid}")
        
        all_transactions = Transaction.objects.filter(
            stripe_payment_intent_id=pid
        )
        
        logger.info(f"Found {all_transactions.count()} total transactions")
        
        # Log each transaction found
        for i, txn in enumerate(all_transactions, 1):
            logger.info(f"Transaction {i}:")
            logger.info(f"  - ID: {txn.id}")
            logger.info(f"  - User: {txn.user.username}")
            logger.info(f"  - Type: {txn.transaction_type}")
            logger.info(f"  - Amount: ${txn.amount}")
            logger.info(f"  - Status: {txn.status}")
            logger.info(f"  - Created: {txn.created_at}")
        
        if not all_transactions.exists():
            logger.error(f"❌ No transactions found for {pid}")
            
            # Show recent transactions for debugging
            recent_txns = Transaction.objects.filter(
                created_at__gte=timezone.now() - timedelta(hours=2)
            ).order_by('-created_at')[:5]
            
            logger.info(f"Recent transactions for debugging:")
            for txn in recent_txns:
                logger.info(f"  - {txn.id}: {txn.stripe_payment_intent_id} | {txn.status} | ${txn.amount}")
            
            return False
        
        # Find deposit transactions only
        deposit_transactions = all_transactions.filter(transaction_type='deposit')
        logger.info(f"Found {deposit_transactions.count()} deposit transactions")
        
        if not deposit_transactions.exists():
            logger.error(f"❌ No deposit transactions found for {pid}")
            return False
        
        # Check for completed transactions
        completed = deposit_transactions.filter(status='completed')
        if completed.exists():
            logger.info(f"✅ Payment {pid} already completed in transaction {completed.first().id}")
            return True
        
        # Find transaction to process
        pending = deposit_transactions.filter(status='pending').first()
        if pending:
            target_txn = pending
            logger.info(f"✅ Found pending transaction: {target_txn.id}")
        else:
            target_txn = deposit_transactions.first()
            logger.info(f"ℹ️ No pending transaction, using: {target_txn.id} (status: {target_txn.status})")
        
        # Validate amount
        if abs(target_txn.amount - stripe_amount) > Decimal('0.01'):
            logger.error(f"❌ Amount mismatch: DB=${target_txn.amount} vs Stripe=${stripe_amount}")
            return False
        
        # Process the transaction
        logger.info(f"🔄 Processing transaction {target_txn.id}")
        
        with db_transaction.atomic():
            user = target_txn.user
            old_balance = user.balance
            new_balance = old_balance + target_txn.amount
            
            logger.info(f"Balance update: {user.username} ${old_balance} + ${target_txn.amount} = ${new_balance}")
            
            # Update user
            user.balance = new_balance
            user.save(update_fields=['balance', 'updated_at'])
            
            # Update transaction
            target_txn.status = 'completed'
            target_txn.balance_before = old_balance
            target_txn.balance_after = new_balance
            target_txn.description = f"Deposit completed via Stripe webhook {pid}"
            
            if not target_txn.metadata:
                target_txn.metadata = {}
            target_txn.metadata.update({
                "webhook_processed_at": timezone.now().isoformat(),
                "stripe_status": payment_intent.get("status"),
                "webhook_amount": str(stripe_amount)
            })
            
            target_txn.save(update_fields=[
                'status', 'balance_before', 'balance_after', 
                'description', 'metadata', 'updated_at'
            ])
            
            logger.info(f"✅ SUCCESS: Transaction {target_txn.id} completed")
            logger.info(f"✅ User balance updated: ${old_balance} → ${new_balance}")
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Error in handle_successful_payment: {e}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return False


def handle_failed_payment(payment_intent):
    """FIXED: Mark transaction as failed if found"""
    pid = payment_intent.get("id")
    logger.info(f"Handling failed payment_intent {pid}")
    
    try:
        with db_transaction.atomic():
            # Look for any transaction with this payment_intent_id that's not already failed
            txn = Transaction.objects.select_for_update().filter(
                stripe_payment_intent_id=pid
            ).exclude(status="failed").first()
            
            if txn:
                txn.status = "failed"
                txn.description = f"Payment failed via Stripe {pid}"
                
                if not txn.metadata:
                    txn.metadata = {}
                txn.metadata.update({
                    "stripe_webhook_processed": timezone.now().isoformat(),
                    "payment_intent_status": payment_intent.get("status"),
                    "failure_reason": payment_intent.get("last_payment_error", {}).get("message", "Unknown")
                })
                txn.save(update_fields=["status", "description", "metadata", "updated_at"])
                logger.info(f"✗ Transaction {txn.id} marked failed for payment_intent {pid}")
            else:
                logger.warning(f"No transaction found to mark failed for payment_intent {pid}")
                
    except Exception as e:
        logger.error(f"Error updating failed payment {pid}: {e}", exc_info=True)


def handle_canceled_payment(payment_intent):
    """FIXED: Mark transaction as canceled if found"""
    pid = payment_intent.get("id")
    logger.info(f"Handling canceled payment_intent {pid}")
    
    try:
        with db_transaction.atomic():
            # Look for any transaction with this payment_intent_id that's not already cancelled
            txn = Transaction.objects.select_for_update().filter(
                stripe_payment_intent_id=pid
            ).exclude(status="cancelled").first()
            
            if txn:
                txn.status = "cancelled"
                txn.description = f"Payment cancelled via Stripe {pid}"
                
                if not txn.metadata:
                    txn.metadata = {}
                txn.metadata.update({
                    "stripe_webhook_processed": timezone.now().isoformat(),
                    "payment_intent_status": payment_intent.get("status")
                })
                txn.save(update_fields=["status", "description", "metadata", "updated_at"])
                logger.info(f"⚠ Transaction {txn.id} marked cancelled for payment_intent {pid}")
            else:
                logger.warning(f"No transaction found to mark cancelled for payment_intent {pid}")
                
    except Exception as e:
        logger.error(f"Error updating canceled payment {pid}: {e}", exc_info=True)
        


@login_required
def wallet_withdraw(request):
    """Handle withdrawals with automatic TCN/USDT switching"""
    
    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount', 0))
            wallet_address = request.POST.get('wallet_address', '').strip()
            network = request.POST.get('network', None)  # Will be handled by service
            
            # Initialize flexible service
            withdrawal_service = FlexibleCoinremitterService()
            mode_info = withdrawal_service.get_current_mode_info()
            
            # Basic validation
            if amount < mode_info['min_amount']:
                messages.error(request, f'Minimum withdrawal is ${mode_info["min_amount"]} in {mode_info["mode"]} mode')
                return redirect('dashboard')
            
            if request.user.balance < amount:
                messages.error(request, 'Insufficient balance')
                return redirect('dashboard')
            
            if not wallet_address:
                messages.error(request, 'Wallet address is required')
                return redirect('dashboard')
            
            # Validate address
            if not withdrawal_service.validate_address(wallet_address, network):
                error_msg = f'Invalid wallet address for {mode_info["display_name"]}'
                if mode_info['is_testing']:
                    error_msg += ' (TCN test mode)'
                messages.error(request, error_msg)
                return redirect('dashboard')
            
            # Calculate fees
            fee_percentage = Decimal(str(getattr(settings, 'WITHDRAWAL_FEE_PERCENTAGE', 0.02)))
            platform_fee = amount * fee_percentage
            network_fee = mode_info['network_fee']
            total_fees = platform_fee + network_fee
            net_amount = amount - total_fees
            
            if net_amount <= 0:
                messages.error(request, f'Amount too small after fees (${total_fees} total fees)')
                return redirect('dashboard')
            
            with db_transaction.atomic():
                # Deduct from user balance
                user = request.user
                user.balance -= amount
                user.save()
                
                # Create withdrawal transaction
                from predict.models import Transaction
                
                # Create description based on mode
                if mode_info['is_testing']:
                    description = f'Test withdrawal: {amount} TCN to {wallet_address[:10]}...{wallet_address[-6:]} (Testing Mode)'
                else:
                    description = f'USDT withdrawal to {wallet_address[:10]}...{wallet_address[-6:]} via {mode_info["network_name"]}'
                
                withdrawal_tx = Transaction.objects.create(
                    user=user,
                    transaction_type='withdrawal',
                    amount=-amount,
                    balance_before=user.balance + amount,
                    balance_after=user.balance,
                    status='pending',
                    description=description,
                    metadata={
                        'wallet_address': wallet_address,
                        'network': network,
                        'mode': mode_info['mode'],
                        'coin_symbol': mode_info['coin_symbol'],
                        'platform_fee': str(platform_fee),
                        'network_fee': str(network_fee),
                        'total_fees': str(total_fees),
                        'net_amount': str(net_amount),
                        'is_testing': mode_info['is_testing']
                    }
                )
                
                # Process withdrawal
                result = withdrawal_service.send_withdrawal(
                    address=wallet_address,
                    amount=net_amount,
                    user_id=str(user.id),
                    network=network
                )
                
                if result['success']:
                    # Update transaction with success details
                    withdrawal_tx.blockchain_tx_hash = result.get('tx_hash')
                    withdrawal_tx.external_id = result.get('tx_id')
                    withdrawal_tx.status = 'completed'
                    withdrawal_tx.metadata.update({
                        'coinremitter_tx_id': result.get('tx_id'),
                        'coinremitter_custom_id': result.get('custom_id'),
                        'coinremitter_fee': str(result.get('fee', 0)),
                        'explorer_url': result.get('explorer_url'),
                        'withdrawal_mode': result.get('mode')
                    })
                    
                    # Add testing-specific metadata
                    if result.get('testing_notice'):
                        withdrawal_tx.metadata.update({
                            'testing_notice': result['testing_notice'],
                            'production_equivalent': result['production_equivalent']
                        })
                    
                    withdrawal_tx.save()
                    
                    # Create platform fee transaction
                    Transaction.objects.create(
                        user=user,
                        transaction_type='fee',
                        amount=platform_fee,
                        balance_before=user.balance,
                        balance_after=user.balance,
                        status='completed',
                        description=f'Withdrawal fee ({fee_percentage*100}%) - {mode_info["mode"]} mode',
                        metadata={
                            'fee_type': 'withdrawal_platform',
                            'original_withdrawal': str(withdrawal_tx.id),
                            'mode': mode_info['mode']
                        }
                    )
                    
                    # Create success message based on mode
                    if mode_info['is_testing']:
                        success_msg = (
                            f'🧪 TEST WITHDRAWAL SUCCESSFUL! '
                            f'{net_amount} TCN sent to your wallet for testing. '
                            f'In production, this would be ${net_amount} USDT. '
                            f'TX ID: {result.get("tx_id", "N/A")}'
                        )
                    else:
                        success_msg = (
                            f'✅ Withdrawal successful! '
                            f'${net_amount} USDT sent via {result.get("network", "blockchain")}. '
                            f'Transaction ID: {result.get("tx_id", "N/A")}'
                        )
                        
                        if result.get('explorer_url'):
                            success_msg += f' | Track: {result.get("explorer_url")}'
                    
                    messages.success(request, success_msg)
                    logger.info(f"Successful withdrawal for user {user.id} in {mode_info['mode']} mode: {result}")
                    
                else:
                    # Withdrawal failed - refund user
                    user.balance += amount
                    user.save()
                    
                    withdrawal_tx.status = 'failed'
                    withdrawal_tx.metadata.update({
                        'error': result.get('error', 'Unknown error'),
                        'refunded': True,
                        'failure_mode': result.get('mode')
                    })
                    withdrawal_tx.save()
                    
                    # Create refund transaction
                    Transaction.objects.create(
                        user=user,
                        transaction_type='refund',
                        amount=amount,
                        balance_before=user.balance - amount,
                        balance_after=user.balance,
                        status='completed',
                        description=f'Withdrawal refund ({mode_info["mode"]} mode) - {result.get("error", "Failed")}',
                        metadata={
                            'original_withdrawal': str(withdrawal_tx.id),
                            'refund_mode': mode_info['mode']
                        }
                    )
                    
                    error_msg = f'Withdrawal failed in {mode_info["mode"]} mode: {result.get("error", "Unknown error")}. Your balance has been refunded.'
                    messages.error(request, error_msg)
                    logger.error(f"Withdrawal failed for user {user.id} in {mode_info['mode']} mode: {result}")
        
        except ValueError:
            messages.error(request, 'Invalid withdrawal amount')
        except Exception as e:
            logger.error(f"Withdrawal error for user {request.user.id}: {str(e)}")
            messages.error(request, 'Withdrawal processing failed. Please try again later.')
    
    return redirect('dashboard')

# API Views for real-time data
def api_market_data(request, market_id):
    """API endpoint for real-time market data"""
    try:
        market = Market.objects.get(id=market_id, status='active')
        
        data = {
            'total_volume': float(market.total_volume),
            'up_volume': float(market.up_volume),
            'down_volume': float(market.down_volume),
            'flat_volume': float(market.flat_volume),
            'up_odds': float(market.up_odds),
            'down_odds': float(market.down_odds),
            'flat_odds': float(market.flat_odds),
            'participants': market.get_participant_count(),
            'round_info': MarketDataService.get_round_info(market),
        }
        
        return JsonResponse(data)
    except Market.DoesNotExist:
        return JsonResponse({'error': 'Market not found'}, status=404)


def api_crypto_prices(request):
    """API endpoint for crypto prices"""
    prices = CryptoPriceService.get_crypto_prices()
    return JsonResponse(prices)


def api_market_ohlc(request, market_id):
    """API endpoint for market-specific OHLC data"""
    try:
        market = Market.objects.get(id=market_id, status='active')
        
        # Extract symbol from market
        symbol = 'BTC'
        if 'ETH' in market.title.upper():
            symbol = 'ETH'
        elif 'BTC' in market.title.upper():
            symbol = 'BTC'
        
        # Get OHLC data for the symbol
        ohlc_response = api_crypto_ohlc(request, symbol)
        
        if ohlc_response.status_code == 200:
            import json
            data = json.loads(ohlc_response.content)
            
            # Add market-specific information
            data['market_id'] = str(market_id)
            data['market_title'] = market.title
            data['round_duration'] = market.round_duration
            
            return JsonResponse(data)
        else:
            return ohlc_response
            
    except Market.DoesNotExist:
        return JsonResponse({'error': 'Market not found'}, status=404)
    except Exception as e:
        logger.error(f"Error fetching market OHLC data: {e}")
        return JsonResponse({'error': 'Unable to fetch market chart data'}, status=500)
    

def api_crypto_ohlc(request, symbol='BTC'):
    """API endpoint for OHLC candlestick data"""
    try:
        # Get historical price data
        price_history = CryptoPriceService.get_price_history(symbol.upper(), days=1)
        
        if not price_history or 'prices' not in price_history:
            # Generate mock OHLC data for demo
            import random
            from datetime import datetime, timedelta
            
            current_price = 67432.50 if symbol.upper() == 'BTC' else 3421.80
            ohlc_data = []
            
            # Generate 24 hours of hourly data
            base_time = datetime.now().timestamp() * 1000
            
            for i in range(24):
                time = base_time - (24 - i) * 3600000  # 1 hour intervals
                
                # Simulate price movement
                variation = random.uniform(-0.02, 0.02)  # ±2% variation
                open_price = current_price * (1 + variation)
                
                high_variation = random.uniform(0, 0.015)  # 0-1.5% above open
                low_variation = random.uniform(-0.015, 0)  # 0-1.5% below open
                
                high = open_price * (1 + high_variation)
                low = open_price * (1 + low_variation)
                
                close_variation = random.uniform(-0.01, 0.01)
                close = open_price * (1 + close_variation)
                
                # Ensure OHLC logic is correct
                high = max(high, open_price, close)
                low = min(low, open_price, close)
                
                ohlc_data.append({
                    'x': int(time),
                    'o': round(open_price, 2),
                    'h': round(high, 2),
                    'l': round(low, 2),
                    'c': round(close, 2)
                })
                
                current_price = close
            
            return JsonResponse({
                'symbol': symbol.upper(),
                'data': ohlc_data
            })
        
        # Convert real price history to OHLC format
        # This is a simplified conversion - in production you'd want actual OHLC data
        prices = price_history['prices']
        ohlc_data = []
        
        # Group prices into hourly candles
        for i in range(0, len(prices), 4):  # Take every 4th point for hourly data
            if i + 3 < len(prices):
                slice_prices = prices[i:i+4]
                timestamp = int(prices[i][0])
                
                price_values = [p[1] for p in slice_prices]
                open_price = price_values[0]
                close_price = price_values[-1]
                high_price = max(price_values)
                low_price = min(price_values)
                
                ohlc_data.append({
                    'x': timestamp,
                    'o': round(open_price, 2),
                    'h': round(high_price, 2),
                    'l': round(low_price, 2),
                    'c': round(close_price, 2)
                })
        
        return JsonResponse({
            'symbol': symbol.upper(),
            'data': ohlc_data[-24:]  # Last 24 hours
        })
        
    except Exception as e:
        logger.error(f"Error fetching OHLC data: {e}")
        return JsonResponse({'error': 'Unable to fetch chart data'}, status=500)

@csrf_exempt
@require_POST
def coinremitter_webhook(request):
    """Handle Coinremitter webhook notifications"""
    try:
        # Get the webhook data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            data = request.POST.dict()
        
        logger.info(f"Coinremitter webhook received: {data}")
        
        # Extract key information
        transaction_type = data.get('type', '').lower()
        coin_symbol = data.get('coin_symbol', '')
        amount = data.get('amount', '')
        txid = data.get('txid', '')
        confirmations = data.get('confirmations', 0)
        merchant_id = data.get('merchant_id', '')
        
        # Handle different transaction types
        if transaction_type == 'send':
            # This is a withdrawal transaction
            handle_withdrawal_webhook(data)
        elif transaction_type == 'receive':
            # This is a deposit transaction (if you implement crypto deposits later)
            # handle_deposit_webhook(data)
            pass
        
        return JsonResponse({'status': 'success', 'message': 'Webhook processed'})
        
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

def handle_withdrawal_webhook(data):
    """Handle withdrawal webhook notifications"""
    try:
        from predict.models import Transaction
        
        # Extract transaction details
        txid = data.get('txid')
        merchant_id = data.get('merchant_id')
        confirmations = int(data.get('confirmations', 0))
        status = data.get('status', '').lower()
        
        # Find the transaction by external_id or custom_id
        transaction = None
        
        # Try to find by external_id first
        if merchant_id:
            try:
                transaction = Transaction.objects.get(
                    external_id__icontains=merchant_id,
                    transaction_type='withdrawal'
                )
            except Transaction.DoesNotExist:
                pass
        
        # Try to find by blockchain_tx_hash
        if not transaction and txid:
            try:
                transaction = Transaction.objects.get(
                    blockchain_tx_hash=txid,
                    transaction_type='withdrawal'
                )
            except Transaction.DoesNotExist:
                pass
        
        if not transaction:
            logger.warning(f"Transaction not found for webhook: {data}")
            return
    
        old_status = transaction.status
        
        if status == 'success' or confirmations >= 1:
            transaction.status = 'completed'
        elif status == 'failed':
            transaction.status = 'failed'
            if old_status == 'pending':
                refund_failed_withdrawal(transaction)
        else:
            transaction.status = 'pending'
        
        # Update transaction details
        if txid and not transaction.blockchain_tx_hash:
            transaction.blockchain_tx_hash = txid
        
        transaction.metadata.update({
            'webhook_data': data,
            'confirmations': confirmations,
            'webhook_timestamp': timezone.now().isoformat()
        })
        
        transaction.save()
        
        logger.info(f"Updated transaction {transaction.id} status: {old_status} -> {transaction.status}")
        
    except Exception as e:
        logger.error(f"Error handling withdrawal webhook: {e}")

def refund_failed_withdrawal(transaction):
    """Refund user for failed withdrawal"""
    try:
        user = transaction.user
        refund_amount = abs(transaction.amount)  # amount is negative for withdrawals
        
        # Add money back to user balance
        user.balance += refund_amount
        user.save()
        
        # Create refund transaction
        Transaction.objects.create(
            user=user,
            transaction_type='refund',
            amount=refund_amount,
            balance_before=user.balance - refund_amount,
            balance_after=user.balance,
            status='completed',
            description=f'Refund for failed withdrawal - TX: {transaction.blockchain_tx_hash or "N/A"}',
            metadata={
                'original_withdrawal': str(transaction.id),
                'refund_reason': 'withdrawal_failed_on_blockchain'
            }
        )
        
        logger.info(f"Refunded ${refund_amount} to user {user.username} for failed withdrawal")
        
    except Exception as e:
        logger.error(f"Error processing refund: {e}")

def api_user_stats(request):
    """API endpoint for user statistics"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    stats = {
        'balance': float(request.user.balance),
        'level': request.user.level,
        'xp': request.user.xp,
        'level_title': request.user.get_level_title(),
        'next_level_xp': request.user.get_xp_for_next_level(),
    }
    
    return JsonResponse(stats)


def get_current_crypto_price(market):
    """Get current price for the market's crypto"""
    try:
        crypto_prices = CryptoPriceService.get_crypto_prices()
        trading_pair = getattr(market, 'trading_pair', 'BTC/USDT')
        
        for symbol, data in crypto_prices.items():
            if symbol.lower() in trading_pair.lower():
                return data.get('price', 0)
        
        # Default prices if no real data
        return Decimal('67432.50') if 'BTC' in trading_pair else Decimal('3421.80')
    except:
        return Decimal('67432.50')


@login_required
def referral_dashboard(request):
    """Enhanced referral dashboard with tier system"""
    
    profile, created = ReferralProfile.objects.get_or_create(user=request.user)
    
    # Get tier configuration
    config = profile.get_tier_config()
    xp_progress = 0
    active_progress = 0
    
    if config['next_tier']:
        xp_progress = (profile.tier_xp / config['xp_needed']) * 100 if config['xp_needed'] > 0 else 100
        active_progress = (profile.active_referrals / config['active_needed']) * 100 if config['active_needed'] > 0 else 100
    
    # Get referrals
    referrals = CustomUser.objects.filter(referral_profile__referred_by=request.user)
    
    # Get recent transactions
    referral_transactions = ReferralTransaction.objects.filter(referrer=request.user)[:20]
    earnings_breakdown = {
        'signup': profile.signup_earnings,
        'deposit': profile.deposit_earnings,
        'withdrawal': profile.withdrawal_earnings,
        'trading': profile.trading_earnings,
    }
    
    context = {
        'profile': profile,
        'referral_code': profile.referral_code,
        'tier': profile.tier,
        'tier_config': config,
        'total_referrals': profile.total_referrals,
        'active_referrals': profile.active_referrals,
        'total_earnings': profile.total_earnings,
        'tier_xp': profile.tier_xp,
        'total_xp': profile.total_xp,
        'xp_progress': xp_progress,
        'active_progress': active_progress,
        'referrals': referrals,
        'referral_transactions': referral_transactions,
        'earnings_breakdown': earnings_breakdown,
        'referral_link': request.build_absolute_uri(f'/register/?ref={profile.referral_code}'),
        'settings': settings,
    }
    
    return render(request, 'referral_dashboard.html', context)




@login_required
@csrf_protect
def crypto_deposit_b2binpay(request):
    """
    Create crypto deposit using B2BinPay
    Generates unique deposit address for user
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    
    try:
        data = json.loads(request.body)
        amount = Decimal(str(data.get('amount', 0)))
        currency = data.get('currency', 'BTC').upper()
        wallet_id = data.get('wallet_id')  # Admin must provide wallet ID from B2BinPay dashboard
        
        logger.info(f"Crypto deposit request: User={request.user.username}, Amount=${amount}, Currency={currency}")
        
        # Validation
        if amount < Decimal('10.00'):
            return JsonResponse({'success': False, 'error': 'Minimum deposit is $10.00'})
        
        if amount > Decimal('50000.00'):
            return JsonResponse({'success': False, 'error': 'Maximum deposit is $50,000.00'})
        
        if not wallet_id:
            return JsonResponse({
                'success': False,
                'error': 'Wallet ID not configured. Contact admin.'
            })
        
        # Build callback URL
        try:
            from django.conf import settings
            site_url = getattr(settings, 'SITE_URL', None)
            if not site_url:
                scheme = 'https' if request.is_secure() else 'http'
                site_url = f"{scheme}://{request.get_host()}"
            
            site_url = site_url.rstrip('/')
            callback_url = f"{site_url}/market/wallet/b2binpay-callback/"
            
            logger.info(f"Callback URL: {callback_url}")
        except Exception as e:
            logger.error(f"Error building callback URL: {e}")
            return JsonResponse({'success': False, 'error': 'Configuration error'})
        
        # Create deposit via B2BinPay
        try:
            b2binpay = B2BinPayService()
            
            tracking_id = f"deposit_{request.user.id}_{int(time.time())}"
            
            deposit_result = b2binpay.create_deposit(
                wallet_id=wallet_id,
                amount=amount,
                user_id=str(request.user.id),
                callback_url=callback_url,
                tracking_id=tracking_id
            )
            
            logger.info(f"B2BinPay deposit result: {deposit_result}")
            
            if not deposit_result.get('success'):
                error_msg = deposit_result.get('error', 'Unknown error from B2BinPay')
                logger.error(f"B2BinPay API error: {error_msg}")
                return JsonResponse({
                    'success': False,
                    'error': f'Payment gateway error: {error_msg}'
                })
            
            # Create pending transaction
            with db_transaction.atomic():
                transaction = Transaction.objects.create(
                    user=request.user,
                    transaction_type='deposit',
                    amount=amount,
                    balance_before=request.user.balance,
                    balance_after=request.user.balance,
                    status='pending',
                    external_id=deposit_result.get('deposit_id'),
                    description=f'Crypto deposit via B2BinPay - {currency}',
                    metadata={
                        'deposit_id': deposit_result.get('deposit_id'),
                        'payment_address': deposit_result.get('address'),
                        'currency': currency,
                        'tracking_id': tracking_id,
                        'wallet_id': wallet_id,
                        'callback_url': callback_url,
                        'provider': 'b2binpay'
                    }
                )
                
                logger.info(f"Transaction created: ID={transaction.id}, DepositID={deposit_result.get('deposit_id')}")
            
            return JsonResponse({
                'success': True,
                'deposit_id': deposit_result.get('deposit_id'),
                'payment_address': deposit_result.get('address'),
                'currency': currency,
                'amount': float(amount),
                'transaction_id': str(transaction.id),
                'tracking_id': tracking_id,
                'message': f'Send {currency} to the address below'
            })
            
        except Exception as e:
            logger.error(f"B2BinPay API exception: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': f'Payment gateway error: {str(e)}'
            })
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid request format'})
    except Exception as e:
        logger.error(f"Crypto deposit error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})



@login_required
@csrf_protect
def place_target_bet(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    
    try:
        data = json.loads(request.body)
        market_id = data.get('market_id')
        prediction = data.get('prediction')
        amount = Decimal(str(data.get('amount', 0)))
        
        # Validation
        if prediction not in ['YES', 'NO']:
            return JsonResponse({'success': False, 'error': 'Invalid prediction. Must be YES or NO.'})
        
        if amount < Decimal('1.00'):
            return JsonResponse({'success': False, 'error': 'Minimum bet is $1.00'})
        
        if amount > request.user.balance:
            return JsonResponse({
                'success': False, 
                'error': f'Insufficient balance. You have ${request.user.balance:.2f}'
            })
        
        # Get market
        try:
            market = Market.objects.get(id=market_id, market_type='target', status='active')
        except Market.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Market not found or closed'})
        
        # Check deadline
        if timezone.now() >= market.resolution_date:
            return JsonResponse({'success': False, 'error': 'Market has closed (deadline passed)'})
        
        outcome = 'UP' if prediction == 'YES' else 'DOWN'
        
        # Calculate odds based on current volume
        if outcome == 'UP':
            odds = market.up_odds  # YES odds
        else:
            odds = market.down_odds  # NO odds
        
        potential_payout = amount * odds
        
        # Place bet within atomic transaction
        with db_transaction.atomic():
            # Lock user for update
            user = CustomUser.objects.select_for_update().get(id=request.user.id)
            
            # Double-check balance
            if user.balance < amount:
                return JsonResponse({'success': False, 'error': 'Insufficient balance'})
            
            # Deduct from user
            old_balance = user.balance
            user.balance -= amount
            user.save()
            
            # Create bet
            bet = Bet.objects.create(
                user=user,
                market=market,
                bet_type='regular',
                outcome=outcome,
                amount=amount,
                odds_at_bet=odds,
                potential_payout=potential_payout,
                round_number=1,
                round_start_price=market.round_start_price,
                status='active'
            )
            
            # Update market volume
            market.total_volume += amount
            if outcome == 'UP':  # YES
                market.up_volume += amount
            else:  # NO
                market.down_volume += amount
            market.save()
            
            # Create transaction record
            Transaction.objects.create(
                user=user,
                transaction_type='bet',
                amount=-amount,
                balance_before=old_balance,
                balance_after=user.balance,
                status='completed',
                bet=bet,
                market=market,
                description=f'{prediction} bet on {market.title[:50]}...',
                metadata={
                    'prediction': prediction,
                    'market_type': 'target',
                    'target_price': str(market.target_price)
                }
            )
            
            # Award XP
            xp_earned = min(int(amount), 50)
            user.xp += xp_earned
            user.save()
        
        logger.info(
            f"Target bet placed: User {user.username} bet ${amount} {prediction} "
            f"on market {market.id}"
        )
        
        return JsonResponse({
            'success': True,
            'message': f'{prediction} bet placed successfully! +{xp_earned} XP',
            'bet_id': str(bet.id),
            'new_balance': float(user.balance),
            'odds': float(odds),
            'potential_payout': float(potential_payout),
            'xp_earned': xp_earned
        })
        
    except Market.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Market not found'})
    except Exception as e:
        logger.error(f"Target bet error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': f'Error placing bet: {str(e)}'})
    
@login_required
@csrf_protect
def virtual_wallet_transfer(request):
    """
    P2P transfer between users' virtual wallets
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    
    try:
        data = json.loads(request.body)
        recipient_identifier = data.get('recipient', '').strip()
        amount = Decimal(str(data.get('amount', 0)))
        description = data.get('description', '').strip() or 'P2P transfer'
        
        # Validation
        if amount < Decimal('1.00'):
            return JsonResponse({'success': False, 'error': 'Minimum transfer amount is $1.00'})
        
        if amount > request.user.balance:
            return JsonResponse({
                'success': False,
                'error': f'Insufficient balance. Available: ${request.user.balance}'
            })
        
        # Perform transfer
        result = VirtualWalletService.transfer_between_users(
            sender=request.user,
            recipient_identifier=recipient_identifier,
            amount=amount,
            description=description
        )
        
        if result['success']:
            messages.success(request, result['message'])
        
        return JsonResponse(result)
        
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid request format'})
    except Exception as e:
        logger.error(f"P2P transfer error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})

@staff_member_required
@login_required
def create_price_target_market(request):
    
    if request.method == 'POST':
        try:
            # Extract and validate form data
            crypto_symbol = request.POST.get('crypto_symbol', 'BTC').upper()
            target_price_str = request.POST.get('target_price', '0')
            
            # Log the incoming request
            logger.info(f"Create target market request: symbol={crypto_symbol}, target={target_price_str}, user={request.user.username}")
            
            # Validate and convert target price
            try:
                target_price = Decimal(target_price_str)
            except (InvalidOperation, ValueError) as e:
                logger.error(f"Invalid target price format: {target_price_str}")
                messages.error(request, f'Invalid target price format: {target_price_str}')
                return redirect('create-target-market')
            
            # Validation
            if target_price <= 0:
                messages.error(request, 'Target price must be greater than 0')
                return redirect('create-target-market')
            
            # Optional: custom end date
            end_date_str = request.POST.get('end_date', '').strip()
            end_date = None
            
            if end_date_str:
                try:
                    from datetime import datetime
                    # Parse the datetime-local format
                    end_date = timezone.make_aware(
                        datetime.strptime(end_date_str, '%Y-%m-%dT%H:%M')
                    )
                    
                    # Validate end date is in the future
                    if end_date <= timezone.now():
                        messages.error(request, 'End date must be in the future')
                        return redirect('create-target-market')
                        
                except ValueError as e:
                    logger.error(f"Invalid date format: {end_date_str}, error: {e}")
                    messages.error(request, 'Invalid date format')
                    return redirect('create-target-market')
            
            # Create market using the service
            logger.info(f"Attempting to create market: {crypto_symbol} @ ${target_price}")
            
            from market.utils import PriceTargetMarketService
            
            market = PriceTargetMarketService.create_target_market(
                creator=request.user,
                crypto_symbol=crypto_symbol,
                target_price=target_price,
                end_date=end_date
            )
            
            logger.info(f"Market created successfully: ID={market.id}, Title={market.title}")
            
            messages.success(
                request,
                f'Price target market created successfully: {market.title}'
            )
            return redirect('market-detail', market_id=market.id)
            
        except ValueError as e:
            # Specific error from create_target_market
            logger.error(f"ValueError creating market: {str(e)}", exc_info=True)
            messages.error(request, f'Error: {str(e)}')
            return redirect('create-target-market')
            
        except Exception as e:
            # Catch-all for unexpected errors
            logger.error(
                f"Unexpected error creating target market: {str(e)}", 
                exc_info=True  # This logs the full traceback
            )
            
            if settings.DEBUG:
                messages.error(
                    request, 
                    f'Development Error: {str(e)}\n\nCheck server logs for full traceback'
                )
            else:
                messages.error(
                    request,
                    'An error occurred while creating the market. Our team has been notified.'
                )
            
            return redirect('create-target-market')
    
    # GET request - show the form
    try:
        crypto_prices = CryptoPriceService.get_crypto_prices()
    except Exception as e:
        logger.error(f"Error fetching crypto prices: {e}")
        crypto_prices = {
            'BTC': {'price': 67432},
            'ETH': {'price': 3421}
        }
    
    context = {
        'crypto_prices': crypto_prices,
        'suggested_targets': {
            'BTC': [75000, 80000, 90000, 100000, 110000, 120000],
            'ETH': [3000, 3500, 4000, 4500, 5000, 5500]
        },
        'current_prices': {
            'BTC': crypto_prices.get('BTC', {}).get('price', 67432),
            'ETH': crypto_prices.get('ETH', {}).get('price', 3421)
        }
    }
    
    return render(request, 'create_target_market.html', context)

@csrf_exempt
@require_POST
def b2binpay_callback(request):
    """
    Handle B2BinPay deposit callbacks
    """
    try:
        # Get signature
        signature = request.headers.get('x-sign', '') or request.META.get('HTTP_X_SIGN', '')
        
        # Parse body
        if request.content_type == 'application/json':
            callback_data = json.loads(request.body)
        else:
            callback_data = json.loads(request.body.decode('utf-8'))
        
        logger.info(f"B2BinPay callback received: {json.dumps(callback_data, indent=2)}")
        
        # Verify signature
        b2binpay = B2BinPayService()
        if not b2binpay.verify_callback(callback_data, signature):
            logger.error("Invalid B2BinPay callback signature")
            return HttpResponse("Invalid signature", status=400)
        
        # Extract deposit information
        deposit_data = callback_data.get('data', {}).get('attributes', {})
        tracking_id = deposit_data.get('tracking_id')
        
        # Find associated transfer
        included = callback_data.get('included', [])
        transfer = None
        for item in included:
            if item.get('type') == 'transfer':
                transfer = item.get('attributes', {})
                break
        
        if not transfer:
            logger.error("Transfer data not found in callback")
            return HttpResponse("Transfer data missing", status=400)
        
        transfer_status = transfer.get('status')
        transfer_amount = Decimal(str(transfer.get('amount', 0)))
        
        logger.info(f"Transfer status: {transfer_status}, Amount: {transfer_amount}, Tracking ID: {tracking_id}")
        
        # Process based on status
        if transfer_status == 'success':
            # Find transaction
            try:
                transaction = Transaction.objects.get(
                    metadata__tracking_id=tracking_id,
                    transaction_type='deposit',
                    status='pending'
                )
                
                with db_transaction.atomic():
                    # Credit user's virtual wallet
                    result = VirtualWalletService.credit_wallet(
                        user=transaction.user,
                        amount=transfer_amount,
                        description=f"Crypto deposit completed - {tracking_id}",
                        transaction_type='deposit'
                    )
                    
                    if result['success']:
                        # Update original pending transaction
                        transaction.status = 'completed'
                        transaction.amount = transfer_amount
                        transaction.balance_after = result['new_balance']
                        transaction.metadata['completed_at'] = str(time.time())
                        transaction.metadata['transfer_status'] = transfer_status
                        transaction.save()
                        
                        logger.info(f"Deposit completed: ${transfer_amount} credited to {transaction.user.username}")
                        return HttpResponse("Deposit processed successfully", status=200)
                    else:
                        logger.error(f"Failed to credit wallet: {result.get('error')}")
                        return HttpResponse("Wallet credit failed", status=500)
                
            except Transaction.DoesNotExist:
                logger.warning(f"Transaction not found for tracking_id: {tracking_id}")
                return HttpResponse("Transaction not found", status=404)
        
        elif transfer_status == 'failed':
            # Mark transaction as failed
            try:
                transaction = Transaction.objects.get(
                    metadata__tracking_id=tracking_id,
                    status='pending'
                )
                transaction.status = 'failed'
                transaction.metadata['transfer_status'] = transfer_status
                transaction.save()
                
                logger.info(f"Deposit marked as failed: {tracking_id}")
            except Transaction.DoesNotExist:
                pass
        
        return HttpResponse("Callback processed", status=200)
        
    except Exception as e:
        logger.error(f"B2BinPay callback error: {str(e)}", exc_info=True)
        return HttpResponse("Callback processing error", status=500)

@login_required
@csrf_protect
def stripe_card_deposit(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    
    try:
        data = json.loads(request.body)
        amount = Decimal(str(data.get('amount', 0)))
        payment_method_id = data.get('payment_method_id')
        
        logger.info(f"Stripe deposit request: User={request.user.username}, Amount=${amount}")
        
        # Validation
        if amount < Decimal('5.00'):
            return JsonResponse({'success': False, 'error': 'Minimum deposit is $5.00'})
        
        if amount > Decimal('10000.00'):
            return JsonResponse({'success': False, 'error': 'Maximum deposit is $10,000.00'})
        
        if not payment_method_id:
            return JsonResponse({'success': False, 'error': 'Payment method required'})
        
        try:
            # Create Stripe payment intent
            intent = stripe.PaymentIntent.create(
                amount=int(amount * 100),  # Stripe uses cents
                currency='usd',
                payment_method=payment_method_id,
                confirm=True,
                description=f'Wallet deposit - {request.user.username}',
                metadata={
                    'user_id': str(request.user.id),
                    'username': request.user.username,
                    'type': 'wallet_deposit'
                },
                return_url=f"{settings.SITE_URL}/market/payment-complete/"
            )
            
            logger.info(f"Stripe PaymentIntent created: {intent.id}, Status: {intent.status}")
            
            # Check payment status
            if intent.status == 'succeeded':
                # Credit user's virtual wallet immediately
                with db_transaction.atomic():
                    result = VirtualWalletService.credit_wallet(
                        user=request.user,
                        amount=amount,
                        description=f"Card deposit via Stripe - {intent.id}",
                        transaction_type='deposit'
                    )
                    
                    if result['success']:
                        # Create completed transaction record
                        Transaction.objects.create(
                            user=request.user,
                            transaction_type='deposit',
                            amount=amount,
                            balance_before=result['balance_before'],
                            balance_after=result['new_balance'],
                            status='completed',
                            external_id=intent.id,
                            description=f'Card deposit via Stripe',
                            metadata={
                                'payment_intent_id': intent.id,
                                'payment_method': payment_method_id,
                                'provider': 'stripe',
                                'completed_at': str(time.time())
                            }
                        )
                        
                        logger.info(f"Stripe deposit completed: ${amount} credited to {request.user.username}")
                        
                        return JsonResponse({
                            'success': True,
                            'amount': float(amount),
                            'new_balance': float(result['new_balance']),
                            'transaction_id': intent.id,
                            'message': f'Successfully deposited ${amount}'
                        })
                    else:
                        logger.error(f"Failed to credit wallet: {result.get('error')}")
                        return JsonResponse({
                            'success': False,
                            'error': 'Failed to credit wallet. Contact support.'
                        })
            
            elif intent.status == 'requires_action':
                # 3D Secure or additional authentication required
                return JsonResponse({
                    'success': False,
                    'requires_action': True,
                    'client_secret': intent.client_secret,
                    'message': 'Additional authentication required'
                })
            
            else:
                return JsonResponse({
                    'success': False,
                    'error': f'Payment failed: {intent.status}'
                })
        
        except stripe.error.CardError as e:
            logger.error(f"Stripe card error: {e.user_message}")
            return JsonResponse({'success': False, 'error': e.user_message})
        
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error: {str(e)}")
            return JsonResponse({'success': False, 'error': 'Payment processing error'})
    
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid request format'})
    except Exception as e:
        logger.error(f"Stripe deposit error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})
    
@login_required
def deposit_status(request, deposit_id):
    try:
        transaction = Transaction.objects.get(
            user=request.user,
            external_id=deposit_id,
            transaction_type='deposit'
        )
        
        return JsonResponse({
            'success': True,
            'status': transaction.status,
            'amount': float(transaction.amount),
            'new_balance': float(transaction.balance_after) if transaction.status == 'completed' else None
        })
        
    except Transaction.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Deposit not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Deposit status error: {e}")
        return JsonResponse({'success': False, 'error': str(e)})
    

@login_required
@csrf_protect
def crypto_withdrawal(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    
    try:
        data = json.loads(request.body)
        amount = Decimal(str(data.get('amount', 0)))
        network = data.get('network', 'ethereum').lower()
        wallet_address = data.get('wallet_address', '').strip()
        
        logger.info(f"Withdrawal request: User={request.user.username}, Amount=${amount}, Network={network}")
        
        # Validation
        if amount < Decimal('10.00'):
            return JsonResponse({'success': False, 'error': 'Minimum withdrawal is $10.00'})
        
        if amount > request.user.balance:
            return JsonResponse({
                'success': False,
                'error': f'Insufficient balance. Available: ${request.user.balance}'
            })
        
        if not wallet_address:
            return JsonResponse({'success': False, 'error': 'Wallet address required'})
        
        # Network-specific validation
        if network == 'ethereum' or network == 'bsc':
            if not wallet_address.startswith('0x') or len(wallet_address) != 42:
                return JsonResponse({'success': False, 'error': 'Invalid Ethereum/BSC address format'})
        elif network == 'polygon':
            if not wallet_address.startswith('0x') or len(wallet_address) != 42:
                return JsonResponse({'success': False, 'error': 'Invalid Polygon address format'})
        
        # Calculate fees
        network_fees = {
            'ethereum': Decimal('5.00'),
            'bsc': Decimal('1.00'),
            'polygon': Decimal('0.50')
        }
        
        network_fee = network_fees.get(network, Decimal('5.00'))
        platform_fee = amount * Decimal('0.02')  # 2%
        total_fee = platform_fee + network_fee
        net_amount = amount - total_fee
        
        if net_amount <= 0:
            return JsonResponse({
                'success': False,
                'error': 'Amount too small after fees'
            })
        
        # Debit user's virtual wallet
        with db_transaction.atomic():
            result = VirtualWalletService.debit_wallet(
                user=request.user,
                amount=amount,
                description=f"Withdrawal to {wallet_address[:10]}... ({network.upper()})",
                transaction_type='withdrawal'
            )
            
            if not result['success']:
                return JsonResponse({
                    'success': False,
                    'error': result.get('error', 'Withdrawal failed')
                })
            
            # Create withdrawal transaction record
            withdrawal_txn = Transaction.objects.create(
                user=request.user,
                transaction_type='withdrawal',
                amount=-amount,  # Negative for withdrawal
                balance_before=result['balance_before'],
                balance_after=result['new_balance'],
                status='processing',
                description=f'USDT withdrawal - {network.upper()}',
                metadata={
                    'wallet_address': wallet_address,
                    'network': network,
                    'requested_amount': float(amount),
                    'platform_fee': float(platform_fee),
                    'network_fee': float(network_fee),
                    'total_fee': float(total_fee),
                    'net_amount': float(net_amount),
                    'provider': 'manual',  # Manual processing for now
                    'requested_at': str(time.time())
                }
            )
            
            logger.info(f"Withdrawal initiated: ${amount} debited from {request.user.username}")
            
            return JsonResponse({
                'success': True,
                'transaction_id': str(withdrawal_txn.id),
                'amount': float(amount),
                'net_amount': float(net_amount),
                'platform_fee': float(platform_fee),
                'network_fee': float(network_fee),
                'total_fee': float(total_fee),
                'new_balance': float(result['new_balance']),
                'message': f'Withdrawal request submitted. You will receive ${net_amount:.2f} after fees.',
                'status': 'processing'
            })
    
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid request format'})
    except Exception as e:
        logger.error(f"Withdrawal error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})
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
from .payment_utils import *
from django.views.decorators.http import require_POST
from .models import Market, CryptocurrencyCategory, EconomicEvent
from predict.models import NewsArticle
from decimal import Decimal, InvalidOperation
from django.views.decorators.csrf import csrf_protect
from .utils import *
from predict.models import Bet, Transaction, UserStats
import logging

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
    }
    
    return render(request, 'profile.html', context)


@login_required 
@csrf_exempt
def place_bet(request):
    """Handle bet placement via AJAX"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    
    try:
        data = json.loads(request.body)
        market_id = data.get('market_id')
        outcome = data.get('outcome')  # UP, DOWN, FLAT
        amount = Decimal(str(data.get('amount', 0)))
        bet_type = data.get('bet_type', 'regular')  # regular or quick
        
        # Validation
        if not all([market_id, outcome, amount]):
            return JsonResponse({'success': False, 'error': 'Missing required fields'})
        
        if outcome not in ['UP', 'DOWN', 'FLAT']:
            return JsonResponse({'success': False, 'error': 'Invalid outcome'})
        
        if amount < Decimal('1.00'):
            return JsonResponse({'success': False, 'error': 'Minimum bet is $1.00'})
        
        if amount > request.user.balance:
            return JsonResponse({'success': False, 'error': 'Insufficient balance'})
        
        # Get market
        try:
            market = Market.objects.get(id=market_id, status='active')
        except Market.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Market not found'})
        
        # Check market is still active
        if not market.is_active:
            return JsonResponse({'success': False, 'error': 'Market is no longer active'})
        
        # Calculate odds based on current volume
        if outcome == 'UP':
            odds = market.up_odds
        elif outcome == 'DOWN':
            odds = market.down_odds
        else:  # FLAT
            odds = market.flat_odds
        
        potential_payout = amount * odds
        
        # Create bet within transaction
        from django.db import transaction as db_transaction
        
        with db_transaction.atomic():
            # Store old balance for transaction record
            old_balance = request.user.balance
            
            # Deduct from user balance
            request.user.balance -= amount
            request.user.save(update_fields=['balance'])
            
            # Create bet record
            bet = Bet.objects.create(
                user=request.user,
                market=market,
                bet_type=bet_type,
                outcome=outcome,
                amount=amount,
                odds_at_bet=odds,
                potential_payout=potential_payout,
                round_number=market.current_round,
                round_start_price=market.round_start_price,
                status='active'
            )
            
            # Update market volume
            market.total_volume += amount
            if outcome == 'UP':
                market.up_volume += amount
            elif outcome == 'DOWN':
                market.down_volume += amount
            else:  # FLAT
                market.flat_volume += amount
            market.save()
            
            # Create transaction record with proper balance tracking
            Transaction.objects.create(
                user=request.user,
                transaction_type='bet',
                amount=-amount,  # Negative because it's deducted
                balance_before=old_balance,
                balance_after=request.user.balance,
                status='completed',
                bet=bet,
                market=market,
                description=f"Bet placed: {outcome} on {market.title}"
            )
            
            # Award XP based on bet amount
            xp_earned = min(int(amount), 50)  # Max 50 XP per bet
            if bet_type == 'quick':
                xp_earned = 25  # Fixed XP for quick bets
            
            request.user.xp += xp_earned
            request.user.save(update_fields=['xp'])
        
        return JsonResponse({
            'success': True,
            'message': f'Bet placed successfully! {xp_earned} XP earned.',
            'bet_id': str(bet.id),
            'new_balance': float(request.user.balance),
            'new_xp': request.user.xp,
            'xp_earned': xp_earned
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@csrf_protect
def wallet_deposit(request):
    """Handle wallet deposit via Stripe"""
    
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
            payment_intent = stripe_service.create_payment_intent(
                amount=amount,
                user=request.user
            )
            
            if payment_intent:
                # Create pending transaction - FIXED: Store payment intent ID
                transaction = Transaction.objects.create(
                    user=request.user,
                    transaction_type='deposit',
                    amount=amount,
                    balance_before=request.user.balance,
                    balance_after=request.user.balance,  # Will update on completion
                    status='pending',
                    stripe_payment_intent_id=payment_intent['id'],  # CRUCIAL: Store this
                    description=f"Wallet deposit via Stripe - ${amount}"
                )
                
                return JsonResponse({
                    'success': True,
                    'client_secret': payment_intent['client_secret'],
                    'amount': float(amount),
                    'transaction_id': str(transaction.id)  # Include for reference
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Unable to process payment. Please try again.'
                })
                
        except Exception as e:
            # Log the full error for debugging
            import logging
            logger = logging.getLogger(__name__)
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
    Handle Stripe webhooks - specifically payment_intent.succeeded events
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    
    # Get webhook secret from environment or settings
    STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')
    
    if not STRIPE_WEBHOOK_SECRET:
        logger.error("STRIPE_WEBHOOK_SECRET not configured")
        return HttpResponse("Webhook secret not configured", status=500)
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
        
        logger.info(f"Received Stripe webhook: {event['type']} - {event['id']}")
        
    except ValueError as e:
        logger.error(f"Invalid payload: {e}")
        return HttpResponse("Invalid payload", status=400)
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid signature: {e}")
        return HttpResponse("Invalid signature", status=400)
    
    # Handle the event
    if event['type'] == 'payment_intent.succeeded':
        payment_intent = event['data']['object']
        success = handle_successful_payment(payment_intent)
        return HttpResponse("Success" if success else "Processing failed", status=200)
        
    elif event['type'] == 'payment_intent.payment_failed':
        payment_intent = event['data']['object']
        handle_failed_payment(payment_intent)
        
    else:
        logger.info(f"Unhandled event type: {event['type']}")
    
    return HttpResponse("Event received", status=200)


def handle_successful_payment(payment_intent):
    """
    FIXED: Handle successful payment - update transaction and user balance
    """
    try:
        payment_intent_id = payment_intent['id']
        amount_cents = payment_intent.get('amount', 0)
        amount_dollars = Decimal(str(amount_cents)) / Decimal('100')
        
        logger.info(f"Processing successful payment: {payment_intent_id} for ${amount_dollars}")
        
        from predict.models import Transaction
        from django.db import transaction as db_transaction
        
        # Use atomic transaction to ensure data consistency
        with db_transaction.atomic():
            try:
                # Find the pending transaction - this is the critical part
                transaction = Transaction.objects.select_for_update().get(
                    stripe_payment_intent_id=payment_intent_id,
                    status='pending',
                    transaction_type='deposit'
                )
                
                logger.info(f"Found pending transaction {transaction.id} for user {transaction.user.username}")
                
                # Get fresh user instance
                user = transaction.user
                user.refresh_from_db()
                
                # Store old balance
                old_balance = user.balance
                
                # Update user balance
                user.balance += transaction.amount
                user.save(update_fields=['balance'])
                
                # CRITICAL: Update transaction status to completed
                transaction.status = 'completed'
                transaction.balance_before = old_balance
                transaction.balance_after = user.balance
                transaction.completed_at = timezone.now()
                transaction.save(update_fields=['status', 'balance_before', 'balance_after', 'completed_at'])
                
                logger.info(f"Transaction {transaction.id} successfully updated to completed status")
                
                return True
                
            except Transaction.DoesNotExist:
                logger.error(f"No pending transaction found for payment_intent: {payment_intent_id}")
                
                # Debug: check what transactions exist with this payment_intent_id
                existing = Transaction.objects.filter(stripe_payment_intent_id=payment_intent_id)
                for txn in existing:
                    logger.info(f"Found existing transaction {txn.id}: status={txn.status}, type={txn.transaction_type}")
                
                return False
        
    except Exception as e:
        logger.error(f"Error in handle_successful_payment: {e}", exc_info=True)
        return False


def handle_failed_payment(payment_intent):
    """
    Handle failed payment - mark transaction as failed
    """
    try:
        payment_intent_id = payment_intent['id']
        
        logger.info(f"Processing failed payment: {payment_intent_id}")
        
        # Find the pending transaction and mark it as failed
        try:
            from predict.models import Transaction
            
            transaction = Transaction.objects.get(
                stripe_payment_intent_id=payment_intent_id,
                status='pending'
            )
            
            transaction.status = 'failed'
            transaction.description += ' - Payment failed'
            transaction.save(update_fields=['status', 'description'])
            
            logger.info(f"Marked transaction {transaction.id} as failed")
            
        except Transaction.DoesNotExist:
            logger.error(f"No pending transaction found for failed payment: {payment_intent_id}")
    
    except Exception as e:
        logger.error(f"Error processing failed payment: {e}", exc_info=True)


@login_required
@csrf_protect
def wallet_deposit(request):
    """Handle wallet deposit via Stripe"""
    
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
            
            stripe_service = StripePaymentService()
            payment_intent = stripe_service.create_payment_intent(
                amount=amount,
                user=request.user
            )
            
            if payment_intent:
                from predict.models import Transaction
                
                transaction = Transaction.objects.create(
                    user=request.user,
                    transaction_type='deposit',
                    amount=amount,
                    balance_before=request.user.balance,
                    balance_after=request.user.balance,  # Will update on completion
                    status='pending',
                    stripe_payment_intent_id=payment_intent['id'],  # CRUCIAL: Store this exactly
                    description=f"Wallet deposit via Stripe - ${amount}"
                )
                
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Created pending transaction {transaction.id} with payment_intent_id: {payment_intent['id']}")
                
                return JsonResponse({
                    'success': True,
                    'client_secret': payment_intent['client_secret'],
                    'amount': float(amount),
                    'transaction_id': str(transaction.id),
                    'payment_intent_id': payment_intent['id']  # Include for debugging
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Unable to process payment. Please try again.'
                })
                
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Deposit error for user {request.user.id}: {str(e)}", exc_info=True)
            
            return JsonResponse({
                'success': False,
                'error': f'Payment error: {str(e)}'
            })
    
    return redirect('dashboard')


@login_required
def wallet_withdraw(request):
    """Handle wallet withdrawal"""
    from .payment_utils import WithdrawalService
    
    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount', 0))
            wallet_address = request.POST.get('wallet_address', '').strip()
            network = request.POST.get('network', 'ethereum')
            
            # Validation
            if amount < Decimal('10.00'):
                messages.error(request, 'Minimum withdrawal is $10.00')
                return redirect('dashboard')
            
            if amount > request.user.balance:
                messages.error(request, 'Insufficient balance')
                return redirect('dashboard')
            
            if not wallet_address:
                messages.error(request, 'Wallet address is required')
                return redirect('dashboard')
            
            # Process withdrawal
            withdrawal_service = WithdrawalService()
            result = withdrawal_service.process_withdrawal(
                user=request.user,
                amount=amount,
                wallet_address=wallet_address,
                network=network
            )
            
            if result['success']:
                messages.success(request, 'Withdrawal request submitted successfully!')
            else:
                messages.error(request, result['error'])
                
        except Exception as e:
            messages.error(request, f'Withdrawal error: {str(e)}')
    
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


# Manual data sync view for admin
@login_required
def manual_data_sync(request):
    """Manual trigger for data synchronization (admin only)"""
    if not request.user.is_staff:
        return JsonResponse({'error': 'Admin access required'}, status=403)
    
    try:
        from .utils import DataSyncService
        DataSyncService.sync_all_data()
        return JsonResponse({'success': True, 'message': 'Data sync completed'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

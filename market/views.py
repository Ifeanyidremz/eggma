from django.shortcuts import render
from .models import *
from .utils import CryptoPriceService
from datetime import timedelta
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from predict.models import *



def marketPage(request):
    """Main market listing page with filters and real-time data"""
    
    # Get filter parameters
    category_filter = request.GET.get('category', 'all')
    search_query = request.GET.get('search', '')
    sort_by = request.GET.get('sort', 'popular')
    
    # Base queryset
    markets = Market.objects.filter(status='active').select_related('category', 'creator')
    
    # Apply filters
    if category_filter != 'all':
        markets = markets.filter(category__category_type=category_filter)
    
    if search_query:
        markets = markets.filter(
            Q(title__icontains=search_query) |
            Q(description__icontains=search_query)
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
    
    # Paginate results
    from django.core.paginator import Paginator
    paginator = Paginator(markets, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get trending markets (highest volume in last 24h)
    trending_markets = Market.objects.filter(
        status='active',
        created_at__gte=timezone.now() - timedelta(days=1)
    ).order_by('-total_volume')[:3]
    
    # Get categories for filters
    categories = CryptocurrencyCategory.objects.filter(is_active=True)
    
    # Get real-time crypto prices
    crypto_prices = CryptoPriceService.get_crypto_prices()
    
    # Calculate additional market data
    for market in page_obj:
        market.participant_count = market.bets.values('user').distinct().count()
        market.time_remaining = max(0, (market.resolution_date - timezone.now()).days)
        
        # Add price data if market is crypto-related
        market.crypto_data = None
        for symbol, data in crypto_prices.items():
            if symbol.lower() in market.title.lower():
                market.crypto_data = data
                break
    
    context = {
        'markets': page_obj,
        'trending_markets': trending_markets,
        'categories': categories,
        'crypto_prices': crypto_prices,
        'current_category': category_filter,
        'search_query': search_query,
        'sort_by': sort_by,
        'total_markets': paginator.count,
    }
    
    return render(request, 'market_list.html', context)




@login_required
def marketDetail(request, market_id):
    """Market detail page with betting functionality"""
    
    market = get_object_or_404(Market, id=market_id)
    
    # Get user's existing bets on this market
    user_bets = Bet.objects.filter(
        user=request.user,
        market=market,
        status='active'
    ).order_by('-placed_at')
    
    # Get market statistics
    total_bets = market.bets.filter(status='active').count()
    unique_participants = market.bets.filter(status='active').values('user').distinct().count()
    
    # Get recent bets (anonymized)
    recent_bets = market.bets.filter(status='active').select_related('user')[:10]
    
    # Get comments
    comments = market.comments.filter(is_hidden=False).select_related('user')[:20]
    
    # Get related crypto price data
    crypto_prices = CryptoPriceService.get_crypto_prices()
    market.crypto_data = None
    for symbol, data in crypto_prices.items():
        if symbol.lower() in market.title.lower():
            market.crypto_data = data
            break
    
    context = {
        'market': market,
        'user_bets': user_bets,
        'total_bets': total_bets,
        'unique_participants': unique_participants,
        'recent_bets': recent_bets,
        'comments': comments,
        'crypto_prices': crypto_prices,
        'user_balance': request.user.balance,
        'min_bet': market.min_bet,
        'max_bet': market.max_bet,
    }
    
    return render(request, 'market_detail.html', context)


@login_required
def userPortfolio(request):
    """User's betting portfolio and statistics"""
    
    # Get user's active bets
    active_bets = Bet.objects.filter(
        user=request.user,
        status='active'
    ).select_related('market').order_by('-placed_at')
    
    # Get user's bet history
    bet_history = Bet.objects.filter(
        user=request.user,
        status__in=['won', 'lost']
    ).select_related('market').order_by('-resolved_at')[:20]
    
    # Get or create user stats
    user_stats, created = UserStats.objects.get_or_create(user=request.user)
    
    # Calculate portfolio value
    potential_winnings = sum([bet.potential_payout for bet in active_bets])
    
    context = {
        'active_bets': active_bets,
        'bet_history': bet_history,
        'user_stats': user_stats,
        'potential_winnings': potential_winnings,
        'user_balance': request.user.balance,
    }
    
    return render(request, 'profile.html', context)

from django.urls import path
from . import views

# urlpatterns = [
#     path('', views.marketPage, name="market-data"),
#     path('marketz-full/', views.marketDetail, name="market-detail"),
#     path('portfolio/', views.userPortfolio, name="live-data"),
# ]


urlpatterns = [
    path('', views.marketPage, name='market-data'),
    # path('detail/', views.marketDetail, name='market-detail'),
    path('detail/<uuid:market_id>/', views.marketDetail, name='market-detail'),
    path('portfolio/', views.userPortfolio, name="dashboard"),
    
    # API endpoints
    path('api/place-bet/', views.place_bet, name='place-bet'),
    path('api/market/<uuid:market_id>/', views.api_market_data, name='api-market-data'),
    path('api/crypto-prices/', views.api_crypto_prices, name='api-crypto-prices'),
    path('api/user-stats/', views.api_user_stats, name='api-user-stats'),
    
    # Wallet management
    path('wallet/deposit/', views.wallet_deposit, name='wallet-deposit'),
    path('wallet/withdraw/', views.wallet_withdraw, name='wallet-withdraw'),

    path('api/crypto/<str:symbol>/ohlc/', views.api_crypto_ohlc, name='api-crypto-ohlc'),
    path('api/market/<str:market_id>/ohlc/', views.api_market_ohlc, name='api-market-ohlc'),
    path('api/market/<str:market_id>/', views.api_market_data, name='api-market-data'),
    path('api/crypto-prices/', views.api_crypto_prices, name='api-crypto-prices'),
    path('api/user-stats/', views.api_user_stats, name='api-user-stats'),

    path('stripe-webhook/', views.stripe_webhook, name='stripe-webhook'),

    path('debug/webhook/', views.webhook_debug_view, name='webhook_debug_view'),
    path('debug/fix-transaction/', views.fix_transaction_view, name='fix_transaction_view'),
    path('debug/process-webhook/', views.process_webhook_manually_view, name='process_webhook_manually_view'),

    # Add to urls.py
    path('debug/webhook-comprehensive/', views.comprehensive_webhook_debug, name='comprehensive_webhook_debug'),
    
]

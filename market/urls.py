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

    # path('webhooks/coinremitter/', views.coinremitter_webhook, name='coinremitter_webhook'),

    path('api/crypto/<str:symbol>/ohlc/', views.api_crypto_ohlc, name='api-crypto-ohlc'),
    path('api/market/<str:market_id>/ohlc/', views.api_market_ohlc, name='api-market-ohlc'),
    path('api/market/<str:market_id>/', views.api_market_data, name='api-market-data'),
    path('api/crypto-prices/', views.api_crypto_prices, name='api-crypto-prices'),
    path('api/user-stats/', views.api_user_stats, name='api-user-stats'),

    path('stripe-webhook/', views.stripe_webhook, name='stripe-webhook'),

    path('wallet/deposit-crypto/', views.crypto_deposit, name='crypto-deposit'),
    path('wallet/withdraw-crypto/', views.crypto_withdraw, name='crypto-withdraw'),
    path('wallet/transfer/', views.wallet_transfer, name='wallet-transfer'),
    path('wallet/nowpayments-ipn/', views.nowpayments_ipn, name='nowpayments-ipn'),
    path('referral/dashboard/', views.referral_dashboard, name='referral-dashboard'),


]

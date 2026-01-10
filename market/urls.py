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

    path('target-bet', views.place_target_bet, name='place-target-bet'),

    path('target-market/create/', views.create_price_target_market, name='create-target-market'),

    path('api/crypto/<str:symbol>/ohlc/', views.api_crypto_ohlc, name='api-crypto-ohlc'),
    path('api/market/<str:market_id>/ohlc/', views.api_market_ohlc, name='api-market-ohlc'),
    path('api/market/<str:market_id>/', views.api_market_data, name='api-market-data'),
    path('api/crypto-prices/', views.api_crypto_prices, name='api-crypto-prices'),
    path('api/user-stats/', views.api_user_stats, name='api-user-stats'),

    path('stripe-webhook/', views.stripe_webhook, name='stripe-webhook'),

    path('wallet/deposit-card/', views.stripe_card_deposit, name='stripe_card_deposit'),
    path('wallet/crypto-deposit/', views.crypto_deposit_b2binpay, name='crypto_deposit_b2binpay'),
    path('wallet/b2binpay-callback/', views.b2binpay_callback, name='b2binpay_callback'),
    path('wallet/deposit-status/<str:deposit_id>/', views.deposit_status, name='deposit_status'),
    path('wallet/withdraw/', views.crypto_withdrawal, name='crypto_withdrawal'),
    path('wallet/transfer/', views.virtual_wallet_transfer, name='virtual_wallet_transfer'),
    path('wallet/balance/', views.get_wallet_balance, name='get_wallet_balance'),
    path('wallet/dashboard/', views.wallet_dashboard, name='wallet_dashboard'),


]

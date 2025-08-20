from django.urls import path
from . import views

urlpatterns = [
    path('', views.marketPage, name="market-data"),
    path('marketz-full/', views.marketDetail, name="market-detail"),
    path('live-data/', views.userPortfolio, name="live-data"),
]

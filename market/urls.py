from django.urls import path
from . import views

urlpatterns = [
    path('market/', views.marketPage, name="market-data"),
]

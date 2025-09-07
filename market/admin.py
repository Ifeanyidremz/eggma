from django.contrib import admin
from .models import CryptocurrencyCategory, Market, EconomicEvent
# Register your models here.

admin.site.register(CryptocurrencyCategory)
admin.site.register(Market)
admin.site.register(EconomicEvent)
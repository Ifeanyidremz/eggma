from django.contrib import admin
from .models import Bet,Transaction,MarketComment,UserStats,NewsArticle,WalletAddress
# Register your models here.


admin.site.register(Bet)
admin.site.register(Transaction)
admin.site.register(MarketComment)
admin.site.register(UserStats)
admin.site.register(NewsArticle)
admin.site.register(WalletAddress)
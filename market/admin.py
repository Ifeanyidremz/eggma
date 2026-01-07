from django.contrib import admin
from .models import Market
from .utils import PriceTargetMarketService
from django.utils.html import format_html


@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'market_type', 'status', 
        'target_price_display', 'highest_price_display',
        'resolution_date', 'total_volume'
    ]
    
    list_filter = ['market_type', 'status', 'category']
    
    actions = ['resolve_target_markets_admin']
    
    def target_price_display(self, obj):
        """Show target price for target markets"""
        if obj.market_type == 'target' and obj.target_price:
            return f"${obj.target_price:,.0f}"
        return '-'
    target_price_display.short_description = 'Target Price'
    
    def highest_price_display(self, obj):
        """Show highest price reached"""
        if obj.market_type == 'target' and obj.highest_price_reached:
            reached = obj.highest_price_reached >= obj.target_price if obj.target_price else False
            color = 'green' if reached else 'orange'
            return format_html(
                '<span style="color: {};">${:,.2f}</span>',
                color,
                obj.highest_price_reached
            )
        return '-'
    highest_price_display.short_description = 'Highest Reached'
    
    def resolve_target_markets_admin(self, request, queryset):
        """Admin action to manually resolve target markets"""
        resolved_count = 0
        
        for market in queryset.filter(market_type='target', status='active'):
            try:
                PriceTargetMarketService.resolve_target_market(market)
                resolved_count += 1
            except Exception as e:
                self.message_user(
                    request,
                    f"Error resolving market {market.id}: {str(e)}",
                    level='ERROR'
                )
        
        self.message_user(
            request,
            f"Successfully resolved {resolved_count} markets"
        )
    
    resolve_target_markets_admin.short_description = "Manually resolve selected target markets"
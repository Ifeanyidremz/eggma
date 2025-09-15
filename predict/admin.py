from django.contrib import admin
from .models import Bet,Transaction,MarketComment,UserStats,NewsArticle,WalletAddress
from django.utils.html import format_html
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.contrib import messages
from decimal import Decimal
# Register your models here.



@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'user', 'transaction_type', 'amount', 'status', 
        'created_at', 'blockchain_link', 'coinremitter_status'
    ]
    list_filter = [
        'transaction_type', 'status', 'created_at',
        ('user', admin.RelatedOnlyFieldListFilter)
    ]
    search_fields = ['user__username', 'user__email', 'external_id', 'blockchain_tx_hash']
    readonly_fields = [
        'id', 'created_at', 'updated_at', 'balance_before', 'balance_after'
    ]
    ordering = ['-created_at']
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('user', 'transaction_type', 'amount', 'status', 'description')
        }),
        ('Balance', {
            'fields': ('balance_before', 'balance_after')
        }),
        ('External References', {
            'fields': ('external_id', 'blockchain_tx_hash', 'stripe_payment_intent_id')
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def blockchain_link(self, obj):
        """Display clickable blockchain explorer link"""
        if obj.blockchain_tx_hash and obj.transaction_type == 'withdrawal':
            # USDT on Ethereum - you can adjust for other networks
            url = f"https://etherscan.io/tx/{obj.blockchain_tx_hash}"
            return format_html(
                '<a href="{}" target="_blank">View on Etherscan</a>',
                url
            )
        return '-'
    blockchain_link.short_description = 'Blockchain'
    
    def coinremitter_status(self, obj):
        """Show Coinremitter status for withdrawals"""
        if obj.transaction_type == 'withdrawal' and obj.external_id:
            return format_html(
                '<span style="color: {};">{}</span>',
                'green' if obj.status == 'completed' else 'orange' if obj.status == 'pending' else 'red',
                obj.status.upper()
            )
        return '-'
    coinremitter_status.short_description = 'Status'
    
    actions = ['check_withdrawal_status', 'refund_failed_withdrawal']
    
    def check_withdrawal_status(self, request, queryset):
        """Check status of selected withdrawals"""
        from market.utils import CoinremitterWithdrawalService
        
        service = CoinremitterWithdrawalService()
        updated_count = 0
        
        for transaction in queryset.filter(transaction_type='withdrawal', external_id__isnull=False):
            try:
                result = service.get_transaction_status(transaction.external_id)
                
                if result['success']:
                    old_status = transaction.status
                    new_status = result.get('status')
                    
                    if new_status == 'success' and old_status != 'completed':
                        transaction.status = 'completed'
                        transaction.blockchain_tx_hash = result.get('tx_hash')
                        transaction.save()
                        updated_count += 1
                        
                    elif new_status == 'failed' and old_status != 'failed':
                        transaction.status = 'failed'
                        transaction.save()
                        updated_count += 1
                        
            except Exception as e:
                messages.error(request, f"Error checking transaction {transaction.id}: {str(e)}")
        
        messages.success(request, f"Updated {updated_count} transactions")
    
    check_withdrawal_status.short_description = "Check Coinremitter status"

  
    def refund_failed_withdrawal(self, request, queryset):
        """Manually refund failed withdrawals"""
        refunded_count = 0
        
        for transaction in queryset.filter(transaction_type='withdrawal', status='failed'):
            if not transaction.metadata.get('refunded'):
                try:
                    user = transaction.user
                    refund_amount = abs(transaction.amount)
                    
                    # Add money back to user account
                    user.balance += refund_amount
                    user.save()
                    
                    # Mark as refunded
                    transaction.metadata['refunded'] = True
                    transaction.metadata['manual_refund'] = True
                    transaction.save()
                    
                    # Create refund transaction
                    Transaction.objects.create(
                        user=user,
                        transaction_type='refund',
                        amount=refund_amount,
                        balance_before=user.balance - refund_amount,
                        balance_after=user.balance,
                        status='completed',
                        description=f'Manual refund for failed withdrawal {transaction.id}',
                        metadata={'original_withdrawal': str(transaction.id)}
                    )
                    
                    refunded_count += 1
                    
                except Exception as e:
                    messages.error(request, f"Error refunding transaction {transaction.id}: {str(e)}")
        
        messages.success(request, f"Refunded {refunded_count} transactions")
    
    refund_failed_withdrawal.short_description = "Refund failed withdrawals"
  


admin.site.register(Bet)
admin.site.register(MarketComment)
admin.site.register(UserStats)
admin.site.register(NewsArticle)
admin.site.register(WalletAddress)

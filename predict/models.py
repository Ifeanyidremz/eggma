from django.db import models
from decimal import Decimal
from acounts.models import CustomUser
import uuid
from market.models import Market

class Bet(models.Model):
    """Individual user bets on markets"""
    
    OUTCOME_CHOICES = [
        ('YES', 'Yes'),
        ('NO', 'No'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('won', 'Won'),
        ('lost', 'Lost'),
        ('refunded', 'Refunded'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='bets')
    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='bets')
    
    # Bet details
    outcome = models.CharField(max_length=3, choices=OUTCOME_CHOICES)
    amount = models.DecimalField(max_digits=15, decimal_places=6)
    odds_at_bet = models.DecimalField(max_digits=8, decimal_places=4)
    potential_payout = models.DecimalField(max_digits=20, decimal_places=6)
    
    # Status and timing
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    placed_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    # Transaction details
    actual_payout = models.DecimalField(
        max_digits=20, 
        decimal_places=6, 
        null=True, 
        blank=True
    )
    fees_paid = models.DecimalField(
        max_digits=10, 
        decimal_places=6, 
        default=Decimal('0.000000')
    )

    class Meta:
        ordering = ['-placed_at']
        indexes = [
            models.Index(fields=['user', '-placed_at']),
            models.Index(fields=['market', 'outcome']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.user.username} - ${self.amount} on {self.outcome} - {self.market.title[:50]}"
    
    def save(self, *args, **kwargs):
        # Calculate potential payout when bet is created
        if not self.potential_payout:
            self.potential_payout = self.amount * self.odds_at_bet
        super().save(*args, **kwargs)


class Transaction(models.Model):
    """Track all financial transactions"""
    
    TYPE_CHOICES = [
        ('deposit', 'Deposit'),
        ('withdrawal', 'Withdrawal'),
        ('bet', 'Bet Placed'),
        ('payout', 'Payout'),
        ('refund', 'Refund'),
        ('fee', 'Fee'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='transactions')
    
    # Transaction details
    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    balance_before = models.DecimalField(max_digits=20, decimal_places=6)
    balance_after = models.DecimalField(max_digits=20, decimal_places=6)
    
    # Related objects
    bet = models.ForeignKey(Bet, on_delete=models.SET_NULL, null=True, blank=True)
    market = models.ForeignKey(Market, on_delete=models.SET_NULL, null=True, blank=True)
    
    # External references
    blockchain_tx_hash = models.CharField(max_length=66, blank=True, null=True)
    external_id = models.CharField(max_length=100, blank=True, null=True)
    
    # Metadata
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['transaction_type']),
            models.Index(fields=['blockchain_tx_hash']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.get_transaction_type_display()} - ${self.amount}"


class MarketComment(models.Model):
    """Comments and discussions on markets"""
    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    content = models.TextField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Moderation
    is_flagged = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} on {self.market.title[:30]}"


class UserStats(models.Model):
    """Cached user statistics for performance"""
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='stats')
    
    # Betting stats
    total_bets = models.IntegerField(default=0)
    active_bets = models.IntegerField(default=0)
    won_bets = models.IntegerField(default=0)
    lost_bets = models.IntegerField(default=0)
    
    # Financial stats
    total_wagered = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0'))
    total_winnings = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0'))
    net_profit = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0'))
    
    # Performance
    win_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0'))  # 0.0000 to 1.0000
    roi = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal('0'))  # Return on Investment
    
    # Market creation
    markets_created = models.IntegerField(default=0)
    creator_fees_earned = models.DecimalField(max_digits=15, decimal_places=6, default=Decimal('0'))
    
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} Stats - Win Rate: {self.win_rate:.1%}"
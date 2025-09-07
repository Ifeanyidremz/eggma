from django.db import models
from decimal import Decimal
from acounts.models import CustomUser
import uuid
from market.models import Market

class Bet(models.Model):
    """Individual user bets on markets"""
    
    OUTCOME_CHOICES = [
        ('UP', 'Up'),
        ('DOWN', 'Down'),
        ('FLAT', 'Flat'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('won', 'Won'),
        ('lost', 'Lost'),
        ('refunded', 'Refunded'),
    ]
    
    BET_TYPES = [
        ('regular', 'Regular Bet'),
        ('quick', 'Quick Bet'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='bets')
    market = models.ForeignKey(Market, on_delete=models.CASCADE, related_name='bets')
    
    # Bet details
    bet_type = models.CharField(max_length=10, choices=BET_TYPES, default='regular')
    outcome = models.CharField(max_length=4, choices=OUTCOME_CHOICES)
    amount = models.DecimalField(max_digits=15, decimal_places=6)
    odds_at_bet = models.DecimalField(max_digits=8, decimal_places=4)
    potential_payout = models.DecimalField(max_digits=20, decimal_places=6)
    
    # Round tracking
    round_number = models.IntegerField(default=1)
    round_start_price = models.DecimalField(max_digits=15, decimal_places=6, null=True, blank=True)
    round_end_price = models.DecimalField(max_digits=15, decimal_places=6, null=True, blank=True)
    
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
            models.Index(fields=['status', 'round_number']),
        ]

    def __str__(self):
        return f"{self.user.username} - ${self.amount} on {self.outcome} - {self.market.title[:50]}"
    
    def save(self, *args, **kwargs):
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
        ('bonus', 'Bonus'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='transactions')
    
    # Transaction details
    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=20, decimal_places=6)
    balance_before = models.DecimalField(max_digits=20, decimal_places=6)
    balance_after = models.DecimalField(max_digits=20, decimal_places=6)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Related objects
    bet = models.ForeignKey(Bet, on_delete=models.SET_NULL, null=True, blank=True)
    market = models.ForeignKey(Market, on_delete=models.SET_NULL, null=True, blank=True)
    
    # External payment references
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, null=True)
    blockchain_tx_hash = models.CharField(max_length=66, blank=True, null=True)
    external_id = models.CharField(max_length=100, blank=True, null=True)
    
    # Metadata
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['transaction_type', 'status']),
            models.Index(fields=['stripe_payment_intent_id']),
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
    win_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0'))
    roi = models.DecimalField(max_digits=8, decimal_places=4, default=Decimal('0'))
    
    # Streaks and achievements
    current_win_streak = models.IntegerField(default=0)
    longest_win_streak = models.IntegerField(default=0)
    
    # Market creation
    markets_created = models.IntegerField(default=0)
    creator_fees_earned = models.DecimalField(max_digits=15, decimal_places=6, default=Decimal('0'))
    
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} Stats - Win Rate: {self.win_rate:.1%}"
    
    def update_stats(self):
        """Recalculate all user statistics"""
        from django.db.models import Count, Sum, Avg
        
        bets = self.user.bets.all()
        
        self.total_bets = bets.count()
        self.active_bets = bets.filter(status='active').count()
        self.won_bets = bets.filter(status='won').count()
        self.lost_bets = bets.filter(status='lost').count()
        
        self.total_wagered = bets.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')
        
        self.total_winnings = bets.filter(status='won').aggregate(
            total=Sum('actual_payout')
        )['total'] or Decimal('0')
        
        if self.total_bets > 0:
            self.win_rate = Decimal(str(self.won_bets / self.total_bets))
        
        if self.total_wagered > 0:
            self.roi = (self.total_winnings - self.total_wagered) / self.total_wagered
        
        self.save()


class WalletAddress(models.Model):
    """User wallet addresses for withdrawals"""
    
    NETWORK_CHOICES = [
        ('ethereum', 'Ethereum (ERC-20)'),
        ('bsc', 'Binance Smart Chain (BEP-20)'),
        ('polygon', 'Polygon (MATIC)'),
        ('bitcoin', 'Bitcoin'),
    ]
    
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='wallet_addresses')
    address = models.CharField(max_length=100)
    network = models.CharField(max_length=20, choices=NETWORK_CHOICES)
    label = models.CharField(max_length=50, default='My Wallet')
    is_verified = models.BooleanField(default=False)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['user', 'address', 'network']
    
    def __str__(self):
        return f"{self.user.username} - {self.label} ({self.network})"
    
    def save(self, *args, **kwargs):
        # Ensure only one default wallet per user
        if self.is_default:
            WalletAddress.objects.filter(user=self.user, is_default=True).update(is_default=False)
        super().save(*args, **kwargs)


class NewsArticle(models.Model):
    """Market-moving news articles"""
    
    IMPACT_LEVELS = [
        ('high', 'High Impact'),
        ('medium', 'Medium Impact'),
        ('low', 'Low Impact'),
    ]
    
    title = models.CharField(max_length=500)
    summary = models.TextField()
    impact_level = models.CharField(max_length=10, choices=IMPACT_LEVELS)
    source = models.CharField(max_length=100)
    url = models.URLField(blank=True)
    
    published_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    
    # Related markets
    related_markets = models.ManyToManyField(Market, blank=True)
    
    class Meta:
        ordering = ['-published_at']
    
    def __str__(self):
        return f"{self.title} - {self.impact_level}"
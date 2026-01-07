from django.db import models
from decimal import Decimal
from acounts.models import CustomUser
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid
from datetime import datetime, timezone


class CryptocurrencyCategory(models.Model):
    """Cryptocurrency-specific market categories"""
    
    CRYPTO_CATEGORIES = [
        ('bitcoin', 'Bitcoin (BTC)'),
        ('ethereum', 'Ethereum (ETH)'),
        ('altcoins', 'Altcoins'),
        ('defi', 'DeFi Tokens'),
        ('nft', 'NFT Collections'),
        ('memecoins', 'Meme Coins'),
        ('stablecoins', 'Stablecoins'),
        ('layer1', 'Layer 1 Blockchains'),
        ('layer2', 'Layer 2 Solutions'),
        ('exchanges', 'Exchange Tokens'),
        ('gaming', 'Gaming Tokens'),
        ('metaverse', 'Metaverse Tokens'),
        ('ai', 'AI Tokens'),
        ('privacy', 'Privacy Coins'),
        ('governance', 'DAO Governance'),
        ('general', 'General Crypto'),
    ]
    
    category_type = models.CharField(max_length=20, choices=CRYPTO_CATEGORIES, unique=True)
    display_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=10, default='₿')
    color_code = models.CharField(max_length=7, default='#F7931A')
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Cryptocurrency Categories"
        ordering = ['sort_order', 'display_name']

    def __str__(self):
        return self.display_name


class Market(models.Model):
    """Main prediction market model"""
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('closed', 'Closed'),
        ('resolved', 'Resolved'),
        ('cancelled', 'Cancelled'),
    ]
    
    MARKET_TYPES = [
        ('event', 'Economic Event'),
        ('price', 'Price Prediction'),
        ('quick', 'Quick Predict'),
        ('target', 'Price Target'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    market_type = models.CharField(max_length=10, choices=MARKET_TYPES, default='price')
    creator = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='created_markets')
    category = models.ForeignKey(CryptocurrencyCategory, on_delete=models.CASCADE, related_name='markets')
    
    # Trading pair information
    base_currency = models.CharField(max_length=10, default='BTC')  # BTC, ETH, SOL
    quote_currency = models.CharField(max_length=10, default='USDT')
    
    # Market configuration
    min_bet = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1.00'))
    max_bet = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('10000.00'))
    
    # Time settings for different market types
    created_at = models.DateTimeField(auto_now_add=True)
    resolution_date = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    round_duration = models.IntegerField(default=900)  # Duration in seconds (15m default)
    
    # Market state
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    winning_outcome = models.CharField(max_length=10, choices=[('UP', 'Up'), ('DOWN', 'Down'), ('FLAT', 'Flat')], null=True, blank=True)
    
    # Volume tracking
    total_volume = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    up_volume = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    down_volume = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    flat_volume = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    
    # Current round tracking
    current_round = models.IntegerField(default=1)
    round_start_time = models.DateTimeField(null=True, blank=True)
    round_start_price = models.DecimalField(max_digits=15, decimal_places=6, null=True, blank=True)
    
    # Fee structure
    creator_fee_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=4, 
        default=Decimal('0.0200'),
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('0.1000'))]
    )
    platform_fee_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=4, 
        default=Decimal('0.0100'),
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('0.0500'))]
    )
    
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['category', '-total_volume']),
            models.Index(fields=['resolution_date']),
            models.Index(fields=['market_type', 'status']),
        ]

    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"
    
    @property
    def is_active(self):
        return (self.status == 'active' and 
                self.resolution_date > datetime.now(timezone.utc))
    
    @property
    def trading_pair(self):
        return f"{self.base_currency}/{self.quote_currency}"
    
    @property
    def up_probability(self):
        """Calculate UP probability based on volume"""
        if self.total_volume == 0:
            return Decimal('0.33')
        return self.up_volume / self.total_volume
    
    @property
    def down_probability(self):
        """Calculate DOWN probability based on volume"""
        if self.total_volume == 0:
            return Decimal('0.33')
        return self.down_volume / self.total_volume
    
    @property
    def flat_probability(self):
        """Calculate FLAT probability based on volume"""
        if self.total_volume == 0:
            return Decimal('0.34')
        return self.flat_volume / self.total_volume
    
    @property
    def up_odds(self):
        """Calculate UP odds (multiplier)"""
        prob = self.up_probability
        if prob == 0:
            return Decimal('2.00')
        return min(Decimal('1.00') / prob, Decimal('100.00'))
    
    @property
    def down_odds(self):
        """Calculate DOWN odds (multiplier)"""
        prob = self.down_probability
        if prob == 0:
            return Decimal('2.00')
        return min(Decimal('1.00') / prob, Decimal('100.00'))
    
    @property
    def flat_odds(self):
        """Calculate FLAT odds (multiplier)"""
        prob = self.flat_probability
        if prob == 0:
            return Decimal('3.00')
        return min(Decimal('1.00') / prob, Decimal('100.00'))
    
    def get_participant_count(self):
        """Get number of unique participants in current round"""
        return self.bets.filter(
            round_number=self.current_round,
            status='active'
        ).values('user').distinct().count()


class EconomicEvent(models.Model):
    """Economic events that affect crypto markets"""
    
    EVENT_TYPES = [
        ('cpi', 'Consumer Price Index'),
        ('fomc', 'Federal Open Market Committee'),
        ('nfp', 'Non-Farm Payrolls'),
        ('gdp', 'GDP Release'),
        ('unemployment', 'Unemployment Data'),
        ('retail_sales', 'Retail Sales'),
    ]
    
    IMPACT_LEVELS = [
        ('high', 'High Impact'),
        ('medium', 'Medium Impact'),
        ('low', 'Low Impact'),
    ]
    
    name = models.CharField(max_length=200)
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    impact_level = models.CharField(max_length=10, choices=IMPACT_LEVELS)
    description = models.TextField()
    
    scheduled_time = models.DateTimeField()
    actual_time = models.DateTimeField(null=True, blank=True)
    
    expected_value = models.CharField(max_length=50, blank=True)
    actual_value = models.CharField(max_length=50, blank=True)
    previous_value = models.CharField(max_length=50, blank=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['scheduled_time']
    
    def __str__(self):
        return f"{self.name} - {self.scheduled_time.strftime('%Y-%m-%d %H:%M')}"
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
    icon = models.CharField(max_length=10, default='₿')  # Crypto symbols/emojis
    color_code = models.CharField(max_length=7, default='#F7931A')  # Hex color for UI
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Cryptocurrency Categories"
        ordering = ['sort_order', 'display_name']

    def __str__(self):
        return self.display_name
    
    @classmethod
    def get_default_categories(cls):
        """Create default crypto categories if they don't exist"""
        defaults = [
            ('bitcoin', 'Bitcoin (BTC)', '₿', '#F7931A', 1),
            ('ethereum', 'Ethereum (ETH)', 'Ξ', '#627EEA', 2),
            ('altcoins', 'Altcoins', '🚀', '#00D4AA', 3),
            ('defi', 'DeFi Tokens', '🏦', '#FF6B6B', 4),
            ('nft', 'NFT Collections', '🎨', '#9B59B6', 5),
            ('memecoins', 'Meme Coins', '🐕', '#FFD93D', 6),
            ('layer1', 'Layer 1 Blockchains', '⛓️', '#3498DB', 7),
            ('exchanges', 'Exchange Tokens', '💱', '#E74C3C', 8),
            ('general', 'General Crypto', '📊', '#95A5A6', 9),
        ]
        
        for category_type, display_name, icon, color, order in defaults:
            cls.objects.get_or_create(
                category_type=category_type,
                defaults={
                    'display_name': display_name,
                    'icon': icon,
                    'color_code': color,
                    'sort_order': order,
                    'is_active': True
                }
            )


class Market(models.Model):
    """Main prediction market model"""
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('closed', 'Closed'),
        ('resolved', 'Resolved'),
        ('cancelled', 'Cancelled'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    creator = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='created_markets')
    category = models.ForeignKey(CryptocurrencyCategory, on_delete=models.CASCADE, related_name='markets')
    
    # Market configuration
    min_bet = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1.00'))
    max_bet = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('10000.00'))
    
    # Time settings
    created_at = models.DateTimeField(auto_now_add=True)
    resolution_date = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    # Market state
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    winning_outcome = models.CharField(max_length=10, choices=[('YES', 'Yes'), ('NO', 'No')], null=True, blank=True)
    
    # Volume tracking
    total_volume = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    yes_volume = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    no_volume = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    
    # Fee structure
    creator_fee_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=4, 
        default=Decimal('0.0200'),  # 2%
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('0.1000'))]
    )
    platform_fee_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=4, 
        default=Decimal('0.0100'),  # 1%
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('0.0500'))]
    )
    
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['category', '-total_volume']),
            models.Index(fields=['resolution_date']),
        ]

    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"
    
    @property
    def is_active(self):
        return (self.status == 'active' and 
                self.resolution_date > datetime.now(timezone.utc))
    
    @property
    def yes_probability(self):
        """Calculate YES probability based on volume"""
        if self.total_volume == 0:
            return Decimal('0.50')  # 50% default
        return self.yes_volume / self.total_volume
    
    @property
    def no_probability(self):
        """Calculate NO probability"""
        return Decimal('1.00') - self.yes_probability
    
    @property
    def yes_odds(self):
        """Calculate YES odds (multiplier)"""
        prob = self.yes_probability
        if prob == 0:
            return Decimal('2.00')
        return min(Decimal('1.00') / prob, Decimal('100.00'))
    
    @property
    def no_odds(self):
        """Calculate NO odds (multiplier)"""
        prob = self.no_probability
        if prob == 0:
            return Decimal('2.00')
        return min(Decimal('1.00') / prob, Decimal('100.00'))



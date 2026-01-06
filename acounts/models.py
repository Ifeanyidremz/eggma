from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid
import random
import string
from django.utils import timezone
from decimal import Decimal
from django.core.validators import MinValueValidator
from datetime import timedelta

class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    is_email_verified = models.BooleanField(default=False)
    
    # Wallet and financial fields
    wallet_address = models.CharField(max_length=42, blank=True, null=True)
    balance = models.DecimalField(
        max_digits=20, 
        decimal_places=6, 
        default=Decimal('0.000000'),
        validators=[MinValueValidator(Decimal('0'))]
    )
    total_volume = models.DecimalField(
        max_digits=20, 
        decimal_places=6, 
        default=Decimal('0.000000')
    )
    total_winnings = models.DecimalField(
        max_digits=20, 
        decimal_places=6, 
        default=Decimal('0.000000')
    )
    
    # User experience and gamification
    level = models.IntegerField(default=1)
    xp = models.IntegerField(default=0)
    accuracy_rate = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=Decimal('0.00')
    )
    
    # Stripe customer integration
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'full_name']

    def __str__(self):
        return f"{self.email} - Balance: ${self.balance}"
    
    def get_level_title(self):
        """Get user's level title"""
        level_titles = {
            1: "Novice Predictor",
            2: "Amateur Trader",
            3: "Skilled Analyst", 
            4: "Advanced Trader",
            5: "Expert Predictor",
            6: "Master Oracle",
            7: "Elite Forecaster",
            8: "Legendary Predictor"
        }
        return level_titles.get(self.level, "Expert Predictor")
    
    def get_xp_for_next_level(self):
        """Calculate XP needed for next level"""
        return self.level * 600  # 600, 1200, 1800, etc.
    
    def add_xp(self, amount):
        """Add XP and check for level up"""
        self.xp += amount
        next_level_xp = self.get_xp_for_next_level()
        
        if self.xp >= next_level_xp and self.level < 8:
            self.level += 1
            # Bonus for leveling up
            self.balance += Decimal('10.00')  # $10 level up bonus
        
        self.save()


class EmailVerificationToken(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    
    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)
    
    def is_expired(self):
        return timezone.now() > self.expires_at
    
    def __str__(self):
        return f"Token for {self.user.email}"

def generate_referral_code():
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=8))
        if not ReferralProfile.objects.filter(referral_code=code).exists():
            return code


class ReferralProfile(models.Model): 
    TIER_CHOICES = [
        ('bronze', 'Bronze'),
        ('silver', 'Silver'),
        ('gold', 'Gold'),
        ('diamond', 'Diamond'),
        ('platinum', 'Platinum'),
    ]
    
    # Tier requirements (active referrals needed)
    TIER_REQUIREMENTS = {
        'bronze': 0,      # Start tier
        'silver': 100,    # Need 100 active referrals
        'gold': 300,      # Need 300 active referrals
        'diamond': 1000,  # Need 1000 active referrals
        'platinum': 5000, # Need 5000 active referrals
    }
    
    # XP requirements to pass to next tier
    XP_REQUIREMENTS = {
        'bronze': 15000,
        'silver': 30000,
        'gold': 70000,
        'diamond': 100000,
        'platinum': 0,  # Max tier
    }
    
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='referral_profile')
    referral_code = models.CharField(max_length=20, unique=True, default=generate_referral_code)
    referred_by = models.ForeignKey(
        CustomUser, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='referrals'
    )
    
    # Tier and XP
    tier = models.CharField(max_length=20, choices=TIER_CHOICES, default='bronze')
    tier_xp = models.IntegerField(default=0)  # XP in current tier
    total_xp = models.IntegerField(default=0)  # Total XP earned ever
    
    # Referral counts
    total_referrals = models.IntegerField(default=0)  # All time
    active_referrals = models.IntegerField(default=0)  # Currently active users
    
    # Earnings
    total_earnings = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    signup_earnings = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    deposit_earnings = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    withdrawal_earnings = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    trading_earnings = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    
    # Statistics
    total_referral_volume = models.DecimalField(max_digits=20, decimal_places=6, default=Decimal('0.000000'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['referral_code']),
            models.Index(fields=['tier', '-total_xp']),
            models.Index(fields=['-active_referrals']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.tier.upper()} ({self.active_referrals} active)"
    
    def get_tier_config(self):
        """Get configuration for current tier"""
        configs = {
            'bronze': {
                'signup_xp': 20,
                'signup_bonus': Decimal('10.00'),
                'deposit_xp': 1.5,
                'deposit_commission': Decimal('0.0001'),  # 0.01%
                'withdrawal_xp': 1,
                'withdrawal_commission': Decimal('0.00008'),  # 0.008%
                'first_bet_xp': 2,
                'bet_xp': 0.5,
                'bet_commission': Decimal('0.0001'),  # 0.01%
                'color': '#CD7F32',
                'next_tier': 'silver',
                'xp_needed': 15000,
                'active_needed': 100,
            },
            'silver': {
                'signup_xp': 15,
                'signup_bonus': Decimal('8.00'),
                'deposit_xp': 1,
                'deposit_commission': Decimal('0.0001'),  # 0.01%
                'withdrawal_xp': 1,
                'withdrawal_commission': Decimal('0.0001'),  # 0.01%
                'first_bet_xp': 1.5,
                'bet_xp': 0.3,
                'bet_commission': Decimal('0.0001'),  # 0.01%
                'color': '#C0C0C0',
                'next_tier': 'gold',
                'xp_needed': 30000,
                'active_needed': 300,
            },
            'gold': {
                'signup_xp': 10,
                'signup_bonus': Decimal('5.00'),
                'deposit_xp': 0.5,
                'deposit_commission': Decimal('0.0001'),  # 0.01%
                'withdrawal_xp': 0.5,
                'withdrawal_commission': Decimal('0.0005'),  # 0.05%
                'first_bet_xp': 1,
                'bet_xp': 0.1,
                'bet_commission': Decimal('0.0001'),  # 0.01%
                'color': '#FFD700',
                'next_tier': 'diamond',
                'xp_needed': 70000,
                'active_needed': 1000,
            },
            'diamond': {
                'signup_xp': 5,
                'signup_bonus': Decimal('3.00'),
                'deposit_xp': 0.3,
                'deposit_commission': Decimal('0.0001'),  # 0.01%
                'withdrawal_xp': 0.3,
                'withdrawal_commission': Decimal('0.0008'),  # 0.08%
                'first_bet_xp': 0.5,
                'bet_xp': 0.1,
                'bet_commission': Decimal('0.0001'),  # 0.01%
                'color': '#B9F2FF',
                'next_tier': 'platinum',
                'xp_needed': 100000,
                'active_needed': 5000,
            },
            'platinum': {
                'signup_xp': 3,
                'signup_bonus': Decimal('2.00'),
                'deposit_xp': 0.2,
                'deposit_commission': Decimal('0.0001'),  # 0.01%
                'withdrawal_xp': 0.2,
                'withdrawal_commission': Decimal('0.001'),  # 0.10%
                'first_bet_xp': 0.3,
                'bet_xp': 0.05,
                'bet_commission': Decimal('0.0001'),  # 0.01%
                'color': '#E5E4E2',
                'next_tier': None,
                'xp_needed': 0,  # Max tier
                'active_needed': 0,
            },
        }
        return configs.get(self.tier, configs['bronze'])
    
    def add_xp(self, amount, activity_type='general'):
        """Add XP and check for tier upgrade"""
        self.tier_xp += amount
        self.total_xp += amount
        
        # Check for tier upgrade
        config = self.get_tier_config()
        
        if config['next_tier']:
            # Check if meets BOTH requirements: XP AND active referrals
            if self.tier_xp >= config['xp_needed'] and self.active_referrals >= config['active_needed']:
                old_tier = self.tier
                self.tier = config['next_tier']
                self.tier_xp = 0  # Reset tier XP for new tier
                
                ReferralTransaction.objects.create(
                    referrer=self.user,
                    referred=self.user,  # Self-reference for tier upgrade
                    transaction_type='tier_upgrade',
                    amount=Decimal('0'),
                    xp_earned=0,
                    metadata={
                        'old_tier': old_tier,
                        'new_tier': self.tier,
                        'total_xp': self.total_xp,
                        'active_referrals': self.active_referrals
                    }
                )
        
        self.save()
    
    def update_active_referrals(self):
        from predict.models import Transaction
        
        active_count = CustomUser.objects.filter(
            referral_profile__referred_by=self.user,
            transactions__transaction_type='deposit',
            transactions__status='completed'
        ).distinct().count()
        
        self.active_referrals = active_count
        self.save()


class ReferralTransaction(models.Model):
    
    TRANSACTION_TYPES = [
        ('signup', 'Signup Bonus'),
        ('deposit', 'Deposit Commission'),
        ('withdrawal', 'Withdrawal Commission'),
        ('first_bet', 'First Bet Bonus'),
        ('bet', 'Bet Commission'),
        ('tier_upgrade', 'Tier Upgrade'),
    ]
    
    referrer = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='referrer_transactions')
    referred = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='referred_transactions')
    
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=20, decimal_places=6)  
    xp_earned = models.IntegerField(default=0)
    
    source_transaction_id = models.UUIDField(null=True, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['referrer', '-created_at']),
            models.Index(fields=['transaction_type']),
        ]
    
    def __str__(self):
        return f"{self.referrer.username} <- {self.referred.username}: {self.transaction_type} ${self.amount}"

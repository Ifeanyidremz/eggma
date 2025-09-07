from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid
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
from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid
from django.utils import timezone
from decimal import Decimal
from django.core.validators import MinValueValidator
import uuid
from datetime import timedelta

class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    is_email_verified = models.BooleanField(default=False)
    
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
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'full_name']

    def __str__(self):
        return f"{self.email} - Balance: ${self.balance}"

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
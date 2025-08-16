from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
import re

User = get_user_model()

class CustomUserRegistrationForm(UserCreationForm):
    full_name = forms.CharField(
        max_length=255, 
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-input',
            'placeholder': 'Enter your full name',
            'id': 'fullName'
        })
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-input',
            'placeholder': 'Enter your email address',
            'id': 'email'
        })
    )
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Create a strong password',
            'id': 'password'
        })
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-input',
            'placeholder': 'Confirm your password',
            'id': 'confirmPassword'
        })
    )
    terms_accepted = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={
            'id': 'termsCheckbox',
            'class': 'custom-checkbox'
        })
    )
    
    class Meta:
        model = User
        fields = ('full_name', 'email', 'password1', 'password2', 'terms_accepted')
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError("A user with this email already exists.")
        return email
    
    def clean_password1(self):
        password = self.cleaned_data.get('password1')
        
        # Password strength validation
        if len(password) < 8:
            raise ValidationError("Password must be at least 8 characters long.")
        
        strength_score = 0
        if re.search(r'[a-z]', password) and re.search(r'[A-Z]', password):
            strength_score += 1
        if re.search(r'\d', password):
            strength_score += 1
        if re.search(r'[^a-zA-Z0-9]', password):
            strength_score += 1
        if len(password) >= 8:
            strength_score += 1
            
        if strength_score < 2:
            raise ValidationError("Password is too weak. Include uppercase, lowercase, numbers, and special characters.")
            
        return password
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.full_name = self.cleaned_data['full_name']
        user.email = self.cleaned_data['email']
        user.username = self.cleaned_data['email']  # Use email as username
        user.is_active = False  # User will be activated after email verification
        
        if commit:
            user.save()
        return user
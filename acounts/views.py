from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import login
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.sites.shortcuts import get_current_site
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.crypto import get_random_string
from datetime import timedelta
from django.utils import timezone
from django.views.generic import View
from django.db import transaction as db_transaction
from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate, login, logout
import json
import hashlib
from acounts.referral_service import ReferralService
import hmac
from acounts.models import ReferralProfile, ReferralTransaction
from predict.models import Transaction
from django.conf import settings
from decimal import Decimal
import logging
logger = logging.getLogger(__name__)
from .forms import CustomUserRegistrationForm
from .models import EmailVerificationToken
from .utils import send_verification_email, send_welcome_email

User = get_user_model()
# logger = logging.getLogger(__name__)

def index(request):
    """Landing page view"""
    return render(request, "index.html")

class RegisterView(View):
    template_name = 'register.html'
    form_class = CustomUserRegistrationForm
    
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard')
        
        form = self.form_class()
        return render(request, self.template_name, {'form': form})
    
    def post(self, request):
        form = self.form_class(request.POST)
        
        if form.is_valid():
            try:
                from django.db import transaction as db_transaction
                
                with db_transaction.atomic():
                    user = form.save()
                    
                    # Get referral code from POST or GET
                    referral_code = request.POST.get('referral_code', '').strip() or request.GET.get('ref', '').strip()
                    
                    # Create referral profile
                    referral_profile = ReferralProfile.objects.create(user=user)
                    
                    # Handle referral if code provided
                    if referral_code:
                        try:
                            referrer_profile = ReferralProfile.objects.get(referral_code=referral_code)
                            referrer = referrer_profile.user
                            
                            # Set referrer
                            referral_profile.referred_by = referrer
                            referral_profile.save()
                            
                            # Give signup bonus to new user
                            signup_bonus = Decimal(str(settings.REFERRAL_SIGNUP_BONUS))
                            user.balance += signup_bonus
                            user.save()
                            
                            # Record signup bonus
                            Transaction.objects.create(
                                user=user,
                                transaction_type='bonus',
                                amount=signup_bonus,
                                balance_before=Decimal('0'),
                                balance_after=user.balance,
                                status='completed',
                                description=f'Signup bonus from referral code {referral_code}'
                            )
                            
                            # Give referral bonus to referrer
                            referral_bonus = Decimal(str(settings.REFERRAL_BONUS_AMOUNT))
                            referrer.balance += referral_bonus
                            referrer.save()
                            
                            # Update referrer stats
                            referrer_profile.total_referrals += 1
                            referrer_profile.total_earnings += referral_bonus
                            referrer_profile.save()
                            
                            # Record referral bonus
                            Transaction.objects.create(
                                user=referrer,
                                transaction_type='bonus',
                                amount=referral_bonus,
                                balance_before=referrer.balance - referral_bonus,
                                balance_after=referrer.balance,
                                status='completed',
                                description=f'Referral bonus for {user.username} signup'
                            )
                            
                            # Record referral transaction
                            ReferralTransaction.objects.create(
                                referrer=referrer,
                                referred=user,
                                amount=referral_bonus,
                                transaction_type='signup'
                            )
                            
                            logger.info(f"Referral processed: {referrer.username} referred {user.username}")
                            
                        except ReferralProfile.DoesNotExist:
                            logger.warning(f"Invalid referral code: {referral_code}")
                
                # Send verification email (outside transaction)
                if send_verification_email(user, request):
                    messages.success(
                        request, 
                        f'Account created successfully! Please check your email ({user.email}) '
                        'for verification instructions.'
                    )
                    return redirect('email-verification-sent')
                else:
                    messages.error(
                        request,
                        'Account created but failed to send verification email. '
                        'Please contact support.'
                    )
                    user.delete()
                    
            except Exception as e:
                logger.error(f"Registration error: {str(e)}", exc_info=True)
                messages.error(request, 'An error occurred during registration. Please try again.')
        
        return render(request, self.template_name, {'form': form})


@method_decorator(csrf_exempt, name='dispatch')
class AjaxRegisterView(View):
    """AJAX endpoint with full referral tier system"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            # Extract data
            full_name = data.get('fullName', '').strip()
            email = data.get('email', '').strip()
            password = data.get('password', '')
            confirm_password = data.get('confirmPassword', '')
            terms_accepted = data.get('termsAccepted', False)
            referral_code = data.get('referralCode', '').strip()
            
            # Validation
            if not all([full_name, email, password, confirm_password]):
                return JsonResponse({
                    'success': False,
                    'message': 'All fields are required.'
                }, status=400)
            
            if password != confirm_password:
                return JsonResponse({
                    'success': False,
                    'message': 'Passwords do not match.'
                }, status=400)
            
            if not terms_accepted:
                return JsonResponse({
                    'success': False,
                    'message': 'You must accept the terms and conditions.'
                }, status=400)
            
            if User.objects.filter(email=email).exists():
                return JsonResponse({
                    'success': False,
                    'message': 'A user with this email already exists.'
                }, status=400)
            
            # Create user with referral handling
            with db_transaction.atomic():
                # Create user
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=password,
                    full_name=full_name,
                    is_active=False 
                )
                
                # Create referral profile
                referral_profile = ReferralProfile.objects.create(user=user)
                
                # Process referral if code provided
                referrer_found = False
                if referral_code:
                    try:
                        referrer_profile = ReferralProfile.objects.get(referral_code=referral_code)
                        referrer = referrer_profile.user
                        
                        # Set referrer
                        referral_profile.referred_by = referrer
                        referral_profile.save()
                        
                        # Process signup bonuses through service
                        ReferralService.process_signup(referrer, user)
                        
                        referrer_found = True
                        logger.info(f"Referral: {referrer.username} referred {user.username}")
                        
                    except ReferralProfile.DoesNotExist:
                        logger.warning(f"Invalid referral code: {referral_code}")
            
            # Send verification email
            if send_verification_email(user, request):
                success_message = f'Account created successfully! Please check your email ({email}) for verification instructions.'
                
                if referrer_found:
                    success_message += 'You received $5.00 signup bonus!'
                
                return JsonResponse({
                    'success': True,
                    'message': success_message,
                    'redirect_url': '/email-verification-sent/'
                })
            else:
                user.delete()
                return JsonResponse({
                    'success': False,
                    'message': 'Failed to send verification email. Please try again.'
                }, status=500)
                
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Invalid JSON data.'
            }, status=400)
        except Exception as e:
            logger.error(f"Registration error: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': 'An error occurred during registration. Please try again.'
            }, status=500)

class EmailVerificationSentView(View):
    template_name = 'email_verification_sent.html'
    
    def get(self, request):
        return render(request, self.template_name)

class VerifyEmailView(View):

    def get(self, request, token):
        try:
            verification_token = get_object_or_404(
                EmailVerificationToken,
                token=token
            )
            
            # Check if user is already verified
            if verification_token.user.is_email_verified:
                messages.info(request, 'Your email is already verified! You can log in.')
                return redirect('login-page') 
            
            # Check if token is already used
            if verification_token.is_used:
                messages.error(request, 'This verification link has already been used. Please request a new one if needed.')
                return render(request, 'email_verification_error.html')
            
            # Check if token is expired
            if verification_token.is_expired():
                messages.error(request, 'Verification link has expired. Please request a new one.')
                return render(request, 'email_verification_expired.html')
            
            user = verification_token.user
            user.is_active = True
            user.is_email_verified = True
            user.save()
            
            # Mark token as used
            verification_token.is_used = True
            verification_token.save()
            
            messages.success(request, 'Email verified successfully! You can now log in.')
            return redirect('login-page') 
            
        except EmailVerificationToken.DoesNotExist:
            messages.error(request, 'Invalid verification link.')
            return render(request, 'email_verification_error.html')
            
        except Exception as e:
            messages.error(request, 'An error occurred during verification. Please try again.')
            return render(request, 'email_verification_error.html')

class ResendVerificationView(View):
    def post(self, request):
        email = request.POST.get('email')
        
        try:
            user = User.objects.get(email=email, is_active=False)
            
            if send_verification_email(user, request):
                messages.success(request, 'Verification email sent successfully!')
            else:
                messages.error(request, 'Failed to send verification email. Please try again.')
                
        except User.DoesNotExist:
            # Don't reveal if email exists or not
            messages.success(request, 'If the email exists, a verification link has been sent.')
        
        return redirect('email-verification-sent')
    


class LoginView(View):
    template_name = 'login.html'
    
    def get(self, request):
        # Redirect authenticated users to dashboard
        if request.user.is_authenticated:
            return redirect('dashboard')  # Change to your dashboard URL name
        
        return render(request, self.template_name)
    
    def post(self, request):
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        remember_me = request.POST.get('remember_me', False)
        
        # Basic validation
        if not email or not password:
            messages.error(request, 'Please provide both email and password.')
            return render(request, self.template_name)
        
        # Authenticate user
        user = authenticate(request, username=email, password=password)
        
        if user is not None:
            # Check if user is active
            if not user.is_active:
                messages.error(request, 'Your account is not activated. Please check your email for verification instructions.')
                return render(request, self.template_name)
            
            # Check if email is verified (if you require email verification)
            if hasattr(user, 'is_email_verified') and not user.is_email_verified:
                messages.error(request, 'Please verify your email before logging in.')
                return render(request, self.template_name)
            
            # Login user
            login(request, user)
            
            # Set session expiry based on remember_me
            if remember_me:
                request.session.set_expiry(30 * 24 * 60 * 60)  # 30 days
            else:
                request.session.set_expiry(0)  # Browser session
            
            # Success message
            messages.success(request, f'Welcome back, {user.get_full_name() or user.username}!')
            
            # Redirect to next page or dashboard
            next_url = request.GET.get('next') or request.POST.get('next')
            if next_url:
                return redirect(next_url)
            
            return redirect('dashboard')
        
        else:
            messages.error(request, 'Invalid email or password.')
            return render(request, self.template_name)


@method_decorator(csrf_exempt, name='dispatch')
class AjaxLoginView(View):
    """AJAX endpoint for login"""
    
    def post(self, request):
        try:
            data = json.loads(request.body)
            
            email = data.get('email', '').strip()
            password = data.get('password', '')
            remember_me = data.get('rememberMe', False)
            
            # Basic validation
            if not email or not password:
                return JsonResponse({
                    'success': False,
                    'message': 'Please provide both email and password.'
                }, status=400)
            
            # Authenticate user
            user = authenticate(request, username=email, password=password)
            
            if user is not None:
                # Check if user is active
                if not user.is_active:
                    return JsonResponse({
                        'success': False,
                        'message': 'Your account is not activated. Please check your email for verification instructions.'
                    }, status=400)
                
                # Check if email is verified
                if hasattr(user, 'is_email_verified') and not user.is_email_verified:
                    return JsonResponse({
                        'success': False,
                        'message': 'Please verify your email before logging in.'
                    }, status=400)
                
                # Login user
                login(request, user)
                
                # Set session expiry based on remember_me
                if remember_me:
                    request.session.set_expiry(30 * 24 * 60 * 60)  # 30 days
                else:
                    request.session.set_expiry(0)  # Browser session
                
                return JsonResponse({
                    'success': True,
                    'message': f'Welcome back, {user.get_full_name() or user.username}!',
                    'redirect_url': '/dashboard/'
                })
            
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid email or password.'
                }, status=400)
                
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Invalid JSON data.'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': 'An error occurred during login. Please try again.'
            }, status=500)


class LogoutView(View):
    def get(self, request):
        return self.post(request)
    
    def post(self, request):
        if request.user.is_authenticated:
            user_name = request.user.get_full_name() or request.user.username
            logout(request)
            messages.success(request, f'Goodbye {user_name}! You have been logged out successfully.')
        
        return redirect('landing-page')


class ForgotPasswordView(View):
    template_name = 'forgot-password.html'  # Your existing template
    
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return render(request, self.template_name)
    
    def post(self, request):
        email = request.POST.get('email', '').strip()
        
        if not email:
            # Return JSON response for your frontend JavaScript to handle
            if request.headers.get('Content-Type') == 'application/json':
                return JsonResponse({'success': False, 'message': 'Please provide your email address.'})
            messages.error(request, 'Please provide your email address.')
            return render(request, self.template_name)
        
        try:
            user = User.objects.get(email=email)
            
            # Generate secure reset token
            reset_token = self.generate_reset_token(user)
            
            # Store token in session or cache (expires in 15 minutes)
            request.session[f'reset_token_{user.id}'] = {
                'token': reset_token,
                'expires': (timezone.now() + timedelta(minutes=15)).timestamp(),
                'email': email
            }
            
            # Send password reset email
            self.send_reset_email(request, user, reset_token)
            
        except User.DoesNotExist:
            # Still show success message for security (don't reveal if email exists)
            pass
        
        # Return JSON response for AJAX or regular response
        success_message = f'If an account with this email exists, you will receive password reset instructions.'
        
        if request.headers.get('Content-Type') == 'application/json':
            return JsonResponse({'success': True, 'message': success_message})
        
        messages.success(request, success_message)
        return render(request, self.template_name)
    
    def generate_reset_token(self, user):
        """Generate a secure reset token for the user"""
        # Create a unique string using user info and current time
        unique_string = f"{user.id}_{user.email}_{timezone.now().timestamp()}_{get_random_string(32)}"
        
        # Create HMAC signature using Django's SECRET_KEY
        signature = hmac.new(
            settings.SECRET_KEY.encode(),
            unique_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return f"{unique_string}.{signature}"
    
    def send_reset_email(self, request, user, reset_token):
        """Send password reset email to user"""
        current_site = get_current_site(request)
        
        # Build reset URL
        reset_url = f"{request.scheme}://{current_site.domain}{reverse('password_reset_confirm')}?token={reset_token}&user={user.id}"
        
        # Email context
        context = {
            'user': user,
            'reset_url': reset_url,
            'site_name': 'EVGxchain',
            'domain': current_site.domain,
            'expiry_minutes': 15,
        }
        
        # Render HTML email template
        html_message = render_to_string('password_reset_email.html', context)
        
        # Create plain text version
        plain_message = f"""
        Hi {user.first_name or user.username},

        You have requested to reset your password for your EVGxchain account.

        Click the link below to reset your password:
        {reset_url}

        This link will expire in 15 minutes for security reasons.

        If you didn't request this password reset, please ignore this email.

        Best regards,
        The EVGxchain Team
        """.strip()
        
        try:
            send_mail(
                subject='Reset Your EVGxchain Password',
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
        except Exception as e:
            # Log the error but don't reveal it to user for security
            print(f"Email sending failed: {e}")
            # In production, use proper logging:
            # logger.error(f"Password reset email failed for user {user.id}: {e}")


class PasswordResetConfirmView(View):
    """Handle the password reset confirmation when user clicks email link"""
    template_name = 'password_reset_confirm.html'
    
    def get(self, request):
        token = request.GET.get('token')
        user_id = request.GET.get('user')
        
        if not token or not user_id:
            messages.error(request, 'Invalid reset link.')
            return redirect('forgot-password')
        
        # Only verify token, don't invalidate it yet (save for POST request)
        if not self.verify_reset_token(request, token, user_id):
            messages.error(request, 'This reset link has expired, is invalid, or has already been used.')
            return redirect('forgot-password')
        
        return render(request, self.template_name, {'user_id': user_id, 'token': token})
    
    def post(self, request):
        token = request.POST.get('token')
        user_id = request.POST.get('user_id')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        
        # IMPORTANT: Check and invalidate token BEFORE any other validation
        if not self.verify_and_invalidate_token(request, token, user_id):
            messages.error(request, 'This reset link has expired, is invalid, or has already been used.')
            return redirect('forgot-password')
        
        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            # Don't pass token back - it's already been invalidated
            return redirect('forgot-password')
        
        if len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
            # Don't pass token back - it's already been invalidated
            return redirect('forgot-password')
        
        try:
            user = User.objects.get(id=user_id)
            user.set_password(password)
            user.save()
            
            messages.success(request, 'Your password has been reset successfully. You can now log in.')
            return redirect('login-page')
            
        except User.DoesNotExist:
            messages.error(request, 'Invalid user.')
            return redirect('forgot-password')
    
    def verify_reset_token(self, request, token, user_id):
        """Verify the reset token is valid and not expired (for GET requests only)"""
        try:
            session_key = f'reset_token_{user_id}'
            stored_data = request.session.get(session_key)
            
            if not stored_data:
                return False
            
            # Check if token matches
            if stored_data['token'] != token:
                return False
            
            # Check if token has expired
            if timezone.now().timestamp() > stored_data['expires']:
                del request.session[session_key]
                return False
            
            return True
            
        except Exception:
            return False
    
    def verify_and_invalidate_token(self, request, token, user_id):
        """Verify the reset token and immediately invalidate it (one-time use)"""
        try:
            session_key = f'reset_token_{user_id}'
            stored_data = request.session.get(session_key)
            
            if not stored_data:
                return False
            
            # Check if token matches
            if stored_data['token'] != token:
                return False
            
            # Check if token has expired
            if timezone.now().timestamp() > stored_data['expires']:
                del request.session[session_key]
                return False
            
            # IMPORTANT: Immediately invalidate the token after successful verification
            del request.session[session_key]
            return True
            
        except Exception:
            return False
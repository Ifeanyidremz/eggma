from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.urls import reverse
from .models import EmailVerificationToken
# import logging

# logger = logging.getLogger(__name__)

import logging

logger = logging.getLogger(__name__)

def send_verification_email(user, request):
    try:
        token, created = EmailVerificationToken.objects.get_or_create(
            user=user,
            is_used=False,
            defaults={}
        )
        
        if not created and token.is_expired():
            token.delete()
            token = EmailVerificationToken.objects.create(user=user)
        
        verification_url = request.build_absolute_uri(
            reverse('verify-email', kwargs={'token': str(token.token)})
        )
        
        context = {
            'user': user,
            'verification_url': verification_url,
            'site_name': 'EVGxchain',
            'token_expiry_hours': 24
        }
        
        html_message = render_to_string('verification_email.html', context)
        plain_message = strip_tags(html_message)

        send_mail(
            subject='Verify your EVGxchain account',
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Error sending verification email: {str(e)}", exc_info=True)
        return False

def send_welcome_email(user):
    try:
        context = {
            'user': user,
            'site_name': 'EVGxchain',
            'login_url': settings.SITE_URL + reverse('login-page')
        }
        
        html_message = render_to_string('welcome_email.html', context)
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject='Welcome to EVGxchain!',
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        # logger.info(f"Welcome email sent to {user.email}")
        return True
        
    except Exception as e:
        # logger.error(f"Failed to send welcome email to {user.email}: {str(e)}")
        return False
    


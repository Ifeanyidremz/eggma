from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name="landing-page"),
    path('register/', views.RegisterView.as_view(), name='register-page'),
    path('ajax-register/', views.AjaxRegisterView.as_view(), name='ajax-register'),
    path('email-verification-sent/', views.EmailVerificationSentView.as_view(), name='email-verification-sent'),
    path('verify-email/<uuid:token>/', views.VerifyEmailView.as_view(), name='verify-email'),
    path('resend-verification/', views.ResendVerificationView.as_view(), name='resend-verification'),
    
    # Login/Logout endpoints
    path('login/', views.LoginView.as_view(), name='login-page'),
    # path('ajax-login/', views.AjaxLoginView.as_view(), name='ajax-login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    
    # Password reset (optional)
    path('forgot-password/', views.ForgotPasswordView.as_view(), name='forgot-password'),
    path('reset-password/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
]
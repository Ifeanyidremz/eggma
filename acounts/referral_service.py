from django.db import transaction as db_transaction
from django.contrib.auth import get_user_model
from decimal import Decimal
from .models import ReferralProfile, ReferralTransaction
from predict.models import Transaction
import logging

User = get_user_model()
logger = logging.getLogger(__name__)


class ReferralService:
    @staticmethod
    def process_signup(referrer, new_user):
        """Process signup bonus when referred user registers"""
        try:
            with db_transaction.atomic():
                referrer_profile = ReferralProfile.objects.select_for_update().get(user=referrer)
                new_user_profile = ReferralProfile.objects.select_for_update().get(user=new_user)
                
                config = referrer_profile.get_tier_config()
                
                # Give signup bonus to referrer
                signup_bonus = config['signup_bonus']
                signup_xp = config['signup_xp']
                
                referrer.balance += signup_bonus
                referrer.save()
                
                # Update referrer profile
                referrer_profile.total_referrals += 1
                referrer_profile.total_earnings += signup_bonus
                referrer_profile.signup_earnings += signup_bonus
                referrer_profile.add_xp(signup_xp, 'signup')
                
                # Create transaction record for referrer
                Transaction.objects.create(
                    user=referrer,
                    transaction_type='bonus',
                    amount=signup_bonus,
                    balance_before=referrer.balance - signup_bonus,
                    balance_after=referrer.balance,
                    status='completed',
                    description=f'Referral signup bonus for {new_user.username}'
                )
                
                # Create referral transaction
                ReferralTransaction.objects.create(
                    referrer=referrer,
                    referred=new_user,
                    transaction_type='signup',
                    amount=signup_bonus,
                    xp_earned=signup_xp,
                    metadata={
                        'tier': referrer_profile.tier,
                        'new_user_email': new_user.email
                    }
                )
                
                # Give new user signup bonus (fixed $5 for all tiers)
                new_user_signup_bonus = Decimal('5.00')
                new_user.balance += new_user_signup_bonus
                new_user.save()
                
                Transaction.objects.create(
                    user=new_user,
                    transaction_type='bonus',
                    amount=new_user_signup_bonus,
                    balance_before=Decimal('0'),
                    balance_after=new_user.balance,
                    status='completed',
                    description=f'Welcome bonus from referral code'
                )
                
                logger.info(f"Signup referral: {referrer.username} earned ${signup_bonus} + {signup_xp}XP")
                
                return True
                
        except Exception as e:
            logger.error(f"Signup referral error: {str(e)}")
            return False
    
    @staticmethod
    def process_deposit(user, deposit_amount):
        """Process deposit commission for referrer"""
        try:
            user_profile = ReferralProfile.objects.select_related('referred_by').get(user=user)
            
            if not user_profile.referred_by:
                return  # User wasn't referred
            
            referrer = user_profile.referred_by
            referrer_profile = ReferralProfile.objects.select_for_update().get(user=referrer)
            
            config = referrer_profile.get_tier_config()
            
            # Calculate commission
            commission = deposit_amount * config['deposit_commission']
            xp = config['deposit_xp']
            
            if commission > 0:
                with db_transaction.atomic():
                    referrer.balance += commission
                    referrer.save()
                    
                    referrer_profile.total_earnings += commission
                    referrer_profile.deposit_earnings += commission
                    referrer_profile.total_referral_volume += deposit_amount
                    referrer_profile.add_xp(int(xp), 'deposit')
                    
                    # Update active referrals count
                    referrer_profile.update_active_referrals()
                    
                    Transaction.objects.create(
                        user=referrer,
                        transaction_type='bonus',
                        amount=commission,
                        balance_before=referrer.balance - commission,
                        balance_after=referrer.balance,
                        status='completed',
                        description=f'Deposit commission from {user.username} (${deposit_amount})'
                    )
                    
                    ReferralTransaction.objects.create(
                        referrer=referrer,
                        referred=user,
                        transaction_type='deposit',
                        amount=commission,
                        xp_earned=int(xp),
                        metadata={
                            'tier': referrer_profile.tier,
                            'deposit_amount': str(deposit_amount),
                            'commission_rate': str(config['deposit_commission'])
                        }
                    )
                    
                    logger.info(f"Deposit commission: {referrer.username} earned ${commission} + {xp}XP")
                    
        except ReferralProfile.DoesNotExist:
            pass  # User has no referral profile
        except Exception as e:
            logger.error(f"Deposit commission error: {str(e)}")
    
    @staticmethod
    def process_withdrawal(user, withdrawal_amount):
        """Process withdrawal commission for referrer"""
        try:
            user_profile = ReferralProfile.objects.select_related('referred_by').get(user=user)
            
            if not user_profile.referred_by:
                return
            
            referrer = user_profile.referred_by
            referrer_profile = ReferralProfile.objects.select_for_update().get(user=referrer)
            
            config = referrer_profile.get_tier_config()
            
            # Calculate commission
            commission = withdrawal_amount * config['withdrawal_commission']
            xp = config['withdrawal_xp']
            
            if commission > 0:
                with db_transaction.atomic():
                    referrer.balance += commission
                    referrer.save()
                    
                    referrer_profile.total_earnings += commission
                    referrer_profile.withdrawal_earnings += commission
                    referrer_profile.add_xp(int(xp), 'withdrawal')
                    
                    Transaction.objects.create(
                        user=referrer,
                        transaction_type='bonus',
                        amount=commission,
                        balance_before=referrer.balance - commission,
                        balance_after=referrer.balance,
                        status='completed',
                        description=f'Withdrawal commission from {user.username} (${withdrawal_amount})'
                    )
                    
                    ReferralTransaction.objects.create(
                        referrer=referrer,
                        referred=user,
                        transaction_type='withdrawal',
                        amount=commission,
                        xp_earned=int(xp),
                        metadata={
                            'tier': referrer_profile.tier,
                            'withdrawal_amount': str(withdrawal_amount),
                            'commission_rate': str(config['withdrawal_commission'])
                        }
                    )
                    
                    logger.info(f"Withdrawal commission: {referrer.username} earned ${commission} + {xp}XP")
                    
        except ReferralProfile.DoesNotExist:
            pass
        except Exception as e:
            logger.error(f"Withdrawal commission error: {str(e)}")
    
    @staticmethod
    def process_first_bet(user):
        """Process first bet XP bonus for referrer"""
        try:
            user_profile = ReferralProfile.objects.select_related('referred_by').get(user=user)
            
            if not user_profile.referred_by:
                return
            
            # Check if this is truly the first bet
            from predict.models import Bet
            bet_count = Bet.objects.filter(user=user).count()
            
            if bet_count != 1:
                return  # Not first bet
            
            referrer = user_profile.referred_by
            referrer_profile = ReferralProfile.objects.select_for_update().get(user=referrer)
            
            config = referrer_profile.get_tier_config()
            xp = config['first_bet_xp']
            
            with db_transaction.atomic():
                referrer_profile.add_xp(int(xp), 'first_bet')
                
                ReferralTransaction.objects.create(
                    referrer=referrer,
                    referred=user,
                    transaction_type='first_bet',
                    amount=Decimal('0'),
                    xp_earned=int(xp),
                    metadata={
                        'tier': referrer_profile.tier,
                        'first_bet': True
                    }
                )
                
                logger.info(f"First bet bonus: {referrer.username} earned {xp}XP from {user.username}")
                
        except ReferralProfile.DoesNotExist:
            pass
        except Exception as e:
            logger.error(f"First bet bonus error: {str(e)}")
    
    @staticmethod
    def process_bet(user, bet_amount):
        """Process bet commission for referrer"""
        try:
            user_profile = ReferralProfile.objects.select_related('referred_by').get(user=user)
            
            if not user_profile.referred_by:
                return
            
            referrer = user_profile.referred_by
            referrer_profile = ReferralProfile.objects.select_for_update().get(user=referrer)
            
            config = referrer_profile.get_tier_config()
            
            # Calculate commission
            commission = bet_amount * config['bet_commission']
            xp = config['bet_xp']
            
            if commission > 0:
                with db_transaction.atomic():
                    referrer.balance += commission
                    referrer.save()
                    
                    referrer_profile.total_earnings += commission
                    referrer_profile.trading_earnings += commission
                    referrer_profile.total_referral_volume += bet_amount
                    referrer_profile.add_xp(int(xp * 10) / 10, 'bet')  # Handle decimal XP
                    
                    Transaction.objects.create(
                        user=referrer,
                        transaction_type='bonus',
                        amount=commission,
                        balance_before=referrer.balance - commission,
                        balance_after=referrer.balance,
                        status='completed',
                        description=f'Trading commission from {user.username} (${bet_amount})'
                    )
                    
                    ReferralTransaction.objects.create(
                        referrer=referrer,
                        referred=user,
                        transaction_type='bet',
                        amount=commission,
                        xp_earned=int(xp),
                        metadata={
                            'tier': referrer_profile.tier,
                            'bet_amount': str(bet_amount),
                            'commission_rate': str(config['bet_commission'])
                        }
                    )
                    
        except ReferralProfile.DoesNotExist:
            pass
        except Exception as e:
            logger.error(f"Bet commission error: {str(e)}")
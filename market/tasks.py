from celery import shared_task
from django.core.management import call_command
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def sync_crypto_news(self):
    """Celery task to sync crypto news from CryptoPanic"""
    try:
        call_command('sync_news')
        logger.info("Successfully synced crypto news")
        return "News sync completed"
    except Exception as e:
        logger.error(f"Error syncing news: {e}")
        if self.request.retries < self.max_retries:
            # Retry in 5 minutes with exponential backoff
            raise self.retry(countdown=300 * (2 ** self.request.retries), exc=e)
        raise

@shared_task(bind=True, max_retries=3)
def sync_economic_events(self):
    """Celery task to sync economic events"""
    try:
        call_command('sync_events')
        logger.info("Successfully synced economic events")
        return "Events sync completed"
    except Exception as e:
        logger.error(f"Error syncing events: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=600 * (2 ** self.request.retries), exc=e)
        raise

@shared_task(bind=True, max_retries=2)
def update_market_data(self):
    """Celery task to update market volumes and data"""
    try:
        call_command('update_market_volumes')
        call_command('sync_markets')
        logger.info("Successfully updated market data")
        return "Market data updated"
    except Exception as e:
        logger.error(f"Error updating market data: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=180 * (2 ** self.request.retries), exc=e)
        raise

@shared_task
def full_data_sync():
    """Comprehensive data synchronization task"""
    try:
        call_command('sync_all_data', '--verbose')
        logger.info("Full data sync completed successfully")
        return "Full sync completed"
    except Exception as e:
        logger.error(f"Full data sync failed: {e}")
        raise

@shared_task
def cleanup_old_data():
    """Clean up old data periodically"""
    try:
        from market.utils import EconomicCalendarService
        from predict.models import NewsArticle
        from django.utils import timezone
        
        # Clean up old events
        EconomicCalendarService.cleanup_old_events()
        
        # Clean up old news (older than 7 days)
        cutoff_date = timezone.now() - timedelta(days=7)
        old_news_count = NewsArticle.objects.filter(
            published_at__lt=cutoff_date,
            is_active=True
        ).update(is_active=False)
        
        logger.info(f"Cleaned up {old_news_count} old news articles")
        return f"Cleanup completed: {old_news_count} news articles archived"
        
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        raise
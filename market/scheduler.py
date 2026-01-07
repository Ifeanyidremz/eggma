from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.conf import settings
from market.models import Market
from market.utils import PriceTargetMarketService
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(settings.SCHEDULER_CONFIG)

def monitor_price_targets():
    try:
        active_markets = Market.objects.filter(
            market_type='target',
            status='active'
        )
        
        for market in active_markets:
            try:
                if timezone.now() >= market.resolution_date:
                    PriceTargetMarketService.resolve_target_market(market)
                else:
                    reached, _ = PriceTargetMarketService.check_target_reached(market)
                    if reached:
                        PriceTargetMarketService.resolve_target_market(market)
            except Exception as e:
                logger.error(f"Error processing market {market.id}: {e}")
                
    except Exception as e:
        logger.error(f"Fatal error in scheduler: {e}")

def start_scheduler():
    """Start the background scheduler"""
    if settings.DEBUG:
        scheduler.add_job(
            monitor_price_targets,
            'interval',
            minutes=5,
            id='monitor_price_targets_dev',
            replace_existing=True
        )
    else:
        scheduler.add_job(
            monitor_price_targets,
            CronTrigger(minute=0), 
            id='monitor_price_targets',
            replace_existing=True
        )
    
    scheduler.start()
    logger.info("Scheduler started successfully")
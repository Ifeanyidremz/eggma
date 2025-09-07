import os
from celery import Celery
from celery.schedules import crontab

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'evgwork.settings')

app = Celery('your_project')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Celery Beat Schedule for automated tasks
app.conf.beat_schedule = {
    # Sync news every 30 minutes
    'sync-crypto-news': {
        'task': 'market.tasks.sync_crypto_news',
        'schedule': crontab(minute='*/30'),
    },
    # Sync economic events every 6 hours
    'sync-economic-events': {
        'task': 'market.tasks.sync_economic_events',
        'schedule': crontab(minute=0, hour='*/6'),
    },
    # Update market data every 5 minutes
    'update-market-data': {
        'task': 'market.tasks.update_market_data',
        'schedule': crontab(minute='*/5'),
    },
    # Full data sync once daily at 3 AM
    'full-data-sync': {
        'task': 'market.tasks.full_data_sync',
        'schedule': crontab(minute=0, hour=3),
    },
    # Cleanup old data once daily at 2 AM
    'cleanup-old-data': {
        'task': 'market.tasks.cleanup_old_data',
        'schedule': crontab(minute=0, hour=2),
    },
}

app.conf.timezone = 'UTC'
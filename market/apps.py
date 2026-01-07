from django.apps import AppConfig
from django.conf import settings

class MarketConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'market'
    
    def ready(self):
        if settings.SCHEDULER_AUTOSTART:
            from market.scheduler import start_scheduler
            import sys
            if 'runserver' in sys.argv or 'gunicorn' in sys.argv[0]:
                start_scheduler()
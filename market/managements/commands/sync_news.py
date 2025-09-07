from django.core.management.base import BaseCommand
from market.utils import CryptoPanicNewsService
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Fetch and store latest crypto news from CryptoPanic API'

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('Starting news sync from CryptoPanic...')
        )
        
        try:
            articles = CryptoPanicNewsService.fetch_and_store_news()
            
            if articles:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Successfully synced {len(articles)} news articles'
                    )
                )
                for article in articles:
                    self.stdout.write(f'  - {article.title}')
            else:
                self.stdout.write(
                    self.style.WARNING('No new articles were stored')
                )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error syncing news: {str(e)}')
            )
            logger.error(f'News sync error: {e}')
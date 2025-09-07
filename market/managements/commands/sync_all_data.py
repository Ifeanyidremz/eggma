from django.core.management.base import BaseCommand
from market.utils import DataSyncService
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Sync all external data - news, events, and markets'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show verbose output',
        )

    def handle(self, *args, **options):
        if options['verbose']:
            logging.basicConfig(level=logging.INFO)
        
        self.stdout.write(
            self.style.SUCCESS('Starting full data synchronization...')
        )
        
        try:
            DataSyncService.sync_all_data()
            
            self.stdout.write(
                self.style.SUCCESS('All data synchronized successfully!')
            )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error during data sync: {str(e)}')
            )
            logger.error(f'Full data sync error: {e}')
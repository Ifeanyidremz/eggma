# Generated migration for target market fields

from django.db import migrations, models
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('market', '0002_alter_market_market_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='market',
            name='target_price',
            field=models.DecimalField(
                decimal_places=2,
                max_digits=15,
                null=True,
                blank=True,
                help_text='Target price for price target markets'
            ),
        ),
        migrations.AddField(
            model_name='market',
            name='highest_price_reached',
            field=models.DecimalField(
                decimal_places=2,
                max_digits=15,
                null=True,
                blank=True,
                help_text='Highest price reached during market lifetime'
            ),
        ),
        migrations.AddField(
            model_name='market',
            name='round_end_price',
            field=models.DecimalField(
                decimal_places=6,
                max_digits=15,
                null=True,
                blank=True,
                help_text='Price at round end/market resolution'
            ),
        ),
    ]
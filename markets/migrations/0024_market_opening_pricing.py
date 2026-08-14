from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("markets", "0023_compliancedecisionproposal")]

    operations = [
        migrations.AddField(
            model_name="market",
            name="face_value_ugx",
            field=models.PositiveIntegerField(default=1000),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="market",
            name="face_value_ugx",
            field=models.PositiveIntegerField(default=10000),
        ),
        migrations.AddField(
            model_name="marketoutcome",
            name="opening_price",
            field=models.DecimalField(blank=True, decimal_places=5, max_digits=6, null=True),
        ),
        migrations.AddConstraint(
            model_name="marketoutcome",
            constraint=models.CheckConstraint(
                condition=Q(opening_price__isnull=True)
                | (Q(opening_price__gt=0) & Q(opening_price__lt=1)),
                name="market_outcome_opening_price_between_zero_and_one",
            ),
        ),
    ]

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("markets", "0025_remove_kyc_status_fields"),
        ("markets", "0026_market_settles_by"),
    ]

    operations = []

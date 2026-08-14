from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("markets", "0024_remove_markets_kyc_models"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="marketparticipantcompliance",
            name="kyc_status",
        ),
        migrations.RemoveField(
            model_name="marketcompliancereview",
            name="previous_kyc_status",
        ),
        migrations.RemoveField(
            model_name="marketcompliancereview",
            name="new_kyc_status",
        ),
    ]

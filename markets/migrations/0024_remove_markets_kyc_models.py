from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("markets", "0023_compliancedecisionproposal"),
    ]

    operations = [
        migrations.DeleteModel(
            name="KYCVerificationSession",
        ),
        migrations.DeleteModel(
            name="KYCVerificationEvent",
        ),
    ]

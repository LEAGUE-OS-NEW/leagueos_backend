from django.db import migrations

PROVIDER_CODE = "PESAPAL_SANDBOX"


def ensure_pesapal_sandbox_provider(apps, schema_editor):
    PaymentProvider = apps.get_model(
        "wallets",
        "PaymentProvider",
    )

    provider = PaymentProvider.objects.filter(
        code=PROVIDER_CODE,
    ).first()

    existing_config = dict(provider.config or {}) if provider is not None else {}

    existing_config.update(
        {
            "supports_deposit": True,
            "supports_withdrawal": False,
            "environment": "SANDBOX",
        }
    )

    PaymentProvider.objects.update_or_create(
        code=PROVIDER_CODE,
        defaults={
            "name": "Pesapal Sandbox",
            "provider_type": "GENERIC",
            "is_active": True,
            "config": existing_config,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        (
            "wallets",
            "0006_withdrawal_auto_approval_policy",
        ),
    ]

    operations = [
        migrations.RunPython(
            ensure_pesapal_sandbox_provider,
            migrations.RunPython.noop,
        ),
    ]

"""Management command to seed wallet configuration data."""

from django.core.management.base import BaseCommand

from wallets.models import PaymentProvider

PAYMENT_PROVIDERS = [
    {
        "code": "PESAPAL_SANDBOX",
        "name": "Pesapal Sandbox",
        "provider_type": "GENERIC",
        "config": {
            "supports_deposit": True,
            "supports_withdrawal": False,
            "environment": "SANDBOX",
        },
    },
    {
        "code": "MOCK",
        "name": "Mock Payment Provider",
        "provider_type": "MOCK",
        "config": {"supports_deposit": True, "supports_withdrawal": True},
    },
    {
        "code": "MTN_MOMO",
        "name": "MTN Mobile Money",
        "provider_type": "GENERIC",
        "config": {"supports_deposit": True, "supports_withdrawal": True},
    },
    {
        "code": "AIRTEL_MONEY",
        "name": "Airtel Money",
        "provider_type": "GENERIC",
        "config": {"supports_deposit": True, "supports_withdrawal": True},
    },
    {
        "code": "CARD",
        "name": "Card Payments",
        "provider_type": "GENERIC",
        "config": {"supports_deposit": True, "supports_withdrawal": False},
    },
]


class Command(BaseCommand):
    help = "Seed wallet configuration data (payment providers)."

    def handle(self, *args, **options):
        self.stdout.write("Seeding wallet configuration data...")

        for provider_data in PAYMENT_PROVIDERS:
            code = provider_data["code"]
            defaults = {k: v for k, v in provider_data.items() if k != "code"}
            defaults["is_active"] = True
            provider, created = PaymentProvider.objects.get_or_create(code=code, defaults=defaults)
            self.stdout.write(
                f"  {'Created' if created else 'Found'} payment provider: {provider.code}"
            )

        self.stdout.write(self.style.SUCCESS("Wallet configuration seeded successfully."))

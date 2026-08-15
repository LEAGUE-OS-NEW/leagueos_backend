from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from markets.models import MarketLiquidityProvider


class Command(BaseCommand):
    help = "Create or update an unfunded platform liquidity treasury service account."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--code", default="PLATFORM_TREASURY")
        parser.add_argument("--display-name", default="League OS Platform Treasury")

    @transaction.atomic
    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        if not email:
            raise CommandError("A valid treasury email is required.")
        User = get_user_model()
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": email,
                "first_name": "Liquidity",
                "last_name": "Treasury",
                "is_active": True,
                "is_verified": True,
            },
        )
        user.set_unusable_password()
        user.is_staff = False
        user.is_superuser = False
        user.save(update_fields=["password", "is_staff", "is_superuser", "updated_at"])
        provider, _ = MarketLiquidityProvider.objects.update_or_create(
            code=options["code"],
            defaults={
                "provider_type": MarketLiquidityProvider.ProviderType.PLATFORM_TREASURY,
                "user": user,
                "is_active": True,
                "display_name": options["display_name"],
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Provider {provider.code} uses {user.email}; no funds were created."
            )
        )

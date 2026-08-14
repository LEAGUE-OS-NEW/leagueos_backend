from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from markets.models import Market
from markets.services.opening_pricing_service import MarketOpeningPricingService


class Command(BaseCommand):
    help = "Configure opening pricing for explicitly selected, untraded local markets."

    def add_arguments(self, parser):
        parser.add_argument("--market-id", action="append", required=True)
        parser.add_argument("--face-value-ugx", type=int, default=10000)
        parser.add_argument("--yes-probability", default="50")
        parser.add_argument("--actor-email", required=True)

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command is local-only and requires DEBUG=True.")
        user_model = Market._meta.get_field("created_by").remote_field.model
        try:
            actor = user_model.objects.get(email__iexact=options["actor_email"])
        except user_model.DoesNotExist as error:
            raise CommandError("Actor email was not found.") from error

        markets = list(Market.objects.filter(pk__in=options["market_id"]))
        if len(markets) != len(set(options["market_id"])):
            raise CommandError("Every explicitly supplied market id must exist.")
        for market in markets:
            try:
                MarketOpeningPricingService.configure_local_untraded_historical_market(
                    market=market,
                    actor=actor,
                    face_value_ugx=options["face_value_ugx"],
                    yes_probability=options["yes_probability"],
                )
            except ValidationError as error:
                raise CommandError(f"Market {market.pk}: {error}") from error
            operation = (
                "historical local demo backfill"
                if market.status == Market.Status.OPEN
                else "local untraded pricing configuration"
            )
            self.stdout.write(self.style.SUCCESS(f"Configured {market.pk} ({operation})"))

from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid5

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from authentication.services.permission_service import PermissionService
from markets.models import (
    Market,
    MarketLiquidityConfiguration,
    MarketLiquidityProvider,
)
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.liquidity_service import MarketLiquidityService
from markets.services.opening_pricing_service import MarketOpeningPricingService
from wallets.models import LedgerEntry, Wallet
from wallets.services.wallet_service import WalletService

TREASURY_EMAIL = "presentation.liquidity@leagueos.test"
TREASURY_CODE = "PRESENTATION_PLATFORM_TREASURY"
FUNDING_NAMESPACE = UUID("13a8bf6b-a2b8-4f5c-bc4e-e80af486987c")
DEMO_LIQUIDITY = Decimal("400000")
DEMO_MARKETS = {
    "Will KOBS Rugby Club score 3 or more tries in their next league match?": 62,
    "Will City Oilers win the National Basketball League?": 71,
    "Will KOBS Rugby Club win the Nile Special Rugby Premiership?": 58,
    "Will Vipers SC win the Uganda Premier League?": 66,
}


class Command(BaseCommand):
    help = "Prepare the existing markets catalogue for a local presentation."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", action="store_true")
        parser.add_argument("--market-admin-email")
        parser.add_argument(
            "--exclusive-catalogue",
            action="store_true",
            help=("Hide every non-curated market from the " "public presentation catalogue."),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("Explicit confirmation is required; rerun with --confirm.")
        if not settings.DEBUG:
            raise CommandError("This local-only command requires DEBUG=True.")

        actor = self._actor(options["market_admin_email"])
        markets = {
            market.question: market
            for market in Market.objects.filter(question__in=DEMO_MARKETS)
            .select_related("liquidity_configuration")
            .prefetch_related("outcomes")
        }
        missing = set(DEMO_MARKETS) - set(markets)
        if missing:
            raise CommandError("Missing required existing market(s): " + "; ".join(sorted(missing)))

        now = timezone.now()
        closes_at = now + timedelta(days=30)
        required = sum(
            (
                DEMO_LIQUIDITY
                for market in markets.values()
                if not market.complete_set_issuances.exists()
            ),
            Decimal("0"),
        )
        provider = self._prepare_treasury(required)

        for question, probability in DEMO_MARKETS.items():
            market = markets[question]
            if market.status != Market.Status.OPEN:
                raise CommandError(f"Curated market is not OPEN: {question}")
            market.opens_at = min(market.opens_at or now, now)
            market.closes_at = closes_at
            market.settles_by = closes_at + timedelta(days=2)
            market.is_catalog_visible = True
            market.is_featured = True
            market.save(
                update_fields=[
                    "opens_at",
                    "closes_at",
                    "settles_by",
                    "is_catalog_visible",
                    "is_featured",
                    "updated_at",
                ]
            )

            if not market.complete_set_issuances.exists():
                MarketOpeningPricingService.configure_local_untraded_historical_market(
                    market=market,
                    actor=actor,
                    face_value_ugx=10000,
                    yes_probability=probability,
                )
                MarketLiquidityService.configure_local_untraded_historical_market(
                    market=market,
                    actor=actor,
                    provider=provider,
                    initial_liquidity_ugx=DEMO_LIQUIDITY,
                )
                MarketLiquidityService.activate_opening_liquidity(market=market, actor=actor)

        curated = set(markets.values())
        archived = self._archive_stale(
            now,
            actor,
            curated,
        )

        if options["exclusive_catalogue"]:
            archived.extend(self._hide_non_curated(curated))

        self._report(markets.values(), archived)

    @staticmethod
    def _actor(email):
        users = get_user_model().objects.filter(is_active=True)
        actor = (
            users.filter(email__iexact=email).first()
            if email
            else users.filter(is_superuser=True).first()
        )
        if actor is None or not PermissionService.has_permission(actor, "manage_market"):
            raise CommandError("A market admin with manage_market permission is required.")
        return actor

    @staticmethod
    def _prepare_treasury(required):
        user, _ = get_user_model().objects.get_or_create(
            email=TREASURY_EMAIL,
            defaults={"username": TREASURY_EMAIL, "is_active": True},
        )
        if user.has_usable_password():
            user.set_unusable_password()
            user.save(update_fields=["password", "updated_at"])
        provider, _ = MarketLiquidityProvider.objects.update_or_create(
            code=TREASURY_CODE,
            defaults={
                "provider_type": MarketLiquidityProvider.ProviderType.PLATFORM_TREASURY,
                "user": user,
                "is_active": True,
                "display_name": "League OS Presentation Liquidity",
            },
        )
        wallet = Wallet.objects.filter(user=user, currency="UGX").first()
        available = wallet.available_balance if wallet else Decimal("0")
        top_up = max(Decimal("0"), required - available)
        if top_up:
            WalletService.credit(
                user=user,
                currency="UGX",
                amount=top_up,
                idempotency_reference=uuid5(FUNDING_NAMESPACE, f"fund:{required:.4f}"),
            )
        return provider

    @staticmethod
    def _has_financial_history(market):
        return (
            market.orders.exists()
            or market.fills.exists()
            or market.positions.exists()
            or LedgerEntry.objects.filter(market=market).exists()
            or market.complete_set_issuances.exists()
            or hasattr(market, "settlement")
        )

    def _archive_stale(self, now, actor, curated):
        archived = []
        stale = Market.objects.filter(status=Market.Status.OPEN, closes_at__lt=now).exclude(
            id__in=[market.id for market in curated]
        )
        for market in stale:
            config = MarketLiquidityConfiguration.objects.filter(market=market).first()
            prices = list(market.outcomes.values_list("opening_price", flat=True))
            usable = bool(
                config
                and config.status == MarketLiquidityConfiguration.Status.ACTIVE
                and all(p is not None for p in prices)
            )
            if usable:
                continue
            history = self._has_financial_history(market)
            if not history:
                MarketLifecycleService.close(
                    market_id=market.id,
                    actor=actor,
                    notes="Expired local presentation record; no result was fabricated.",
                )
            Market.objects.filter(pk=market.pk).update(is_catalog_visible=False, is_featured=False)
            archived.append(
                (
                    market.question,
                    market.status if history else "CLOSED",
                    (
                        "financial history preserved unchanged; hidden from catalogue"
                        if history
                        else "expired without usable pricing/liquidity"
                    ),
                )
            )
        return archived

    @staticmethod
    def _hide_non_curated(curated):
        curated_ids = [market.id for market in curated]

        extras = list(
            Market.objects.exclude(
                id__in=curated_ids,
            )
            .filter(
                is_catalog_visible=True,
            )
            .order_by("created_at")
        )

        if not extras:
            return []

        Market.objects.filter(id__in=[market.id for market in extras]).update(
            is_catalog_visible=False,
            is_featured=False,
        )

        return [
            (
                market.question,
                market.status,
                ("hidden from exclusive presentation " "catalogue; history preserved"),
            )
            for market in extras
        ]

    def _report(self, markets, archived):
        self.stdout.write("\nACTIVE PRESENTATION MARKETS")
        for market in markets:
            market.refresh_from_db()
            prices = dict(market.outcomes.values_list("side", "opening_price"))
            config = market.liquidity_configuration
            self.stdout.write(
                f"- {market.question} | {market.status} | YES {prices.get('YES')} | "
                f"NO {prices.get('NO')} | UGX {config.initial_liquidity_ugx} | "
                f"closes {market.closes_at.isoformat()} | visible {market.is_catalog_visible}"
            )
        self.stdout.write("\nARCHIVED / HIDDEN")
        for question, status, reason in archived:
            self.stdout.write(f"- {question} | {status} | {reason}")
        if not archived:
            self.stdout.write("- none")
        self.stdout.write("\nCOULD NOT SAFELY CHANGE\n- none")
        self.stdout.write(self.style.SUCCESS("Local market presentation data is ready."))

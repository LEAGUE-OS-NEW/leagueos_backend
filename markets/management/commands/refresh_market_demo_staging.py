from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid5

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from authentication.models import Role, UserRole
from kyc.models import KYCVerification
from markets.models import (
    Market,
    MarketCompleteSetIssuance,
    MarketPosition,
    MarketProvisionalResult,
    MarketResultDispute,
    MarketLiquidityProvider,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.liquidity_service import MarketLiquidityService
from markets.services.opening_pricing_service import MarketOpeningPricingService
from markets.services.resolution_service import MarketResolutionService
from markets.services.void_refund_service import MarketVoidRefundService
from sports.models import EventParticipant, SportingEvent
from wallets.models import LedgerEntry, Wallet
from wallets.services.wallet_service import WalletService

DEMO_SOURCE = "LEAGUE_OS_DEMO"
TREASURY_EMAIL = "liquidity.treasury@leagueos.test"
FAN_EMAILS = (
    "fan.kyc.local@leagueos.test",
    "fan.a.local@leagueos.test",
    "fan.b.local@leagueos.test",
)
FUNDING_NAMESPACE = UUID("1ab343f5-d1e3-4935-8953-eb1cc06e736d")
TREASURY_BUFFER = Decimal("100000")
YES_PROBABILITIES = {
    "Will Vipers SC beat KCCA FC?": 58,
    "Will Vipers SC vs KCCA FC have over 2.5 goals?": 52,
    "Will both SC Villa and Express FC score?": 49,
    "Will BUL FC cover a -1 goal handicap against URA FC?": 44,
    "Will KOBS Rugby Club beat Platinum Credit Heathens?": 55,
    "Will KOBS vs Heathens have over 42.5 total points?": 51,
    "Will Black Pirates win by 1 to 7 points?": 38,
    "Will Rhinos vs Mongers include a yellow card?": 47,
    "Will City Oilers beat Namuwongo Blazers?": 64,
    "Will City Oilers vs Blazers exceed 155.5 total points?": 53,
    "Will UCU Canons cover a -4.5 point spread?": 48,
    "Will JT Jaguars score 80 or more points?": 46,
    "Will Vipers SC win the Uganda Premier League?": 36,
    "Will KOBS Rugby Club win the Nile Special Rugby Premiership?": 34,
    "Will City Oilers win the National Basketball League?": 57,
    "Will KOBS Rugby Club score 3 or more tries in their next league match?": 54,
}


class Command(BaseCommand):
    help = "Dry-run-first refresh of LEAGUE_OS_DEMO staging markets and test funding."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", action="store_true")
        parser.add_argument("--days-ahead", type=int, default=30)
        parser.add_argument("--market-admin-email")
        parser.add_argument("--result-admin-email")
        parser.add_argument("--initial-liquidity-ugx", type=Decimal, default=Decimal("500000"))
        parser.add_argument("--opening-spread-bps", type=int, default=100)
        parser.add_argument("--fan-wallet-ugx", type=Decimal, default=Decimal("1000000"))

    @transaction.atomic
    def handle(self, *args, **options):
        if (
            options["days_ahead"] < 1
            or min(options["initial_liquidity_ugx"], options["fan_wallet_ugx"]) < 0
        ):
            raise CommandError("days-ahead must be positive and funding amounts non-negative.")
        if not 0 <= options["opening_spread_bps"] <= 5000:
            raise CommandError("opening-spread-bps must be between 0 and 5000.")

        actor = self._user(options["market_admin_email"], options["confirm"], "market admin")
        result_actor = self._user(options["result_admin_email"], options["confirm"], "result admin")
        now = timezone.now()
        events = list(
            SportingEvent.objects.filter(source_name=DEMO_SOURCE).order_by("source_reference", "id")
        )
        planned = []
        for index, event in enumerate(events):
            start = now + timedelta(days=options["days_ahead"], hours=(index * 24) % (14 * 24))
            markets = list(event.markets.select_related("category", "sport").all())
            historical = event.starts_at <= now and any(self._has_history(m) for m in markets)
            decision = "PRESERVE_HISTORICAL" if historical else "RESCHEDULE_IN_PLACE"
            self.stdout.write(f"{decision} EVENT {event.source_reference}")
            if historical:
                for market in markets:
                    action = (
                        "CLOSE_AND_VOID"
                        if market.status
                        in {Market.Status.OPEN, Market.Status.SUSPENDED, Market.Status.CLOSED}
                        else "PRESERVE_HISTORICAL"
                    )
                    self.stdout.write(f"{action} MARKET {market.id}")
                self.stdout.write(
                    "CREATE_REPLACEMENT EVENT "
                    f"{self._replacement_reference(event)} at {start.isoformat()}"
                )
            else:
                for market in markets:
                    self.stdout.write(
                        f"RESCHEDULE_IN_PLACE MARKET {market.id}: closes_at="
                        f"{(start - timedelta(minutes=15)).isoformat()}"
                    )
            planned.extend(markets)
            if options["confirm"]:
                if historical:
                    self._preserve_and_replace(
                        event, markets, start, now, actor, result_actor, options
                    )
                else:
                    self._reschedule(event, markets, start, now, actor, options)

        long_horizon = list(
            Market.objects.filter(
                Q(scope_type="COMPETITION", competition__source_name=DEMO_SOURCE)
                | Q(scope_type="PARTICIPANT", participant__source_name=DEMO_SOURCE),
                sporting_event__isnull=True,
            )
            .select_related("sport", "category", "template", "competition", "participant")
            .order_by("created_at", "id")
        )
        for index, market in enumerate(long_horizon):
            start = now + timedelta(days=options["days_ahead"] + index)
            historical = market.closes_at is not None and market.closes_at <= now
            historical = historical and self._has_history(market)
            self.stdout.write(
                f"{'PRESERVE_HISTORICAL' if historical else 'RESCHEDULE_IN_PLACE'} "
                f"{market.scope_type} MARKET {market.id}"
            )
            planned.append(market)
            if options["confirm"]:
                if historical:
                    self._replace_long_horizon(market, start, now, actor, options)
                else:
                    self._reschedule_long_horizon(market, start, now, actor, options)

        configured_market_ids = {
            market.id
            for market in Market.objects.filter(
                liquidity_configuration__status="CONFIGURED"
            ).filter(
                Q(sporting_event__source_name=DEMO_SOURCE)
                | Q(competition__source_name=DEMO_SOURCE)
                | Q(participant__source_name=DEMO_SOURCE)
            )
            if not MarketCompleteSetIssuance.objects.filter(market=market).exists()
        }
        required = sum(
            (
                market.liquidity_configuration.initial_liquidity_ugx
                for market in Market.objects.filter(id__in=configured_market_ids).select_related(
                    "liquidity_configuration"
                )
            ),
            Decimal("0"),
        )
        current = self._treasury_available()
        top_up = max(Decimal("0"), required + TREASURY_BUFFER - current)
        self.stdout.write(f"required collateral: UGX {required:.4f}")
        self.stdout.write(f"current treasury available balance: UGX {current:.4f}")
        self.stdout.write(f"proposed top-up: UGX {top_up:.4f}")
        self.stdout.write(f"number of markets to activate: {len(configured_market_ids)}")
        for email in FAN_EMAILS:
            self.stdout.write(f"FAN_REVIEW {email}: ensure UGX {options['fan_wallet_ugx']:.4f}")

        if options["confirm"]:
            self._prepare_treasury(top_up)
            self._fund_existing_fans(options["fan_wallet_ugx"])
            self.stdout.write(self.style.SUCCESS("Confirmed LEAGUE_OS_DEMO refresh complete."))
        else:
            transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING("DRY RUN: no rows written; use --confirm."))

    @staticmethod
    def _user(email, required, label):
        user = get_user_model().objects.filter(email__iexact=email).first() if email else None
        if required and email and user is None:
            raise CommandError(f"The requested {label} does not exist.")
        return user

    @staticmethod
    def _has_history(market):
        return (
            market.orders.exists()
            or market.fills.exists()
            or MarketPosition.objects.filter(market=market).exists()
            or LedgerEntry.objects.filter(market=market).exists()
            or hasattr(market, "settlement")
            or hasattr(market, "void_refund")
            or MarketProvisionalResult.objects.filter(market=market).exists()
            or MarketResultDispute.objects.filter(provisional_result__market=market).exists()
            or market.collateral_entries.exists()
        )

    @staticmethod
    def _replacement_reference(event):
        return f"{event.source_reference}--refresh-v1"

    def _reschedule(self, event, markets, start, now, actor, options):
        duration = (event.ends_at - event.starts_at) if event.ends_at else timedelta(hours=3)
        event.starts_at, event.ends_at = start, start + max(duration, timedelta(minutes=1))
        event.status = SportingEvent.Status.SCHEDULED
        event.is_verified = True
        event.verified_at = event.verified_at or now
        event.full_clean()
        event.save()
        for market in markets:
            market.opens_at = min(market.opens_at or now, now)
            market.closes_at = start - timedelta(minutes=15)
            market.settles_by = event.ends_at + timedelta(hours=48)
            market.face_value_ugx = 10000
            market.full_clean()
            market.save(
                update_fields=[
                    "opens_at",
                    "closes_at",
                    "settles_by",
                    "face_value_ugx",
                    "updated_at",
                ]
            )
            self._configure_market(market, actor, options)

    def _preserve_and_replace(self, event, markets, start, now, actor, result_actor, options):
        for market in markets:
            if market.status in {Market.Status.OPEN, Market.Status.SUSPENDED}:
                if actor is None:
                    raise CommandError(
                        "--market-admin-email is required to close historical markets."
                    )
                MarketLifecycleService.close(
                    market_id=market.id, actor=actor, notes="Demo refresh historical cleanup."
                )
            market.refresh_from_db()
            if (
                market.status == Market.Status.CLOSED
                and MarketPosition.objects.filter(market=market, quantity__gt=0).exists()
            ):
                if result_actor is None:
                    raise CommandError(
                        "--result-admin-email is required to void historical positions."
                    )
                MarketResolutionService.void(
                    market_id=market.id,
                    actor=result_actor,
                    notes="Stale demo market has no trustworthy result.",
                    evidence="LEAGUE_OS_DEMO refresh policy.",
                )
                MarketVoidRefundService.refund_void_market(market_id=market.id, actor=result_actor)

        reference = self._replacement_reference(event)
        replacement = SportingEvent.objects.filter(
            source_name=DEMO_SOURCE, source_reference=reference
        ).first()
        if replacement is None:
            duration = (event.ends_at - event.starts_at) if event.ends_at else timedelta(hours=3)
            replacement = SportingEvent.objects.create(
                sport=event.sport,
                competition=event.competition,
                event_type=event.event_type,
                name=event.name,
                starts_at=start,
                ends_at=start + max(duration, timedelta(minutes=1)),
                status=SportingEvent.Status.SCHEDULED,
                venue=event.venue,
                country_code=event.country_code,
                source_name=DEMO_SOURCE,
                source_reference=reference,
                is_verified=True,
                verified_at=now,
            )
            for entry in event.event_participants.all():
                EventParticipant.objects.create(
                    event=replacement,
                    participant=entry.participant,
                    role=entry.role,
                    position=entry.position,
                )
        for market in markets:
            if replacement.markets.filter(question=market.question).exists():
                continue
            fresh = MarketCatalogService.create_market(
                sport=market.sport,
                category=market.category,
                template=market.template,
                scope_type=market.scope_type,
                sporting_event=replacement,
                question=market.question,
                description=market.description,
                rules=market.rules,
                resolution_source=market.resolution_source,
                resolution_criteria=market.resolution_criteria,
                face_value_ugx=10000,
                status=Market.Status.DRAFT,
                opens_at=now,
                closes_at=start - timedelta(minutes=15),
                settles_by=replacement.ends_at + timedelta(hours=48),
                created_by=actor or market.created_by,
                yes_label=market.outcomes.get(side="YES").label,
                no_label=market.outcomes.get(side="NO").label,
            )
            self._configure_market(fresh, actor, options)

    def _reschedule_long_horizon(self, market, close_at, now, actor, options):
        market.opens_at = min(market.opens_at or now, now)
        market.closes_at = close_at
        market.settles_by = close_at + timedelta(hours=48)
        market.face_value_ugx = 10000
        market.full_clean()
        market.save(
            update_fields=["opens_at", "closes_at", "settles_by", "face_value_ugx", "updated_at"]
        )
        self._configure_market(market, actor, options)

    def _replace_long_horizon(self, market, close_at, now, actor, options):
        target = {"competition": market.competition, "participant": market.participant}
        lookup = {
            "question": market.question,
            "scope_type": market.scope_type,
            "sporting_event__isnull": True,
            "competition": market.competition,
            "participant": market.participant,
            "closes_at__gt": now,
        }
        fresh = Market.objects.filter(**lookup).exclude(pk=market.pk).order_by("created_at").first()
        if fresh is None:
            fresh = MarketCatalogService.create_market(
                sport=market.sport,
                category=market.category,
                template=market.template,
                scope_type=market.scope_type,
                sporting_event=None,
                competition=target["competition"],
                participant=target["participant"],
                question=market.question,
                description=market.description,
                rules=market.rules,
                resolution_source=market.resolution_source,
                resolution_criteria=market.resolution_criteria,
                face_value_ugx=10000,
                status=Market.Status.DRAFT,
                opens_at=now,
                closes_at=close_at,
                settles_by=close_at + timedelta(hours=48),
                created_by=actor or market.created_by,
                yes_label=market.outcomes.get(side="YES").label,
                no_label=market.outcomes.get(side="NO").label,
            )
        self._configure_market(fresh, actor, options)

    @staticmethod
    def _configure_market(market, actor, options):
        probability = YES_PROBABILITIES.get(market.question)
        if probability is None or market.status not in {
            Market.Status.DRAFT,
            Market.Status.REJECTED,
        }:
            return
        MarketOpeningPricingService.configure(
            market=market, actor=actor, face_value_ugx=10000, yes_probability=probability
        )
        MarketLiquidityService.configure(
            market=market,
            actor=actor,
            initial_liquidity_ugx=options["initial_liquidity_ugx"],
            opening_spread_bps=options["opening_spread_bps"],
        )

    @staticmethod
    def _treasury_available():
        wallet = Wallet.objects.filter(user__email__iexact=TREASURY_EMAIL, currency="UGX").first()
        return wallet.available_balance if wallet else Decimal("0")

    @staticmethod
    def _prepare_treasury(top_up):
        user, _ = get_user_model().objects.get_or_create(
            email=TREASURY_EMAIL,
            defaults={"username": TREASURY_EMAIL, "is_active": True},
        )
        if user.has_usable_password():
            user.set_unusable_password()
            user.save(update_fields=["password", "updated_at"])
        MarketLiquidityProvider.objects.update_or_create(
            code="PLATFORM_TREASURY",
            defaults={
                "provider_type": MarketLiquidityProvider.ProviderType.PLATFORM_TREASURY,
                "user": user,
                "is_active": True,
                "display_name": "League OS Demo Liquidity",
            },
        )
        if top_up > 0:
            WalletService.credit(
                user=user,
                currency="UGX",
                amount=top_up,
                idempotency_reference=uuid5(FUNDING_NAMESPACE, f"treasury:{top_up:.4f}"),
            )

    @staticmethod
    def _fund_existing_fans(target):
        for user in get_user_model().objects.filter(email__in=FAN_EMAILS):
            now = timezone.now()
            verification, _ = KYCVerification.objects.select_for_update().get_or_create(user=user)
            verification.status = KYCVerification.Status.VERIFIED
            verification.verification_source = KYCVerification.VerificationSource.DEVELOPMENT_BYPASS
            verification.verification_started_at = verification.verification_started_at or now
            verification.verification_completed_at = now
            verification.verified_at = now
            verification.rejection_reason = ""
            verification.retry_reason = ""
            verification.save()
            if not user.is_verified:
                user.is_verified = True
                user.save(update_fields=["is_verified", "updated_at"])
            role = Role.objects.filter(name="Verified Market User").first()
            if role:
                UserRole.objects.update_or_create(
                    user=user,
                    role=role,
                    defaults={"is_active": True, "revoked_at": None, "revoked_by": None},
                )
            wallet = Wallet.objects.filter(user=user, currency="UGX").first()
            current = wallet.available_balance if wallet else Decimal("0")
            amount = max(Decimal("0"), target - current)
            if amount:
                WalletService.credit(
                    user=user,
                    currency="UGX",
                    amount=amount,
                    idempotency_reference=uuid5(FUNDING_NAMESPACE, f"fan:{user.id}:{target:.4f}"),
                )

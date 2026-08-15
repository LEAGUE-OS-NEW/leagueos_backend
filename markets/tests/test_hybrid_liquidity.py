from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import DatabaseError
from django.test import TestCase
from django.utils import timezone

from authentication.tests.factories import (
    PermissionFactory,
    RoleFactory,
    RolePermissionFactory,
    UserFactory,
    UserRoleFactory,
)
from markets.models import (
    Market,
    MarketCategory,
    MarketCollateralEntry,
    MarketCollateralPool,
    MarketCompleteSetIssuance,
    MarketLiquidityProvider,
    MarketOrder,
    MarketOutcome,
    MarketPosition,
    MarketScope,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.liquidity_service import MarketLiquidityService
from markets.services.opening_pricing_service import MarketOpeningPricingService
from markets.services.participation_service import MarketParticipationService
from markets.tests.eligibility_test_support import make_market_eligible
from markets.tests.wallet_test_support import fund_market_wallet
from sports.models import Competition, Participant, Sport, SportingEvent
from wallets.models import LedgerEntry, Wallet


class HybridLiquidityTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        permissions = {}
        for name, action in (
            ("manage_market", "manage"),
            ("approve_market", "approve"),
            ("participate_market", "participate"),
        ):
            permissions[name] = PermissionFactory(name=name, resource="market", action=action)
        operations = RoleFactory(name="Hybrid Operations", display_name="Operations")
        approval = RoleFactory(name="Hybrid Approval", display_name="Approval")
        participant = RoleFactory(name="Hybrid Participant", display_name="Participant")
        RolePermissionFactory(role=operations, permission=permissions["manage_market"])
        RolePermissionFactory(role=approval, permission=permissions["approve_market"])
        RolePermissionFactory(role=participant, permission=permissions["participate_market"])
        self.operator = UserFactory()
        self.approver = UserFactory()
        UserRoleFactory(user=self.operator, role=operations)
        UserRoleFactory(user=self.approver, role=approval)
        self.participant_role = participant
        self.provider_user = self.trader()
        self.provider = MarketLiquidityProvider.objects.create(
            code="PLATFORM_TREASURY",
            provider_type=MarketLiquidityProvider.ProviderType.PLATFORM_TREASURY,
            user=self.provider_user,
            display_name="Platform Liquidity",
        )
        self.sport = Sport.objects.create(name="Hybrid Football", code="HYBRID_FOOTBALL")
        self.category = MarketCategory.objects.create(name="Hybrid Match Result")
        self.competition = Competition.objects.create(
            sport=self.sport, name="Hybrid League", country_code="UG", is_verified=True
        )
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="Hybrid Home vs Away",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

    def trader(self):
        user = UserFactory(is_verified=True)
        UserRoleFactory(user=user, role=self.participant_role)
        make_market_eligible(user)
        fund_market_wallet(user)
        return user

    def draft_market(self, question="Will Hybrid Home win?"):
        return MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question=question,
            description="Prediction market.",
            rules="Official result.",
            resolution_source="Official result",
            resolution_criteria="Verified score.",
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=1),
            created_by=self.operator,
            yes_label="Yes",
            no_label="No",
        )

    def open_market(self, market):
        MarketLifecycleService.submit(market_id=market.id, actor=self.operator, notes="Ready.")
        MarketLifecycleService.approve(market_id=market.id, actor=self.approver, notes="Approved.")
        return MarketLifecycleService.open(
            market_id=market.id, actor=self.approver, notes="Opened."
        )

    def configure(self, market, amount="500000", spread=100):
        MarketOpeningPricingService.configure(
            market=market,
            actor=self.operator,
            face_value_ugx=Decimal("10000"),
            yes_probability=60,
        )
        return MarketLiquidityService.configure(
            market=market,
            actor=self.operator,
            provider=self.provider,
            initial_liquidity_ugx=Decimal(amount),
            opening_spread_bps=spread,
        )

    def place_buy(self, user, market, side, quantity, price, time_in_force="GTC"):
        outcome = market.outcomes.get(side=side)
        return MarketParticipationService.place_order(
            user=user,
            market_id=market.id,
            outcome_id=outcome.id,
            side=MarketOrder.Side.BUY,
            quantity=Decimal(quantity),
            limit_price=Decimal(price),
            time_in_force=time_in_force,
        )

    def test_zero_liquidity_opens_without_issuance(self):
        market = self.draft_market()
        self.configure(market, amount="0")
        opened = self.open_market(market)
        self.assertEqual(opened.status, Market.Status.OPEN)
        self.assertFalse(MarketCompleteSetIssuance.objects.filter(market=market).exists())

    def test_funded_opening_liquidity_is_exact_backed_real_and_idempotent(self):
        market = self.draft_market()
        self.configure(market)
        self.open_market(market)
        issuance = MarketCompleteSetIssuance.objects.get(market=market)
        pool = MarketCollateralPool.objects.get(market=market)
        positions = MarketPosition.objects.filter(market=market, user=self.provider_user)
        orders = MarketOrder.objects.filter(market=market, user=self.provider_user)
        self.assertEqual(issuance.quantity, Decimal("500000.0000"))
        self.assertEqual(issuance.quantity / Decimal("10000"), Decimal("50.0000"))
        self.assertEqual(pool.locked_collateral, issuance.quantity)
        self.assertEqual(set(positions.values_list("quantity", flat=True)), {issuance.quantity})
        self.assertEqual(
            set(positions.values_list("reserved_quantity", flat=True)), {issuance.quantity}
        )
        self.assertEqual(positions.count(), 2)
        self.assertEqual(orders.count(), 2)
        self.assertFalse(orders.exclude(status=MarketOrder.Status.OPEN).exists())
        yes = market.outcomes.get(side=MarketOutcome.Side.YES)
        no = market.outcomes.get(side=MarketOutcome.Side.NO)
        self.assertEqual(
            positions.get(outcome=yes).total_cost,
            issuance.quantity * yes.opening_price,
        )
        self.assertEqual(
            positions.get(outcome=no).total_cost,
            issuance.quantity * no.opening_price,
        )
        self.assertEqual(
            orders.get(outcome=yes).limit_price, yes.opening_price + Decimal("0.00500")
        )
        self.assertEqual(orders.get(outcome=no).limit_price, no.opening_price + Decimal("0.00500"))
        MarketLiquidityService.activate_opening_liquidity(market=market, actor=self.approver)
        self.assertEqual(MarketCompleteSetIssuance.objects.filter(market=market).count(), 1)

    def test_missing_provider_and_bad_prices_roll_back_market_open(self):
        market = self.draft_market("Missing provider")
        self.configure(market)
        self.provider.is_active = False
        self.provider.save(update_fields=["is_active", "updated_at"])
        with self.assertRaises(ValidationError):
            self.open_market(market)
        market.refresh_from_db()
        self.assertEqual(market.status, Market.Status.APPROVED)
        self.assertFalse(MarketCollateralPool.objects.filter(market=market).exists())

        self.provider.is_active = True
        self.provider.save(update_fields=["is_active", "updated_at"])
        yes = market.outcomes.get(side=MarketOutcome.Side.YES)
        yes.opening_price = Decimal("0.61000")
        yes.save(update_fields=["opening_price", "updated_at"])
        with self.assertRaises(ValidationError):
            MarketLifecycleService.open(
                market_id=market.id, actor=self.approver, notes="Retry open."
            )
        market.refresh_from_db()
        self.assertEqual(market.status, Market.Status.APPROVED)

    def test_insufficient_treasury_rolls_back_every_opening_mutation(self):
        market = self.draft_market()
        self.configure(market, amount="2000000")
        before_entries = LedgerEntry.objects.count()
        with self.assertRaises(ValidationError):
            self.open_market(market)
        market.refresh_from_db()
        self.assertEqual(market.status, Market.Status.APPROVED)
        self.assertFalse(MarketCollateralPool.objects.filter(market=market).exists())
        self.assertFalse(MarketPosition.objects.filter(market=market).exists())
        self.assertFalse(MarketOrder.objects.filter(market=market).exists())
        self.assertFalse(MarketCollateralEntry.objects.filter(market=market).exists())
        self.assertEqual(LedgerEntry.objects.count(), before_entries)

    def test_complementary_buys_use_oldest_maker_complement_and_release_improvement(self):
        market = self.open_market(self.draft_market())
        yes_user, no_user = self.trader(), self.trader()
        yes = self.place_buy(yes_user, market, MarketOutcome.Side.YES, "10", "0.60")
        yes_wallet = Wallet.objects.get(user=yes_user, currency="UGX")
        no = self.place_buy(no_user, market, MarketOutcome.Side.NO, "10", "0.45")
        yes.refresh_from_db()
        no.refresh_from_db()
        yes_wallet.refresh_from_db()
        issuance = MarketCompleteSetIssuance.objects.get(market=market)
        self.assertEqual(issuance.yes_execution_price, Decimal("0.60000"))
        self.assertEqual(issuance.no_execution_price, Decimal("0.40000"))
        self.assertEqual(yes.status, MarketOrder.Status.FILLED)
        self.assertEqual(no.status, MarketOrder.Status.FILLED)
        self.assertEqual(yes_wallet.reserved_balance, Decimal("0.0000"))
        self.assertEqual(
            MarketCollateralPool.objects.get(market=market).locked_collateral,
            Decimal("10.0000"),
        )
        self.assertEqual(
            set(MarketPosition.objects.filter(market=market).values_list("quantity", flat=True)),
            {Decimal("10.0000")},
        )

    def test_complementary_matching_partial_self_match_ioc_and_atomic_failure(self):
        market = self.open_market(self.draft_market())
        user, other = self.trader(), self.trader()
        self.place_buy(user, market, MarketOutcome.Side.YES, "8", "0.60")
        self.place_buy(user, market, MarketOutcome.Side.NO, "8", "0.40")
        self.assertFalse(MarketCompleteSetIssuance.objects.filter(market=market).exists())
        no_order = self.place_buy(other, market, MarketOutcome.Side.NO, "3", "0.40")
        no_order.refresh_from_db()
        yes_order = MarketOrder.objects.get(market=market, user=user, outcome__side="YES")
        yes_order.refresh_from_db()
        self.assertEqual(no_order.status, MarketOrder.Status.FILLED)
        self.assertEqual(yes_order.status, MarketOrder.Status.PARTIALLY_FILLED)
        self.assertEqual(yes_order.filled_quantity, Decimal("3.0000"))
        ioc = self.place_buy(other, market, MarketOutcome.Side.YES, "2", "0.20", "IOC")
        self.assertEqual(ioc.status, MarketOrder.Status.CANCELLED)

        rollback_market = self.open_market(self.draft_market("Atomic complement"))
        maker = self.trader()
        self.place_buy(maker, rollback_market, MarketOutcome.Side.YES, "2", "0.60")
        with patch(
            "markets.services.liquidity_service.MarketLiquidityService.lock_complementary_collateral",
            side_effect=DatabaseError("injected"),
        ):
            with self.assertRaises(DatabaseError):
                self.place_buy(self.trader(), rollback_market, MarketOutcome.Side.NO, "2", "0.40")
        self.assertFalse(MarketCompleteSetIssuance.objects.filter(market=rollback_market).exists())
        self.assertFalse(MarketPosition.objects.filter(market=rollback_market).exists())

    def test_demo_refresh_is_dry_by_default_and_reschedules_only_demo_data(self):
        market = self.draft_market("Will Vipers SC beat KCCA FC?")
        self.event.source_name = "LEAGUE_OS_DEMO"
        self.event.source_reference = "demo-match-1"
        self.event.starts_at = self.now - timedelta(days=10)
        self.event.save()
        original_start = self.event.starts_at
        real_event = SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="Provider event",
            starts_at=self.now - timedelta(days=2),
            source_name="REAL_PROVIDER",
            source_reference="provider-1",
        )
        output = StringIO()
        call_command("refresh_market_demo_staging", stdout=output)
        self.event.refresh_from_db()
        real_event.refresh_from_db()
        self.assertEqual(self.event.starts_at, original_start)
        self.assertEqual(real_event.starts_at, self.now - timedelta(days=2))
        self.assertIn("RESCHEDULE_IN_PLACE", output.getvalue())
        self.assertIn("DRY RUN", output.getvalue())
        self.assertFalse(hasattr(market, "liquidity_configuration"))

        call_command(
            "refresh_market_demo_staging",
            "--confirm",
            "--market-admin-email",
            self.operator.email,
            stdout=StringIO(),
        )
        self.event.refresh_from_db()
        market.refresh_from_db()
        self.assertGreaterEqual(self.event.starts_at, self.now + timedelta(days=29))
        self.assertEqual(market.settles_by, self.event.ends_at + timedelta(hours=48))
        self.assertEqual(market.face_value_ugx, 10000)
        self.assertEqual(market.outcomes.get(side="YES").opening_price, Decimal("0.58000"))
        self.assertEqual(market.liquidity_configuration.initial_liquidity_ugx, Decimal("500000"))

    def test_demo_refresh_preserves_history_and_replacement_is_idempotent(self):
        historical = self.draft_market("Will Vipers SC beat KCCA FC?")
        self.event.source_name = "LEAGUE_OS_DEMO"
        self.event.source_reference = "demo-traded-1"
        self.event.starts_at = self.now - timedelta(days=10)
        self.event.save()
        yes = historical.outcomes.get(side="YES")
        MarketPosition.objects.create(
            user=self.provider_user,
            market=historical,
            outcome=yes,
            quantity=Decimal("1"),
            average_entry_price=Decimal("0.5"),
            total_cost=Decimal("0.5"),
        )
        original_start = self.event.starts_at
        output = StringIO()
        args = ("--confirm", "--market-admin-email", self.operator.email)
        call_command("refresh_market_demo_staging", *args, stdout=output)
        call_command("refresh_market_demo_staging", *args, stdout=StringIO())
        self.event.refresh_from_db()
        self.assertEqual(self.event.starts_at, original_start)
        self.assertEqual(
            SportingEvent.objects.filter(
                source_name="LEAGUE_OS_DEMO",
                source_reference="demo-traded-1--refresh-v1",
            ).count(),
            1,
        )
        replacement = SportingEvent.objects.get(
            source_name="LEAGUE_OS_DEMO",
            source_reference="demo-traded-1--refresh-v1",
        )
        self.assertEqual(replacement.markets.filter(question=historical.question).count(), 1)
        self.assertEqual(MarketPosition.objects.get(pk=historical.positions.get().pk).quantity, 1)
        self.assertIn("PRESERVE_HISTORICAL", output.getvalue())
        self.assertIn("CREATE_REPLACEMENT", output.getvalue())

    def test_confirmed_demo_refresh_does_not_duplicate_financial_ledger_entries(self):
        market = self.draft_market("Will Vipers SC beat KCCA FC?")
        self.event.source_name = "LEAGUE_OS_DEMO"
        self.event.source_reference = "demo-ledger-idempotency"
        self.event.save()
        fan = UserFactory(email="fan.a.local@leagueos.test", is_verified=True)
        UserRoleFactory(user=fan, role=self.participant_role)
        make_market_eligible(fan)
        args = ("--confirm", "--market-admin-email", self.operator.email)
        call_command("refresh_market_demo_staging", *args, stdout=StringIO())
        self.open_market(market)

        treasury_wallet = Wallet.objects.get(user__email="liquidity.treasury@leagueos.test")
        fan_wallet = Wallet.objects.get(user=fan, currency="UGX")
        financial_before = {
            "treasury_entries": LedgerEntry.objects.filter(wallet=treasury_wallet).count(),
            "fan_entries": LedgerEntry.objects.filter(wallet=fan_wallet).count(),
            "locks": MarketCollateralEntry.objects.filter(
                market=market,
                entry_type=MarketCollateralEntry.EntryType.TREASURY_LOCK,
            ).count(),
            "issuances": MarketCompleteSetIssuance.objects.filter(market=market).count(),
            "references": set(
                LedgerEntry.objects.exclude(idempotency_reference=None).values_list(
                    "idempotency_reference", flat=True
                )
            ),
        }
        call_command("refresh_market_demo_staging", *args, stdout=StringIO())
        self.assertEqual(
            LedgerEntry.objects.filter(wallet=treasury_wallet).count(),
            financial_before["treasury_entries"],
        )
        self.assertEqual(
            LedgerEntry.objects.filter(wallet=fan_wallet).count(), financial_before["fan_entries"]
        )
        self.assertEqual(
            MarketCollateralEntry.objects.filter(
                market=market,
                entry_type=MarketCollateralEntry.EntryType.TREASURY_LOCK,
            ).count(),
            financial_before["locks"],
        )
        self.assertEqual(
            MarketCompleteSetIssuance.objects.filter(market=market).count(),
            financial_before["issuances"],
        )
        references = list(
            LedgerEntry.objects.exclude(idempotency_reference=None).values_list(
                "idempotency_reference", flat=True
            )
        )
        self.assertEqual(set(references), financial_before["references"])
        self.assertEqual(len(references), len(set(references)))

    def test_demo_refresh_covers_untraded_competition_and_participant_horizons(self):
        self.competition.source_name = "LEAGUE_OS_DEMO"
        self.competition.source_reference = "demo-long-competition"
        self.competition.save()
        participant = Participant.objects.create(
            sport=self.sport,
            name="Vipers SC",
            source_name="LEAGUE_OS_DEMO",
            source_reference="demo-long-participant",
            is_verified=True,
        )
        competition_market = MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.COMPETITION,
            competition=self.competition,
            question="Will Vipers SC win the Uganda Premier League?",
            description="Long horizon.",
            rules="Official table.",
            resolution_source="Official result",
            resolution_criteria="Champion.",
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(days=1),
            closes_at=self.now - timedelta(hours=1),
            created_by=self.operator,
        )
        participant_market = MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.PARTICIPANT,
            participant=participant,
            question="Will KOBS Rugby Club score 3 or more tries in their next league match?",
            description="Long horizon.",
            rules="Official result.",
            resolution_source="Official result",
            resolution_criteria="Try count.",
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(days=1),
            closes_at=self.now - timedelta(hours=1),
            created_by=self.operator,
        )
        before_events = SportingEvent.objects.count()
        args = ("--confirm", "--market-admin-email", self.operator.email)
        call_command("refresh_market_demo_staging", *args, stdout=StringIO())
        for market, scope in (
            (competition_market, MarketScope.COMPETITION),
            (participant_market, MarketScope.PARTICIPANT),
        ):
            market.refresh_from_db()
            self.assertEqual(market.scope_type, scope)
            self.assertIsNone(market.sporting_event_id)
            self.assertGreater(market.closes_at, self.now)
            self.assertEqual(market.settles_by, market.closes_at + timedelta(hours=48))
            self.assertEqual(market.face_value_ugx, 10000)
            self.assertEqual(market.liquidity_configuration.initial_liquidity_ugx, 500000)
        self.assertEqual(SportingEvent.objects.count(), before_events)

    def test_demo_refresh_preserves_traded_long_horizon_and_reuses_replacement(self):
        self.competition.source_name = "LEAGUE_OS_DEMO"
        self.competition.source_reference = "demo-historical-competition"
        self.competition.save()
        participant = Participant.objects.create(
            sport=self.sport,
            name="Historical KOBS Rugby Club",
            source_name="LEAGUE_OS_DEMO",
            source_reference="demo-historical-participant",
            is_verified=True,
        )
        historical_competition = MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.COMPETITION,
            competition=self.competition,
            question="Will Vipers SC win the Uganda Premier League?",
            description="Historical long horizon.",
            rules="Official table.",
            resolution_source="Official result",
            resolution_criteria="Champion.",
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(days=20),
            closes_at=self.now - timedelta(days=10),
            created_by=self.operator,
        )
        historical_participant = MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.PARTICIPANT,
            participant=participant,
            question="Will KOBS Rugby Club score 3 or more tries in their next league match?",
            description="Historical participant horizon.",
            rules="Official result.",
            resolution_source="Official result",
            resolution_criteria="Try count.",
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(days=20),
            closes_at=self.now - timedelta(days=10),
            created_by=self.operator,
        )
        historical_markets = (historical_competition, historical_participant)
        for historical in historical_markets:
            MarketPosition.objects.create(
                user=self.provider_user,
                market=historical,
                outcome=historical.outcomes.get(side="YES"),
                quantity=Decimal("1"),
                average_entry_price=Decimal("0.5"),
                total_cost=Decimal("0.5"),
            )
        original_closes = {market.id: market.closes_at for market in historical_markets}
        before_events = SportingEvent.objects.count()
        args = ("--confirm", "--market-admin-email", self.operator.email)
        call_command("refresh_market_demo_staging", *args, stdout=StringIO())
        call_command("refresh_market_demo_staging", *args, stdout=StringIO())
        for historical in historical_markets:
            historical.refresh_from_db()
            self.assertEqual(historical.closes_at, original_closes[historical.id])
            replacements = Market.objects.filter(
                question=historical.question,
                scope_type=historical.scope_type,
                competition=historical.competition,
                participant=historical.participant,
                sporting_event__isnull=True,
                closes_at__gt=self.now,
            )
            self.assertEqual(replacements.count(), 1)
            self.assertIsNone(replacements.get().sporting_event_id)
            self.assertEqual(MarketPosition.objects.get(market=historical).quantity, 1)
        self.assertEqual(SportingEvent.objects.count(), before_events)

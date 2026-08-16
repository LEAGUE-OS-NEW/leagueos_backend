from decimal import Decimal
from io import StringIO
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

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
    MarketFill,
    MarketOrder,
    MarketPosition,
    MarketScope,
    MarketSettlement,
    MarketStatusTransition,
)
from markets.serializers import MarketPublicSerializer
from markets.services.catalog_service import MarketCatalogService
from markets.services.liquidity_service import MarketLiquidityService
from markets.services.opening_pricing_service import MarketOpeningPricingService
from sports.models import Sport
from wallets.models import WalletTransaction


class MarketOpeningPricingTests(TestCase):
    def setUp(self):
        permission = PermissionFactory(name="manage_market", resource="market", action="manage")
        role = RoleFactory(name="Opening Price Operations", display_name="Opening Price Operations")
        RolePermissionFactory(role=role, permission=permission)
        self.actor = UserFactory()
        UserRoleFactory(user=self.actor, role=role)
        self.outsider = UserFactory()
        self.sport = Sport.objects.create(name="Opening Price Sport", code="OPENING_PRICE")
        self.category = MarketCategory.objects.create(name="Opening Price Tests")
        self.market = MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.CUSTOM,
            custom_subject="Test subject",
            question="Will this test pass?",
            created_by=self.actor,
        )

    def configure(self, probability=60, face_value=10000):
        return MarketOpeningPricingService.configure(
            market=self.market,
            actor=self.actor,
            face_value_ugx=face_value,
            yes_probability=probability,
        )

    def test_new_market_default_and_complementary_prices(self):
        self.assertEqual(self.market.face_value_ugx, 10000)
        self.configure()
        outcomes = {outcome.side: outcome for outcome in self.market.outcomes.all()}
        self.assertEqual(outcomes["YES"].opening_price, Decimal("0.60000"))
        self.assertEqual(outcomes["NO"].opening_price, Decimal("0.40000"))
        self.assertEqual(sum(item.opening_price for item in outcomes.values()), Decimal("1.00000"))
        data = MarketPublicSerializer(Market.objects.get(pk=self.market.pk)).data
        by_side = {item["side"]: item for item in data["outcomes"]}
        self.assertEqual(by_side["YES"]["opening_price_ugx"], 6000)
        self.assertEqual(by_side["NO"]["opening_price_ugx"], 4000)

    def test_invalid_endpoints_are_rejected(self):
        for probability in (0, 100):
            with self.subTest(probability=probability), self.assertRaises(ValidationError):
                self.configure(probability)

    def test_can_edit_pre_open_but_not_open(self):
        self.configure(60)
        self.configure(55)
        self.market.status = Market.Status.OPEN
        self.market.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            self.configure(50)

    def test_unprivileged_actor_is_denied(self):
        with self.assertRaises(ValidationError):
            MarketOpeningPricingService.configure(
                market=self.market,
                actor=self.outsider,
                face_value_ugx=10000,
                yes_probability=50,
            )

    def open_market(self):
        self.market.status = Market.Status.OPEN
        self.market.save(update_fields=["status"])

    def local_backfill(self, actor=None):
        return MarketOpeningPricingService.configure_local_untraded_historical_market(
            market=self.market,
            actor=actor or self.actor,
            face_value_ugx=12000,
            yes_probability=65,
        )

    @override_settings(DEBUG=True)
    def test_local_historical_backfill_accepts_untraded_open_market(self):
        self.open_market()
        self.local_backfill()
        self.market.refresh_from_db()
        outcomes = {outcome.side: outcome.opening_price for outcome in self.market.outcomes.all()}
        self.assertEqual(self.market.status, Market.Status.OPEN)
        self.assertEqual(self.market.face_value_ugx, 12000)
        self.assertEqual(outcomes, {"YES": Decimal("0.65000"), "NO": Decimal("0.35000")})
        self.assertEqual(sum(outcomes.values()), Decimal("1.00000"))

    @override_settings(DEBUG=False)
    def test_local_historical_backfill_rejects_debug_false(self):
        self.open_market()
        with self.assertRaises(ValidationError):
            self.local_backfill()

    @override_settings(DEBUG=True)
    def test_local_historical_backfill_requires_manage_market(self):
        self.open_market()
        with self.assertRaises(ValidationError):
            self.local_backfill(actor=self.outsider)

    def create_order(self, *, user=None, side=MarketOrder.Side.BUY):
        return MarketOrder.objects.create(
            user=user or self.actor,
            market=self.market,
            outcome=self.market.outcomes.get(side="YES"),
            side=side,
            quantity=Decimal("1.0000"),
            limit_price=Decimal("0.50000"),
        )

    @override_settings(DEBUG=True)
    def test_local_historical_backfill_rejects_order(self):
        self.open_market()
        self.create_order()
        with self.assertRaises(ValidationError):
            self.local_backfill()

    @override_settings(DEBUG=True)
    def test_local_historical_backfill_rejects_fill(self):
        self.open_market()
        buy_order = self.create_order()
        sell_order = self.create_order(user=self.outsider, side=MarketOrder.Side.SELL)
        MarketFill.objects.create(
            execution_reference=uuid4(),
            market=self.market,
            outcome=buy_order.outcome,
            buy_order=buy_order,
            sell_order=sell_order,
            maker_order=buy_order,
            taker_order=sell_order,
            quantity=Decimal("1.0000"),
            price=Decimal("0.50000"),
        )
        with self.assertRaises(ValidationError):
            self.local_backfill()

    @override_settings(DEBUG=True)
    def test_local_historical_backfill_rejects_position(self):
        self.open_market()
        MarketPosition.objects.create(
            user=self.actor,
            market=self.market,
            outcome=self.market.outcomes.get(side="YES"),
        )
        with self.assertRaises(ValidationError):
            self.local_backfill()

    @override_settings(DEBUG=True)
    def test_local_historical_backfill_rejects_settlement(self):
        self.open_market()
        MarketSettlement.objects.create(
            market=self.market,
            winning_outcome=self.market.outcomes.get(side="YES"),
            payout_per_unit=Decimal("1000.0000"),
            settlement_currency="UGX",
            executed_by=self.actor,
        )
        with self.assertRaises(ValidationError):
            self.local_backfill()

    @override_settings(DEBUG=True)
    def test_local_backfill_creates_no_financial_or_lifecycle_records(self):
        self.open_market()
        before = (
            MarketOrder.objects.count(),
            MarketFill.objects.count(),
            MarketPosition.objects.count(),
            WalletTransaction.objects.count(),
            MarketStatusTransition.objects.count(),
        )
        self.local_backfill()
        self.assertEqual(
            before,
            (
                MarketOrder.objects.count(),
                MarketFill.objects.count(),
                MarketPosition.objects.count(),
                WalletTransaction.objects.count(),
                MarketStatusTransition.objects.count(),
            ),
        )

    @override_settings(DEBUG=True)
    def test_command_backfills_explicit_untraded_open_market(self):
        self.open_market()
        output = StringIO()
        call_command(
            "configure_untraded_market_opening_pricing",
            market_id=[str(self.market.pk)],
            actor_email=self.actor.email,
            face_value_ugx=15000,
            yes_probability="70",
            stdout=output,
        )
        self.market.refresh_from_db()
        self.assertEqual(self.market.status, Market.Status.OPEN)
        self.assertEqual(self.market.face_value_ugx, 15000)
        self.assertIn("historical local demo backfill", output.getvalue())

    @override_settings(DEBUG=True)
    def test_command_refuses_missing_market_ids(self):
        with self.assertRaises(CommandError):
            call_command(
                "configure_untraded_market_opening_pricing",
                actor_email=self.actor.email,
            )

    def test_public_serializer_exposes_safe_opening_liquidity_summary(self):
        self.configure(
            probability=50,
            face_value=10000,
        )

        MarketLiquidityService.configure(
            market=self.market,
            actor=self.actor,
            initial_liquidity_ugx=Decimal("500000.0000"),
            opening_spread_bps=100,
        )

        data = MarketPublicSerializer(
            Market.objects.get(
                pk=self.market.pk,
            )
        ).data

        self.assertEqual(
            data["opening_liquidity"],
            {
                "initial_liquidity_ugx": "500000.0000",
                "opening_spread_bps": 100,
                "activation_status": "CONFIGURED",
            },
        )

        self.assertNotIn(
            "provider",
            data["opening_liquidity"],
        )
        self.assertNotIn(
            "locked_collateral",
            data["opening_liquidity"],
        )

    def test_snapshot_uses_reference_without_creating_trading_records(self):
        self.configure(60)
        before = (
            MarketOrder.objects.count(),
            MarketFill.objects.count(),
            MarketPosition.objects.count(),
        )
        data = MarketPublicSerializer(Market.objects.get(pk=self.market.pk)).data
        yes = self.market.outcomes.get(side="YES")
        snapshot = data["trading_snapshot"]["outcomes"][str(yes.pk)]
        self.assertIsNone(snapshot["best_bid"])
        self.assertIsNone(snapshot["best_ask"])
        self.assertIsNone(snapshot["last_trade"])
        self.assertEqual(snapshot["mark_price"], "0.60000")
        self.assertEqual(snapshot["opening_price"], "0.60000")
        self.assertEqual(snapshot["mark_source"], "OPENING_REFERENCE")
        self.assertEqual(
            before,
            (
                MarketOrder.objects.count(),
                MarketFill.objects.count(),
                MarketPosition.objects.count(),
            ),
        )

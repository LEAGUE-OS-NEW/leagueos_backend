from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.apps import apps
from django.core.exceptions import ValidationError
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
    MarketOrder,
    MarketOutcome,
    MarketPosition,
    MarketScope,
)
from markets.services.catalog_service import (
    MarketCatalogService,
)
from markets.services.lifecycle_service import (
    MarketLifecycleService,
)
from markets.services.participation_service import (
    MarketParticipationService,
)
from markets.tests.wallet_test_support import (
    fund_market_wallet,
)
from sports.models import (
    Competition,
    Sport,
    SportingEvent,
)


class MarketFillModelTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

        manage_permission = PermissionFactory(
            name="manage_market",
            resource="market",
            action="manage",
        )
        approve_permission = PermissionFactory(
            name="approve_market",
            resource="market",
            action="approve",
        )
        participate_permission = PermissionFactory(
            name="participate_market",
            resource="market",
            action="participate",
        )

        operations_role = RoleFactory(
            name="Market Operations Admin",
            display_name="Market Operations Admin",
        )
        approval_role = RoleFactory(
            name="Market Approval Admin",
            display_name="Market Approval Admin",
        )
        participant_role = RoleFactory(
            name="Verified Market User",
            display_name="Verified Market User",
        )

        RolePermissionFactory(
            role=operations_role,
            permission=manage_permission,
        )
        RolePermissionFactory(
            role=approval_role,
            permission=approve_permission,
        )
        RolePermissionFactory(
            role=participant_role,
            permission=participate_permission,
        )

        self.operations_user = UserFactory()
        self.approver_user = UserFactory()

        self.buyer = UserFactory(
            is_verified=True,
        )
        self.seller = UserFactory(
            is_verified=True,
        )

        fund_market_wallet(self.buyer)
        fund_market_wallet(self.seller)

        UserRoleFactory(
            user=self.operations_user,
            role=operations_role,
        )
        UserRoleFactory(
            user=self.approver_user,
            role=approval_role,
        )
        UserRoleFactory(
            user=self.buyer,
            role=participant_role,
        )
        UserRoleFactory(
            user=self.seller,
            role=participant_role,
        )

        self.sport = Sport.objects.create(
            name="Football",
            code="FOOTBALL",
        )
        self.category = MarketCategory.objects.create(
            name="Match Result",
        )
        self.competition = Competition.objects.create(
            sport=self.sport,
            name="Uganda Premier League",
            country_code="UG",
            is_verified=True,
        )
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="KCCA FC vs Vipers SC",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

        self.market = self.open_market(
            self.create_market(
                question="Will KCCA FC win?",
            )
        )
        self.outcome = self.market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        self.buy_order = self.create_order(
            user=self.buyer,
            market=self.market,
            outcome=self.outcome,
            side=MarketOrder.Side.BUY,
            limit_price=Decimal("0.60000"),
        )
        MarketPosition.objects.create(
            user=self.buyer,
            market=self.market,
            outcome=self.outcome,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.50000"),
            total_cost=Decimal("5.0000"),
        )
        MarketPosition.objects.create(
            user=self.seller,
            market=self.market,
            outcome=self.outcome,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.45000"),
            total_cost=Decimal("4.5000"),
        )
        self.sell_order = self.create_order(
            user=self.seller,
            market=self.market,
            outcome=self.outcome,
            side=MarketOrder.Side.SELL,
            limit_price=Decimal("0.55000"),
        )

    @property
    def fill_model(self):
        return apps.get_model(
            "markets",
            "MarketFill",
        )

    def create_market(self, *, question):
        return MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question=question,
            description="Match prediction market.",
            rules=("Resolve using the official " "competition result."),
            resolution_source=("Official competition result"),
            resolution_criteria=("Use the verified final score."),
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=1),
            created_by=self.operations_user,
            yes_label="Yes",
            no_label="No",
        )

    def open_market(self, market):
        market = MarketLifecycleService.submit(
            market_id=market.id,
            actor=self.operations_user,
            notes="Ready for review.",
        )
        market = MarketLifecycleService.approve(
            market_id=market.id,
            actor=self.approver_user,
            notes="Market verified.",
        )

        return MarketLifecycleService.open(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading opened.",
        )

    def create_order(
        self,
        *,
        user,
        market,
        outcome,
        side,
        quantity=Decimal("10.0000"),
        limit_price=Decimal("0.55000"),
    ):
        return MarketParticipationService.place_order(
            user=user,
            market_id=market.id,
            outcome_id=outcome.id,
            side=side,
            quantity=quantity,
            limit_price=limit_price,
        )

    def build_fill(
        self,
        *,
        execution_reference=None,
        market=None,
        outcome=None,
        buy_order=None,
        sell_order=None,
        maker_order=None,
        taker_order=None,
        quantity=None,
        price=None,
    ):
        buy_order = self.buy_order if buy_order is None else buy_order
        sell_order = self.sell_order if sell_order is None else sell_order

        return self.fill_model(
            execution_reference=(execution_reference or uuid4()),
            market=(self.market if market is None else market),
            outcome=(self.outcome if outcome is None else outcome),
            buy_order=buy_order,
            sell_order=sell_order,
            maker_order=(sell_order if maker_order is None else maker_order),
            taker_order=(buy_order if taker_order is None else taker_order),
            quantity=(Decimal("4.0000") if quantity is None else quantity),
            price=(Decimal("0.55000") if price is None else price),
        )

    def create_fill(self, **kwargs):
        fill = self.build_fill(**kwargs)
        fill.full_clean()
        fill.save(force_insert=True)
        return fill

    def test_fill_records_execution_relationships(
        self,
    ):
        execution_reference = uuid4()

        fill = self.create_fill(
            execution_reference=(execution_reference),
        )

        self.assertEqual(
            fill.execution_reference,
            execution_reference,
        )
        self.assertEqual(
            fill.market,
            self.market,
        )
        self.assertEqual(
            fill.outcome,
            self.outcome,
        )
        self.assertEqual(
            fill.buy_order,
            self.buy_order,
        )
        self.assertEqual(
            fill.sell_order,
            self.sell_order,
        )
        self.assertEqual(
            fill.maker_order,
            self.sell_order,
        )
        self.assertEqual(
            fill.taker_order,
            self.buy_order,
        )
        self.assertEqual(
            fill.quantity,
            Decimal("4.0000"),
        )
        self.assertEqual(
            fill.price,
            Decimal("0.55000"),
        )
        self.assertIsNotNone(fill.created_at)

        self.assertTrue(
            self.buy_order.buy_fills.filter(
                id=fill.id,
            ).exists()
        )
        self.assertTrue(
            self.sell_order.sell_fills.filter(
                id=fill.id,
            ).exists()
        )

    def test_execution_reference_is_unique(self):
        field = self.fill_model._meta.get_field("execution_reference")

        self.assertTrue(field.unique)

        execution_reference = uuid4()
        self.create_fill(
            execution_reference=(execution_reference),
        )

        duplicate = self.build_fill(
            execution_reference=(execution_reference),
        )

        with self.assertRaises(ValidationError) as context:
            duplicate.full_clean()

        self.assertIn(
            "execution_reference",
            context.exception.message_dict,
        )

    def test_buy_order_must_be_buy_side(self):
        invalid_buy_order = self.create_order(
            user=self.buyer,
            market=self.market,
            outcome=self.outcome,
            side=MarketOrder.Side.SELL,
        )

        fill = self.build_fill(
            buy_order=invalid_buy_order,
            maker_order=self.sell_order,
            taker_order=invalid_buy_order,
        )

        with self.assertRaises(ValidationError) as context:
            fill.full_clean()

        self.assertIn(
            "buy_order",
            context.exception.message_dict,
        )

    def test_sell_order_must_be_sell_side(self):
        invalid_sell_order = self.create_order(
            user=self.seller,
            market=self.market,
            outcome=self.outcome,
            side=MarketOrder.Side.BUY,
        )

        fill = self.build_fill(
            sell_order=invalid_sell_order,
            maker_order=invalid_sell_order,
            taker_order=self.buy_order,
        )

        with self.assertRaises(ValidationError) as context:
            fill.full_clean()

        self.assertIn(
            "sell_order",
            context.exception.message_dict,
        )

    def test_market_and_outcome_must_match_orders(
        self,
    ):
        other_market = self.open_market(
            self.create_market(
                question=("Will Vipers SC score?"),
            )
        )
        other_outcome = other_market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        fill = self.build_fill(
            market=other_market,
            outcome=other_outcome,
        )

        with self.assertRaises(ValidationError) as context:
            fill.full_clean()

        self.assertIn(
            "market",
            context.exception.message_dict,
        )
        self.assertIn(
            "outcome",
            context.exception.message_dict,
        )

    def test_maker_and_taker_must_be_fill_orders(
        self,
    ):
        fill = self.build_fill(
            maker_order=self.buy_order,
            taker_order=self.buy_order,
        )

        with self.assertRaises(ValidationError) as context:
            fill.full_clean()

        self.assertIn(
            "taker_order",
            context.exception.message_dict,
        )

    def test_fill_quantity_must_be_positive(self):
        fill = self.build_fill(
            quantity=Decimal("0.0000"),
        )

        with self.assertRaises(ValidationError) as context:
            fill.full_clean()

        self.assertIn(
            "quantity",
            context.exception.message_dict,
        )

    def test_fill_price_must_be_between_zero_and_one(
        self,
    ):
        invalid_prices = [
            Decimal("0.00000"),
            Decimal("1.00000"),
        ]

        for invalid_price in invalid_prices:
            with self.subTest(price=invalid_price):
                fill = self.build_fill(
                    price=invalid_price,
                )

                with self.assertRaises(ValidationError) as context:
                    fill.full_clean()

                self.assertIn(
                    "price",
                    context.exception.message_dict,
                )

    def test_self_trade_is_rejected(self):
        self_sell_order = self.create_order(
            user=self.buyer,
            market=self.market,
            outcome=self.outcome,
            side=MarketOrder.Side.SELL,
        )

        fill = self.build_fill(
            sell_order=self_sell_order,
            maker_order=self_sell_order,
            taker_order=self.buy_order,
        )

        with self.assertRaises(ValidationError) as context:
            fill.full_clean()

        self.assertIn(
            "sell_order",
            context.exception.message_dict,
        )

    def test_existing_fill_cannot_be_updated(self):
        fill = self.create_fill()
        original_price = fill.price

        fill.price = Decimal("0.56000")

        with self.assertRaises(ValidationError):
            fill.save(
                update_fields=[
                    "price",
                    "updated_at",
                ]
            )

        fill.refresh_from_db()

        self.assertEqual(
            fill.price,
            original_price,
        )

    def test_existing_fill_cannot_be_deleted(self):
        fill = self.create_fill()

        with self.assertRaises(ValidationError):
            fill.delete()

        self.assertTrue(
            self.fill_model.objects.filter(
                id=fill.id,
            ).exists()
        )

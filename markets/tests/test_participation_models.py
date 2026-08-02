from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from authentication.tests.factories import UserFactory
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
from sports.models import (
    Competition,
    Sport,
    SportingEvent,
)


class ParticipationModelTestCase(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.user = UserFactory()

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

        self.market = self.create_market(question="Will KCCA FC win?")
        self.other_market = self.create_market(question="Will Vipers SC score?")

        self.outcome = self.market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )
        self.other_outcome = self.other_market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

    def create_market(self, *, question):
        return MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question=question,
            description="Match prediction market.",
            rules="Resolve using the official result.",
            resolution_source=("Official competition result"),
            resolution_criteria=("Use the verified final score."),
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=1),
            created_by=self.user,
            yes_label="Yes",
            no_label="No",
        )

    def valid_order(self, **overrides):
        values = {
            "user": self.user,
            "market": self.market,
            "outcome": self.outcome,
            "side": MarketOrder.Side.BUY,
            "quantity": Decimal("10.0000"),
            "limit_price": Decimal("0.55000"),
            "filled_quantity": Decimal("0.0000"),
            "status": MarketOrder.Status.PENDING,
        }
        values.update(overrides)

        return MarketOrder(**values)

    def valid_position(self, **overrides):
        values = {
            "user": self.user,
            "market": self.market,
            "outcome": self.outcome,
            "quantity": Decimal("10.0000"),
            "reserved_quantity": Decimal("0.0000"),
            "average_entry_price": Decimal("0.55000"),
            "total_cost": Decimal("5.5000"),
            "realized_pnl": Decimal("0.0000"),
        }
        values.update(overrides)

        return MarketPosition(**values)


class MarketOrderModelTests(ParticipationModelTestCase):
    def test_valid_order_passes_validation(self):
        order = self.valid_order()

        order.full_clean()

    def test_order_quantity_must_be_positive(self):
        order = self.valid_order(
            quantity=Decimal("0.0000"),
        )

        with self.assertRaises(ValidationError) as context:
            order.full_clean()

        self.assertIn(
            "quantity",
            context.exception.message_dict,
        )

    def test_order_limit_price_must_be_valid(self):
        order = self.valid_order(
            limit_price=Decimal("1.00000"),
        )

        with self.assertRaises(ValidationError) as context:
            order.full_clean()

        self.assertIn(
            "limit_price",
            context.exception.message_dict,
        )

    def test_order_outcome_must_belong_to_market(
        self,
    ):
        order = self.valid_order(
            outcome=self.other_outcome,
        )

        with self.assertRaises(ValidationError) as context:
            order.full_clean()

        self.assertIn(
            "outcome",
            context.exception.message_dict,
        )

    def test_filled_quantity_cannot_exceed_order(
        self,
    ):
        order = self.valid_order(
            quantity=Decimal("10.0000"),
            filled_quantity=Decimal("11.0000"),
        )

        with self.assertRaises(ValidationError) as context:
            order.full_clean()

        self.assertIn(
            "filled_quantity",
            context.exception.message_dict,
        )

    def test_database_rejects_zero_quantity(self):
        order = self.valid_order(
            quantity=Decimal("0.0000"),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketOrder.objects.create(
                    user=order.user,
                    market=order.market,
                    outcome=order.outcome,
                    side=order.side,
                    quantity=order.quantity,
                    limit_price=order.limit_price,
                    filled_quantity=(order.filled_quantity),
                    status=order.status,
                )

    def test_database_rejects_invalid_price(self):
        order = self.valid_order(
            limit_price=Decimal("1.00000"),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketOrder.objects.create(
                    user=order.user,
                    market=order.market,
                    outcome=order.outcome,
                    side=order.side,
                    quantity=order.quantity,
                    limit_price=order.limit_price,
                    filled_quantity=(order.filled_quantity),
                    status=order.status,
                )

    def test_database_rejects_excess_fill(self):
        order = self.valid_order(
            quantity=Decimal("10.0000"),
            filled_quantity=Decimal("11.0000"),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketOrder.objects.create(
                    user=order.user,
                    market=order.market,
                    outcome=order.outcome,
                    side=order.side,
                    quantity=order.quantity,
                    limit_price=order.limit_price,
                    filled_quantity=(order.filled_quantity),
                    status=order.status,
                )


class MarketPositionModelTests(ParticipationModelTestCase):
    def test_valid_position_passes_validation(self):
        position = self.valid_position()

        position.full_clean()

    def test_position_quantity_cannot_be_negative(
        self,
    ):
        position = self.valid_position(
            quantity=Decimal("-1.0000"),
        )

        with self.assertRaises(ValidationError) as context:
            position.full_clean()

        self.assertIn(
            "quantity",
            context.exception.message_dict,
        )

    def test_reserved_quantity_cannot_be_negative(self):
        position = self.valid_position(
            reserved_quantity=Decimal("-0.0001"),
        )

        with self.assertRaises(ValidationError) as context:
            position.full_clean()

        self.assertIn("reserved_quantity", context.exception.message_dict)

    def test_reserved_quantity_cannot_exceed_quantity(self):
        position = self.valid_position(
            quantity=Decimal("10.0000"),
            reserved_quantity=Decimal("10.0001"),
        )

        with self.assertRaises(ValidationError) as context:
            position.full_clean()

        self.assertIn("reserved_quantity", context.exception.message_dict)

    def test_quantity_cannot_be_reduced_below_reserved_quantity(self):
        position = self.valid_position(
            quantity=Decimal("4.9999"),
            reserved_quantity=Decimal("5.0000"),
        )

        with self.assertRaises(ValidationError) as context:
            position.full_clean()

        self.assertIn("quantity", context.exception.message_dict)

    def test_database_rejects_negative_reserved_quantity(self):
        position = self.valid_position()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketPosition.objects.create(
                    user=position.user,
                    market=position.market,
                    outcome=position.outcome,
                    quantity=position.quantity,
                    reserved_quantity=Decimal("-0.0001"),
                    average_entry_price=position.average_entry_price,
                    total_cost=position.total_cost,
                    realized_pnl=position.realized_pnl,
                )

    def test_database_rejects_reserved_quantity_above_quantity(self):
        position = self.valid_position()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketPosition.objects.create(
                    user=position.user,
                    market=position.market,
                    outcome=position.outcome,
                    quantity=position.quantity,
                    reserved_quantity=Decimal("10.0001"),
                    average_entry_price=position.average_entry_price,
                    total_cost=position.total_cost,
                    realized_pnl=position.realized_pnl,
                )

    def test_position_outcome_must_belong_to_market(
        self,
    ):
        position = self.valid_position(
            outcome=self.other_outcome,
        )

        with self.assertRaises(ValidationError) as context:
            position.full_clean()

        self.assertIn(
            "outcome",
            context.exception.message_dict,
        )

    def test_position_is_unique_per_user_market_outcome(
        self,
    ):
        MarketPosition.objects.create(
            user=self.user,
            market=self.market,
            outcome=self.outcome,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.55000"),
            total_cost=Decimal("5.5000"),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketPosition.objects.create(
                    user=self.user,
                    market=self.market,
                    outcome=self.outcome,
                    quantity=Decimal("5.0000"),
                    average_entry_price=Decimal("0.60000"),
                    total_cost=Decimal("3.0000"),
                )

    def test_database_rejects_negative_quantity(
        self,
    ):
        position = self.valid_position(
            quantity=Decimal("-1.0000"),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MarketPosition.objects.create(
                    user=position.user,
                    market=position.market,
                    outcome=position.outcome,
                    quantity=position.quantity,
                    average_entry_price=(position.average_entry_price),
                    total_cost=position.total_cost,
                    realized_pnl=(position.realized_pnl),
                )

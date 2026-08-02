from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
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
from sports.models import (
    Competition,
    Sport,
    SportingEvent,
)


class MarketFillServiceTests(TestCase):
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
        self.sell_order = self.create_order(
            user=self.seller,
            market=self.market,
            outcome=self.outcome,
            side=MarketOrder.Side.SELL,
            limit_price=Decimal("0.55000"),
        )

        self.seller_position = MarketPosition(
            user=self.seller,
            market=self.market,
            outcome=self.outcome,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.45000"),
            total_cost=Decimal("4.5000"),
            realized_pnl=Decimal("0.0000"),
        )
        self.seller_position.full_clean()
        self.seller_position.save()

    @property
    def fill_model(self):
        return apps.get_model(
            "markets",
            "MarketFill",
        )

    @property
    def fill_service(self):
        from markets.services.fill_service import (
            MarketFillService,
        )

        return MarketFillService

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

    def set_existing_fill_state(
        self,
        *,
        order,
        filled_quantity,
        average_fill_price,
    ):
        order.filled_quantity = filled_quantity
        order.average_fill_price = average_fill_price
        order.status = (
            MarketOrder.Status.FILLED
            if filled_quantity == order.quantity
            else MarketOrder.Status.PARTIALLY_FILLED
        )
        order.full_clean()
        order.save(
            update_fields=[
                "filled_quantity",
                "average_fill_price",
                "status",
                "updated_at",
            ]
        )

    def execute_fill(
        self,
        *,
        execution_reference=None,
        buy_order=None,
        sell_order=None,
        maker_order=None,
        taker_order=None,
        quantity=Decimal("4.0000"),
        price=Decimal("0.55000"),
    ):
        buy_order = buy_order or self.buy_order
        sell_order = sell_order or self.sell_order

        return self.fill_service.execute_fill(
            execution_reference=(execution_reference or uuid4()),
            buy_order_id=buy_order.id,
            sell_order_id=sell_order.id,
            maker_order_id=(maker_order.id if maker_order is not None else sell_order.id),
            taker_order_id=(taker_order.id if taker_order is not None else buy_order.id),
            quantity=quantity,
            price=price,
        )

    def assert_order_unchanged(self, order):
        order.refresh_from_db()

        self.assertEqual(
            order.filled_quantity,
            Decimal("0.0000"),
        )
        self.assertIsNone(
            order.average_fill_price,
        )
        self.assertEqual(
            order.status,
            MarketOrder.Status.OPEN,
        )

    def test_execute_fill_creates_record_and_partially_fills_orders(
        self,
    ):
        execution_reference = uuid4()

        fill = self.execute_fill(
            execution_reference=(execution_reference),
            quantity=Decimal("4.0000"),
            price=Decimal("0.55000"),
        )

        self.buy_order.refresh_from_db()
        self.sell_order.refresh_from_db()

        self.assertEqual(
            fill.execution_reference,
            execution_reference,
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

        for order in [
            self.buy_order,
            self.sell_order,
        ]:
            self.assertEqual(
                order.filled_quantity,
                Decimal("4.0000"),
            )
            self.assertEqual(
                order.average_fill_price,
                Decimal("0.55000"),
            )
            self.assertEqual(
                order.status,
                MarketOrder.Status.PARTIALLY_FILLED,
            )

    def test_execute_fill_marks_fully_consumed_orders_filled(
        self,
    ):
        buy_order = self.create_order(
            user=self.buyer,
            market=self.market,
            outcome=self.outcome,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("4.0000"),
            limit_price=Decimal("0.60000"),
        )
        sell_order = self.create_order(
            user=self.seller,
            market=self.market,
            outcome=self.outcome,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("4.0000"),
            limit_price=Decimal("0.55000"),
        )

        self.execute_fill(
            buy_order=buy_order,
            sell_order=sell_order,
            quantity=Decimal("4.0000"),
        )

        buy_order.refresh_from_db()
        sell_order.refresh_from_db()

        self.assertEqual(
            buy_order.status,
            MarketOrder.Status.FILLED,
        )
        self.assertEqual(
            sell_order.status,
            MarketOrder.Status.FILLED,
        )
        self.assertEqual(
            buy_order.filled_quantity,
            buy_order.quantity,
        )
        self.assertEqual(
            sell_order.filled_quantity,
            sell_order.quantity,
        )

    def test_execute_fill_updates_weighted_average_prices(
        self,
    ):
        self.set_existing_fill_state(
            order=self.buy_order,
            filled_quantity=Decimal("2.0000"),
            average_fill_price=Decimal("0.50000"),
        )
        self.set_existing_fill_state(
            order=self.sell_order,
            filled_quantity=Decimal("2.0000"),
            average_fill_price=Decimal("0.55000"),
        )

        self.execute_fill(
            quantity=Decimal("2.0000"),
            price=Decimal("0.60000"),
        )

        self.buy_order.refresh_from_db()
        self.sell_order.refresh_from_db()

        self.assertEqual(
            self.buy_order.filled_quantity,
            Decimal("4.0000"),
        )
        self.assertEqual(
            self.buy_order.average_fill_price,
            Decimal("0.55000"),
        )
        self.assertEqual(
            self.sell_order.filled_quantity,
            Decimal("4.0000"),
        )
        self.assertEqual(
            self.sell_order.average_fill_price,
            Decimal("0.57500"),
        )

    def test_fill_cannot_exceed_buy_remaining_quantity(
        self,
    ):
        self.set_existing_fill_state(
            order=self.buy_order,
            filled_quantity=Decimal("8.0000"),
            average_fill_price=Decimal("0.55000"),
        )

        with self.assertRaises(ValidationError) as context:
            self.execute_fill(
                quantity=Decimal("3.0000"),
            )

        self.assertIn(
            "quantity",
            context.exception.message_dict,
        )

        self.buy_order.refresh_from_db()
        self.sell_order.refresh_from_db()

        self.assertEqual(
            self.buy_order.filled_quantity,
            Decimal("8.0000"),
        )
        self.assertEqual(
            self.sell_order.filled_quantity,
            Decimal("0.0000"),
        )
        self.assertEqual(
            self.fill_model.objects.count(),
            0,
        )

    def test_fill_cannot_exceed_sell_remaining_quantity(
        self,
    ):
        self.set_existing_fill_state(
            order=self.sell_order,
            filled_quantity=Decimal("9.0000"),
            average_fill_price=Decimal("0.55000"),
        )

        with self.assertRaises(ValidationError) as context:
            self.execute_fill(
                quantity=Decimal("2.0000"),
            )

        self.assertIn(
            "quantity",
            context.exception.message_dict,
        )

        self.buy_order.refresh_from_db()
        self.sell_order.refresh_from_db()

        self.assertEqual(
            self.buy_order.filled_quantity,
            Decimal("0.0000"),
        )
        self.assertEqual(
            self.sell_order.filled_quantity,
            Decimal("9.0000"),
        )
        self.assertEqual(
            self.fill_model.objects.count(),
            0,
        )

    def test_fill_requires_open_or_partially_filled_orders(
        self,
    ):
        invalid_statuses = [
            MarketOrder.Status.CANCELLED,
            MarketOrder.Status.REJECTED,
            MarketOrder.Status.FILLED,
        ]

        for invalid_status in invalid_statuses:
            with self.subTest(status=invalid_status):
                buy_order = self.create_order(
                    user=self.buyer,
                    market=self.market,
                    outcome=self.outcome,
                    side=MarketOrder.Side.BUY,
                    quantity=Decimal("4.0000"),
                    limit_price=Decimal("0.60000"),
                )
                sell_order = self.create_order(
                    user=self.seller,
                    market=self.market,
                    outcome=self.outcome,
                    side=MarketOrder.Side.SELL,
                    quantity=Decimal("4.0000"),
                    limit_price=Decimal("0.55000"),
                )

                buy_order.status = invalid_status

                if invalid_status == MarketOrder.Status.FILLED:
                    buy_order.filled_quantity = buy_order.quantity
                    buy_order.average_fill_price = Decimal("0.55000")

                buy_order.full_clean()
                buy_order.save(
                    update_fields=[
                        "status",
                        "filled_quantity",
                        "average_fill_price",
                        "updated_at",
                    ]
                )

                with self.assertRaises(ValidationError) as context:
                    self.execute_fill(
                        buy_order=buy_order,
                        sell_order=sell_order,
                    )

                self.assertIn(
                    "status",
                    context.exception.message_dict,
                )

    def test_fill_requires_matching_market_and_outcome(
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
        other_sell_order = self.create_order(
            user=self.seller,
            market=other_market,
            outcome=other_outcome,
            side=MarketOrder.Side.SELL,
            limit_price=Decimal("0.55000"),
        )

        with self.assertRaises(ValidationError) as context:
            self.execute_fill(
                sell_order=other_sell_order,
            )

        self.assertIn(
            "market",
            context.exception.message_dict,
        )
        self.assertIn(
            "outcome",
            context.exception.message_dict,
        )

        self.assert_order_unchanged(self.buy_order)
        self.assert_order_unchanged(other_sell_order)

    def test_execution_price_must_respect_both_order_limits(
        self,
    ):
        invalid_prices = [
            Decimal("0.54000"),
            Decimal("0.61000"),
        ]

        for invalid_price in invalid_prices:
            with self.subTest(price=invalid_price):
                buy_order = self.create_order(
                    user=self.buyer,
                    market=self.market,
                    outcome=self.outcome,
                    side=MarketOrder.Side.BUY,
                    limit_price=Decimal("0.60000"),
                )
                sell_order = self.create_order(
                    user=self.seller,
                    market=self.market,
                    outcome=self.outcome,
                    side=MarketOrder.Side.SELL,
                    limit_price=Decimal("0.55000"),
                )

                with self.assertRaises(ValidationError) as context:
                    self.execute_fill(
                        buy_order=buy_order,
                        sell_order=sell_order,
                        price=invalid_price,
                    )

                self.assertIn(
                    "price",
                    context.exception.message_dict,
                )

                self.assert_order_unchanged(buy_order)
                self.assert_order_unchanged(sell_order)

    def test_maker_and_taker_must_be_distinct_fill_orders(
        self,
    ):
        with self.assertRaises(ValidationError) as context:
            self.execute_fill(
                maker_order=self.buy_order,
                taker_order=self.buy_order,
            )

        self.assertIn(
            "taker_order",
            context.exception.message_dict,
        )
        self.assert_order_unchanged(self.buy_order)
        self.assert_order_unchanged(self.sell_order)

    def test_self_trade_is_rejected_without_mutation(
        self,
    ):
        self_sell_order = self.create_order(
            user=self.buyer,
            market=self.market,
            outcome=self.outcome,
            side=MarketOrder.Side.SELL,
            limit_price=Decimal("0.55000"),
        )

        with self.assertRaises(ValidationError) as context:
            self.execute_fill(
                sell_order=self_sell_order,
            )

        self.assertIn(
            "sell_order",
            context.exception.message_dict,
        )
        self.assert_order_unchanged(self.buy_order)
        self.assert_order_unchanged(self_sell_order)
        self.assertEqual(
            self.fill_model.objects.count(),
            0,
        )

    def test_execution_reference_replay_is_idempotent(
        self,
    ):
        execution_reference = uuid4()

        first_fill = self.execute_fill(
            execution_reference=(execution_reference),
            quantity=Decimal("2.0000"),
        )
        second_fill = self.execute_fill(
            execution_reference=(execution_reference),
            quantity=Decimal("2.0000"),
        )

        self.buy_order.refresh_from_db()
        self.sell_order.refresh_from_db()

        self.assertEqual(
            second_fill.id,
            first_fill.id,
        )
        self.assertEqual(
            self.fill_model.objects.count(),
            1,
        )
        self.assertEqual(
            self.buy_order.filled_quantity,
            Decimal("2.0000"),
        )
        self.assertEqual(
            self.sell_order.filled_quantity,
            Decimal("2.0000"),
        )

    def test_conflicting_execution_reference_replay_is_rejected(
        self,
    ):
        execution_reference = uuid4()

        first_fill = self.execute_fill(
            execution_reference=(execution_reference),
            quantity=Decimal("2.0000"),
        )

        with self.assertRaises(ValidationError) as context:
            self.execute_fill(
                execution_reference=(execution_reference),
                quantity=Decimal("3.0000"),
            )

        self.assertIn(
            "execution_reference",
            context.exception.message_dict,
        )

        self.buy_order.refresh_from_db()
        self.sell_order.refresh_from_db()

        self.assertEqual(
            self.fill_model.objects.count(),
            1,
        )
        self.assertEqual(
            self.fill_model.objects.get().id,
            first_fill.id,
        )
        self.assertEqual(
            self.buy_order.filled_quantity,
            Decimal("2.0000"),
        )
        self.assertEqual(
            self.sell_order.filled_quantity,
            Decimal("2.0000"),
        )

    def test_fill_creation_failure_rolls_back_order_updates(
        self,
    ):
        with patch.object(
            self.fill_model,
            "save",
            side_effect=ValidationError({"fill": ("Synthetic fill failure.")}),
        ):
            with self.assertRaises(ValidationError):
                self.execute_fill()

        self.assert_order_unchanged(self.buy_order)
        self.assert_order_unchanged(self.sell_order)
        self.assertEqual(
            self.fill_model.objects.count(),
            0,
        )

    def test_fill_updates_position_accounting(
        self,
    ):
        self.execute_fill()

        buyer_position = MarketPosition.objects.get(
            user=self.buyer,
            market=self.market,
            outcome=self.outcome,
        )
        self.seller_position.refresh_from_db()

        self.assertEqual(
            MarketPosition.objects.count(),
            2,
        )
        self.assertEqual(
            buyer_position.quantity,
            Decimal("4.0000"),
        )
        self.assertEqual(
            self.seller_position.quantity,
            Decimal("6.0000"),
        )

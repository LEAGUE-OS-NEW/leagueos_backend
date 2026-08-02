from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

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
    MarketFill,
    MarketOrder,
    MarketOutcome,
    MarketPosition,
    MarketScope,
)
from markets.services.catalog_service import (
    MarketCatalogService,
)
from markets.services.fill_service import (
    MarketFillService,
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


class MarketPositionAccountingServiceTests(TestCase):
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

        self.market = self.open_market(self.create_market())
        self.outcome = self.market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        self.buy_order = self.create_order(
            user=self.buyer,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("10.0000"),
            limit_price=Decimal("0.70000"),
        )
        self.sell_order = None

    def create_market(self):
        return MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question="Will KCCA FC win?",
            description="Match prediction market.",
            rules=("Resolve using the official " "competition result."),
            resolution_source=("Official competition result"),
            resolution_criteria=("Use the verified final score."),
            status=Market.Status.DRAFT,
            opens_at=(self.now - timedelta(hours=1)),
            closes_at=(self.now + timedelta(hours=1)),
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
        side,
        quantity=Decimal("10.0000"),
        limit_price=Decimal("0.50000"),
    ):
        return MarketParticipationService.place_order(
            user=user,
            market_id=self.market.id,
            outcome_id=self.outcome.id,
            side=side,
            quantity=quantity,
            limit_price=limit_price,
        )

    def create_position(
        self,
        *,
        user,
        quantity,
        average_entry_price,
        total_cost,
        realized_pnl=Decimal("0.0000"),
    ):
        position = MarketPosition(
            user=user,
            market=self.market,
            outcome=self.outcome,
            quantity=quantity,
            average_entry_price=(average_entry_price),
            total_cost=total_cost,
            realized_pnl=realized_pnl,
        )
        position.full_clean()
        position.save()
        return position

    def execute_fill(
        self,
        *,
        execution_reference=None,
        buy_order=None,
        sell_order=None,
        quantity=Decimal("4.0000"),
        price=Decimal("0.60000"),
    ):
        buy_order = buy_order or self.buy_order
        sell_order = sell_order or self.sell_order
        if sell_order is None:
            seller_position = MarketPosition.objects.filter(
                user=self.seller,
                market=self.market,
                outcome=self.outcome,
            ).first()
            if seller_position is None:
                sell_order = MarketOrder.objects.create(
                    user=self.seller,
                    market=self.market,
                    outcome=self.outcome,
                    side=MarketOrder.Side.SELL,
                    quantity=Decimal("10.0000"),
                    limit_price=Decimal("0.40000"),
                    filled_quantity=Decimal("0.0000"),
                    status=MarketOrder.Status.OPEN,
                )
            else:
                sell_order = self.create_order(
                    user=self.seller,
                    side=MarketOrder.Side.SELL,
                    quantity=seller_position.quantity,
                    limit_price=Decimal("0.40000"),
                )
            self.sell_order = sell_order

        return MarketFillService.execute_fill(
            execution_reference=(execution_reference or uuid4()),
            buy_order_id=buy_order.id,
            sell_order_id=sell_order.id,
            maker_order_id=sell_order.id,
            taker_order_id=buy_order.id,
            quantity=quantity,
            price=price,
        )

    def get_position(self, user):
        return MarketPosition.objects.get(
            user=user,
            market=self.market,
            outcome=self.outcome,
        )

    def assert_order_open_and_unfilled(
        self,
        order,
    ):
        order.refresh_from_db()

        self.assertEqual(
            order.status,
            MarketOrder.Status.OPEN,
        )
        self.assertEqual(
            order.filled_quantity,
            Decimal("0.0000"),
        )
        self.assertIsNone(
            order.average_fill_price,
        )

    def test_buy_fill_creates_buyer_position(
        self,
    ):
        self.create_position(
            user=self.seller,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.45000"),
            total_cost=Decimal("4.5000"),
        )

        self.execute_fill(
            quantity=Decimal("4.0000"),
            price=Decimal("0.60000"),
        )

        buyer_position = self.get_position(self.buyer)

        self.assertEqual(
            buyer_position.quantity,
            Decimal("4.0000"),
        )
        self.assertEqual(
            buyer_position.average_entry_price,
            Decimal("0.60000"),
        )
        self.assertEqual(
            buyer_position.total_cost,
            Decimal("2.4000"),
        )
        self.assertEqual(
            buyer_position.realized_pnl,
            Decimal("0.0000"),
        )

    def test_buy_fill_updates_existing_position_weighted_average(
        self,
    ):
        self.create_position(
            user=self.buyer,
            quantity=Decimal("2.0000"),
            average_entry_price=Decimal("0.50000"),
            total_cost=Decimal("1.0000"),
        )
        self.create_position(
            user=self.seller,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.45000"),
            total_cost=Decimal("4.5000"),
        )

        self.execute_fill(
            quantity=Decimal("2.0000"),
            price=Decimal("0.60000"),
        )

        buyer_position = self.get_position(self.buyer)

        self.assertEqual(
            buyer_position.quantity,
            Decimal("4.0000"),
        )
        self.assertEqual(
            buyer_position.total_cost,
            Decimal("2.2000"),
        )
        self.assertEqual(
            buyer_position.average_entry_price,
            Decimal("0.55000"),
        )
        self.assertEqual(
            buyer_position.realized_pnl,
            Decimal("0.0000"),
        )

    def test_partial_sell_reduces_quantity_and_cost_basis_proportionally(
        self,
    ):
        self.create_position(
            user=self.seller,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("4.0000"),
        )

        self.execute_fill(
            quantity=Decimal("4.0000"),
            price=Decimal("0.60000"),
        )

        seller_position = self.get_position(self.seller)

        self.assertEqual(
            seller_position.quantity,
            Decimal("6.0000"),
        )
        self.assertEqual(
            seller_position.total_cost,
            Decimal("2.4000"),
        )
        self.assertEqual(
            seller_position.average_entry_price,
            Decimal("0.40000"),
        )

    def test_profitable_sell_increases_realized_pnl(
        self,
    ):
        self.create_position(
            user=self.seller,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("4.0000"),
            realized_pnl=Decimal("0.5000"),
        )

        self.execute_fill(
            quantity=Decimal("4.0000"),
            price=Decimal("0.60000"),
        )

        seller_position = self.get_position(self.seller)

        # Proceeds: 4 × 0.60 = 2.40
        # Released cost: 4 × 0.40 = 1.60
        # New realized P&L: 0.50 + 0.80
        self.assertEqual(
            seller_position.realized_pnl,
            Decimal("1.3000"),
        )

    def test_loss_making_sell_reduces_realized_pnl(
        self,
    ):
        self.create_position(
            user=self.seller,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.65000"),
            total_cost=Decimal("6.5000"),
            realized_pnl=Decimal("0.2000"),
        )

        self.execute_fill(
            quantity=Decimal("4.0000"),
            price=Decimal("0.50000"),
        )

        seller_position = self.get_position(self.seller)

        # Proceeds: 4 × 0.50 = 2.00
        # Released cost: 4 × 0.65 = 2.60
        # New realized P&L: 0.20 - 0.60
        self.assertEqual(
            seller_position.realized_pnl,
            Decimal("-0.4000"),
        )
        self.assertEqual(
            seller_position.quantity,
            Decimal("6.0000"),
        )
        self.assertEqual(
            seller_position.total_cost,
            Decimal("3.9000"),
        )

    def test_full_sell_closes_position_without_deleting_it(
        self,
    ):
        seller_position = self.create_position(
            user=self.seller,
            quantity=Decimal("4.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("1.6000"),
        )

        sell_order = self.create_order(
            user=self.seller,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("4.0000"),
            limit_price=Decimal("0.40000"),
        )
        buy_order = self.create_order(
            user=self.buyer,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("4.0000"),
            limit_price=Decimal("0.70000"),
        )

        self.execute_fill(
            buy_order=buy_order,
            sell_order=sell_order,
            quantity=Decimal("4.0000"),
            price=Decimal("0.60000"),
        )

        seller_position.refresh_from_db()

        self.assertEqual(
            seller_position.quantity,
            Decimal("0.0000"),
        )
        self.assertEqual(
            seller_position.total_cost,
            Decimal("0.0000"),
        )
        self.assertEqual(
            seller_position.average_entry_price,
            Decimal("0.00000"),
        )
        self.assertEqual(
            seller_position.realized_pnl,
            Decimal("0.8000"),
        )
        self.assertTrue(
            MarketPosition.objects.filter(
                id=seller_position.id,
            ).exists()
        )

    def test_sell_without_position_is_rejected(
        self,
    ):
        with self.assertRaises(ValidationError) as context:
            self.execute_fill()

        self.assertIn(
            "position",
            context.exception.message_dict,
        )
        self.assertEqual(
            MarketFill.objects.count(),
            0,
        )
        self.assertEqual(
            MarketPosition.objects.count(),
            0,
        )
        self.assert_order_open_and_unfilled(self.buy_order)
        self.assert_order_open_and_unfilled(self.sell_order)

    def test_sell_cannot_exceed_position_quantity(
        self,
    ):
        seller_position = self.create_position(
            user=self.seller,
            quantity=Decimal("3.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("1.2000"),
        )
        self.sell_order = MarketOrder.objects.create(
            user=self.seller,
            market=self.market,
            outcome=self.outcome,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("10.0000"),
            limit_price=Decimal("0.40000"),
            filled_quantity=Decimal("0.0000"),
            status=MarketOrder.Status.OPEN,
        )

        with self.assertRaises(ValidationError) as context:
            self.execute_fill(
                quantity=Decimal("4.0000"),
            )

        self.assertIn(
            "position",
            context.exception.message_dict,
        )

        seller_position.refresh_from_db()

        self.assertEqual(
            seller_position.quantity,
            Decimal("3.0000"),
        )
        self.assertEqual(
            seller_position.total_cost,
            Decimal("1.2000"),
        )
        self.assertEqual(
            seller_position.realized_pnl,
            Decimal("0.0000"),
        )
        self.assertEqual(
            MarketFill.objects.count(),
            0,
        )
        self.assert_order_open_and_unfilled(self.buy_order)
        self.assert_order_open_and_unfilled(self.sell_order)

    def test_execution_replay_does_not_apply_positions_twice(
        self,
    ):
        execution_reference = uuid4()

        self.create_position(
            user=self.seller,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("4.0000"),
        )

        first_fill = self.execute_fill(
            execution_reference=(execution_reference),
            quantity=Decimal("2.0000"),
            price=Decimal("0.60000"),
        )
        second_fill = self.execute_fill(
            execution_reference=(execution_reference),
            quantity=Decimal("2.0000"),
            price=Decimal("0.60000"),
        )

        buyer_position = self.get_position(self.buyer)
        seller_position = self.get_position(self.seller)

        self.assertEqual(
            second_fill.id,
            first_fill.id,
        )
        self.assertEqual(
            MarketFill.objects.count(),
            1,
        )
        self.assertEqual(
            buyer_position.quantity,
            Decimal("2.0000"),
        )
        self.assertEqual(
            buyer_position.total_cost,
            Decimal("1.2000"),
        )
        self.assertEqual(
            seller_position.quantity,
            Decimal("8.0000"),
        )
        self.assertEqual(
            seller_position.total_cost,
            Decimal("3.2000"),
        )
        self.assertEqual(
            seller_position.realized_pnl,
            Decimal("0.4000"),
        )

    def test_sequential_buys_accumulate_one_position(
        self,
    ):
        self.create_position(
            user=self.seller,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("4.0000"),
        )

        first_buy_order = self.buy_order

        self.execute_fill(
            buy_order=first_buy_order,
            quantity=Decimal("2.0000"),
            price=Decimal("0.50000"),
        )
        first_sell_order = self.sell_order

        MarketParticipationService.cancel_order(
            user=self.seller,
            order_id=first_sell_order.id,
        )

        second_buy_order = self.create_order(
            user=self.buyer,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("3.0000"),
            limit_price=Decimal("0.70000"),
        )
        second_sell_order = self.create_order(
            user=self.seller,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("3.0000"),
            limit_price=Decimal("0.40000"),
        )

        self.execute_fill(
            buy_order=second_buy_order,
            sell_order=second_sell_order,
            quantity=Decimal("3.0000"),
            price=Decimal("0.60000"),
        )

        buyer_positions = MarketPosition.objects.filter(
            user=self.buyer,
            market=self.market,
            outcome=self.outcome,
        )
        buyer_position = buyer_positions.get()

        self.assertEqual(
            buyer_positions.count(),
            1,
        )
        self.assertEqual(
            buyer_position.quantity,
            Decimal("5.0000"),
        )
        self.assertEqual(
            buyer_position.total_cost,
            Decimal("2.8000"),
        )
        self.assertEqual(
            buyer_position.average_entry_price,
            Decimal("0.56000"),
        )

    def test_position_failure_rolls_back_fill_orders_and_positions(
        self,
    ):
        seller_position = self.create_position(
            user=self.seller,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("4.0000"),
        )

        original_save = MarketPosition.save

        def failing_save(
            position,
            *args,
            **kwargs,
        ):
            if position.user_id == self.buyer.id:
                raise ValidationError({"position": ("Synthetic position " "failure.")})

            return original_save(
                position,
                *args,
                **kwargs,
            )

        with patch.object(
            MarketPosition,
            "save",
            new=failing_save,
        ):
            with self.assertRaises(ValidationError):
                self.execute_fill()

        seller_position.refresh_from_db()

        self.assertEqual(
            seller_position.quantity,
            Decimal("10.0000"),
        )
        self.assertEqual(
            seller_position.total_cost,
            Decimal("4.0000"),
        )
        self.assertEqual(
            seller_position.realized_pnl,
            Decimal("0.0000"),
        )
        self.assertFalse(
            MarketPosition.objects.filter(
                user=self.buyer,
                market=self.market,
                outcome=self.outcome,
            ).exists()
        )
        self.assertEqual(
            MarketFill.objects.count(),
            0,
        )
        self.assert_order_open_and_unfilled(self.buy_order)
        self.assert_order_open_and_unfilled(self.sell_order)

    def test_existing_realized_pnl_is_preserved_for_buyer(
        self,
    ):
        buyer_position = self.create_position(
            user=self.buyer,
            quantity=Decimal("2.0000"),
            average_entry_price=Decimal("0.50000"),
            total_cost=Decimal("1.0000"),
            realized_pnl=Decimal("1.2500"),
        )
        self.create_position(
            user=self.seller,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("4.0000"),
        )

        self.execute_fill(
            quantity=Decimal("2.0000"),
            price=Decimal("0.60000"),
        )

        buyer_position.refresh_from_db()

        self.assertEqual(
            buyer_position.realized_pnl,
            Decimal("1.2500"),
        )
        self.assertEqual(
            buyer_position.quantity,
            Decimal("4.0000"),
        )
        self.assertEqual(
            buyer_position.total_cost,
            Decimal("2.2000"),
        )

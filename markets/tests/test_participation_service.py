from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

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
from wallets.models import (
    LedgerEntry,
    Wallet,
)
from wallets.services.wallet_service import (
    WalletService,
)


class MarketParticipationServiceTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

        self.manage_permission = PermissionFactory(
            name="manage_market",
            resource="market",
            action="manage",
        )
        self.approve_permission = PermissionFactory(
            name="approve_market",
            resource="market",
            action="approve",
        )
        self.participate_permission = PermissionFactory(
            name="participate_market",
            resource="market",
            action="participate",
        )

        self.operations_role = RoleFactory(
            name="Market Operations Admin",
            display_name="Market Operations Admin",
        )
        self.approval_role = RoleFactory(
            name="Market Approval Admin",
            display_name="Market Approval Admin",
        )
        self.participant_role = RoleFactory(
            name="Verified Market User",
            display_name="Verified Market User",
        )

        RolePermissionFactory(
            role=self.operations_role,
            permission=self.manage_permission,
        )
        RolePermissionFactory(
            role=self.approval_role,
            permission=self.approve_permission,
        )
        RolePermissionFactory(
            role=self.participant_role,
            permission=self.participate_permission,
        )

        self.operations_user = UserFactory()
        self.approver_user = UserFactory()
        self.participant = UserFactory(
            is_verified=True,
        )
        self.unverified_participant = UserFactory(
            is_verified=False,
        )
        self.outsider = UserFactory(
            is_verified=True,
        )

        UserRoleFactory(
            user=self.operations_user,
            role=self.operations_role,
        )
        UserRoleFactory(
            user=self.approver_user,
            role=self.approval_role,
        )
        UserRoleFactory(
            user=self.participant,
            role=self.participant_role,
        )
        UserRoleFactory(
            user=self.unverified_participant,
            role=self.participant_role,
        )

        self.wallet = Wallet.objects.create(
            user=self.participant,
            currency="UGX",
            available_balance=Decimal("100.0000"),
            reserved_balance=Decimal("0.0000"),
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

    def create_market(
        self,
        *,
        question="Will KCCA FC win?",
        opens_at=None,
        closes_at=None,
    ):
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
            opens_at=(opens_at or self.now - timedelta(hours=1)),
            closes_at=(closes_at or self.now + timedelta(hours=1)),
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

    def place_order(
        self,
        *,
        user=None,
        market=None,
        outcome=None,
        side=MarketOrder.Side.BUY,
        quantity=Decimal("10.0000"),
        limit_price=Decimal("0.55000"),
    ):
        market = market or self.open_market(self.create_market())
        outcome = outcome or market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        return MarketParticipationService.place_order(
            user=user or self.participant,
            market_id=market.id,
            outcome_id=outcome.id,
            side=side,
            quantity=quantity,
            limit_price=limit_price,
        )

    def test_verified_user_can_place_order(self):
        market = self.open_market(self.create_market())
        outcome = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        order = self.place_order(
            market=market,
            outcome=outcome,
        )

        self.assertEqual(
            order.user,
            self.participant,
        )
        self.assertEqual(
            order.market,
            market,
        )
        self.assertEqual(
            order.outcome,
            outcome,
        )
        self.assertEqual(
            order.side,
            MarketOrder.Side.BUY,
        )
        self.assertEqual(
            order.quantity,
            Decimal("10.0000"),
        )
        self.assertEqual(
            order.limit_price,
            Decimal("0.55000"),
        )
        self.assertEqual(
            order.status,
            MarketOrder.Status.OPEN,
        )
        self.assertEqual(
            order.filled_quantity,
            Decimal("0"),
        )
        self.assertIsNone(
            order.average_fill_price,
        )

    def test_place_order_requires_permission(self):
        market = self.open_market(self.create_market())

        with self.assertRaises(PermissionDenied):
            self.place_order(
                user=self.outsider,
                market=market,
            )

        self.assertFalse(
            MarketOrder.objects.filter(
                user=self.outsider,
            ).exists()
        )

    def test_place_order_requires_verified_user(
        self,
    ):
        market = self.open_market(self.create_market())

        with self.assertRaises(PermissionDenied):
            self.place_order(
                user=self.unverified_participant,
                market=market,
            )

        self.assertFalse(
            MarketOrder.objects.filter(
                user=self.unverified_participant,
            ).exists()
        )

    def test_place_order_requires_open_market(self):
        market = self.create_market()

        with self.assertRaises(ValidationError) as context:
            self.place_order(
                market=market,
            )

        self.assertIn(
            "status",
            context.exception.message_dict,
        )

    def test_place_order_rejects_closed_market(self):
        market = self.open_market(self.create_market())
        market = MarketLifecycleService.close(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading completed.",
        )

        with self.assertRaises(ValidationError) as context:
            self.place_order(
                market=market,
            )

        self.assertIn(
            "status",
            context.exception.message_dict,
        )

    def test_place_order_rejects_expired_window(self):
        market = self.open_market(self.create_market())
        market.closes_at = timezone.now() - timedelta(minutes=1)
        market.save(
            update_fields=[
                "closes_at",
                "updated_at",
            ]
        )

        with self.assertRaises(ValidationError) as context:
            self.place_order(
                market=market,
            )

        self.assertIn(
            "closes_at",
            context.exception.message_dict,
        )

    def test_outcome_must_belong_to_market(self):
        market = self.open_market(self.create_market(question="Will KCCA FC win?"))
        other_market = self.open_market(self.create_market(question="Will Vipers SC score?"))
        other_outcome = other_market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        with self.assertRaises(ValidationError) as context:
            self.place_order(
                market=market,
                outcome=other_outcome,
            )

        self.assertIn(
            "outcome",
            context.exception.message_dict,
        )

    def test_quantity_must_be_positive(self):
        with self.assertRaises(ValidationError) as context:
            self.place_order(
                quantity=Decimal("0.0000"),
            )

        self.assertIn(
            "quantity",
            context.exception.message_dict,
        )

    def test_limit_price_must_be_valid(self):
        with self.assertRaises(ValidationError) as context:
            self.place_order(
                limit_price=Decimal("1.00000"),
            )

        self.assertIn(
            "limit_price",
            context.exception.message_dict,
        )

    def test_sell_order_can_be_accepted(self):
        market = self.open_market(self.create_market())
        outcome = market.outcomes.get(side=MarketOutcome.Side.YES)
        position = MarketPosition.objects.create(
            user=self.participant,
            market=market,
            outcome=outcome,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("4.0000"),
        )
        order = self.place_order(
            market=market,
            outcome=outcome,
            side=MarketOrder.Side.SELL,
        )

        self.assertEqual(
            order.side,
            MarketOrder.Side.SELL,
        )
        position.refresh_from_db()
        self.assertEqual(position.reserved_quantity, Decimal("10.0000"))

    def test_sell_order_leaves_wallet_balances_unchanged(self):
        market = self.open_market(self.create_market())
        outcome = market.outcomes.get(side=MarketOutcome.Side.YES)
        MarketPosition.objects.create(
            user=self.participant,
            market=market,
            outcome=outcome,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("4.0000"),
        )

        self.place_order(market=market, outcome=outcome, side=MarketOrder.Side.SELL)

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.available_balance, Decimal("100.0000"))
        self.assertEqual(self.wallet.reserved_balance, Decimal("0.0000"))
        self.assertFalse(LedgerEntry.objects.filter(wallet=self.wallet).exists())

    def test_sell_order_without_position_is_rejected(self):
        market = self.open_market(self.create_market())

        with self.assertRaises(ValidationError) as context:
            self.place_order(market=market, side=MarketOrder.Side.SELL)

        self.assertIn("position", context.exception.message_dict)
        self.assertFalse(MarketOrder.objects.filter(market=market).exists())

    def test_sell_order_cannot_exceed_available_quantity(self):
        market = self.open_market(self.create_market())
        outcome = market.outcomes.get(side=MarketOutcome.Side.YES)
        position = MarketPosition.objects.create(
            user=self.participant,
            market=market,
            outcome=outcome,
            quantity=Decimal("10.0000"),
            reserved_quantity=Decimal("4.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("4.0000"),
        )

        with self.assertRaises(ValidationError) as context:
            self.place_order(
                market=market,
                outcome=outcome,
                side=MarketOrder.Side.SELL,
                quantity=Decimal("6.0001"),
            )

        self.assertIn("quantity", context.exception.message_dict)
        position.refresh_from_db()
        self.assertEqual(position.reserved_quantity, Decimal("4.0000"))

    def test_sell_order_exactly_equal_to_available_quantity_succeeds(self):
        market = self.open_market(self.create_market())
        outcome = market.outcomes.get(side=MarketOutcome.Side.YES)
        position = MarketPosition.objects.create(
            user=self.participant,
            market=market,
            outcome=outcome,
            quantity=Decimal("10.0000"),
            reserved_quantity=Decimal("4.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("4.0000"),
        )

        self.place_order(
            market=market, outcome=outcome, side=MarketOrder.Side.SELL, quantity=Decimal("6.0000")
        )

        position.refresh_from_db()
        self.assertEqual(position.reserved_quantity, Decimal("10.0000"))

    def test_multiple_sell_orders_cannot_over_reserve_position(self):
        market = self.open_market(self.create_market())
        outcome = market.outcomes.get(side=MarketOutcome.Side.YES)
        position = MarketPosition.objects.create(
            user=self.participant,
            market=market,
            outcome=outcome,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("4.0000"),
        )
        self.place_order(
            market=market, outcome=outcome, side=MarketOrder.Side.SELL, quantity=Decimal("6.0000")
        )

        with self.assertRaises(ValidationError):
            self.place_order(
                market=market,
                outcome=outcome,
                side=MarketOrder.Side.SELL,
                quantity=Decimal("4.0001"),
            )

        position.refresh_from_db()
        self.assertEqual(position.reserved_quantity, Decimal("6.0000"))
        self.assertEqual(MarketOrder.objects.filter(market=market).count(), 1)

    def test_sell_order_creation_failure_rolls_back_reservation(self):
        market = self.open_market(self.create_market())
        outcome = market.outcomes.get(side=MarketOutcome.Side.YES)
        position = MarketPosition.objects.create(
            user=self.participant,
            market=market,
            outcome=outcome,
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("4.0000"),
        )

        with patch.object(MarketOrder, "save", side_effect=RuntimeError("Order failed.")):
            with self.assertRaises(RuntimeError):
                self.place_order(market=market, outcome=outcome, side=MarketOrder.Side.SELL)

        position.refresh_from_db()
        self.assertEqual(position.reserved_quantity, Decimal("0.0000"))
        self.assertFalse(MarketOrder.objects.filter(market=market).exists())

    def test_order_does_not_create_position(self):
        self.place_order()

        self.assertFalse(self.participant.market_positions.exists())

    def test_buy_order_reserves_maximum_limit_cost(
        self,
    ):
        market = self.open_market(self.create_market())
        outcome = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        self.place_order(
            market=market,
            outcome=outcome,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("10.0000"),
            limit_price=Decimal("0.55000"),
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("94.5000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("5.5000"),
        )

    def test_buy_reservation_creates_order_linked_ledger_entry(
        self,
    ):
        market = self.open_market(self.create_market())
        outcome = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        order = self.place_order(
            market=market,
            outcome=outcome,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("10.0000"),
            limit_price=Decimal("0.55000"),
        )

        entry = LedgerEntry.objects.get(
            order=order,
        )

        self.assertEqual(
            entry.wallet_id,
            self.wallet.id,
        )
        self.assertEqual(
            entry.market_id,
            market.id,
        )
        self.assertEqual(
            entry.entry_type,
            LedgerEntry.EntryType.RESERVE,
        )
        self.assertEqual(
            entry.amount,
            Decimal("5.5000"),
        )
        self.assertEqual(
            entry.available_balance_before,
            Decimal("100.0000"),
        )
        self.assertEqual(
            entry.available_balance_after,
            Decimal("94.5000"),
        )
        self.assertEqual(
            entry.reserved_balance_before,
            Decimal("0.0000"),
        )
        self.assertEqual(
            entry.reserved_balance_after,
            Decimal("5.5000"),
        )

    def test_buy_order_rejects_insufficient_wallet_balance(
        self,
    ):
        self.wallet.available_balance = Decimal("5.4999")
        self.wallet.save(
            update_fields=[
                "available_balance",
                "updated_at",
            ]
        )

        market = self.open_market(self.create_market())
        outcome = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        with self.assertRaises(ValidationError) as context:
            self.place_order(
                market=market,
                outcome=outcome,
                side=MarketOrder.Side.BUY,
                quantity=Decimal("10.0000"),
                limit_price=Decimal("0.55000"),
            )

        self.assertIn(
            "available_balance",
            context.exception.message_dict,
        )
        self.assertFalse(
            MarketOrder.objects.filter(
                user=self.participant,
                market=market,
            ).exists()
        )
        self.assertFalse(
            LedgerEntry.objects.filter(
                wallet=self.wallet,
            ).exists()
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("5.4999"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("0.0000"),
        )

    def test_buy_order_requires_wallet(
        self,
    ):
        self.wallet.delete()

        market = self.open_market(self.create_market())
        outcome = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        with self.assertRaises(ValidationError) as context:
            self.place_order(
                market=market,
                outcome=outcome,
                side=MarketOrder.Side.BUY,
                quantity=Decimal("10.0000"),
                limit_price=Decimal("0.55000"),
            )

        self.assertIn(
            "wallet",
            context.exception.message_dict,
        )
        self.assertFalse(
            MarketOrder.objects.filter(
                user=self.participant,
                market=market,
            ).exists()
        )
        self.assertEqual(
            LedgerEntry.objects.count(),
            0,
        )

    def test_buy_reservation_rounds_up_to_wallet_precision(
        self,
    ):
        market = self.open_market(self.create_market())
        outcome = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        order = self.place_order(
            market=market,
            outcome=outcome,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("3.0000"),
            limit_price=Decimal("0.33333"),
        )

        entry = LedgerEntry.objects.get(
            order=order,
        )

        self.assertEqual(
            entry.amount,
            Decimal("1.0000"),
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("99.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("1.0000"),
        )

    def test_reservation_failure_rolls_back_order_creation(
        self,
    ):
        market = self.open_market(self.create_market())
        outcome = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        with patch.object(
            WalletService,
            "reserve",
            side_effect=RuntimeError("Wallet reservation failed."),
        ):
            with self.assertRaises(RuntimeError):
                self.place_order(
                    market=market,
                    outcome=outcome,
                    side=MarketOrder.Side.BUY,
                    quantity=Decimal("10.0000"),
                    limit_price=Decimal("0.55000"),
                )

        self.assertFalse(
            MarketOrder.objects.filter(
                user=self.participant,
                market=market,
            ).exists()
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("100.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("0.0000"),
        )

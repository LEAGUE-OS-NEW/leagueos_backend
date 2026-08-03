from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
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
    MarketCloseCleanup,
    MarketCloseOrderCancellation,
    MarketFill,
    MarketOrder,
    MarketOutcome,
    MarketPosition,
    MarketStatusTransition,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.matching_service import MarketMatchingService
from markets.services.participation_service import MarketParticipationService
from markets.tests.eligibility_test_support import make_market_eligible
from sports.models import Competition, Sport, SportingEvent
from wallets.models import LedgerEntry, Wallet
from wallets.services.wallet_service import WalletService


class MarketCloseCleanupFixtureMixin:
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        approve = PermissionFactory(name="approve_market", resource="market", action="approve")
        participate = PermissionFactory(
            name="participate_market", resource="market", action="participate"
        )
        manage = PermissionFactory(name="manage_market", resource="market", action="manage")
        approval_role = RoleFactory(name="Close Cleanup Admin", display_name="Close Cleanup Admin")
        participant_role = RoleFactory(
            name="Close Cleanup Trader", display_name="Close Cleanup Trader"
        )
        operations_role = RoleFactory(name="Close Cleanup Ops", display_name="Close Cleanup Ops")
        RolePermissionFactory(role=approval_role, permission=approve)
        RolePermissionFactory(role=participant_role, permission=participate)
        RolePermissionFactory(role=operations_role, permission=manage)
        self.actor = UserFactory()
        self.creator = UserFactory()
        self.buyer = UserFactory(is_verified=True)
        self.seller = UserFactory(is_verified=True)
        make_market_eligible(self.buyer)
        make_market_eligible(self.seller)
        UserRoleFactory(user=self.actor, role=approval_role)
        UserRoleFactory(user=self.creator, role=operations_role)
        UserRoleFactory(user=self.buyer, role=participant_role)
        UserRoleFactory(user=self.seller, role=participant_role)
        self.sport = Sport.objects.create(name="Football", code="FOOTBALL")
        self.category = MarketCategory.objects.create(name="Close cleanup")
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
            name="KCCA v Vipers",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

    def create_open_market(self):
        market = MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type="EVENT",
            sporting_event=self.event,
            question="Will KCCA win?",
            description="Close cleanup test.",
            rules="Official result applies.",
            resolution_source="Official result",
            resolution_criteria="Use final result.",
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=1),
            created_by=self.creator,
            yes_label="Yes",
            no_label="No",
        )
        MarketLifecycleService.submit(market_id=market.id, actor=self.creator, notes="Ready")
        MarketLifecycleService.approve(market_id=market.id, actor=self.actor, notes="Approved")
        return MarketLifecycleService.open(market_id=market.id, actor=self.actor, notes="Open")

    def reserve_buy(self, market, *, quantity="3.0000", price="0.33333"):
        WalletService.credit(
            user=self.buyer,
            currency="UGX",
            amount=Decimal("20.0000"),
            idempotency_reference=UUID("f617c068-b45f-45e1-b0e3-73f74e399762"),
        )
        outcome = market.outcomes.get(side=MarketOutcome.Side.YES)
        with patch.object(MarketParticipationService, "_require_active_trading_window"):
            with patch(
                "markets.services.participation_service.MarketMatchingService.match_order",
                return_value=[],
            ):
                return MarketParticipationService.place_order(
                    user=self.buyer,
                    market_id=market.id,
                    outcome_id=outcome.id,
                    side=MarketOrder.Side.BUY,
                    quantity=Decimal(quantity),
                    limit_price=Decimal(price),
                )

    def reserve_sell(self, market, *, quantity="3.0000"):
        outcome = market.outcomes.get(side=MarketOutcome.Side.YES)
        position = MarketPosition.objects.create(
            user=self.seller,
            market=market,
            outcome=outcome,
            quantity=Decimal("5.0000"),
            reserved_quantity=Decimal("0.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("2.0000"),
            realized_pnl=Decimal("0.7500"),
        )
        with patch(
            "markets.services.participation_service.MarketMatchingService.match_order",
            return_value=[],
        ):
            order = MarketParticipationService.place_order(
                user=self.seller,
                market_id=market.id,
                outcome_id=outcome.id,
                side=MarketOrder.Side.SELL,
                quantity=Decimal(quantity),
                limit_price=Decimal("0.60000"),
            )
        return order, position


class MarketCloseCleanupModelTests(MarketCloseCleanupFixtureMixin, TestCase):
    def test_cleanup_records_are_unique_and_immutable(self):
        market = self.create_open_market()
        order = self.reserve_buy(market)
        cleanup = MarketCloseCleanup.objects.create(market=market, executed_by=self.actor)
        record = MarketCloseOrderCancellation.objects.create(
            market_close_cleanup=cleanup,
            market_order=order,
            order_side=order.side,
            remaining_quantity_cancelled=order.quantity,
        )
        for audit in (cleanup, record):
            with self.assertRaises(ValidationError):
                audit.save()
            with self.assertRaises(ValidationError):
                audit.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            MarketCloseCleanup.objects.create(market=market, executed_by=self.actor)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MarketCloseOrderCancellation.objects.create(
                market_close_cleanup=cleanup,
                market_order=order,
                order_side=order.side,
                remaining_quantity_cancelled=order.quantity,
            )


class MarketCloseCleanupServiceTests(MarketCloseCleanupFixtureMixin, TestCase):
    def test_order_placement_after_closes_at_is_rejected(self):
        market = self.create_open_market()
        Market.objects.filter(pk=market.pk).update(closes_at=self.now - timedelta(seconds=1))
        outcome = market.outcomes.get(side=MarketOutcome.Side.YES)
        with self.assertRaises(ValidationError) as error:
            MarketParticipationService.place_order(
                user=self.buyer,
                market_id=market.id,
                outcome_id=outcome.id,
                side=MarketOrder.Side.BUY,
                quantity=Decimal("1.0000"),
                limit_price=Decimal("0.50000"),
            )
        self.assertIn("closes_at", error.exception.message_dict)
        self.assertFalse(MarketOrder.objects.filter(market=market).exists())

    def test_matching_after_closes_at_skips_existing_orders(self):
        market = self.create_open_market()
        buy = self.reserve_buy(market, quantity="1.0000", price="0.60000")
        sell, _ = self.reserve_sell(market, quantity="1.0000")
        Market.objects.filter(pk=market.pk).update(closes_at=self.now - timedelta(seconds=1))
        fills = MarketMatchingService.match_order(buy.id)
        buy.refresh_from_db()
        sell.refresh_from_db()
        self.assertEqual(fills, [])
        self.assertEqual(buy.status, MarketOrder.Status.OPEN)
        self.assertEqual(sell.status, MarketOrder.Status.OPEN)
        self.assertFalse(MarketFill.objects.filter(buy_order__market=market).exists())

    def test_close_cancels_buy_and_sell_remainders_and_reconciles(self):
        market = self.create_open_market()
        buy = self.reserve_buy(market)
        MarketOrder.objects.filter(pk=buy.pk).update(
            status=MarketOrder.Status.PARTIALLY_FILLED,
            filled_quantity=Decimal("1.0000"),
            average_fill_price=Decimal("0.30000"),
        )
        WalletService.consume_reserved(
            user=self.buyer,
            currency="UGX",
            amount=Decimal("0.3333"),
            idempotency_reference=UUID("752d302d-96c9-4136-9221-069fa80f2456"),
            market=market,
            order=buy,
        )
        sell, position = self.reserve_sell(market)
        MarketOrder.objects.filter(pk=sell.pk).update(
            status=MarketOrder.Status.PARTIALLY_FILLED,
            filled_quantity=Decimal("1.0000"),
            average_fill_price=Decimal("0.65000"),
        )
        MarketPosition.objects.filter(pk=position.pk).update(reserved_quantity=Decimal("2.0000"))
        wallet = Wallet.objects.get(user=self.buyer, currency="UGX")
        available_before, reserved_before = wallet.available_balance, wallet.reserved_balance

        closed = MarketLifecycleService.close(
            market_id=market.id, actor=self.actor, notes="Trading completed."
        )

        buy.refresh_from_db()
        sell.refresh_from_db()
        position.refresh_from_db()
        wallet.refresh_from_db()
        cleanup = MarketCloseCleanup.objects.get(market=market)
        self.assertEqual(closed.status, Market.Status.CLOSED)
        self.assertEqual(buy.status, MarketOrder.Status.CANCELLED)
        self.assertEqual(buy.filled_quantity, Decimal("1.0000"))
        self.assertEqual(buy.average_fill_price, Decimal("0.30000"))
        self.assertEqual(sell.status, MarketOrder.Status.CANCELLED)
        self.assertEqual(sell.filled_quantity, Decimal("1.0000"))
        self.assertEqual(sell.average_fill_price, Decimal("0.65000"))
        self.assertEqual(wallet.available_balance, available_before + Decimal("0.6667"))
        self.assertEqual(wallet.reserved_balance, reserved_before - Decimal("0.6667"))
        self.assertEqual(position.quantity, Decimal("5.0000"))
        self.assertEqual(position.reserved_quantity, Decimal("0.0000"))
        self.assertEqual(position.total_cost, Decimal("2.0000"))
        self.assertEqual(position.average_entry_price, Decimal("0.40000"))
        self.assertEqual(position.realized_pnl, Decimal("0.7500"))
        self.assertEqual(cleanup.total_cancelled_order_count, 2)
        self.assertEqual(cleanup.cancelled_buy_order_count, 1)
        self.assertEqual(cleanup.cancelled_sell_order_count, 1)
        self.assertEqual(cleanup.total_released_buy_reservation_amount, Decimal("0.6667"))
        self.assertEqual(cleanup.total_released_sell_reservation_quantity, Decimal("2.0000"))
        children = cleanup.order_cancellations.all()
        self.assertEqual(children.count(), 2)
        self.assertEqual(
            sum((row.released_wallet_reservation_amount for row in children), Decimal("0")),
            cleanup.total_released_buy_reservation_amount,
        )
        release = children.get(market_order=buy).wallet_release_ledger_entry
        self.assertEqual(release.entry_type, LedgerEntry.EntryType.RELEASE)
        self.assertEqual(release.market_id, market.id)
        self.assertEqual(release.order_id, buy.id)

    def test_terminal_orders_are_unchanged_and_empty_close_has_zero_totals(self):
        market = self.create_open_market()
        outcome = market.outcomes.get(side=MarketOutcome.Side.YES)
        terminal = []
        for order_status in (
            MarketOrder.Status.FILLED,
            MarketOrder.Status.CANCELLED,
            MarketOrder.Status.REJECTED,
        ):
            terminal.append(
                MarketOrder.objects.create(
                    user=self.buyer,
                    market=market,
                    outcome=outcome,
                    side=MarketOrder.Side.BUY,
                    quantity=Decimal("1.0000"),
                    filled_quantity=(
                        Decimal("1.0000") if order_status == MarketOrder.Status.FILLED else 0
                    ),
                    average_fill_price=(
                        Decimal("0.50000") if order_status == MarketOrder.Status.FILLED else None
                    ),
                    limit_price=Decimal("0.50000"),
                    status=order_status,
                )
            )
        MarketLifecycleService.close(market_id=market.id, actor=self.actor, notes="Close")
        cleanup = MarketCloseCleanup.objects.get(market=market)
        self.assertEqual(cleanup.total_cancelled_order_count, 0)
        self.assertEqual(cleanup.total_released_buy_reservation_amount, Decimal("0.0000"))
        for order, expected in zip(terminal, ("FILLED", "CANCELLED", "REJECTED"), strict=True):
            order.refresh_from_db()
            self.assertEqual(order.status, expected)

    def test_failure_after_buy_release_rolls_back_all_cleanup_and_history(self):
        market = self.create_open_market()
        buy = self.reserve_buy(market)
        sell, position = self.reserve_sell(market)
        wallet = Wallet.objects.get(user=self.buyer, currency="UGX")
        balances_before = (wallet.available_balance, wallet.reserved_balance)
        ledger_before = list(LedgerEntry.objects.values_list("id", "entry_type", "amount"))
        transition_count = MarketStatusTransition.objects.filter(market=market).count()

        original = MarketParticipationService.cancel_locked_order

        def fail_after_first(*, order):
            result = original(order=order)
            if order.pk == buy.pk:
                raise RuntimeError("forced cleanup failure")
            return result

        with patch.object(
            MarketParticipationService, "cancel_locked_order", side_effect=fail_after_first
        ):
            with self.assertRaises(RuntimeError):
                MarketLifecycleService.close(market_id=market.id, actor=self.actor, notes="Close")

        market.refresh_from_db()
        buy.refresh_from_db()
        sell.refresh_from_db()
        position.refresh_from_db()
        wallet.refresh_from_db()
        self.assertEqual(market.status, Market.Status.OPEN)
        self.assertEqual(buy.status, MarketOrder.Status.OPEN)
        self.assertEqual(sell.status, MarketOrder.Status.OPEN)
        self.assertEqual(position.reserved_quantity, Decimal("3.0000"))
        self.assertEqual((wallet.available_balance, wallet.reserved_balance), balances_before)
        self.assertEqual(
            list(LedgerEntry.objects.values_list("id", "entry_type", "amount")), ledger_before
        )
        self.assertEqual(
            MarketStatusTransition.objects.filter(market=market).count(), transition_count
        )
        self.assertFalse(MarketCloseCleanup.objects.filter(market=market).exists())

    def test_rejected_close_replay_does_not_duplicate_release_or_audit(self):
        market = self.create_open_market()
        self.reserve_buy(market)
        MarketLifecycleService.close(market_id=market.id, actor=self.actor, notes="Close")
        release_count = LedgerEntry.objects.filter(entry_type=LedgerEntry.EntryType.RELEASE).count()
        with self.assertRaises(ValidationError):
            MarketLifecycleService.close(market_id=market.id, actor=self.actor, notes="Replay")
        self.assertEqual(MarketCloseCleanup.objects.filter(market=market).count(), 1)
        self.assertEqual(
            LedgerEntry.objects.filter(entry_type=LedgerEntry.EntryType.RELEASE).count(),
            release_count,
        )

    def test_locked_market_with_existing_cleanup_is_rejected_before_any_release(self):
        market = self.create_open_market()
        order = self.reserve_buy(market)
        wallet = Wallet.objects.get(user=self.buyer, currency="UGX")
        balances_before = (wallet.available_balance, wallet.reserved_balance)
        cleanup = MarketCloseCleanup.objects.create(market=market, executed_by=self.actor)

        with self.assertRaises(ValidationError) as error:
            MarketLifecycleService.close(
                market_id=market.id,
                actor=self.actor,
                notes="Conflicting close cleanup.",
            )

        self.assertIn("close_cleanup", error.exception.message_dict)
        market.refresh_from_db()
        order.refresh_from_db()
        wallet.refresh_from_db()
        self.assertEqual(market.status, Market.Status.OPEN)
        self.assertEqual(order.status, MarketOrder.Status.OPEN)
        self.assertEqual((wallet.available_balance, wallet.reserved_balance), balances_before)
        self.assertEqual(MarketCloseCleanup.objects.get(market=market), cleanup)
        self.assertFalse(cleanup.order_cancellations.exists())

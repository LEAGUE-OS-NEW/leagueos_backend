from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APITestCase

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
    MarketPositionSettlement,
    MarketScope,
    MarketSettlement,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.resolution_service import MarketResolutionService
from markets.services.settlement_service import MarketSettlementService
from notifications.models import Notification, NotificationCategory
from sports.models import Competition, Sport, SportingEvent
from wallets.models import LedgerEntry, Wallet, WalletTransaction
from wallets.services.wallet_service import WalletService


class SettlementFixtureMixin:
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.approve_permission = PermissionFactory(
            name="approve_market",
            resource="market",
            action="approve",
        )
        manage_permission = PermissionFactory(
            name="manage_market", resource="market", action="manage"
        )
        role = RoleFactory(name="Settlement Admin", display_name="Settlement Admin")
        operations_role = RoleFactory(
            name="Settlement Operations", display_name="Settlement Operations"
        )
        RolePermissionFactory(
            role=role,
            permission=self.approve_permission,
        )
        RolePermissionFactory(role=operations_role, permission=manage_permission)
        self.actor = UserFactory()
        UserRoleFactory(user=self.actor, role=role)
        self.outsider = UserFactory()
        UserRoleFactory(user=self.outsider, role=operations_role)
        NotificationCategory.objects.get_or_create(
            code="MARKET_SETTLEMENTS", defaults={"name": "Market Settlements"}
        )
        self.sport = Sport.objects.create(name="Football", code="FOOTBALL")
        self.category = MarketCategory.objects.create(name="Settlement")
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

    def create_market(self, question="Will KCCA win?"):
        return MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question=question,
            description="Settlement test.",
            rules="Official result applies.",
            resolution_source="Official result",
            resolution_criteria="Use final score.",
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=1),
            created_by=self.outsider,
            yes_label="Yes",
            no_label="No",
        )

    def resolve_market(self, market=None):
        market = market or self.create_market()
        market = MarketLifecycleService.submit(
            market_id=market.id, actor=self.outsider, notes="Ready."
        )
        market = MarketLifecycleService.approve(
            market_id=market.id, actor=self.actor, notes="Approved."
        )
        market = MarketLifecycleService.open(market_id=market.id, actor=self.actor, notes="Opened.")
        market = MarketLifecycleService.close(
            market_id=market.id, actor=self.actor, notes="Closed."
        )
        winner = market.outcomes.get(side=MarketOutcome.Side.YES)
        return MarketResolutionService.resolve(
            market_id=market.id,
            actor=self.actor,
            winning_outcome_id=winner.id,
            notes="Final result confirmed.",
            evidence="Official match report.",
        )

    def create_position(
        self,
        *,
        market,
        user=None,
        outcome=None,
        quantity="10.0000",
        cost="6.0000",
        realized="0.0000",
        reserved="0.0000",
    ):
        user = user or UserFactory()
        outcome = outcome or market.winning_outcome
        quantity = Decimal(quantity)
        cost = Decimal(cost)
        average = Decimal("0.00000")
        if quantity:
            average = (cost / quantity).quantize(Decimal("0.00001"))
        return MarketPosition.objects.create(
            user=user,
            market=market,
            outcome=outcome,
            quantity=quantity,
            reserved_quantity=Decimal(reserved),
            average_entry_price=average,
            total_cost=cost,
            realized_pnl=Decimal(realized),
        )


class MarketSettlementModelTests(SettlementFixtureMixin, TestCase):
    def test_market_and_position_settlement_uniqueness_and_immutability(self):
        market = self.resolve_market()
        position = self.create_position(market=market)
        settlement = MarketSettlement.objects.create(
            market=market,
            winning_outcome=market.winning_outcome,
            payout_per_unit=Decimal("1.0000"),
            settlement_currency="UGX",
            executed_by=self.actor,
        )
        record = MarketPositionSettlement.objects.create(
            market_settlement=settlement,
            market_position=position,
            participant=position.user,
            outcome=position.outcome,
            was_winner=True,
            settled_quantity=position.quantity,
            payout_per_unit=Decimal("1.0000"),
            payout_amount=Decimal("10.0000"),
            cost_basis=position.total_cost,
            realized_pnl_delta=Decimal("4.0000"),
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            MarketSettlement.objects.create(
                market=market,
                winning_outcome=market.winning_outcome,
                payout_per_unit=Decimal("1.0000"),
                settlement_currency="UGX",
                executed_by=self.actor,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            MarketPositionSettlement.objects.create(
                market_settlement=settlement,
                market_position=position,
                participant=position.user,
                outcome=position.outcome,
                was_winner=True,
                settled_quantity=Decimal("10.0000"),
                payout_per_unit=Decimal("1.0000"),
                payout_amount=Decimal("10.0000"),
                cost_basis=Decimal("6.0000"),
                realized_pnl_delta=Decimal("4.0000"),
            )
        record.payout_amount = Decimal("99.0000")
        with self.assertRaises(ValidationError):
            record.save()

        settlement.total_payout_amount = Decimal("99.0000")
        with self.assertRaises(ValidationError):
            settlement.save()


class MarketSettlementServiceTests(SettlementFixtureMixin, TestCase):
    def test_full_10000_ugx_share_uses_settlement_value_units(self):
        market = self.resolve_market()
        market.face_value_ugx = 10000
        market.save(update_fields=["face_value_ugx", "updated_at"])
        winner = self.create_position(market=market, quantity="10000.0000", cost="6000.0000")
        loser = self.create_position(
            market=market,
            outcome=market.outcomes.exclude(id=market.winning_outcome_id).get(),
            quantity="10000.0000",
            cost="4000.0000",
        )

        settlement = MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)

        winning_record = settlement.position_settlements.get(market_position=winner)
        losing_record = settlement.position_settlements.get(market_position=loser)
        self.assertEqual(winning_record.payout_amount, Decimal("10000.0000"))
        self.assertEqual(winning_record.realized_pnl_delta, Decimal("4000.0000"))
        self.assertEqual(losing_record.payout_amount, Decimal("0.0000"))
        self.assertEqual(losing_record.realized_pnl_delta, Decimal("-4000.0000"))

    def test_requires_resolved_market_with_valid_winner_and_permission(self):
        market = self.create_market()
        with self.assertRaises(ValidationError):
            MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)

        market.status = Market.Status.OPEN
        market.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValidationError):
            MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)

        market.status = Market.Status.SUSPENDED
        market.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValidationError):
            MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)

        resolved = self.resolve_market(self.create_market("Permission market"))
        with self.assertRaises(PermissionDenied):
            MarketSettlementService.settle_market(market_id=resolved.id, actor=self.outsider)

        Market.objects.filter(id=resolved.id).update(winning_outcome=None)
        with self.assertRaises(ValidationError):
            MarketSettlementService.settle_market(market_id=resolved.id, actor=self.actor)

    def test_rejects_legacy_winner_from_another_market(self):
        market = self.resolve_market()
        other = self.create_market("Other market")
        other_winner = other.outcomes.get(side=MarketOutcome.Side.YES)
        Market.objects.filter(id=market.id).update(winning_outcome=other_winner)
        with self.assertRaises(ValidationError):
            MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)

    def test_settles_winners_losers_multiple_outcomes_and_totals(self):
        market = self.resolve_market()
        loser_outcome = market.outcomes.get(side=MarketOutcome.Side.NO)
        shared_user = UserFactory()
        winner = self.create_position(
            market=market, user=shared_user, quantity="10.0000", cost="6.0000", realized="1.0000"
        )
        self.create_position(market=market, quantity="2.5000", cost="1.0000")
        loser = self.create_position(
            market=market,
            user=shared_user,
            outcome=loser_outcome,
            quantity="4.0000",
            cost="2.4000",
            realized="-0.1000",
        )
        second_loser = self.create_position(
            market=market, outcome=loser_outcome, quantity="3.0000", cost="1.5000"
        )
        zero = self.create_position(
            market=market, outcome=loser_outcome, quantity="0.0000", cost="0.0000"
        )

        settlement = MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)

        self.assertEqual(settlement.total_position_count, 4)
        self.assertEqual(settlement.winning_position_count, 2)
        self.assertEqual(settlement.losing_position_count, 2)
        self.assertEqual(settlement.total_winning_quantity, Decimal("12.5000"))
        self.assertEqual(settlement.total_payout_amount, Decimal("12.5000"))
        self.assertEqual(settlement.position_settlements.count(), 4)
        self.assertFalse(settlement.position_settlements.filter(market_position=zero).exists())

        winner.refresh_from_db()
        loser.refresh_from_db()
        second_loser.refresh_from_db()
        self.assertEqual(winner.quantity, Decimal("0.0000"))
        self.assertEqual(winner.reserved_quantity, Decimal("0.0000"))
        self.assertEqual(winner.total_cost, Decimal("0.0000"))
        self.assertEqual(winner.average_entry_price, Decimal("0.00000"))
        self.assertEqual(winner.realized_pnl, Decimal("5.0000"))
        self.assertEqual(loser.realized_pnl, Decimal("-2.5000"))
        self.assertEqual(second_loser.realized_pnl, Decimal("-1.5000"))

        entries = LedgerEntry.objects.filter(market=market, entry_type="CREDIT")
        self.assertEqual(entries.count(), 2)
        winner_record = settlement.position_settlements.get(market_position=winner)
        loser_record = settlement.position_settlements.get(market_position=loser)
        self.assertEqual(winner_record.payout_amount, Decimal("10.0000"))
        self.assertEqual(winner_record.cost_basis, Decimal("6.0000"))
        self.assertEqual(winner_record.realized_pnl_delta, Decimal("4.0000"))
        self.assertIsNotNone(winner_record.wallet_ledger_entry_id)
        self.assertEqual(winner_record.wallet_ledger_entry.market_id, market.id)
        self.assertIsInstance(winner_record.wallet_ledger_entry.idempotency_reference, UUID)
        self.assertEqual(loser_record.payout_amount, Decimal("0.0000"))
        self.assertEqual(loser_record.realized_pnl_delta, Decimal("-2.4000"))
        self.assertIsNone(loser_record.wallet_ledger_entry)

    def test_winner_without_wallet_receives_wallet_service_credit(self):
        market = self.resolve_market()
        position = self.create_position(market=market, quantity="1.2500", cost="0.5000")
        self.assertFalse(Wallet.objects.filter(user=position.user).exists())
        MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)
        wallet = Wallet.objects.get(user=position.user, currency="UGX")
        self.assertEqual(wallet.available_balance, Decimal("1.2500"))

    def test_replay_is_idempotent_and_preserves_actor_and_time(self):
        market = self.resolve_market()
        position = self.create_position(market=market)
        first = MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)
        original_time = first.executed_at
        original_pnl = first.executed_by_id
        wallet = Wallet.objects.get(user=position.user, currency="UGX")
        original_balance = wallet.available_balance
        second = MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)
        wallet.refresh_from_db()
        self.assertEqual(second.id, first.id)
        self.assertEqual(second.executed_at, original_time)
        self.assertEqual(second.executed_by_id, original_pnl)
        self.assertEqual(wallet.available_balance, original_balance)
        self.assertEqual(LedgerEntry.objects.filter(market=market).count(), 1)
        self.assertEqual(
            MarketPositionSettlement.objects.filter(market_settlement=first).count(), 1
        )

    def test_no_positions_settles_with_zero_totals(self):
        market = self.resolve_market()
        settlement = MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)
        self.assertEqual(settlement.total_position_count, 0)
        self.assertEqual(settlement.total_winning_quantity, Decimal("0.0000"))
        self.assertEqual(settlement.total_payout_amount, Decimal("0.0000"))

    def test_open_partial_orders_and_reservations_block_without_changes(self):
        for order_status in (MarketOrder.Status.OPEN, MarketOrder.Status.PARTIALLY_FILLED):
            with self.subTest(order_status=order_status):
                market = self.resolve_market(self.create_market(f"Blocked {order_status}"))
                position = self.create_position(market=market)
                MarketOrder.objects.create(
                    user=position.user,
                    market=market,
                    outcome=position.outcome,
                    side=MarketOrder.Side.BUY,
                    quantity=Decimal("2.0000"),
                    filled_quantity=(
                        Decimal("1.0000")
                        if order_status == MarketOrder.Status.PARTIALLY_FILLED
                        else Decimal("0.0000")
                    ),
                    average_fill_price=(
                        Decimal("0.50000")
                        if order_status == MarketOrder.Status.PARTIALLY_FILLED
                        else None
                    ),
                    limit_price=Decimal("0.50000"),
                    status=order_status,
                )
                with self.assertRaises(ValidationError) as context:
                    MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)
                self.assertIn("commitments", context.exception.message_dict)
                position.refresh_from_db()
                self.assertEqual(position.quantity, Decimal("10.0000"))
                self.assertFalse(MarketSettlement.objects.filter(market=market).exists())
                self.assertFalse(LedgerEntry.objects.filter(market=market).exists())

        market = self.resolve_market(self.create_market("Reserved position"))
        position = self.create_position(market=market, reserved="1.0000")
        with self.assertRaises(ValidationError):
            MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)
        position.refresh_from_db()
        self.assertEqual(position.quantity, Decimal("10.0000"))

    def test_failure_after_first_credit_rolls_back_everything(self):
        market = self.resolve_market()
        positions = [
            self.create_position(market=market, quantity="2.0000", cost="1.0000"),
            self.create_position(market=market, quantity="3.0000", cost="1.5000"),
        ]
        real_credit = WalletService.credit
        calls = 0

        def failing_credit(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("forced payout failure")
            return real_credit(**kwargs)

        with patch.object(WalletService, "credit", side_effect=failing_credit):
            with self.assertRaises(RuntimeError):
                MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)
        self.assertGreaterEqual(calls, 2)
        self.assertFalse(MarketSettlement.objects.filter(market=market).exists())
        self.assertFalse(
            MarketPositionSettlement.objects.filter(market_position__market=market).exists()
        )
        self.assertFalse(LedgerEntry.objects.filter(market=market).exists())
        self.assertFalse(Wallet.objects.filter(user__in=[p.user for p in positions]).exists())
        for position in positions:
            position.refresh_from_db()
            self.assertGreater(position.quantity, Decimal("0.0000"))

    def test_settlement_totals_reconcile_to_records_and_ledger(self):
        market = self.resolve_market()
        losing_outcome = market.outcomes.get(side=MarketOutcome.Side.NO)

        self.create_position(
            market=market,
            quantity="4.0000",
            cost="2.0000",
        )
        self.create_position(
            market=market,
            quantity="1.5000",
            cost="0.6000",
        )
        self.create_position(
            market=market,
            outcome=losing_outcome,
            quantity="3.0000",
            cost="1.2000",
        )

        settlement = MarketSettlementService.settle_market(
            market_id=market.id,
            actor=self.actor,
        )

        records = settlement.position_settlements.all()
        record_payout_total = sum(
            (record.payout_amount for record in records),
            Decimal("0.0000"),
        )
        ledger_payout_total = sum(
            (
                entry.amount
                for entry in LedgerEntry.objects.filter(
                    market=market,
                    entry_type=LedgerEntry.EntryType.CREDIT,
                )
            ),
            Decimal("0.0000"),
        )

        self.assertEqual(
            settlement.total_position_count,
            records.count(),
        )
        self.assertEqual(
            settlement.winning_position_count,
            records.filter(was_winner=True).count(),
        )
        self.assertEqual(
            settlement.losing_position_count,
            records.filter(was_winner=False).count(),
        )
        self.assertEqual(
            settlement.total_payout_amount,
            record_payout_total,
        )
        self.assertEqual(
            settlement.total_payout_amount,
            ledger_payout_total,
        )

    def test_settlement_creates_wallet_transaction_for_winner_only(self):
        market = self.resolve_market()
        losing_outcome = market.outcomes.get(side=MarketOutcome.Side.NO)

        winner = self.create_position(market=market, quantity="4.0000", cost="2.0000")
        loser = self.create_position(
            market=market,
            outcome=losing_outcome,
            quantity="3.0000",
            cost="1.2000",
        )

        settlement = MarketSettlementService.settle_market(
            market_id=market.id,
            actor=self.actor,
        )
        winner_record = settlement.position_settlements.get(participant=winner.user)

        winner_transaction = WalletTransaction.objects.get(wallet__user=winner.user)
        self.assertEqual(
            winner_transaction.transaction_type,
            WalletTransaction.TransactionType.SETTLEMENT_PAYOUT,
        )
        self.assertEqual(winner_transaction.status, WalletTransaction.Status.COMPLETED)
        self.assertEqual(winner_transaction.amount, winner_record.net_payout_amount)
        self.assertIsNotNone(winner_transaction.completed_at)

        self.assertFalse(WalletTransaction.objects.filter(wallet__user=loser.user).exists())

    def test_settlement_sends_win_and_loss_notifications(self):
        market = self.resolve_market()
        losing_outcome = market.outcomes.get(side=MarketOutcome.Side.NO)

        winner = self.create_position(market=market, quantity="4.0000", cost="2.0000")
        loser = self.create_position(
            market=market,
            outcome=losing_outcome,
            quantity="3.0000",
            cost="1.2000",
        )

        with self.captureOnCommitCallbacks(execute=True):
            settlement = MarketSettlementService.settle_market(
                market_id=market.id,
                actor=self.actor,
            )
        winner_record = settlement.position_settlements.get(participant=winner.user)

        win_notification = Notification.objects.get(recipient=winner.user)
        self.assertEqual(win_notification.event_type, "SETTLEMENT_WIN")
        self.assertEqual(win_notification.category.code, "MARKET_SETTLEMENTS")
        self.assertTrue(win_notification.mandatory)
        self.assertEqual(win_notification.title, "You won!")
        self.assertIn(str(winner_record.net_payout_amount), win_notification.message)

        loss_notification = Notification.objects.get(recipient=loser.user)
        self.assertEqual(loss_notification.event_type, "SETTLEMENT_LOSS")
        self.assertEqual(loss_notification.category.code, "MARKET_SETTLEMENTS")
        self.assertTrue(loss_notification.mandatory)
        self.assertEqual(loss_notification.title, "Market settled")
        self.assertIn("didn't win", loss_notification.message)

    def test_failure_restores_existing_wallet_and_ledger_history(
        self,
    ):
        market = self.resolve_market()
        positions = [
            self.create_position(
                market=market,
                quantity="2.0000",
                cost="1.0000",
            ),
            self.create_position(
                market=market,
                quantity="3.0000",
                cost="1.5000",
            ),
        ]

        existing_entry = WalletService.credit(
            user=positions[0].user,
            currency="UGX",
            amount=Decimal("50.0000"),
            idempotency_reference=uuid4(),
        )
        wallet = Wallet.objects.get(
            user=positions[0].user,
            currency="UGX",
        )
        wallet_values_before = (
            wallet.available_balance,
            wallet.reserved_balance,
            wallet.updated_at,
        )
        ledger_ids_before = list(
            LedgerEntry.objects.order_by("id").values_list(
                "id",
                flat=True,
            )
        )

        real_credit = WalletService.credit
        calls = 0

        def fail_second_credit(**kwargs):
            nonlocal calls
            calls += 1

            if calls == 2:
                raise RuntimeError("forced second payout failure")

            return real_credit(**kwargs)

        with patch.object(
            WalletService,
            "credit",
            side_effect=fail_second_credit,
        ):
            with self.assertRaises(RuntimeError):
                MarketSettlementService.settle_market(
                    market_id=market.id,
                    actor=self.actor,
                )

        wallet.refresh_from_db()

        self.assertEqual(
            (
                wallet.available_balance,
                wallet.reserved_balance,
                wallet.updated_at,
            ),
            wallet_values_before,
        )
        self.assertEqual(
            list(LedgerEntry.objects.order_by("id").values_list("id", flat=True)),
            ledger_ids_before,
        )
        self.assertTrue(LedgerEntry.objects.filter(id=existing_entry.id).exists())
        self.assertFalse(MarketSettlement.objects.filter(market=market).exists())

        for position in positions:
            position.refresh_from_db()
            self.assertGreater(
                position.quantity,
                Decimal("0.0000"),
            )

    def test_replay_by_different_authorized_actor_preserves_original_audit(
        self,
    ):
        market = self.resolve_market()
        self.create_position(market=market)

        second_actor = UserFactory()
        approval_role = RoleFactory(
            name="Second Settlement Admin",
            display_name="Second Settlement Admin",
        )
        RolePermissionFactory(
            role=approval_role,
            permission=self.approve_permission,
        )
        UserRoleFactory(
            user=second_actor,
            role=approval_role,
        )

        first = MarketSettlementService.settle_market(
            market_id=market.id,
            actor=self.actor,
        )
        original_actor = first.executed_by_id
        original_time = first.executed_at
        ledger_count = LedgerEntry.objects.filter(market=market).count()

        replay = MarketSettlementService.settle_market(
            market_id=market.id,
            actor=second_actor,
        )

        self.assertEqual(replay.id, first.id)
        self.assertEqual(
            replay.executed_by_id,
            original_actor,
        )
        self.assertEqual(
            replay.executed_at,
            original_time,
        )
        self.assertEqual(
            LedgerEntry.objects.filter(market=market).count(),
            ledger_count,
        )

    def test_credit_reference_is_deterministic(self):
        market = self.resolve_market()
        position = self.create_position(market=market)
        expected = MarketSettlementService.payout_idempotency_reference(
            market_id=market.id,
            position_id=position.id,
            winning_outcome_id=market.winning_outcome_id,
            payout_per_unit=Decimal("1.0000"),
        )
        settlement = MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)
        entry = settlement.position_settlements.get().wallet_ledger_entry
        self.assertEqual(entry.idempotency_reference, expected)

    def test_settlement_before_settles_by_is_blocked(self):
        market = self.resolve_market()
        market.settles_by = timezone.now() + timedelta(hours=1)
        market.save(update_fields=["settles_by", "updated_at"])
        with self.assertRaises(ValidationError) as context:
            MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)
        self.assertIn("settles_by", context.exception.message_dict)

    def test_settlement_at_settles_by_is_allowed(self):
        market = self.resolve_market()
        target = timezone.now() + timedelta(hours=1)
        market.settles_by = target
        market.save(update_fields=["settles_by", "updated_at"])
        with patch("markets.services.settlement_service.timezone.now", return_value=target):
            settlement = MarketSettlementService.settle_market(
                market_id=market.id, actor=self.actor
            )
        self.assertEqual(settlement.market_id, market.id)

    def test_null_settles_by_preserves_historical_behavior(self):
        market = self.resolve_market()
        self.assertIsNone(market.settles_by)
        settlement = MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)
        self.assertEqual(settlement.market_id, market.id)


class MarketSettlementAPITests(SettlementFixtureMixin, APITestCase):
    def url(self, market_id):
        return reverse("markets:market-settle", kwargs={"market_id": market_id})

    def test_auth_permission_and_missing_market(self):
        market = self.resolve_market()
        self.assertEqual(self.client.post(self.url(market.id), {}, format="json").status_code, 401)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.post(self.url(market.id), {}, format="json").status_code, 403)
        self.client.force_authenticate(self.actor)
        self.assertEqual(self.client.post(self.url(uuid4()), {}, format="json").status_code, 404)

    def test_result_verification_admin_can_settle(self):
        # A Result Verification Admin (verify_results/reject_result only,
        # no approve_market) must be able to reach settlement — this was
        # previously 403 for the whole role.
        verify_permission = PermissionFactory(
            name="verify_results", resource="results", action="verify"
        )
        reject_permission = PermissionFactory(
            name="reject_result", resource="result", action="reject"
        )
        result_verification_role = RoleFactory(
            name="Result Verification Admin", display_name="Result Verification Admin"
        )
        RolePermissionFactory(role=result_verification_role, permission=verify_permission)
        RolePermissionFactory(role=result_verification_role, permission=reject_permission)
        verifier = UserFactory()
        UserRoleFactory(user=verifier, role=result_verification_role)

        market = self.resolve_market()
        self.client.force_authenticate(verifier)
        response = self.client.post(self.url(market.id), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_success_replay_contract_rejects_client_values_and_exposes_no_pii(self):
        market = self.resolve_market()
        self.create_position(market=market, quantity="2.0000", cost="1.0000")
        self.client.force_authenticate(self.actor)
        response = self.client.post(self.url(market.id), {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.data),
            {
                "id",
                "market_id",
                "winning_outcome_id",
                "payout_per_unit",
                "currency",
                "total_position_count",
                "winning_position_count",
                "losing_position_count",
                "total_winning_quantity",
                "total_payout_amount",
                "executed_at",
            },
        )
        self.assertEqual(response.data["payout_per_unit"], "1.0000")
        self.assertEqual(response.data["total_winning_quantity"], "2.0000")
        self.assertEqual(response.data["total_payout_amount"], "2.0000")
        self.assertNotIn("email", str(response.data).lower())
        settlement_id = response.data["id"]
        replay = self.client.post(self.url(market.id), {}, format="json")
        self.assertEqual(replay.status_code, status.HTTP_200_OK)
        self.assertEqual(replay.data["id"], settlement_id)
        rejected = self.client.post(
            self.url(market.id), {"payout_per_unit": "99.0000"}, format="json"
        )
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)

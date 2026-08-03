from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID

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
    MarketPositionVoidRefund,
    MarketScope,
    MarketSettlement,
    MarketVoidOrderCancellation,
    MarketVoidRefund,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.participation_service import MarketParticipationService
from markets.services.resolution_service import MarketResolutionService
from markets.services.settlement_service import MarketSettlementService
from markets.services.void_refund_service import MarketVoidRefundService
from sports.models import Competition, Sport, SportingEvent
from wallets.models import LedgerEntry, Wallet
from wallets.services.wallet_service import WalletService


class VoidRefundFixtureMixin:
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        approve = PermissionFactory(name="approve_market", resource="market", action="approve")
        participate = PermissionFactory(
            name="participate_market", resource="market", action="participate"
        )
        manage = PermissionFactory(name="manage_market", resource="market", action="manage")
        approval_role = RoleFactory(name="Void Refund Admin", display_name="Void Refund Admin")
        participant_role = RoleFactory(name="Void Trader", display_name="Void Trader")
        operations_role = RoleFactory(name="Void Operations", display_name="Void Operations")
        RolePermissionFactory(role=approval_role, permission=approve)
        RolePermissionFactory(role=participant_role, permission=participate)
        RolePermissionFactory(role=operations_role, permission=manage)
        self.actor = UserFactory()
        self.other_actor = UserFactory()
        self.creator = UserFactory()
        self.outsider = UserFactory()
        self.trader = UserFactory(is_verified=True)
        for user in (self.actor, self.other_actor):
            UserRoleFactory(user=user, role=approval_role)
        UserRoleFactory(user=self.creator, role=operations_role)
        UserRoleFactory(user=self.trader, role=participant_role)
        self.sport = Sport.objects.create(name="Football", code="FOOTBALL")
        self.category = MarketCategory.objects.create(name="Void refunds")
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
            description="Void refund test.",
            rules="Official notice applies.",
            resolution_source="Official notice",
            resolution_criteria="Use final notice.",
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=1),
            created_by=self.creator,
            yes_label="Yes",
            no_label="No",
        )

    def approve_market(self, market):
        MarketLifecycleService.submit(market_id=market.id, actor=self.creator, notes="Ready")
        return MarketLifecycleService.approve(
            market_id=market.id, actor=self.actor, notes="Approved"
        )

    def open_market(self, market):
        return MarketLifecycleService.open(
            market_id=self.approve_market(market).id, actor=self.actor, notes="Open"
        )

    def void_market(self, market):
        return MarketResolutionService.void(
            market_id=market.id,
            actor=self.actor,
            notes="Fixture abandoned.",
            evidence="Official abandonment notice.",
        )

    def position(
        self,
        market,
        *,
        user=None,
        outcome=None,
        quantity="4.0000",
        cost="2.4000",
        reserved="0.0000",
        realized="0.0000",
    ):
        quantity = Decimal(quantity)
        cost = Decimal(cost)
        return MarketPosition.objects.create(
            user=user or self.trader,
            market=market,
            outcome=outcome or market.outcomes.get(side=MarketOutcome.Side.YES),
            quantity=quantity,
            reserved_quantity=Decimal(reserved),
            average_entry_price=(
                (cost / quantity).quantize(Decimal("0.00001")) if quantity else Decimal("0.00000")
            ),
            total_cost=cost,
            realized_pnl=Decimal(realized),
        )


class MarketVoidRefundModelTests(VoidRefundFixtureMixin, TestCase):
    def test_audit_models_are_unique_and_immutable(self):
        market = self.void_market(self.approve_market(self.create_market()))
        position = self.position(market)
        order = MarketOrder.objects.create(
            user=self.trader,
            market=market,
            outcome=position.outcome,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("1.0000"),
            limit_price=Decimal("0.50000"),
            status=MarketOrder.Status.CANCELLED,
        )
        refund = MarketVoidRefund.objects.create(
            market=market, refund_currency="UGX", executed_by=self.actor
        )
        cancellation = MarketVoidOrderCancellation.objects.create(
            market_void_refund=refund,
            market_order=order,
            order_side=order.side,
            remaining_quantity_cancelled=Decimal("1.0000"),
        )
        position_refund = MarketPositionVoidRefund.objects.create(
            market_void_refund=refund,
            market_position=position,
            participant=position.user,
            outcome=position.outcome,
            refunded_quantity=position.quantity,
            cost_basis=position.total_cost,
            refund_amount=position.total_cost,
        )
        for record in (refund, cancellation, position_refund):
            with self.assertRaises(ValidationError):
                record.save()
            with self.assertRaises(ValidationError):
                record.delete()
        with self.assertRaises(IntegrityError), transaction.atomic():
            MarketVoidRefund.objects.create(
                market=market, refund_currency="UGX", executed_by=self.actor
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            MarketVoidOrderCancellation.objects.create(
                market_void_refund=refund,
                market_order=order,
                order_side=order.side,
                remaining_quantity_cancelled=Decimal("1.0000"),
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            MarketPositionVoidRefund.objects.create(
                market_void_refund=refund,
                market_position=position,
                participant=position.user,
                outcome=position.outcome,
                refunded_quantity=position.quantity,
                cost_basis=position.total_cost,
                refund_amount=position.total_cost,
            )


class MarketVoidRefundServiceTests(VoidRefundFixtureMixin, TestCase):
    def test_only_final_voided_unsettled_market_with_permission_is_accepted(self):
        for state in (
            Market.Status.DRAFT,
            Market.Status.PENDING_APPROVAL,
            Market.Status.APPROVED,
            Market.Status.OPEN,
            Market.Status.SUSPENDED,
            Market.Status.CLOSED,
            Market.Status.RESOLVED,
        ):
            with self.subTest(state=state):
                market = self.create_market(question=f"State {state}")
                Market.objects.filter(pk=market.pk).update(status=state)
                with self.assertRaises(ValidationError):
                    MarketVoidRefundService.refund_void_market(
                        market_id=market.id, actor=self.actor
                    )
        market = self.void_market(self.approve_market(self.create_market("Unauthorized")))
        with self.assertRaises(PermissionDenied):
            MarketVoidRefundService.refund_void_market(market_id=market.id, actor=self.outsider)
        inconsistent = self.void_market(self.approve_market(self.create_market("Winner")))
        winner = inconsistent.outcomes.get(side=MarketOutcome.Side.YES)
        Market.objects.filter(pk=inconsistent.pk).update(winning_outcome=winner)
        with self.assertRaises(ValidationError):
            MarketVoidRefundService.refund_void_market(market_id=inconsistent.id, actor=self.actor)

    def test_normally_settled_market_is_rejected_even_if_legacy_status_is_voided(self):
        market = self.create_market()
        winner = market.outcomes.get(side=MarketOutcome.Side.YES)
        Market.objects.filter(pk=market.pk).update(
            status=Market.Status.RESOLVED,
            winning_outcome=winner,
            resolved_by=self.actor,
            resolved_at=self.now,
            resolution_notes="Resolved",
            resolution_evidence="Evidence",
        )
        MarketSettlement.objects.create(
            market=market,
            winning_outcome=winner,
            payout_per_unit=Decimal("1.0000"),
            settlement_currency="UGX",
            executed_by=self.actor,
        )
        Market.objects.filter(pk=market.pk).update(status=Market.Status.VOIDED)
        with self.assertRaises(ValidationError):
            MarketVoidRefundService.refund_void_market(market_id=market.id, actor=self.actor)

    def test_cancels_buy_and_sell_remainders_and_preserves_fill_fields(self):
        market = self.open_market(self.create_market())
        outcome = market.outcomes.get(side=MarketOutcome.Side.YES)
        WalletService.credit(
            user=self.trader,
            currency="UGX",
            amount=Decimal("20.0000"),
            idempotency_reference=UUID("f617c068-b45f-45e1-b0e3-73f74e399761"),
        )
        with patch(
            "markets.services.participation_service.MarketMatchingService.match_order",
            return_value=[],
        ):
            buy = MarketParticipationService.place_order(
                user=self.trader,
                market_id=market.id,
                outcome_id=outcome.id,
                side=MarketOrder.Side.BUY,
                quantity=Decimal("3.0000"),
                limit_price=Decimal("0.33333"),
            )
        MarketOrder.objects.filter(pk=buy.pk).update(
            status=MarketOrder.Status.PARTIALLY_FILLED,
            filled_quantity=Decimal("1.0000"),
            average_fill_price=Decimal("0.30000"),
        )
        # Mirror the reservation reduction a real fill would already have performed.
        WalletService.consume_reserved(
            user=self.trader,
            currency="UGX",
            amount=Decimal("0.3333"),
            idempotency_reference=UUID("752d302d-96c9-4136-9221-069fa80f2455"),
            market=market,
            order=buy,
        )
        seller = UserFactory(is_verified=True)
        position = self.position(
            market, user=seller, quantity="5.0000", cost="2.0000", reserved="2.0000"
        )
        sell = MarketOrder.objects.create(
            user=seller,
            market=market,
            outcome=outcome,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("3.0000"),
            filled_quantity=Decimal("1.0000"),
            average_fill_price=Decimal("0.60000"),
            limit_price=Decimal("0.50000"),
            status=MarketOrder.Status.PARTIALLY_FILLED,
        )
        untouched = []
        for order_status in (
            MarketOrder.Status.FILLED,
            MarketOrder.Status.CANCELLED,
            MarketOrder.Status.REJECTED,
        ):
            untouched.append(
                MarketOrder.objects.create(
                    user=seller,
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
        self.void_market(market)
        wallet_before = Wallet.objects.get(user=self.trader, currency="UGX")
        available_before = wallet_before.available_balance
        reserved_before = wallet_before.reserved_balance
        refund = MarketVoidRefundService.refund_void_market(market_id=market.id, actor=self.actor)
        buy.refresh_from_db()
        sell.refresh_from_db()
        position.refresh_from_db()
        wallet_before.refresh_from_db()
        self.assertEqual(buy.status, MarketOrder.Status.CANCELLED)
        self.assertEqual(buy.filled_quantity, Decimal("1.0000"))
        self.assertEqual(buy.average_fill_price, Decimal("0.30000"))
        self.assertEqual(sell.status, MarketOrder.Status.CANCELLED)
        self.assertEqual(sell.filled_quantity, Decimal("1.0000"))
        self.assertEqual(sell.average_fill_price, Decimal("0.60000"))
        self.assertEqual(wallet_before.available_balance, available_before + Decimal("0.6667"))
        self.assertEqual(wallet_before.reserved_balance, reserved_before - Decimal("0.6667"))
        release = refund.order_cancellations.get(market_order=buy)
        self.assertEqual(release.released_wallet_reservation_amount, Decimal("0.6667"))
        self.assertEqual(
            release.wallet_release_ledger_entry.entry_type, LedgerEntry.EntryType.RELEASE
        )
        sell_record = refund.order_cancellations.get(market_order=sell)
        self.assertEqual(sell_record.released_position_reservation_quantity, Decimal("2.0000"))
        self.assertEqual(position.quantity, Decimal("0.0000"))
        self.assertIsNone(sell_record.wallet_release_ledger_entry)
        for order, expected_status in zip(
            untouched,
            (
                MarketOrder.Status.FILLED,
                MarketOrder.Status.CANCELLED,
                MarketOrder.Status.REJECTED,
            ),
            strict=True,
        ):
            order.refresh_from_db()
            self.assertEqual(order.status, expected_status)
        self.assertEqual(refund.total_cancelled_order_count, 2)
        self.assertEqual(refund.cancelled_buy_order_count, 1)
        self.assertEqual(refund.cancelled_sell_order_count, 1)
        self.assertEqual(refund.total_released_buy_reservation_amount, Decimal("0.6667"))
        self.assertEqual(refund.total_released_sell_reservation_quantity, Decimal("2.0000"))

    def test_refunds_current_cost_basis_closes_positions_and_reconciles(self):
        market = self.void_market(self.approve_market(self.create_market()))
        other = UserFactory()
        yes = market.outcomes.get(side=MarketOutcome.Side.YES)
        no = market.outcomes.get(side=MarketOutcome.Side.NO)
        positions = [
            self.position(
                market,
                user=self.trader,
                outcome=yes,
                quantity="4",
                cost="2.4000",
                realized="0.7000",
            ),
            self.position(
                market,
                user=self.trader,
                outcome=no,
                quantity="2",
                cost="0.8000",
                realized="-0.1000",
            ),
            self.position(market, user=other, outcome=yes, quantity="3", cost="0.0000"),
        ]
        zero = self.position(market, user=other, outcome=no, quantity="0", cost="0", reserved="0")
        original_realized = {p.id: p.realized_pnl for p in positions}
        with patch.object(WalletService, "credit", wraps=WalletService.credit) as credit:
            refund = MarketVoidRefundService.refund_void_market(
                market_id=market.id, actor=self.actor
            )
        self.assertEqual(credit.call_count, 2)
        self.assertEqual(refund.refunded_position_count, 3)
        self.assertEqual(refund.total_refunded_position_quantity, Decimal("9.0000"))
        self.assertEqual(refund.total_position_refund_amount, Decimal("3.2000"))
        records = refund.position_refunds.all()
        self.assertEqual(sum((r.refund_amount for r in records), Decimal("0")), Decimal("3.2000"))
        entries = LedgerEntry.objects.filter(market=market, entry_type=LedgerEntry.EntryType.CREDIT)
        self.assertEqual(sum((e.amount for e in entries), Decimal("0")), Decimal("3.2000"))
        self.assertEqual(entries.count(), 2)
        for record in records:
            self.assertEqual(record.refund_amount, record.cost_basis)
            self.assertEqual(record.realized_pnl_delta, Decimal("0.0000"))
            if record.refund_amount:
                self.assertEqual(record.wallet_credit_ledger_entry.market_id, market.id)
                self.assertIsInstance(record.wallet_credit_ledger_entry.idempotency_reference, UUID)
                self.assertEqual(
                    record.wallet_credit_ledger_entry.idempotency_reference,
                    MarketVoidRefundService.position_refund_idempotency_reference(
                        market_id=market.id,
                        position_id=record.market_position_id,
                        participant_id=record.participant_id,
                        cost_basis=record.cost_basis,
                        currency="UGX",
                    ),
                )
            else:
                self.assertIsNone(record.wallet_credit_ledger_entry)
        for position in positions:
            position.refresh_from_db()
            self.assertEqual(position.quantity, Decimal("0.0000"))
            self.assertEqual(position.reserved_quantity, Decimal("0.0000"))
            self.assertEqual(position.total_cost, Decimal("0.0000"))
            self.assertEqual(position.average_entry_price, Decimal("0.00000"))
            self.assertEqual(position.realized_pnl, original_realized[position.id])
        zero.refresh_from_db()
        self.assertFalse(records.filter(market_position=zero).exists())
        self.assertFalse(
            Wallet.objects.filter(user=other, currency="UGX").exclude(available_balance=0).exists()
        )

    def test_replay_is_idempotent_and_preserves_original_actor_and_time(self):
        market = self.void_market(self.approve_market(self.create_market()))
        self.position(market)
        first = MarketVoidRefundService.refund_void_market(market_id=market.id, actor=self.actor)
        counts = (
            LedgerEntry.objects.count(),
            MarketVoidOrderCancellation.objects.count(),
            MarketPositionVoidRefund.objects.count(),
        )
        second = MarketVoidRefundService.refund_void_market(
            market_id=market.id, actor=self.other_actor
        )
        self.assertEqual(second.id, first.id)
        self.assertEqual(second.executed_by_id, self.actor.id)
        self.assertEqual(second.executed_at, first.executed_at)
        self.assertEqual(
            counts,
            (
                LedgerEntry.objects.count(),
                MarketVoidOrderCancellation.objects.count(),
                MarketPositionVoidRefund.objects.count(),
            ),
        )

    def test_failure_after_partial_wallet_progress_rolls_back_everything(self):
        market = self.void_market(self.approve_market(self.create_market()))
        first_user = UserFactory()
        second_user = UserFactory()
        positions = [
            self.position(market, user=first_user, quantity="2", cost="1"),
            self.position(market, user=second_user, quantity="3", cost="1.5"),
        ]
        WalletService.credit(
            user=first_user,
            currency="UGX",
            amount=Decimal("5.0000"),
            idempotency_reference=UUID("36a0d18b-532b-4e04-adf9-81fdd6506f79"),
        )
        wallet = Wallet.objects.get(user=first_user, currency="UGX")
        before = (
            wallet.available_balance,
            wallet.reserved_balance,
            list(wallet.ledger_entries.values_list("id", flat=True)),
        )
        real_credit = WalletService.credit
        calls = 0

        def fail_second(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("forced void refund failure")
            return real_credit(**kwargs)

        with patch.object(WalletService, "credit", side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                MarketVoidRefundService.refund_void_market(market_id=market.id, actor=self.actor)
        wallet.refresh_from_db()
        self.assertEqual(
            (
                wallet.available_balance,
                wallet.reserved_balance,
                list(wallet.ledger_entries.values_list("id", flat=True)),
            ),
            before,
        )
        self.assertFalse(MarketVoidRefund.objects.filter(market=market).exists())
        self.assertFalse(
            MarketPositionVoidRefund.objects.filter(market_position__market=market).exists()
        )
        for position in positions:
            position.refresh_from_db()
            self.assertGreater(position.quantity, Decimal("0.0000"))

    def test_failure_after_order_release_rolls_back_orders_and_reservations(
        self,
    ):
        market = self.open_market(self.create_market("Rollback after reservation release"))
        outcome = market.outcomes.get(side=MarketOutcome.Side.YES)

        WalletService.credit(
            user=self.trader,
            currency="UGX",
            amount=Decimal("10.0000"),
            idempotency_reference=UUID("85f72fc9-3e39-45d1-bec5-4202154d9753"),
        )

        with patch(
            ("markets.services.participation_service." "MarketMatchingService.match_order"),
            return_value=[],
        ):
            buy_order = MarketParticipationService.place_order(
                user=self.trader,
                market_id=market.id,
                outcome_id=outcome.id,
                side=MarketOrder.Side.BUY,
                quantity=Decimal("2.0000"),
                limit_price=Decimal("0.50000"),
            )

        seller = UserFactory(is_verified=True)
        seller_position = self.position(
            market,
            user=seller,
            outcome=outcome,
            quantity="3.0000",
            cost="1.2000",
            reserved="1.0000",
        )
        sell_order = MarketOrder.objects.create(
            user=seller,
            market=market,
            outcome=outcome,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("1.0000"),
            filled_quantity=Decimal("0.0000"),
            limit_price=Decimal("0.50000"),
            status=MarketOrder.Status.OPEN,
        )

        self.void_market(market)

        buyer_wallet = Wallet.objects.get(
            user=self.trader,
            currency="UGX",
        )
        wallet_before = (
            buyer_wallet.available_balance,
            buyer_wallet.reserved_balance,
            buyer_wallet.updated_at,
        )
        ledger_ids_before = list(
            LedgerEntry.objects.order_by("id").values_list(
                "id",
                flat=True,
            )
        )
        position_before = (
            seller_position.quantity,
            seller_position.reserved_quantity,
            seller_position.total_cost,
            seller_position.average_entry_price,
            seller_position.realized_pnl,
        )

        with patch.object(
            WalletService,
            "credit",
            side_effect=RuntimeError("forced failure after order releases"),
        ):
            with self.assertRaises(RuntimeError):
                MarketVoidRefundService.refund_void_market(
                    market_id=market.id,
                    actor=self.actor,
                )

        buy_order.refresh_from_db()
        sell_order.refresh_from_db()
        buyer_wallet.refresh_from_db()
        seller_position.refresh_from_db()

        self.assertEqual(
            buy_order.status,
            MarketOrder.Status.OPEN,
        )
        self.assertEqual(
            sell_order.status,
            MarketOrder.Status.OPEN,
        )
        self.assertEqual(
            (
                buyer_wallet.available_balance,
                buyer_wallet.reserved_balance,
                buyer_wallet.updated_at,
            ),
            wallet_before,
        )
        self.assertEqual(
            list(LedgerEntry.objects.order_by("id").values_list("id", flat=True)),
            ledger_ids_before,
        )
        self.assertEqual(
            (
                seller_position.quantity,
                seller_position.reserved_quantity,
                seller_position.total_cost,
                seller_position.average_entry_price,
                seller_position.realized_pnl,
            ),
            position_before,
        )
        self.assertFalse(MarketVoidRefund.objects.filter(market=market).exists())
        self.assertFalse(
            MarketVoidOrderCancellation.objects.filter(market_order__market=market).exists()
        )
        self.assertFalse(
            MarketPositionVoidRefund.objects.filter(market_position__market=market).exists()
        )

    def test_normal_settlement_cannot_follow_completed_void_refund(
        self,
    ):
        market = self.void_market(
            self.approve_market(self.create_market("Void refund blocks settlement"))
        )
        self.position(
            market,
            quantity="2.0000",
            cost="1.0000",
        )

        void_refund = MarketVoidRefundService.refund_void_market(
            market_id=market.id,
            actor=self.actor,
        )

        winner = market.outcomes.get(side=MarketOutcome.Side.YES)
        Market.objects.filter(pk=market.pk).update(
            status=Market.Status.RESOLVED,
            winning_outcome=winner,
            resolved_by=self.actor,
            resolved_at=self.now,
            resolution_notes="Invalid legacy resolution.",
            resolution_evidence="Invalid legacy evidence.",
        )

        with self.assertRaises(ValidationError):
            MarketSettlementService.settle_market(
                market_id=market.id,
                actor=self.actor,
            )

        self.assertTrue(
            MarketVoidRefund.objects.filter(
                id=void_refund.id,
                market=market,
            ).exists()
        )
        self.assertFalse(MarketSettlement.objects.filter(market=market).exists())

    def test_current_holder_refunded_without_seller_proceeds_clawback(
        self,
    ):
        market = self.approve_market(self.create_market("Preserve prior seller proceeds"))
        seller = UserFactory(is_verified=True)
        current_holder = UserFactory(is_verified=True)

        prior_seller_entry = WalletService.credit(
            user=seller,
            currency="UGX",
            amount=Decimal("7.0000"),
            idempotency_reference=UUID("67d329d4-caf8-4db0-9987-66f149422a70"),
            market=market,
        )
        seller_wallet = Wallet.objects.get(
            user=seller,
            currency="UGX",
        )
        seller_values_before = (
            seller_wallet.available_balance,
            seller_wallet.reserved_balance,
        )
        seller_ledger_ids_before = list(
            seller_wallet.ledger_entries.order_by("id").values_list("id", flat=True)
        )

        position = self.position(
            market,
            user=current_holder,
            quantity="2.0000",
            cost="1.2500",
        )
        market = self.void_market(market)

        refund = MarketVoidRefundService.refund_void_market(
            market_id=market.id,
            actor=self.actor,
        )

        seller_wallet.refresh_from_db()
        holder_wallet = Wallet.objects.get(
            user=current_holder,
            currency="UGX",
        )
        position.refresh_from_db()

        self.assertEqual(
            (
                seller_wallet.available_balance,
                seller_wallet.reserved_balance,
            ),
            seller_values_before,
        )
        self.assertEqual(
            list(seller_wallet.ledger_entries.order_by("id").values_list("id", flat=True)),
            seller_ledger_ids_before,
        )
        self.assertTrue(LedgerEntry.objects.filter(id=prior_seller_entry.id).exists())
        self.assertEqual(
            holder_wallet.available_balance,
            Decimal("1.2500"),
        )
        self.assertEqual(
            refund.total_position_refund_amount,
            Decimal("1.2500"),
        )
        self.assertEqual(
            position.quantity,
            Decimal("0.0000"),
        )


class MarketVoidRefundAPITests(VoidRefundFixtureMixin, APITestCase):
    def url(self, market_id):
        return reverse("markets:market-void-refund", kwargs={"market_id": market_id})

    def test_auth_permission_missing_and_input_contract(self):
        market = self.void_market(self.approve_market(self.create_market()))
        self.assertEqual(self.client.post(self.url(market.id), {}, format="json").status_code, 401)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.post(self.url(market.id), {}, format="json").status_code, 403)
        self.client.force_authenticate(self.actor)
        self.assertEqual(
            self.client.post(self.url(UUID(int=0)), {}, format="json").status_code, 404
        )
        response = self.client.post(
            self.url(market.id), {"refund_amount": "99.0000"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_success_and_replay_return_private_fixed_precision_summary(self):
        market = self.void_market(self.approve_market(self.create_market()))
        self.position(market, quantity="2", cost="1.25")
        self.client.force_authenticate(self.actor)
        first = self.client.post(self.url(market.id), {}, format="json")
        second = self.client.post(self.url(market.id), {}, format="json")
        self.assertEqual(first.status_code, status.HTTP_200_OK, first.data)
        self.assertEqual(second.status_code, status.HTTP_200_OK, second.data)
        self.assertEqual(first.data, second.data)
        self.assertEqual(
            set(first.data),
            {
                "id",
                "market_id",
                "currency",
                "total_cancelled_order_count",
                "cancelled_buy_order_count",
                "cancelled_sell_order_count",
                "total_released_buy_reservation_amount",
                "total_released_sell_reservation_quantity",
                "refunded_position_count",
                "total_refunded_position_quantity",
                "total_position_refund_amount",
                "executed_at",
            },
        )
        self.assertEqual(first.data["total_position_refund_amount"], "1.2500")
        self.assertNotIn("participant", str(first.data).lower())
        self.assertNotIn("email", str(first.data).lower())

    def test_schema_contains_void_refund_endpoint(self):
        response = self.client.get(reverse("api-schema"), {"format": "json"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("/api/v1/markets/{market_id}/void-refund/", response.json()["paths"])

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from authentication.models import Role
from authentication.tests.factories import UserFactory, UserRoleFactory
from markets.models import (
    MarketFeeLedgerEntry,
    MarketFeeSchedule,
    MarketFinancialAdjustment,
    MarketFinancialAdjustmentApproval,
    MarketFinancialAdjustmentLine,
    MarketOrder,
    MarketPosition,
    MarketReconciliationMismatch,
    MarketReconciliationRun,
)
from markets.services.fee_service import MarketFeeService
from markets.services.financial_adjustment_service import MarketFinancialAdjustmentService
from markets.services.order_expiry_service import MarketOrderExpiryService
from markets.services.participation_service import MarketParticipationService
from markets.services.reconciliation_service import MarketReconciliationService
from markets.services.settlement_service import MarketSettlementService
from markets.services.void_refund_service import MarketVoidRefundService
from markets.tests.test_market_order_expiry import MarketOrderExpiryServiceTests
from markets.tests.test_market_settlement import SettlementFixtureMixin
from markets.tests.test_void_refund import VoidRefundFixtureMixin
from markets.tests.wallet_test_support import fund_market_wallet
from wallets.models import LedgerEntry, Wallet
from wallets.services.wallet_service import WalletService


class TimeInForceLifecycleTests(MarketOrderExpiryServiceTests):
    def test_due_sweeper_is_bounded_and_idempotent(self):
        expires_at = self.now + timedelta(minutes=10)
        first = self.create_buy_order(
            quantity=Decimal("1.0000"),
            time_in_force=MarketOrder.TimeInForce.GTD,
            expires_at=expires_at,
        )
        second = self.create_buy_order(
            quantity=Decimal("1.0000"),
            time_in_force=MarketOrder.TimeInForce.GTD,
            expires_at=expires_at,
        )
        with self.subTest("invalid limits"):
            for limit in (0, -1, 1001, True):
                with self.assertRaises(ValidationError):
                    MarketOrderExpiryService.expire_due_orders(limit=limit)
        MarketOrder.objects.filter(id__in=[first.id, second.id]).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        audits = MarketOrderExpiryService.expire_due_orders(limit=1)
        self.assertEqual(len(audits), 1)
        self.assertEqual(MarketOrderExpiryService.expire_due_orders(limit=1).__len__(), 1)
        self.assertEqual(MarketOrderExpiryService.expire_due_orders(), [])

    def test_management_command_is_repeatable(self):
        order = self.create_buy_order(
            quantity=Decimal("1.0000"),
            time_in_force=MarketOrder.TimeInForce.GTD,
            expires_at=self.now + timedelta(minutes=10),
        )
        MarketOrder.objects.filter(id=order.id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        call_command("expire_market_orders", limit=100)
        call_command("expire_market_orders", limit=100)
        order.refresh_from_db()
        self.assertEqual(order.status, MarketOrder.Status.EXPIRED)

    def test_unmatched_ioc_is_cancelled_and_released(self):
        order = self.create_buy_order(
            quantity=Decimal("2.0000"),
            time_in_force=MarketOrder.TimeInForce.IOC,
        )
        order.refresh_from_db()
        self.wallet.refresh_from_db()
        self.assertEqual(order.status, MarketOrder.Status.CANCELLED)
        self.assertEqual(self.wallet.reserved_balance, Decimal("0.0000"))

    def test_partially_filled_ioc_preserves_fill_and_cancels_remainder(self):
        self.create_sell_order(quantity=Decimal("1.0000"), limit_price=Decimal("0.50000"))
        order = self.create_buy_order(
            quantity=Decimal("2.0000"),
            limit_price=Decimal("0.60000"),
            time_in_force=MarketOrder.TimeInForce.IOC,
        )
        self.assertEqual(order.status, MarketOrder.Status.CANCELLED)
        self.assertEqual(order.filled_quantity, Decimal("1.0000"))

    def test_fok_insufficient_liquidity_executes_nothing(self):
        maker, _ = self.create_sell_order(
            quantity=Decimal("1.0000"), limit_price=Decimal("0.50000")
        )
        order = self.create_buy_order(
            quantity=Decimal("2.0000"),
            limit_price=Decimal("0.60000"),
            time_in_force=MarketOrder.TimeInForce.FOK,
        )
        maker.refresh_from_db()
        self.assertEqual(order.status, MarketOrder.Status.CANCELLED)
        self.assertEqual(order.filled_quantity, Decimal("0.0000"))
        self.assertEqual(maker.filled_quantity, Decimal("0.0000"))

    def test_fok_sufficient_liquidity_fills_across_makers(self):
        self.create_sell_order(quantity=Decimal("1.0000"), limit_price=Decimal("0.50000"))

        other = UserFactory(is_verified=True)

        from authentication.tests.factories import UserRoleFactory
        from markets.models import MarketPosition
        from markets.tests.eligibility_test_support import make_market_eligible

        UserRoleFactory(user=other, role=Role.objects.get(name="Expiry Participant"))
        make_market_eligible(other)
        MarketPosition.objects.create(
            user=other,
            market=self.market,
            outcome=self.outcome,
            quantity=Decimal("1.0000"),
            reserved_quantity=Decimal("0.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("0.4000"),
        )
        MarketParticipationService.place_order(
            user=other,
            market_id=self.market.id,
            outcome_id=self.outcome.id,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("1.0000"),
            limit_price=Decimal("0.51000"),
        )
        order = self.create_buy_order(
            quantity=Decimal("2.0000"),
            limit_price=Decimal("0.60000"),
            time_in_force=MarketOrder.TimeInForce.FOK,
        )
        self.assertEqual(order.status, MarketOrder.Status.FILLED)
        self.assertEqual(order.filled_quantity, Decimal("2.0000"))


class FinancialIntegrityServiceTests(MarketOrderExpiryServiceTests):
    def activate_schedule(self):
        schedule = MarketFeeService.create_draft(
            actor=self.operations_user,
            market=self.market,
            effective_at=timezone.now() - timedelta(seconds=1),
            maker_fee_bps=100,
            taker_fee_bps=200,
            settlement_fee_bps=50,
            refund_fee_bps=0,
        )
        return MarketFeeService.activate(schedule_id=schedule.id, actor=self.approver_user)

    def test_schedule_activation_preview_and_immutability(self):
        schedule = self.activate_schedule()
        preview = MarketFeeService.preview(
            market=self.market,
            quantity=Decimal("10.0000"),
            limit_price=Decimal("0.50000"),
        )
        self.assertEqual(preview["estimated_maker_fee"], Decimal("0.0500"))
        self.assertEqual(preview["estimated_taker_fee"], Decimal("0.1000"))
        self.assertEqual(preview["estimated_maximum_buyer_reservation"], Decimal("5.1000"))
        schedule.maker_fee_bps = 0
        with self.assertRaises(ValidationError):
            schedule.save()

    def test_fill_fees_are_snapshotted_for_both_roles(self):
        schedule = self.activate_schedule()
        self.create_sell_order(quantity=Decimal("2.0000"), limit_price=Decimal("0.50000"))
        order = self.create_buy_order(quantity=Decimal("2.0000"), limit_price=Decimal("0.60000"))
        entries = MarketFeeLedgerEntry.objects.filter(fill__buy_order=order)
        self.assertEqual(entries.count(), 2)
        self.assertEqual(set(entries.values_list("schedule_id", flat=True)), {schedule.id})
        self.assertEqual(set(entries.values_list("rate_bps", flat=True)), {100, 200})

    def test_reconciliation_run_is_deterministic(self):
        first = MarketReconciliationService.run(market=self.market, actor=self.operations_user)
        second = MarketReconciliationService.run(market=self.market, actor=self.operations_user)
        self.assertEqual(first.id, second.id)
        self.assertEqual(first.status, MarketReconciliationRun.Status.COMPLETED)

    def test_adjustment_requires_balance_and_independent_approval(self):
        second_wallet = fund_market_wallet(self.seller)
        with self.assertRaises(ValidationError):
            MarketFinancialAdjustmentService.propose(
                actor=self.operations_user,
                reason="Mismatch",
                evidence_reference="R-1",
                currency="UGX",
                lines=[{"wallet_id": self.wallet.id, "direction": "DEBIT", "amount": "1.0000"}],
            )
        adjustment = MarketFinancialAdjustmentService.propose(
            actor=self.operations_user,
            reason="Mismatch",
            evidence_reference="R-2",
            currency="UGX",
            lines=[
                {"wallet_id": self.wallet.id, "direction": "DEBIT", "amount": "1.0000"},
                {"wallet_id": second_wallet.id, "direction": "CREDIT", "amount": "1.0000"},
            ],
        )
        with self.assertRaises(PermissionDenied):
            MarketFinancialAdjustmentService.decide(
                adjustment_id=adjustment.id,
                actor=self.operations_user,
                decision=MarketFinancialAdjustmentApproval.Decision.APPROVED,
            )
        approved = MarketFinancialAdjustmentService.decide(
            adjustment_id=adjustment.id,
            actor=self.approver_user,
            decision=MarketFinancialAdjustmentApproval.Decision.APPROVED,
        )
        self.assertEqual(approved.status, MarketFinancialAdjustment.Status.APPROVED)
        self.assertEqual(approved.lines.exclude(wallet_ledger_entry=None).count(), 2)


class FinancialIntegrityHardeningTests(FinancialIntegrityServiceTests):
    def create_funded_wallet(self, amount="10.0000", currency="UGX"):
        user = UserFactory()
        return Wallet.objects.create(
            user=user,
            currency=currency,
            available_balance=Decimal(amount),
        )

    def test_fee_default_global_override_permissions_and_lifecycle(self):
        preview = MarketFeeService.preview(
            market=self.market,
            quantity=Decimal("2.0000"),
            limit_price=Decimal("0.50000"),
        )
        self.assertIsNone(preview["schedule_id"])
        self.assertEqual(preview["estimated_taker_fee"], Decimal("0.0000"))
        with self.assertRaises(PermissionDenied):
            MarketFeeService.create_draft(
                actor=self.owner,
                market=self.market,
                maker_fee_bps=1,
                taker_fee_bps=1,
                settlement_fee_bps=0,
                refund_fee_bps=0,
            )

        global_schedule = MarketFeeService.create_draft(
            actor=self.operations_user,
            maker_fee_bps=10,
            taker_fee_bps=20,
            settlement_fee_bps=30,
            refund_fee_bps=0,
        )
        with self.assertRaises(PermissionDenied):
            MarketFeeService.activate(
                schedule_id=global_schedule.id,
                actor=self.operations_user,
            )
        global_schedule = MarketFeeService.activate(
            schedule_id=global_schedule.id,
            actor=self.approver_user,
        )
        selected, _rates = MarketFeeService.rates(market=self.market)
        self.assertEqual(selected.id, global_schedule.id)

        override = MarketFeeService.create_draft(
            actor=self.operations_user,
            market=self.market,
            maker_fee_bps=100,
            taker_fee_bps=200,
            settlement_fee_bps=50,
            refund_fee_bps=0,
        )
        override = MarketFeeService.activate(
            schedule_id=override.id,
            actor=self.approver_user,
        )
        selected, _rates = MarketFeeService.rates(market=self.market)
        self.assertEqual(selected.id, override.id)
        with self.assertRaises(ValidationError):
            MarketFeeService.activate(
                schedule_id=override.id,
                actor=self.approver_user,
            )
        with self.assertRaises(PermissionDenied):
            MarketFeeService.retire(
                schedule_id=global_schedule.id,
                actor=self.operations_user,
            )
        retired = MarketFeeService.retire(
            schedule_id=override.id,
            actor=self.approver_user,
        )
        self.assertEqual(retired.status, MarketFeeSchedule.Status.RETIRED)
        with self.assertRaises(ValidationError):
            MarketFeeService.retire(
                schedule_id=retired.id,
                actor=self.approver_user,
            )

    def test_fee_record_replay_validates_original_contract(self):
        self.activate_schedule()
        self.create_sell_order(
            quantity=Decimal("1.0000"),
            limit_price=Decimal("0.50000"),
        )
        order = self.create_buy_order(
            quantity=Decimal("1.0000"),
            limit_price=Decimal("0.60000"),
        )
        entry = MarketFeeLedgerEntry.objects.get(
            fill__buy_order=order,
            participant=self.owner,
        )
        replay = MarketFeeService.record_fee(
            parent_id=entry.fill_id,
            market=entry.market,
            participant=entry.participant,
            fee_type=entry.fee_type,
            rate_bps=entry.rate_bps,
            gross=entry.gross_amount,
            order=entry.order,
            fill=entry.fill,
            schedule=entry.schedule,
        )
        self.assertEqual(replay.id, entry.id)
        with self.assertRaises(ValidationError):
            MarketFeeService.record_fee(
                parent_id=entry.fill_id,
                market=entry.market,
                participant=entry.participant,
                fee_type=entry.fee_type,
                rate_bps=entry.rate_bps + 1,
                gross=entry.gross_amount,
                order=entry.order,
                fill=entry.fill,
                schedule=entry.schedule,
            )

    def test_adjustment_validation_quantization_and_wallet_contracts(self):
        credit = self.create_funded_wallet()
        duplicate = [
            {"wallet_id": self.wallet.id, "direction": "DEBIT", "amount": "1.00004"},
            {"wallet_id": self.wallet.id, "direction": "CREDIT", "amount": "1.00004"},
        ]
        with self.assertRaises(ValidationError):
            MarketFinancialAdjustmentService.propose(
                actor=self.operations_user,
                reason="Duplicate",
                evidence_reference="A-1",
                currency="UGX",
                lines=duplicate,
            )
        with self.assertRaises(ValidationError):
            MarketFinancialAdjustmentService.propose(
                actor=self.operations_user,
                reason="Currency",
                evidence_reference="A-2",
                currency="USD",
                lines=[
                    {"wallet_id": self.wallet.id, "direction": "DEBIT", "amount": "1"},
                    {"wallet_id": credit.id, "direction": "CREDIT", "amount": "1"},
                ],
            )
        kes_wallet = self.create_funded_wallet(currency="KES")
        with self.assertRaises(ValidationError):
            MarketFinancialAdjustmentService.propose(
                actor=self.operations_user,
                reason="Wallet currency",
                evidence_reference="A-3",
                currency="UGX",
                lines=[
                    {"wallet_id": self.wallet.id, "direction": "DEBIT", "amount": "1"},
                    {"wallet_id": kes_wallet.id, "direction": "CREDIT", "amount": "1"},
                ],
            )
        adjustment = MarketFinancialAdjustmentService.propose(
            actor=self.operations_user,
            reason="Quantized",
            evidence_reference="A-4",
            currency="UGX",
            lines=[
                {"wallet_id": self.wallet.id, "direction": "DEBIT", "amount": "1.00004"},
                {"wallet_id": credit.id, "direction": "CREDIT", "amount": "1.00004"},
            ],
        )
        self.assertEqual(
            set(adjustment.lines.values_list("amount", flat=True)),
            {Decimal("1.0000")},
        )

    def test_adjustment_multi_line_rollback_and_idempotent_decisions(self):
        debit_one = self.create_funded_wallet("2.0000")
        debit_two = self.create_funded_wallet("0.5000")
        credit_one = self.create_funded_wallet("0.0000")
        credit_two = self.create_funded_wallet("0.0000")
        adjustment = MarketFinancialAdjustmentService.propose(
            actor=self.operations_user,
            reason="Balanced correction",
            evidence_reference="A-5",
            currency="UGX",
            market=self.market,
            lines=[
                {"wallet_id": debit_one.id, "direction": "DEBIT", "amount": "1.0000"},
                {"wallet_id": debit_two.id, "direction": "DEBIT", "amount": "1.0000"},
                {"wallet_id": credit_one.id, "direction": "CREDIT", "amount": "0.7500"},
                {"wallet_id": credit_two.id, "direction": "CREDIT", "amount": "1.2500"},
            ],
        )
        before = {
            wallet.id: wallet.available_balance
            for wallet in (debit_one, debit_two, credit_one, credit_two)
        }
        ledger_count = LedgerEntry.objects.count()
        with self.assertRaises(ValidationError):
            MarketFinancialAdjustmentService.decide(
                adjustment_id=adjustment.id,
                actor=self.approver_user,
                decision=MarketFinancialAdjustmentApproval.Decision.APPROVED,
            )
        for wallet in (debit_one, debit_two, credit_one, credit_two):
            wallet.refresh_from_db()
            self.assertEqual(wallet.available_balance, before[wallet.id])
        self.assertEqual(LedgerEntry.objects.count(), ledger_count)
        adjustment.refresh_from_db()
        self.assertEqual(adjustment.status, MarketFinancialAdjustment.Status.PENDING)

        successful = MarketFinancialAdjustmentService.propose(
            actor=self.operations_user,
            reason="Successful correction",
            evidence_reference="A-6",
            currency="UGX",
            lines=[
                {"wallet_id": debit_one.id, "direction": "DEBIT", "amount": "1.0000"},
                {"wallet_id": credit_one.id, "direction": "CREDIT", "amount": "1.0000"},
            ],
        )
        approved = MarketFinancialAdjustmentService.decide(
            adjustment_id=successful.id,
            actor=self.approver_user,
            decision=MarketFinancialAdjustmentApproval.Decision.APPROVED,
        )
        replay = MarketFinancialAdjustmentService.decide(
            adjustment_id=successful.id,
            actor=self.approver_user,
            decision=MarketFinancialAdjustmentApproval.Decision.APPROVED,
        )
        self.assertEqual(replay.id, approved.id)
        self.assertEqual(approved.lines.exclude(wallet_ledger_entry=None).count(), 2)
        with self.assertRaises(ValidationError):
            MarketFinancialAdjustmentService.decide(
                adjustment_id=successful.id,
                actor=self.approver_user,
                decision=MarketFinancialAdjustmentApproval.Decision.REJECTED,
            )

    def test_adjustment_rejection_permissions_and_mismatch_link(self):
        credit = self.create_funded_wallet()
        run = MarketReconciliationService.run(
            market=self.market,
            actor=self.operations_user,
        )
        mismatch = MarketReconciliationMismatch.objects.create(
            run=run,
            code="TEST_EVIDENCE",
            severity=MarketReconciliationMismatch.Severity.ERROR,
            market_id_snapshot=self.market.id,
            explanation="Privacy-safe evidence.",
        )
        adjustment = MarketFinancialAdjustmentService.propose(
            actor=self.operations_user,
            reason="Resolve mismatch",
            evidence_reference="A-7",
            currency="UGX",
            market=self.market,
            mismatch=mismatch,
            lines=[
                {"wallet_id": self.wallet.id, "direction": "DEBIT", "amount": "1.0000"},
                {"wallet_id": credit.id, "direction": "CREDIT", "amount": "1.0000"},
            ],
        )
        with self.assertRaises(PermissionDenied):
            MarketFinancialAdjustmentService.propose(
                actor=self.owner,
                reason="No permission",
                evidence_reference="A-8",
                currency="UGX",
                lines=[],
            )
        with self.assertRaises(PermissionDenied):
            MarketFinancialAdjustmentService.decide(
                adjustment_id=adjustment.id,
                actor=self.owner,
                decision=MarketFinancialAdjustmentApproval.Decision.REJECTED,
            )
        rejected = MarketFinancialAdjustmentService.decide(
            adjustment_id=adjustment.id,
            actor=self.approver_user,
            decision=MarketFinancialAdjustmentApproval.Decision.REJECTED,
        )
        replay = MarketFinancialAdjustmentService.decide(
            adjustment_id=adjustment.id,
            actor=self.approver_user,
            decision=MarketFinancialAdjustmentApproval.Decision.REJECTED,
        )
        self.assertEqual(replay.id, rejected.id)
        self.assertEqual(rejected.mismatch_id, mismatch.id)
        with self.assertRaises(ValidationError):
            MarketFinancialAdjustmentService.decide(
                adjustment_id=adjustment.id,
                actor=self.approver_user,
                decision=MarketFinancialAdjustmentApproval.Decision.APPROVED,
            )

    def test_proposer_with_approval_permission_cannot_decide(self):
        UserRoleFactory(
            user=self.operations_user,
            role=Role.objects.get(name="Expiry Approval"),
        )
        credit = self.create_funded_wallet()
        adjustment = MarketFinancialAdjustmentService.propose(
            actor=self.operations_user,
            reason="Separation",
            evidence_reference="A-9",
            currency="UGX",
            lines=[
                {"wallet_id": self.wallet.id, "direction": "DEBIT", "amount": "1"},
                {"wallet_id": credit.id, "direction": "CREDIT", "amount": "1"},
            ],
        )
        for decision in MarketFinancialAdjustmentApproval.Decision.values:
            with self.assertRaises(ValidationError):
                MarketFinancialAdjustmentService.decide(
                    adjustment_id=adjustment.id,
                    actor=self.operations_user,
                    decision=decision,
                )

    def test_financial_models_reject_instance_and_queryset_mutation(self):
        schedule = self.activate_schedule()
        self.create_sell_order(quantity=Decimal("1"), limit_price=Decimal("0.5"))
        order = self.create_buy_order(quantity=Decimal("1"), limit_price=Decimal("0.6"))
        fee = MarketFeeLedgerEntry.objects.filter(fill__buy_order=order).first()
        run = MarketReconciliationService.run(
            market=self.market,
            actor=self.operations_user,
        )
        mismatch = MarketReconciliationMismatch.objects.create(
            run=run,
            code="IMMUTABLE",
            severity=MarketReconciliationMismatch.Severity.ERROR,
            explanation="Immutable snapshot.",
        )
        credit = self.create_funded_wallet()
        adjustment = MarketFinancialAdjustmentService.propose(
            actor=self.operations_user,
            reason="Immutable",
            evidence_reference="A-10",
            currency="UGX",
            lines=[
                {"wallet_id": self.wallet.id, "direction": "DEBIT", "amount": "1"},
                {"wallet_id": credit.id, "direction": "CREDIT", "amount": "1"},
            ],
        )
        adjustment = MarketFinancialAdjustmentService.decide(
            adjustment_id=adjustment.id,
            actor=self.approver_user,
            decision=MarketFinancialAdjustmentApproval.Decision.APPROVED,
        )
        line = adjustment.lines.first()
        approval = adjustment.approval

        for record in (fee, mismatch, approval, line, run, adjustment, schedule):
            with self.assertRaises(ValidationError):
                record.delete()
            record.updated_at = timezone.now()
            with self.assertRaises(ValidationError):
                record.save()
        for model, pk in (
            (MarketFeeLedgerEntry, fee.id),
            (MarketReconciliationMismatch, mismatch.id),
            (MarketFinancialAdjustmentLine, line.id),
            (MarketFinancialAdjustmentApproval, approval.id),
            (MarketReconciliationRun, run.id),
            (MarketFinancialAdjustment, adjustment.id),
            (MarketFeeSchedule, schedule.id),
        ):
            with self.assertRaises(ValidationError):
                model.objects.filter(id=pk).update(updated_at=timezone.now())
            with self.assertRaises(ValidationError):
                model.objects.filter(id=pk).delete()


class ReconciliationScopeAndDetectorTests(FinancialIntegrityServiceTests):
    def create_fill(self, *, market=None, quantity="1.0000"):
        market = market or self.market
        outcome = market.outcomes.get(side=self.outcome.side)
        position, _ = MarketPosition.objects.get_or_create(
            user=self.seller,
            market=market,
            outcome=outcome,
            defaults={
                "quantity": Decimal("10.0000"),
                "reserved_quantity": Decimal("0.0000"),
                "average_entry_price": Decimal("0.40000"),
                "total_cost": Decimal("4.0000"),
                "realized_pnl": Decimal("0.0000"),
            },
        )
        MarketParticipationService.place_order(
            user=self.seller,
            market_id=market.id,
            outcome_id=outcome.id,
            side=MarketOrder.Side.SELL,
            quantity=Decimal(quantity),
            limit_price=Decimal("0.50000"),
        )
        return MarketParticipationService.place_order(
            user=self.owner,
            market_id=market.id,
            outcome_id=outcome.id,
            side=MarketOrder.Side.BUY,
            quantity=Decimal(quantity),
            limit_price=Decimal("0.60000"),
        )

    def test_market_wallet_and_combined_scopes_exclude_unrelated_records(self):
        first_order = self.create_fill()
        second_market = self.open_market(self.create_market())
        second_order = self.create_fill(market=second_market)
        unrelated = fund_market_wallet(UserFactory())

        market_run = MarketReconciliationService.run(
            market=self.market,
            actor=self.operations_user,
        )
        wallet_run = MarketReconciliationService.run(
            wallet=self.wallet,
            actor=self.operations_user,
        )
        combined_run = MarketReconciliationService.run(
            market=self.market,
            wallet=self.wallet,
            actor=self.operations_user,
        )
        unrelated_run = MarketReconciliationService.run(
            wallet=unrelated,
            actor=self.operations_user,
        )

        self.assertEqual(market_run.fill_count, 1)
        self.assertEqual(market_run.total_fee_amount, Decimal("0.0000"))
        self.assertEqual(wallet_run.fill_count, 2)
        self.assertEqual(combined_run.fill_count, 1)
        self.assertEqual(unrelated_run.fill_count, 0)
        self.assertEqual(unrelated_run.order_count, 0)
        self.assertEqual(
            MarketFeeLedgerEntry.objects.filter(fill__in=[first_order.buy_fills.first()]).count(),
            2,
        )
        self.assertTrue(second_order.buy_fills.exists())

    def test_buy_and_sell_reservations_use_current_attributable_effects(self):
        sell_position = MarketPosition.objects.create(
            user=self.seller,
            market=self.market,
            outcome=self.outcome,
            quantity=Decimal("5.0000"),
            reserved_quantity=Decimal("0.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("2.0000"),
        )
        for quantity in ("1.0000", "2.0000"):
            MarketParticipationService.place_order(
                user=self.seller,
                market_id=self.market.id,
                outcome_id=self.outcome.id,
                side=MarketOrder.Side.SELL,
                quantity=Decimal(quantity),
                limit_price=Decimal("0.90000"),
            )
        buy = self.create_buy_order(
            quantity=Decimal("2.0000"),
            limit_price=Decimal("0.10000"),
        )
        clean = MarketReconciliationService.run(
            run_date=timezone.localdate(),
            market=self.market,
            actor=self.operations_user,
        )
        self.assertFalse(
            clean.mismatches.filter(
                code__in=[
                    "OPEN_BUY_RESERVATION_MISMATCH",
                    "OPEN_SELL_RESERVATION_MISMATCH",
                ]
            ).exists()
        )

        WalletService.reserve(
            user=self.owner,
            currency="UGX",
            amount=Decimal("1.0000"),
            idempotency_reference=uuid4(),
            market=self.market,
            order=buy,
        )
        MarketPosition.objects.filter(id=sell_position.id).update(
            reserved_quantity=Decimal("2.5000")
        )
        mismatched = MarketReconciliationService.run(
            run_date=timezone.localdate() + timedelta(days=1),
            market=self.market,
            actor=self.operations_user,
        )
        self.assertTrue(mismatched.mismatches.filter(code="OPEN_BUY_RESERVATION_MISMATCH").exists())
        self.assertTrue(
            mismatched.mismatches.filter(code="OPEN_SELL_RESERVATION_MISMATCH").exists()
        )

    def test_terminal_reservation_and_duplicate_release_detection(self):
        order = self.create_buy_order(
            quantity=Decimal("1.0000"),
            limit_price=Decimal("0.10000"),
        )
        MarketParticipationService.cancel_order(user=self.owner, order_id=order.id)
        WalletService.reserve(
            user=self.owner,
            currency="UGX",
            amount=Decimal("0.1000"),
            idempotency_reference=uuid4(),
            market=self.market,
            order=order,
        )
        WalletService.release(
            user=self.owner,
            currency="UGX",
            amount=Decimal("0.0500"),
            idempotency_reference=uuid4(),
            market=self.market,
            order=order,
        )
        run = MarketReconciliationService.run(
            market=self.market,
            actor=self.operations_user,
        )
        self.assertTrue(run.mismatches.filter(code="TERMINAL_BUY_RESERVATION_MISMATCH").exists())
        self.assertTrue(run.mismatches.filter(code="DUPLICATE_ORDER_RELEASE_EFFECT").exists())

    def test_fill_fee_and_wallet_effect_detectors_are_role_aware(self):
        self.activate_schedule()
        order = self.create_fill()
        fill = order.buy_fills.get()
        original = fill.fee_entries.get(participant=self.owner)
        MarketFeeLedgerEntry.objects.create(
            idempotency_reference=uuid4(),
            schedule=original.schedule,
            schedule_version=999,
            market=fill.market,
            participant=self.owner,
            fill=fill,
            order=fill.sell_order,
            fee_type=MarketFeeLedgerEntry.FeeType.MAKER,
            rate_bps=999,
            gross_amount=Decimal("9.0000"),
            fee_amount=Decimal("1.0000"),
            net_amount=Decimal("8.0000"),
            currency="USD",
        )
        WalletService.credit(
            user=fill.sell_order.user,
            currency="UGX",
            amount=Decimal("0.5000"),
            idempotency_reference=uuid4(),
            market=fill.market,
            order=fill.sell_order,
            fill=fill,
        )
        run = MarketReconciliationService.run(
            market=self.market,
            actor=self.operations_user,
        )
        codes = set(run.mismatches.values_list("code", flat=True))
        self.assertIn("FILL_FEE_RECORD_COUNT_MISMATCH", codes)
        self.assertIn("FILL_FEE_PARTICIPANT_MISMATCH", codes)
        self.assertIn("FILL_SELL_EFFECT_COUNT_MISMATCH", codes)

    def test_fee_rate_amount_net_and_currency_detectors(self):
        self.activate_schedule()
        order = self.create_fill()
        fill = order.buy_fills.get()
        expected = fill.fee_entries.get(participant=self.owner)
        invalid = MarketFeeLedgerEntry(
            idempotency_reference=uuid4(),
            schedule=expected.schedule,
            schedule_version=999,
            market=fill.market,
            participant=self.owner,
            fill=fill,
            order=fill.sell_order,
            fee_type=MarketFeeLedgerEntry.FeeType.MAKER,
            rate_bps=999,
            gross_amount=Decimal("8.0000"),
            fee_amount=Decimal("1.0000"),
            net_amount=Decimal("7.0000"),
            currency="USD",
        )
        run = MarketReconciliationRun.objects.create(
            reference=uuid4(),
            run_date=timezone.localdate(),
            market=self.market,
            status=MarketReconciliationRun.Status.RUNNING,
        )
        MarketReconciliationService._fill_fee(
            run,
            fill,
            fill.buy_order,
            MarketFeeLedgerEntry.FeeType.TAKER,
            Decimal("0.5000"),
            [invalid],
        )
        codes = set(run.mismatches.values_list("code", flat=True))
        self.assertTrue(
            {
                "FILL_FEE_ORDER_MISMATCH",
                "FILL_FEE_TYPE_MISMATCH",
                "FILL_FEE_RATE_MISMATCH",
                "FILL_FEE_GROSS_MISMATCH",
                "FILL_FEE_SCHEDULE_VERSION_MISMATCH",
                "FILL_FEE_CURRENCY_MISMATCH",
                "FILL_FEE_AMOUNT_MISMATCH",
                "FILL_FEE_NET_MISMATCH",
            }.issubset(codes)
        )

    def test_failed_reconciliation_records_failed_snapshot(self):
        with patch.object(
            MarketReconciliationService,
            "_detect",
            side_effect=RuntimeError("detector failed"),
        ):
            with self.assertRaises(RuntimeError):
                MarketReconciliationService.run(
                    market=self.market,
                    actor=self.operations_user,
                )
        run = MarketReconciliationRun.objects.get(market=self.market)
        self.assertEqual(run.status, MarketReconciliationRun.Status.FAILED)
        self.assertIsNotNone(run.completed_at)


class SettlementReconciliationHardeningTests(SettlementFixtureMixin, TestCase):
    def test_settlement_reconciliation_validates_winner_loser_and_scope(self):
        market = self.resolve_market()
        winner = self.create_position(
            market=market,
            quantity="3.0000",
            cost="1.5000",
        )
        loser = self.create_position(
            market=market,
            outcome=market.outcomes.exclude(id=market.winning_outcome_id).get(),
            quantity="2.0000",
            cost="1.0000",
        )
        MarketSettlementService.settle_market(
            market_id=market.id,
            actor=self.actor,
        )
        run = MarketReconciliationService.run(
            market=market,
            actor=self.outsider,
        )
        settlement_codes = run.mismatches.filter(code__startswith="SETTLEMENT")
        self.assertFalse(settlement_codes.exists())
        self.assertFalse(run.mismatches.filter(code="DUPLICATE_SETTLEMENT_FINAL_EFFECT").exists())
        winner_record = winner.settlement_record
        loser_record = loser.settlement_record
        self.assertEqual(winner_record.payout_amount, Decimal("3.0000"))
        self.assertEqual(winner_record.net_payout_amount, Decimal("3.0000"))
        self.assertEqual(loser_record.payout_amount, Decimal("0.0000"))
        self.assertIsNone(loser_record.wallet_ledger_entry)

    def test_settlement_detectors_find_fee_credit_and_value_mismatches(self):
        market = self.resolve_market()
        position = self.create_position(
            market=market,
            quantity="2.0000",
            cost="1.0000",
        )
        MarketSettlementService.settle_market(
            market_id=market.id,
            actor=self.actor,
        )
        record = position.settlement_record
        MarketFeeLedgerEntry.objects.create(
            idempotency_reference=uuid4(),
            market=market,
            participant=record.participant,
            fee_type=MarketFeeLedgerEntry.FeeType.SETTLEMENT,
            rate_bps=100,
            gross_amount=Decimal("2.0000"),
            fee_amount=Decimal("0.0200"),
            net_amount=Decimal("1.9800"),
            currency="UGX",
        )
        WalletService.credit(
            user=record.participant,
            currency="UGX",
            amount=record.net_payout_amount,
            idempotency_reference=uuid4(),
            market=market,
        )
        run = MarketReconciliationService.run(
            market=market,
            actor=self.outsider,
        )
        codes = set(run.mismatches.values_list("code", flat=True))
        self.assertIn("DUPLICATE_SETTLEMENT_FINAL_EFFECT", codes)

        synthetic = MarketReconciliationRun.objects.create(
            reference=uuid4(),
            run_date=timezone.localdate() + timedelta(days=1),
            market=market,
            status=MarketReconciliationRun.Status.RUNNING,
        )
        MarketReconciliationService._final_values(
            synthetic,
            "SETTLEMENT",
            record.participant_id,
            market.id,
            (
                (Decimal("1"), Decimal("2")),
                (Decimal("1"), Decimal("0")),
                (Decimal("1"), Decimal("2")),
            ),
        )
        self.assertEqual(synthetic.mismatches.count(), 3)


class VoidRefundReconciliationHardeningTests(VoidRefundFixtureMixin, TestCase):
    def test_void_refund_reconciliation_validates_gross_fee_net_and_credit(self):
        market = self.void_market(self.approve_market(self.create_market("Reconcile void")))
        position = self.position(
            market,
            quantity="4.0000",
            cost="2.4000",
        )
        MarketVoidRefundService.refund_void_market(
            market_id=market.id,
            actor=self.actor,
        )
        run = MarketReconciliationService.run(
            market=market,
            actor=self.creator,
        )
        self.assertFalse(run.mismatches.filter(code__startswith="VOID_REFUND").exists())
        self.assertFalse(run.mismatches.filter(code="VOID_MARKET_SETTLEMENT_FEE_PRESENT").exists())
        record = position.void_refund_record
        self.assertEqual(record.refund_amount, Decimal("2.4000"))
        self.assertEqual(record.net_refund_amount, Decimal("2.4000"))

    def test_void_refund_detectors_find_duplicate_and_settlement_fee(self):
        market = self.void_market(self.approve_market(self.create_market("Invalid void")))
        position = self.position(
            market,
            quantity="2.0000",
            cost="1.0000",
        )
        MarketVoidRefundService.refund_void_market(
            market_id=market.id,
            actor=self.actor,
        )
        record = position.void_refund_record
        MarketFeeLedgerEntry.objects.create(
            idempotency_reference=uuid4(),
            market=market,
            participant=record.participant,
            fee_type=MarketFeeLedgerEntry.FeeType.SETTLEMENT,
            rate_bps=0,
            gross_amount=Decimal("1.0000"),
            fee_amount=Decimal("0.0000"),
            net_amount=Decimal("1.0000"),
            currency="UGX",
        )
        WalletService.credit(
            user=record.participant,
            currency="UGX",
            amount=record.net_refund_amount,
            idempotency_reference=uuid4(),
            market=market,
        )
        run = MarketReconciliationService.run(
            market=market,
            actor=self.creator,
        )
        codes = set(run.mismatches.values_list("code", flat=True))
        self.assertIn("VOID_MARKET_SETTLEMENT_FEE_PRESENT", codes)
        self.assertIn("DUPLICATE_VOID_REFUND_FINAL_EFFECT", codes)


class FinancialIntegrityAPIAndCommandTests(FinancialIntegrityServiceTests):
    def setUp(self):
        super().setUp()
        self.api = APIClient()

    def authenticate(self, user):
        self.api.force_authenticate(user=user)

    def test_reconciliation_scope_filters_export_and_privacy(self):
        self.authenticate(self.operations_user)
        response = self.api.post(
            reverse("markets:market-reconciliation-start"),
            {
                "market_id": str(self.market.id),
                "wallet_id": str(self.wallet.id),
                "run_date": timezone.localdate().isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        run = MarketReconciliationRun.objects.get(id=response.data["id"])
        self.assertEqual(run.market_id, self.market.id)
        self.assertEqual(run.wallet_id, self.wallet.id)
        first = MarketReconciliationMismatch.objects.create(
            run=run,
            code="SAFE_ONE",
            severity=MarketReconciliationMismatch.Severity.ERROR,
            market_id_snapshot=self.market.id,
            participant_id_snapshot=self.owner.id,
            explanation="Reservation totals differ.",
        )
        other_run = MarketReconciliationRun.objects.create(
            reference=uuid4(),
            run_date=timezone.localdate() + timedelta(days=1),
            status=MarketReconciliationRun.Status.RUNNING,
        )
        MarketReconciliationMismatch.objects.create(
            run=other_run,
            code="SAFE_TWO",
            severity=MarketReconciliationMismatch.Severity.WARNING,
            explanation="Unrelated run.",
        )

        listing = self.api.get(
            reverse("markets:market-reconciliation-mismatch-list"),
            {
                "run_id": str(run.id),
                "code": "SAFE_ONE",
                "severity": "ERROR",
                "resolution_status": "OPEN",
            },
        )
        self.assertEqual(listing.status_code, status.HTTP_200_OK)
        self.assertEqual(listing.data["count"], 1)
        item = listing.data["results"][0]
        self.assertEqual(item["id"], str(first.id))
        self.assertNotIn("email", str(item).lower())

        export = self.api.get(reverse("markets:market-reconciliation-export", args=[run.id]))
        self.assertEqual(export.status_code, status.HTTP_200_OK)
        csv_text = export.content.decode()
        self.assertIn("SAFE_ONE", csv_text)
        self.assertNotIn("SAFE_TWO", csv_text)
        self.assertNotIn(self.owner.email, csv_text)

    def test_adjustment_and_fee_method_and_permission_boundaries(self):
        credit = Wallet.objects.create(
            user=UserFactory(),
            currency="UGX",
            available_balance=Decimal("0.0000"),
        )
        proposal_url = reverse("markets:market-adjustment-propose")
        payload = {
            "reason": "API correction",
            "evidence_reference": "API-1",
            "currency": "UGX",
            "lines": [
                {
                    "wallet_id": str(self.wallet.id),
                    "direction": "DEBIT",
                    "amount": "1.0000",
                },
                {
                    "wallet_id": str(credit.id),
                    "direction": "CREDIT",
                    "amount": "1.0000",
                },
            ],
        }
        self.authenticate(self.owner)
        denied = self.api.post(proposal_url, payload, format="json")
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        self.authenticate(self.operations_user)
        created = self.api.post(proposal_url, payload, format="json")
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        adjustment_id = created.data["id"]
        approve_url = reverse("markets:market-adjustment-approve", args=[adjustment_id])
        denied = self.api.post(approve_url, {}, format="json")
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        self.authenticate(self.approver_user)
        approved = self.api.post(approve_url, {}, format="json")
        self.assertEqual(approved.status_code, status.HTTP_200_OK, approved.data)
        detail_url = reverse("markets:market-adjustment-detail", args=[adjustment_id])
        self.authenticate(self.operations_user)
        self.assertEqual(
            self.api.patch(detail_url, {"reason": "changed"}, format="json").status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.api.delete(detail_url).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

        schedule = MarketFeeService.create_draft(
            actor=self.operations_user,
            market=self.market,
            maker_fee_bps=0,
            taker_fee_bps=0,
            settlement_fee_bps=0,
            refund_fee_bps=0,
        )
        fee_url = reverse("markets:market-fee-schedule-detail", args=[schedule.id])
        self.authenticate(self.operations_user)
        self.assertEqual(
            self.api.patch(fee_url, {"maker_fee_bps": 1}, format="json").status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.api.delete(fee_url).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def test_reconciliation_commands_validate_repeat_and_failure(self):
        with self.assertRaises(CommandError):
            call_command("reconcile_market_finances", limit=0)
        call_command(
            "reconcile_market_finances",
            market_id=str(self.market.id),
            wallet_id=str(self.wallet.id),
            date=timezone.localdate(),
            limit=100,
        )
        call_command(
            "reconcile_market_finances",
            market_id=str(self.market.id),
            wallet_id=str(self.wallet.id),
            date=timezone.localdate(),
            limit=100,
        )
        self.assertEqual(
            MarketReconciliationRun.objects.filter(
                market=self.market,
                wallet=self.wallet,
            ).count(),
            1,
        )
        with patch.object(
            MarketReconciliationService,
            "run",
            side_effect=RuntimeError("failed run"),
        ):
            with self.assertRaises(RuntimeError):
                call_command("reconcile_market_finances")


class OrderExpiryHardeningCoverageTests(MarketOrderExpiryServiceTests):
    def test_empty_sweep_and_existing_audit_replay(self):
        self.assertEqual(MarketOrderExpiryService.expire_due_orders(), [])
        order = self.create_buy_order(
            quantity=Decimal("1.0000"),
            time_in_force=MarketOrder.TimeInForce.GTD,
            expires_at=self.now + timedelta(minutes=5),
        )
        MarketOrder.objects.filter(id=order.id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        first = MarketOrderExpiryService.expire_order(
            order_id=order.id,
            source="SYSTEM",
            reason="Deadline elapsed.",
        )
        replay = MarketOrderExpiryService.expire_order(
            order_id=order.id,
            source="SYSTEM",
            reason="Ignored replay text.",
        )
        self.assertEqual(replay.id, first.id)

    def test_missing_sell_position_fails_without_expiry(self):
        order = MarketOrder.objects.create(
            user=self.seller,
            market=self.market,
            outcome=self.outcome,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("1.0000"),
            filled_quantity=Decimal("0.0000"),
            limit_price=Decimal("0.50000"),
            status=MarketOrder.Status.OPEN,
            time_in_force=MarketOrder.TimeInForce.GTD,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        MarketOrder.objects.filter(id=order.id).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(ValidationError):
            MarketOrderExpiryService.expire_order(
                order_id=order.id,
                source="SYSTEM",
                reason="Deadline elapsed.",
            )
        order.refresh_from_db()
        self.assertEqual(order.status, MarketOrder.Status.OPEN)

    def test_expiry_command_rejects_invalid_limit(self):
        with self.assertRaises(CommandError):
            call_command("expire_market_orders", limit=0)


class AdjustmentValidationBranchTests(FinancialIntegrityServiceTests):
    def test_validation_branches(self):
        second_wallet = fund_market_wallet(self.seller)
        valid = [
            {"wallet_id": self.wallet.id, "direction": "DEBIT", "amount": "1.0000"},
            {"wallet_id": second_wallet.id, "direction": "CREDIT", "amount": "1.0000"},
        ]
        cases = [
            ("", "E", valid),
            ("R", "", valid),
            ("R", "E", [{"amount": "1.0000"}, valid[1]]),
            ("R", "E", [dict(valid[0], direction="OTHER"), valid[1]]),
            ("R", "E", [valid[0], dict(valid[1], amount="2.0000")]),
            ("R", "E", [dict(valid[0], amount="invalid"), valid[1]]),
            ("R", "E", [dict(valid[0], amount="NaN"), valid[1]]),
        ]
        for reason, evidence, lines in cases:
            with self.assertRaises(ValidationError):
                MarketFinancialAdjustmentService.propose(
                    actor=self.operations_user,
                    reason=reason,
                    evidence_reference=evidence,
                    currency="UGX",
                    lines=lines,
                )
        with self.assertRaises(ValidationError):
            MarketFinancialAdjustmentService.propose(
                actor=self.operations_user,
                reason="R",
                evidence_reference="E",
                currency="UGX",
                lines=[
                    {"wallet_id": uuid4(), "direction": "DEBIT", "amount": "1.0000"},
                    valid[1],
                ],
            )
        adjustment = MarketFinancialAdjustmentService.propose(
            actor=self.operations_user,
            reason="R",
            evidence_reference="E",
            currency="UGX",
            lines=valid,
        )
        with self.assertRaises(ValidationError):
            MarketFinancialAdjustmentService.decide(
                adjustment_id=adjustment.id,
                actor=self.approver_user,
                decision="INVALID",
            )

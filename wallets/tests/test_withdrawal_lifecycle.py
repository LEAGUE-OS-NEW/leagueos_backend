from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from authentication.tests.factories import (
    UserFactory,
)
from wallets.models import (
    AuditLog,
    LedgerEntry,
    Wallet,
    WalletTransaction,
    WithdrawalRequest,
)
from wallets.services.wallet_service import (
    WalletService,
)
from wallets.tests.factories import (
    WalletFactory,
)


class WithdrawalRequestLifecycleTests(TestCase):
    def setUp(self):
        self.user = UserFactory(
            is_verified=True,
            is_active=True,
        )
        self.wallet = WalletFactory(
            user=self.user,
            currency="UGX",
            available_balance=Decimal("100000.0000"),
            reserved_balance=Decimal("0.0000"),
        )
        self.destination = {"mobile_money_number": "0777123456"}

    def create_request(
        self,
        *,
        key=None,
        amount=Decimal("20000.0000"),
    ):
        return WalletService.create_withdrawal_request(
            user=self.user,
            amount=amount,
            currency="UGX",
            destination=self.destination,
            idempotency_key=key or uuid4(),
        )

    def test_request_reserves_funds(self):
        withdrawal = self.create_request()

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("80000.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("20000.0000"),
        )

        self.assertEqual(
            withdrawal.status,
            WithdrawalRequest.Status.PENDING_APPROVAL,
        )

        self.assertIsNotNone(withdrawal.transaction_id)

        transaction = withdrawal.transaction

        self.assertEqual(
            transaction.transaction_type,
            WalletTransaction.TransactionType.WITHDRAWAL,
        )
        self.assertEqual(
            transaction.status,
            WalletTransaction.Status.PENDING,
        )

        reserve = LedgerEntry.objects.get(
            transaction=transaction,
            entry_type=LedgerEntry.EntryType.RESERVE,
        )

        self.assertEqual(
            reserve.amount,
            Decimal("20000.0000"),
        )

        self.assertTrue(
            AuditLog.objects.filter(
                action="WITHDRAWAL_REQUESTED",
                related_object_id=withdrawal.id,
            ).exists()
        )

    def test_idempotent_replay_does_not_double_reserve(
        self,
    ):
        key = uuid4()

        first = self.create_request(key=key)
        second = self.create_request(key=key)

        self.assertEqual(
            first.id,
            second.id,
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("80000.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("20000.0000"),
        )

        self.assertEqual(
            WithdrawalRequest.objects.count(),
            1,
        )
        self.assertEqual(
            WalletTransaction.objects.filter(
                transaction_type=WalletTransaction.TransactionType.WITHDRAWAL
            ).count(),
            1,
        )
        self.assertEqual(
            LedgerEntry.objects.filter(entry_type=LedgerEntry.EntryType.RESERVE).count(),
            1,
        )
        self.assertEqual(
            AuditLog.objects.filter(action="WITHDRAWAL_REQUESTED").count(),
            1,
        )

    def test_idempotency_key_rejects_changed_amount(
        self,
    ):
        key = uuid4()

        self.create_request(
            key=key,
            amount=Decimal("20000.0000"),
        )

        with self.assertRaises(ValidationError):
            self.create_request(
                key=key,
                amount=Decimal("25000.0000"),
            )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("80000.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("20000.0000"),
        )

    def test_unverified_user_cannot_withdraw(
        self,
    ):
        self.user.is_verified = False
        self.user.save(update_fields=["is_verified"])

        with self.assertRaises(ValidationError):
            self.create_request()

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("100000.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("0.0000"),
        )
        self.assertEqual(
            WithdrawalRequest.objects.count(),
            0,
        )

    def test_suspended_wallet_cannot_withdraw(
        self,
    ):
        self.wallet.status = Wallet.Status.SUSPENDED
        self.wallet.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.create_request()

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("100000.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("0.0000"),
        )
        self.assertEqual(
            WithdrawalRequest.objects.count(),
            0,
        )

    def test_insufficient_funds_rolls_back_everything(
        self,
    ):
        with self.assertRaises(ValidationError):
            self.create_request(amount=Decimal("150000.0000"))

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("100000.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("0.0000"),
        )

        self.assertEqual(
            WithdrawalRequest.objects.count(),
            0,
        )
        self.assertEqual(
            WalletTransaction.objects.filter(
                transaction_type=WalletTransaction.TransactionType.WITHDRAWAL
            ).count(),
            0,
        )
        self.assertEqual(
            AuditLog.objects.count(),
            0,
        )


class WithdrawalStateTransitionTests(TestCase):
    def setUp(self):
        self.user = UserFactory(
            is_verified=True,
            is_active=True,
        )
        self.actor = UserFactory(
            is_active=True,
        )
        self.wallet = WalletFactory(
            user=self.user,
            currency="UGX",
            available_balance=Decimal("100000.0000"),
            reserved_balance=Decimal("0.0000"),
        )
        self.destination = {"mobile_money_number": "0777123456"}

    def create_request(self):
        return WalletService.create_withdrawal_request(
            user=self.user,
            amount=Decimal("20000.0000"),
            currency="UGX",
            destination=self.destination,
            idempotency_key=uuid4(),
        )

    def approve(self, withdrawal):
        return WalletService.approve_withdrawal(
            withdrawal_id=withdrawal.id,
            actor=self.actor,
        )

    def test_manual_approval_keeps_funds_reserved(self):
        withdrawal = self.create_request()

        approved = self.approve(withdrawal)

        approved.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            approved.status,
            WithdrawalRequest.Status.APPROVED,
        )
        self.assertEqual(
            approved.approval_mode,
            WithdrawalRequest.ApprovalMode.MANUAL,
        )
        self.assertEqual(
            approved.approved_by_id,
            self.actor.id,
        )
        self.assertIsNotNone(approved.approved_at)

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("80000.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("20000.0000"),
        )

        # Replaying approval is a no-op.
        self.approve(approved)

        self.assertEqual(
            AuditLog.objects.filter(
                action="WITHDRAWAL_APPROVED",
                related_object_id=approved.id,
            ).count(),
            1,
        )

    def test_rejection_releases_reserved_funds_once(self):
        withdrawal = self.create_request()

        rejected = WalletService.reject_withdrawal(
            withdrawal_id=withdrawal.id,
            actor=self.actor,
            reason="Manual review rejected payout.",
        )

        rejected.refresh_from_db()
        rejected.transaction.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            rejected.status,
            WithdrawalRequest.Status.REJECTED,
        )
        self.assertEqual(
            rejected.transaction.status,
            WalletTransaction.Status.CANCELLED,
        )
        self.assertEqual(
            self.wallet.available_balance,
            Decimal("100000.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("0.0000"),
        )

        WalletService.reject_withdrawal(
            withdrawal_id=rejected.id,
            actor=self.actor,
            reason="Manual review rejected payout.",
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("100000.0000"),
        )
        self.assertEqual(
            LedgerEntry.objects.filter(
                transaction=rejected.transaction,
                entry_type=LedgerEntry.EntryType.RELEASE,
            ).count(),
            1,
        )

    def test_processing_requires_approval(self):
        withdrawal = self.create_request()

        with self.assertRaises(ValidationError):
            WalletService.mark_withdrawal_processing(
                withdrawal_id=withdrawal.id,
                actor=self.actor,
            )

        self.approve(withdrawal)

        processing = WalletService.mark_withdrawal_processing(
            withdrawal_id=withdrawal.id,
            actor=self.actor,
        )

        processing.refresh_from_db()

        self.assertEqual(
            processing.status,
            WithdrawalRequest.Status.PROCESSING,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                action="WITHDRAWAL_PROCESSING",
                related_object_id=processing.id,
            ).count(),
            1,
        )

        WalletService.mark_withdrawal_processing(
            withdrawal_id=processing.id,
            actor=self.actor,
        )

        self.assertEqual(
            AuditLog.objects.filter(
                action="WITHDRAWAL_PROCESSING",
                related_object_id=processing.id,
            ).count(),
            1,
        )

    def test_completion_consumes_reserved_funds_once(self):
        withdrawal = self.create_request()
        self.approve(withdrawal)
        processing = WalletService.mark_withdrawal_processing(
            withdrawal_id=withdrawal.id,
            actor=self.actor,
        )

        completed = WalletService.complete_withdrawal(
            withdrawal_id=processing.id,
            actor=self.actor,
            provider_reference="MTN-PAYOUT-123",
        )

        completed.refresh_from_db()
        completed.transaction.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            completed.status,
            WithdrawalRequest.Status.COMPLETED,
        )
        self.assertEqual(
            completed.transaction.status,
            WalletTransaction.Status.COMPLETED,
        )
        self.assertEqual(
            completed.transaction.provider_reference,
            "MTN-PAYOUT-123",
        )
        self.assertIsNotNone(completed.transaction.completed_at)

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("80000.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("0.0000"),
        )

        debit = LedgerEntry.objects.get(
            transaction=completed.transaction,
            entry_type=LedgerEntry.EntryType.DEBIT,
        )

        self.assertEqual(
            debit.credit_account,
            LedgerEntry.AccountType.PROVIDER_PAYABLE,
        )

        WalletService.complete_withdrawal(
            withdrawal_id=completed.id,
            actor=self.actor,
            provider_reference="MTN-PAYOUT-123",
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("0.0000"),
        )
        self.assertEqual(
            LedgerEntry.objects.filter(
                transaction=completed.transaction,
                entry_type=LedgerEntry.EntryType.DEBIT,
            ).count(),
            1,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                action="WITHDRAWAL_COMPLETED",
                related_object_id=completed.id,
            ).count(),
            1,
        )

    def test_failed_payout_returns_reserved_funds_once(self):
        withdrawal = self.create_request()
        self.approve(withdrawal)

        failed = WalletService.fail_withdrawal(
            withdrawal_id=withdrawal.id,
            actor=self.actor,
            reason="Provider payout failed.",
        )

        failed.refresh_from_db()
        failed.transaction.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            failed.status,
            WithdrawalRequest.Status.FAILED,
        )
        self.assertEqual(
            failed.failure_reason,
            "Provider payout failed.",
        )
        self.assertEqual(
            failed.transaction.status,
            WalletTransaction.Status.FAILED,
        )

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("100000.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("0.0000"),
        )

        WalletService.fail_withdrawal(
            withdrawal_id=failed.id,
            actor=self.actor,
            reason="Provider payout failed.",
        )

        self.assertEqual(
            LedgerEntry.objects.filter(
                transaction=failed.transaction,
                entry_type=LedgerEntry.EntryType.RELEASE,
            ).count(),
            1,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                action="WITHDRAWAL_FAILED",
                related_object_id=failed.id,
            ).count(),
            1,
        )

    def test_completion_requires_processing_state(self):
        withdrawal = self.create_request()

        with self.assertRaises(ValidationError):
            WalletService.complete_withdrawal(
                withdrawal_id=withdrawal.id,
                actor=self.actor,
                provider_reference="MTN-PAYOUT-INVALID",
            )

        self.wallet.refresh_from_db()

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("80000.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("20000.0000"),
        )


@override_settings(
    WALLET_WITHDRAWAL_AUTO_APPROVAL_ENABLED=True,
    WALLET_WITHDRAWAL_AUTO_APPROVAL_MAX_SINGLE_UGX=Decimal("250000"),
    WALLET_WITHDRAWAL_AUTO_APPROVAL_MAX_24H_UGX=Decimal("500000"),
    WALLET_WITHDRAWAL_AUTO_APPROVAL_MAX_24H_COUNT=3,
    WALLET_WITHDRAWAL_AUTO_APPROVAL_MAX_7D_UGX=Decimal("1500000"),
    WALLET_WITHDRAWAL_AUTO_APPROVAL_REQUIRE_KNOWN_DESTINATION=True,
)
class WithdrawalAutomaticApprovalTests(TestCase):
    def setUp(self):
        self.user = UserFactory(
            is_verified=True,
            is_active=True,
        )
        self.wallet = WalletFactory(
            user=self.user,
            currency="UGX",
            available_balance=Decimal("2000000.0000"),
            reserved_balance=Decimal("0.0000"),
        )
        self.destination = {"mobile_money_number": "0777123456"}

    def seed_known_destination(self):
        return WithdrawalRequest.objects.create(
            wallet=self.wallet,
            amount=Decimal("10000.0000"),
            destination=self.destination,
            status=(WithdrawalRequest.Status.COMPLETED),
            risk_status=(WithdrawalRequest.RiskStatus.PASSED),
            approval_mode=(WithdrawalRequest.ApprovalMode.MANUAL),
            approval_policy_version="manual",
        )

    def create_request(
        self,
        *,
        amount=Decimal("50000.0000"),
        destination=None,
    ):
        return WalletService.create_withdrawal_request(
            user=self.user,
            amount=amount,
            currency="UGX",
            destination=(destination or self.destination),
            idempotency_key=uuid4(),
        )

    def test_clean_known_destination_is_auto_approved(
        self,
    ):
        self.seed_known_destination()

        withdrawal = self.create_request()

        withdrawal.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            withdrawal.status,
            WithdrawalRequest.Status.APPROVED,
        )
        self.assertEqual(
            withdrawal.approval_mode,
            (WithdrawalRequest.ApprovalMode.AUTOMATIC),
        )
        self.assertEqual(
            withdrawal.risk_status,
            WithdrawalRequest.RiskStatus.PASSED,
        )
        self.assertEqual(
            withdrawal.risk_reasons,
            [],
        )
        self.assertEqual(
            withdrawal.approval_policy_version,
            "withdrawal-auto-v1",
        )
        self.assertIsNone(withdrawal.approved_by)
        self.assertIsNotNone(withdrawal.approved_at)

        self.assertEqual(
            self.wallet.available_balance,
            Decimal("1950000.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("50000.0000"),
        )

        self.assertEqual(
            withdrawal.transaction.status,
            WalletTransaction.Status.PENDING,
        )

        self.assertTrue(
            AuditLog.objects.filter(
                action="WITHDRAWAL_APPROVED",
                related_object_id=withdrawal.id,
                metadata__approval_mode="AUTOMATIC",
            ).exists()
        )

    def test_new_destination_requires_manual_review(
        self,
    ):
        withdrawal = self.create_request()

        withdrawal.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(
            withdrawal.status,
            (WithdrawalRequest.Status.PENDING_APPROVAL),
        )
        self.assertEqual(
            withdrawal.approval_mode,
            (WithdrawalRequest.ApprovalMode.PENDING),
        )
        self.assertEqual(
            withdrawal.risk_status,
            WithdrawalRequest.RiskStatus.FLAGGED,
        )
        self.assertIn(
            "NEW_WITHDRAWAL_DESTINATION",
            withdrawal.risk_reasons,
        )

        # Manual-review withdrawals remain reserved.
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("50000.0000"),
        )

    def test_amount_over_limit_requires_manual_review(
        self,
    ):
        self.seed_known_destination()

        withdrawal = self.create_request(amount=Decimal("300000.0000"))

        withdrawal.refresh_from_db()

        self.assertEqual(
            withdrawal.status,
            (WithdrawalRequest.Status.PENDING_APPROVAL),
        )
        self.assertIn(
            "AMOUNT_ABOVE_AUTO_APPROVAL_LIMIT",
            withdrawal.risk_reasons,
        )

    def test_auto_approval_never_consumes_reserved_funds(
        self,
    ):
        self.seed_known_destination()

        withdrawal = self.create_request()

        self.wallet.refresh_from_db()

        self.assertEqual(
            withdrawal.status,
            WithdrawalRequest.Status.APPROVED,
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("50000.0000"),
        )

        self.assertFalse(
            LedgerEntry.objects.filter(
                transaction=withdrawal.transaction,
                entry_type=LedgerEntry.EntryType.DEBIT,
            ).exists()
        )

    def test_auto_approval_can_be_disabled_globally(
        self,
    ):
        self.seed_known_destination()

        with override_settings(WALLET_WITHDRAWAL_AUTO_APPROVAL_ENABLED=False):
            withdrawal = self.create_request()

        withdrawal.refresh_from_db()

        self.assertEqual(
            withdrawal.risk_status,
            WithdrawalRequest.RiskStatus.PASSED,
        )
        self.assertEqual(
            withdrawal.status,
            (WithdrawalRequest.Status.PENDING_APPROVAL),
        )
        self.assertEqual(
            withdrawal.approval_mode,
            (WithdrawalRequest.ApprovalMode.PENDING),
        )

    def test_daily_request_count_routes_to_manual_review(
        self,
    ):
        self.seed_known_destination()

        for _ in range(2):
            WithdrawalRequest.objects.create(
                wallet=self.wallet,
                amount=Decimal("10000.0000"),
                destination=self.destination,
                status=(WithdrawalRequest.Status.COMPLETED),
                risk_status=(WithdrawalRequest.RiskStatus.PASSED),
                approval_mode=(WithdrawalRequest.ApprovalMode.MANUAL),
            )

        withdrawal = self.create_request()

        withdrawal.refresh_from_db()

        self.assertEqual(
            withdrawal.status,
            (WithdrawalRequest.Status.PENDING_APPROVAL),
        )
        self.assertIn(
            "WITHDRAWAL_COUNT_24H_LIMIT",
            withdrawal.risk_reasons,
        )

    def test_recent_failed_withdrawal_requires_review(
        self,
    ):
        self.seed_known_destination()

        WithdrawalRequest.objects.create(
            wallet=self.wallet,
            amount=Decimal("10000.0000"),
            destination=self.destination,
            status=(WithdrawalRequest.Status.FAILED),
            risk_status=(WithdrawalRequest.RiskStatus.FLAGGED),
            approval_mode=(WithdrawalRequest.ApprovalMode.MANUAL),
        )

        withdrawal = self.create_request()

        withdrawal.refresh_from_db()

        self.assertEqual(
            withdrawal.status,
            (WithdrawalRequest.Status.PENDING_APPROVAL),
        )
        self.assertIn(
            "RECENT_FAILED_WITHDRAWAL",
            withdrawal.risk_reasons,
        )

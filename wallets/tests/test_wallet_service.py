from decimal import Decimal
from importlib import import_module
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from authentication.tests.factories import (
    UserFactory,
)
from wallets.models import (
    LedgerEntry,
    Wallet,
)


class WalletServiceTests(TestCase):
    def setUp(self):
        wallet_service_module = import_module("wallets.services.wallet_service")
        self.service = wallet_service_module.WalletService

        self.user = UserFactory()
        self.other_user = UserFactory()

    def create_wallet(
        self,
        *,
        user=None,
        currency="UGX",
        available="100.0000",
        reserved="40.0000",
    ):
        return Wallet.objects.create(
            user=user or self.user,
            currency=currency,
            available_balance=Decimal(str(available)),
            reserved_balance=Decimal(str(reserved)),
        )

    def assert_balances(
        self,
        wallet,
        *,
        available,
        reserved,
    ):
        wallet.refresh_from_db()

        self.assertEqual(
            wallet.available_balance,
            Decimal(str(available)),
        )
        self.assertEqual(
            wallet.reserved_balance,
            Decimal(str(reserved)),
        )

    def test_credit_creates_wallet_and_ledger_entry(
        self,
    ):
        reference = uuid4()

        entry = self.service.credit(
            user=self.user,
            currency="UGX",
            amount=Decimal("50000.0000"),
            idempotency_reference=reference,
        )

        wallet = Wallet.objects.get(
            user=self.user,
            currency="UGX",
        )

        self.assertEqual(
            entry.wallet_id,
            wallet.id,
        )
        self.assertEqual(
            entry.entry_type,
            LedgerEntry.EntryType.CREDIT,
        )
        self.assertEqual(
            entry.amount,
            Decimal("50000.0000"),
        )
        self.assertEqual(
            entry.idempotency_reference,
            reference,
        )
        self.assertEqual(
            entry.available_balance_before,
            Decimal("0.0000"),
        )
        self.assertEqual(
            entry.available_balance_after,
            Decimal("50000.0000"),
        )
        self.assertEqual(
            entry.reserved_balance_before,
            Decimal("0.0000"),
        )
        self.assertEqual(
            entry.reserved_balance_after,
            Decimal("0.0000"),
        )

        self.assert_balances(
            wallet,
            available="50000.0000",
            reserved="0.0000",
        )

    def test_credit_increases_existing_available_balance(
        self,
    ):
        wallet = self.create_wallet()

        entry = self.service.credit(
            user=self.user,
            currency="UGX",
            amount=Decimal("25.0000"),
            idempotency_reference=uuid4(),
        )

        self.assertEqual(
            entry.entry_type,
            LedgerEntry.EntryType.CREDIT,
        )
        self.assertEqual(
            entry.available_balance_before,
            Decimal("100.0000"),
        )
        self.assertEqual(
            entry.available_balance_after,
            Decimal("125.0000"),
        )
        self.assertEqual(
            entry.reserved_balance_before,
            Decimal("40.0000"),
        )
        self.assertEqual(
            entry.reserved_balance_after,
            Decimal("40.0000"),
        )

        self.assert_balances(
            wallet,
            available="125.0000",
            reserved="40.0000",
        )

    def test_reserve_moves_available_balance_to_reserved(
        self,
    ):
        wallet = self.create_wallet()

        entry = self.service.reserve(
            user=self.user,
            currency="UGX",
            amount=Decimal("30.0000"),
            idempotency_reference=uuid4(),
        )

        self.assertEqual(
            entry.entry_type,
            LedgerEntry.EntryType.RESERVE,
        )
        self.assertEqual(
            entry.available_balance_before,
            Decimal("100.0000"),
        )
        self.assertEqual(
            entry.available_balance_after,
            Decimal("70.0000"),
        )
        self.assertEqual(
            entry.reserved_balance_before,
            Decimal("40.0000"),
        )
        self.assertEqual(
            entry.reserved_balance_after,
            Decimal("70.0000"),
        )

        self.assert_balances(
            wallet,
            available="70.0000",
            reserved="70.0000",
        )

    def test_release_moves_reserved_balance_to_available(
        self,
    ):
        wallet = self.create_wallet()

        entry = self.service.release(
            user=self.user,
            currency="UGX",
            amount=Decimal("15.0000"),
            idempotency_reference=uuid4(),
        )

        self.assertEqual(
            entry.entry_type,
            LedgerEntry.EntryType.RELEASE,
        )
        self.assertEqual(
            entry.available_balance_before,
            Decimal("100.0000"),
        )
        self.assertEqual(
            entry.available_balance_after,
            Decimal("115.0000"),
        )
        self.assertEqual(
            entry.reserved_balance_before,
            Decimal("40.0000"),
        )
        self.assertEqual(
            entry.reserved_balance_after,
            Decimal("25.0000"),
        )

        self.assert_balances(
            wallet,
            available="115.0000",
            reserved="25.0000",
        )

    def test_debit_available_reduces_available_balance(
        self,
    ):
        wallet = self.create_wallet()

        entry = self.service.debit_available(
            user=self.user,
            currency="UGX",
            amount=Decimal("20.0000"),
            idempotency_reference=uuid4(),
        )

        self.assertEqual(
            entry.entry_type,
            LedgerEntry.EntryType.DEBIT,
        )
        self.assertEqual(
            entry.available_balance_before,
            Decimal("100.0000"),
        )
        self.assertEqual(
            entry.available_balance_after,
            Decimal("80.0000"),
        )
        self.assertEqual(
            entry.reserved_balance_before,
            Decimal("40.0000"),
        )
        self.assertEqual(
            entry.reserved_balance_after,
            Decimal("40.0000"),
        )

        self.assert_balances(
            wallet,
            available="80.0000",
            reserved="40.0000",
        )

    def test_consume_reserved_reduces_reserved_balance(
        self,
    ):
        wallet = self.create_wallet()

        entry = self.service.consume_reserved(
            user=self.user,
            currency="UGX",
            amount=Decimal("25.0000"),
            idempotency_reference=uuid4(),
        )

        self.assertEqual(
            entry.entry_type,
            LedgerEntry.EntryType.DEBIT,
        )
        self.assertEqual(
            entry.available_balance_before,
            Decimal("100.0000"),
        )
        self.assertEqual(
            entry.available_balance_after,
            Decimal("100.0000"),
        )
        self.assertEqual(
            entry.reserved_balance_before,
            Decimal("40.0000"),
        )
        self.assertEqual(
            entry.reserved_balance_after,
            Decimal("15.0000"),
        )

        self.assert_balances(
            wallet,
            available="100.0000",
            reserved="15.0000",
        )

    def test_reserve_rejects_insufficient_available_balance(
        self,
    ):
        wallet = self.create_wallet()
        reference = uuid4()

        with self.assertRaises(ValidationError) as context:
            self.service.reserve(
                user=self.user,
                currency="UGX",
                amount=Decimal("100.0001"),
                idempotency_reference=reference,
            )

        self.assertIn(
            "available_balance",
            context.exception.message_dict,
        )
        self.assert_balances(
            wallet,
            available="100.0000",
            reserved="40.0000",
        )
        self.assertFalse(
            LedgerEntry.objects.filter(
                idempotency_reference=reference,
            ).exists()
        )

    def test_debit_rejects_insufficient_available_balance(
        self,
    ):
        wallet = self.create_wallet()
        reference = uuid4()

        with self.assertRaises(ValidationError) as context:
            self.service.debit_available(
                user=self.user,
                currency="UGX",
                amount=Decimal("100.0001"),
                idempotency_reference=reference,
            )

        self.assertIn(
            "available_balance",
            context.exception.message_dict,
        )
        self.assert_balances(
            wallet,
            available="100.0000",
            reserved="40.0000",
        )
        self.assertFalse(
            LedgerEntry.objects.filter(
                idempotency_reference=reference,
            ).exists()
        )

    def test_release_rejects_insufficient_reserved_balance(
        self,
    ):
        wallet = self.create_wallet()
        reference = uuid4()

        with self.assertRaises(ValidationError) as context:
            self.service.release(
                user=self.user,
                currency="UGX",
                amount=Decimal("40.0001"),
                idempotency_reference=reference,
            )

        self.assertIn(
            "reserved_balance",
            context.exception.message_dict,
        )
        self.assert_balances(
            wallet,
            available="100.0000",
            reserved="40.0000",
        )
        self.assertFalse(
            LedgerEntry.objects.filter(
                idempotency_reference=reference,
            ).exists()
        )

    def test_consume_rejects_insufficient_reserved_balance(
        self,
    ):
        wallet = self.create_wallet()
        reference = uuid4()

        with self.assertRaises(ValidationError) as context:
            self.service.consume_reserved(
                user=self.user,
                currency="UGX",
                amount=Decimal("40.0001"),
                idempotency_reference=reference,
            )

        self.assertIn(
            "reserved_balance",
            context.exception.message_dict,
        )
        self.assert_balances(
            wallet,
            available="100.0000",
            reserved="40.0000",
        )
        self.assertFalse(
            LedgerEntry.objects.filter(
                idempotency_reference=reference,
            ).exists()
        )

    def test_operations_reject_non_positive_amounts(
        self,
    ):
        wallet = self.create_wallet()

        operation_names = (
            "credit",
            "reserve",
            "release",
            "debit_available",
            "consume_reserved",
        )
        invalid_amounts = (
            Decimal("0.0000"),
            Decimal("-0.0001"),
        )

        for operation_name in operation_names:
            operation = getattr(
                self.service,
                operation_name,
            )

            for amount in invalid_amounts:
                with self.subTest(
                    operation=operation_name,
                    amount=amount,
                ):
                    reference = uuid4()

                    with self.assertRaises(ValidationError) as context:
                        operation(
                            user=self.user,
                            currency="UGX",
                            amount=amount,
                            idempotency_reference=(reference),
                        )

                    self.assertIn(
                        "amount",
                        context.exception.message_dict,
                    )
                    self.assertFalse(
                        LedgerEntry.objects.filter(
                            idempotency_reference=(reference),
                        ).exists()
                    )

        self.assert_balances(
            wallet,
            available="100.0000",
            reserved="40.0000",
        )

    def test_identical_credit_replay_is_idempotent(
        self,
    ):
        wallet = self.create_wallet()
        reference = uuid4()

        first_entry = self.service.credit(
            user=self.user,
            currency="UGX",
            amount=Decimal("25.0000"),
            idempotency_reference=reference,
        )
        replayed_entry = self.service.credit(
            user=self.user,
            currency="UGX",
            amount=Decimal("25.0000"),
            idempotency_reference=reference,
        )

        self.assertEqual(
            replayed_entry.id,
            first_entry.id,
        )
        self.assertEqual(
            LedgerEntry.objects.filter(
                idempotency_reference=reference,
            ).count(),
            1,
        )
        self.assert_balances(
            wallet,
            available="125.0000",
            reserved="40.0000",
        )

    def test_identical_reserve_replay_is_idempotent(
        self,
    ):
        wallet = self.create_wallet()
        reference = uuid4()

        first_entry = self.service.reserve(
            user=self.user,
            currency="UGX",
            amount=Decimal("30.0000"),
            idempotency_reference=reference,
        )
        replayed_entry = self.service.reserve(
            user=self.user,
            currency="UGX",
            amount=Decimal("30.0000"),
            idempotency_reference=reference,
        )

        self.assertEqual(
            replayed_entry.id,
            first_entry.id,
        )
        self.assertEqual(
            LedgerEntry.objects.filter(
                idempotency_reference=reference,
            ).count(),
            1,
        )
        self.assert_balances(
            wallet,
            available="70.0000",
            reserved="70.0000",
        )

    def test_conflicting_amount_replay_is_rejected(
        self,
    ):
        wallet = self.create_wallet()
        reference = uuid4()

        self.service.credit(
            user=self.user,
            currency="UGX",
            amount=Decimal("25.0000"),
            idempotency_reference=reference,
        )

        with self.assertRaises(ValidationError) as context:
            self.service.credit(
                user=self.user,
                currency="UGX",
                amount=Decimal("30.0000"),
                idempotency_reference=reference,
            )

        self.assertIn(
            "idempotency_reference",
            context.exception.message_dict,
        )
        self.assert_balances(
            wallet,
            available="125.0000",
            reserved="40.0000",
        )

    def test_conflicting_operation_replay_is_rejected(
        self,
    ):
        wallet = self.create_wallet()
        reference = uuid4()

        self.service.credit(
            user=self.user,
            currency="UGX",
            amount=Decimal("25.0000"),
            idempotency_reference=reference,
        )

        with self.assertRaises(ValidationError) as context:
            self.service.reserve(
                user=self.user,
                currency="UGX",
                amount=Decimal("25.0000"),
                idempotency_reference=reference,
            )

        self.assertIn(
            "idempotency_reference",
            context.exception.message_dict,
        )
        self.assert_balances(
            wallet,
            available="125.0000",
            reserved="40.0000",
        )

    def test_reference_cannot_be_replayed_for_another_wallet(
        self,
    ):
        wallet = self.create_wallet()
        reference = uuid4()

        self.service.credit(
            user=self.user,
            currency="UGX",
            amount=Decimal("25.0000"),
            idempotency_reference=reference,
        )

        with self.assertRaises(ValidationError) as context:
            self.service.credit(
                user=self.other_user,
                currency="UGX",
                amount=Decimal("25.0000"),
                idempotency_reference=reference,
            )

        self.assertIn(
            "idempotency_reference",
            context.exception.message_dict,
        )
        self.assertFalse(
            Wallet.objects.filter(
                user=self.other_user,
                currency="UGX",
            ).exists()
        )
        self.assert_balances(
            wallet,
            available="125.0000",
            reserved="40.0000",
        )

    def test_ledger_failure_rolls_back_wallet_update(
        self,
    ):
        wallet = self.create_wallet()

        with patch.object(
            LedgerEntry,
            "save",
            side_effect=RuntimeError("Ledger write failed."),
        ):
            with self.assertRaises(RuntimeError):
                self.service.reserve(
                    user=self.user,
                    currency="UGX",
                    amount=Decimal("30.0000"),
                    idempotency_reference=(uuid4()),
                )

        self.assert_balances(
            wallet,
            available="100.0000",
            reserved="40.0000",
        )
        self.assertEqual(
            LedgerEntry.objects.count(),
            0,
        )

    def test_ledger_failure_rolls_back_wallet_creation(
        self,
    ):
        with patch.object(
            LedgerEntry,
            "save",
            side_effect=RuntimeError("Ledger write failed."),
        ):
            with self.assertRaises(RuntimeError):
                self.service.credit(
                    user=self.user,
                    currency="UGX",
                    amount=Decimal("25.0000"),
                    idempotency_reference=(uuid4()),
                )

        self.assertFalse(
            Wallet.objects.filter(
                user=self.user,
                currency="UGX",
            ).exists()
        )
        self.assertEqual(
            LedgerEntry.objects.count(),
            0,
        )

    def test_existing_wallet_row_is_locked_for_mutation(
        self,
    ):
        self.create_wallet()

        with CaptureQueriesContext(connection) as queries:
            self.service.credit(
                user=self.user,
                currency="UGX",
                amount=Decimal("25.0000"),
                idempotency_reference=uuid4(),
            )

        wallet_lock_queries = [
            query["sql"]
            for query in queries.captured_queries
            if ("FOR UPDATE" in query["sql"].upper() and "wallets_wallet" in query["sql"])
        ]

        self.assertTrue(
            wallet_lock_queries,
            "Expected the wallet row to be " "selected FOR UPDATE.",
        )

    def test_currency_is_normalized_before_wallet_lookup(
        self,
    ):
        entry = self.service.credit(
            user=self.user,
            currency=" usd ",
            amount=Decimal("25.0000"),
            idempotency_reference=uuid4(),
        )

        self.assertEqual(
            entry.wallet.currency,
            "USD",
        )
        self.assertTrue(
            Wallet.objects.filter(
                user=self.user,
                currency="USD",
            ).exists()
        )
        self.assertFalse(
            Wallet.objects.filter(
                user=self.user,
                currency=" usd ",
            ).exists()
        )

    def test_mutations_reject_unsupported_context_keywords(self):
        self.create_wallet()

        with self.assertRaises(TypeError):
            self.service.reserve(
                user=self.user,
                currency="UGX",
                amount=Decimal("1.0000"),
                idempotency_reference=uuid4(),
                unsupported_context="discarding this would be unsafe",
            )

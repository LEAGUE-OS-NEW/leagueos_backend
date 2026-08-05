from decimal import Decimal
from importlib import import_module
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from authentication.tests.factories import (
    UserFactory,
)


class WalletModelTestCase(TestCase):
    def setUp(self):
        wallet_models = import_module("wallets.models")

        self.Wallet = wallet_models.Wallet
        self.LedgerEntry = wallet_models.LedgerEntry
        self.user = UserFactory()

    def valid_wallet(self, **overrides):
        values = {
            "user": self.user,
            "currency": "UGX",
            "available_balance": Decimal("100000.0000"),
            "reserved_balance": Decimal("25000.0000"),
        }
        values.update(overrides)

        return self.Wallet(**values)

    def create_wallet(self, **overrides):
        wallet = self.valid_wallet(**overrides)
        wallet.full_clean()
        wallet.save()
        return wallet

    def ledger_values(self, **overrides):
        wallet = overrides.pop(
            "wallet",
            None,
        )

        if wallet is None:
            wallet = getattr(
                self,
                "_ledger_wallet",
                None,
            )

        if wallet is None:
            wallet = self.create_wallet()
            self._ledger_wallet = wallet

        values = {
            "wallet": wallet,
            "entry_type": (self.LedgerEntry.EntryType.RESERVE),
            "amount": Decimal("10000.0000"),
            "currency": "UGX",
            "debit_account": self.LedgerEntry.AccountType.USER_WALLET,
            "credit_account": self.LedgerEntry.AccountType.USER_WALLET,
            "available_balance_before": (Decimal("100000.0000")),
            "available_balance_after": (Decimal("90000.0000")),
            "reserved_balance_before": (Decimal("25000.0000")),
            "reserved_balance_after": (Decimal("35000.0000")),
            "idempotency_reference": uuid4(),
        }
        values.update(overrides)

        return values

    def valid_ledger_entry(
        self,
        **overrides,
    ):
        return self.LedgerEntry(**self.ledger_values(**overrides))

    def create_ledger_entry(
        self,
        **overrides,
    ):
        entry = self.valid_ledger_entry(**overrides)
        entry.full_clean()
        entry.save()
        return entry


class WalletModelTests(WalletModelTestCase):
    def test_wallet_records_user_currency_and_balances(
        self,
    ):
        wallet = self.valid_wallet()

        wallet.full_clean()
        wallet.save()
        wallet.refresh_from_db()

        self.assertEqual(
            wallet.user,
            self.user,
        )
        self.assertEqual(
            wallet.currency,
            "UGX",
        )
        self.assertEqual(
            wallet.available_balance,
            Decimal("100000.0000"),
        )
        self.assertEqual(
            wallet.reserved_balance,
            Decimal("25000.0000"),
        )
        self.assertIsNotNone(wallet.created_at)
        self.assertIsNotNone(wallet.updated_at)

    def test_wallet_defaults_to_ugx_and_zero_balances(
        self,
    ):
        wallet = self.Wallet(
            user=self.user,
        )

        wallet.full_clean()
        wallet.save()
        wallet.refresh_from_db()

        self.assertEqual(
            wallet.currency,
            "UGX",
        )
        self.assertEqual(
            wallet.available_balance,
            Decimal("0.0000"),
        )
        self.assertEqual(
            wallet.reserved_balance,
            Decimal("0.0000"),
        )

    def test_wallet_currency_is_normalized_to_uppercase(
        self,
    ):
        wallet = self.Wallet(
            user=self.user,
            currency="ugx",
        )

        wallet.save()
        wallet.refresh_from_db()

        self.assertEqual(
            wallet.currency,
            "UGX",
        )

    def test_user_cannot_have_duplicate_wallet_for_currency(
        self,
    ):
        self.create_wallet()

        duplicate = self.valid_wallet()

        with self.assertRaises(ValidationError) as context:
            duplicate.full_clean()

        self.assertIn(
            "__all__",
            context.exception.message_dict,
        )

    def test_database_enforces_one_wallet_per_user_and_currency(
        self,
    ):
        self.create_wallet()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.Wallet.objects.create(
                    user=self.user,
                    currency="UGX",
                    available_balance=(Decimal("0.0000")),
                    reserved_balance=(Decimal("0.0000")),
                )

    def test_user_can_have_wallets_in_different_currencies(
        self,
    ):
        ugx_wallet = self.create_wallet(
            currency="UGX",
        )
        usd_wallet = self.create_wallet(
            currency="USD",
        )

        self.assertNotEqual(
            ugx_wallet.id,
            usd_wallet.id,
        )
        self.assertEqual(
            self.Wallet.objects.filter(
                user=self.user,
            ).count(),
            2,
        )

    def test_available_balance_cannot_be_negative(
        self,
    ):
        wallet = self.valid_wallet(
            available_balance=Decimal("-0.0001"),
        )

        with self.assertRaises(ValidationError) as context:
            wallet.full_clean()

        self.assertIn(
            "available_balance",
            context.exception.message_dict,
        )

    def test_reserved_balance_cannot_be_negative(
        self,
    ):
        wallet = self.valid_wallet(
            reserved_balance=Decimal("-0.0001"),
        )

        with self.assertRaises(ValidationError) as context:
            wallet.full_clean()

        self.assertIn(
            "reserved_balance",
            context.exception.message_dict,
        )

    def test_database_rejects_negative_available_balance(
        self,
    ):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.Wallet.objects.create(
                    user=self.user,
                    currency="UGX",
                    available_balance=(Decimal("-0.0001")),
                    reserved_balance=(Decimal("0.0000")),
                )

    def test_database_rejects_negative_reserved_balance(
        self,
    ):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.Wallet.objects.create(
                    user=self.user,
                    currency="UGX",
                    available_balance=(Decimal("0.0000")),
                    reserved_balance=(Decimal("-0.0001")),
                )


class LedgerEntryModelTests(WalletModelTestCase):
    def test_ledger_entry_records_balance_movement(
        self,
    ):
        entry = self.valid_ledger_entry()

        entry.full_clean()
        entry.save()
        entry.refresh_from_db()

        self.assertEqual(
            entry.entry_type,
            self.LedgerEntry.EntryType.RESERVE,
        )
        self.assertEqual(
            entry.amount,
            Decimal("10000.0000"),
        )
        self.assertEqual(
            entry.available_balance_before,
            Decimal("100000.0000"),
        )
        self.assertEqual(
            entry.available_balance_after,
            Decimal("90000.0000"),
        )
        self.assertEqual(
            entry.reserved_balance_before,
            Decimal("25000.0000"),
        )
        self.assertEqual(
            entry.reserved_balance_after,
            Decimal("35000.0000"),
        )
        self.assertIsNotNone(entry.created_at)

    def test_ledger_entry_types_are_controlled(
        self,
    ):
        entry_types = {choice.value for choice in (self.LedgerEntry.EntryType)}

        self.assertEqual(
            entry_types,
            {
                "CREDIT",
                "DEBIT",
                "RESERVE",
                "RELEASE",
            },
        )

    def test_market_references_are_optional(
        self,
    ):
        for field_name in (
            "market",
            "order",
            "fill",
        ):
            with self.subTest(field_name=field_name):
                field = self.LedgerEntry._meta.get_field(field_name)

                self.assertTrue(field.null)
                self.assertTrue(field.blank)

    def test_idempotency_reference_must_be_unique(
        self,
    ):
        reference = uuid4()
        self.create_ledger_entry(
            idempotency_reference=reference,
        )

        duplicate = self.valid_ledger_entry(
            idempotency_reference=reference,
        )

        with self.assertRaises(ValidationError) as context:
            duplicate.full_clean()

        self.assertIn(
            "idempotency_reference",
            context.exception.message_dict,
        )

    def test_database_enforces_unique_idempotency_reference(
        self,
    ):
        reference = uuid4()
        wallet = self.create_wallet()

        self.LedgerEntry.objects.create(
            **self.ledger_values(
                wallet=wallet,
                idempotency_reference=(reference),
            )
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.LedgerEntry.objects.create(
                    **self.ledger_values(
                        wallet=wallet,
                        idempotency_reference=(reference),
                    )
                )

    def test_ledger_amount_must_be_positive(
        self,
    ):
        entry = self.valid_ledger_entry(
            amount=Decimal("0.0000"),
        )

        with self.assertRaises(ValidationError) as context:
            entry.full_clean()

        self.assertIn(
            "amount",
            context.exception.message_dict,
        )

    def test_database_rejects_non_positive_ledger_amount(
        self,
    ):
        values = self.ledger_values(
            amount=Decimal("0.0000"),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.LedgerEntry.objects.create(**values)

    def test_ledger_balance_snapshots_cannot_be_negative(
        self,
    ):
        snapshot_fields = (
            "available_balance_before",
            "available_balance_after",
            "reserved_balance_before",
            "reserved_balance_after",
        )

        for field_name in snapshot_fields:
            with self.subTest(field_name=field_name):
                entry = self.valid_ledger_entry(**{field_name: Decimal("-0.0001")})

                with self.assertRaises(ValidationError) as context:
                    entry.full_clean()

                self.assertIn(
                    field_name,
                    context.exception.message_dict,
                )

    def test_database_rejects_negative_balance_snapshot(
        self,
    ):
        values = self.ledger_values(
            available_balance_after=(Decimal("-0.0001")),
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.LedgerEntry.objects.create(**values)

    def test_existing_ledger_entry_cannot_be_updated(
        self,
    ):
        entry = self.create_ledger_entry()
        original_amount = entry.amount

        entry.amount = Decimal("20000.0000")

        with self.assertRaises(ValidationError):
            entry.save()

        entry.refresh_from_db()

        self.assertEqual(
            entry.amount,
            original_amount,
        )

    def test_existing_ledger_entry_cannot_be_deleted(
        self,
    ):
        entry = self.create_ledger_entry()

        with self.assertRaises(ValidationError):
            entry.delete()

        self.assertTrue(
            self.LedgerEntry.objects.filter(
                id=entry.id,
            ).exists()
        )

    def test_wallet_with_ledger_entries_is_protected_from_deletion(
        self,
    ):
        entry = self.create_ledger_entry()

        with self.assertRaises(ProtectedError):
            entry.wallet.delete()

        self.assertTrue(
            self.Wallet.objects.filter(
                id=entry.wallet_id,
            ).exists()
        )

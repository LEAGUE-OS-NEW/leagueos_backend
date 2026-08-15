from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import TestCase

from authentication.tests.factories import UserFactory
from wallets.models import LedgerEntry
from wallets.services.wallet_service import WalletService
from wallets.tests.factories import WalletFactory


class WalletCounterpartyTests(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.wallet = WalletFactory(
            user=self.user,
            currency="UGX",
            available_balance=Decimal("100000.0000"),
            reserved_balance=Decimal("0.0000"),
        )

        WalletService.reserve(
            user=self.user,
            currency="UGX",
            amount=Decimal("20000.0000"),
            idempotency_reference=uuid4(),
        )

    def test_consume_reserved_can_use_provider_payable(self):
        reference = uuid4()

        entry = WalletService.consume_reserved(
            user=self.user,
            currency="UGX",
            amount=Decimal("20000.0000"),
            idempotency_reference=reference,
            counterparty_account=(LedgerEntry.AccountType.PROVIDER_PAYABLE),
        )

        self.wallet.refresh_from_db()

        self.assertEqual(
            entry.credit_account,
            LedgerEntry.AccountType.PROVIDER_PAYABLE,
        )
        self.assertEqual(
            self.wallet.available_balance,
            Decimal("80000.0000"),
        )
        self.assertEqual(
            self.wallet.reserved_balance,
            Decimal("0.0000"),
        )

    def test_same_counterparty_replay_is_idempotent(self):
        reference = uuid4()

        first = WalletService.consume_reserved(
            user=self.user,
            currency="UGX",
            amount=Decimal("20000.0000"),
            idempotency_reference=reference,
            counterparty_account=(LedgerEntry.AccountType.PROVIDER_PAYABLE),
        )

        second = WalletService.consume_reserved(
            user=self.user,
            currency="UGX",
            amount=Decimal("20000.0000"),
            idempotency_reference=reference,
            counterparty_account=(LedgerEntry.AccountType.PROVIDER_PAYABLE),
        )

        self.assertEqual(first.id, second.id)

        self.assertEqual(
            LedgerEntry.objects.filter(idempotency_reference=reference).count(),
            1,
        )

    def test_counterparty_cannot_change_on_replay(self):
        reference = uuid4()

        WalletService.consume_reserved(
            user=self.user,
            currency="UGX",
            amount=Decimal("20000.0000"),
            idempotency_reference=reference,
            counterparty_account=(LedgerEntry.AccountType.PROVIDER_PAYABLE),
        )

        with self.assertRaises(ValidationError):
            WalletService.consume_reserved(
                user=self.user,
                currency="UGX",
                amount=Decimal("20000.0000"),
                idempotency_reference=reference,
                counterparty_account=(LedgerEntry.AccountType.REVENUE),
            )

        self.assertEqual(
            LedgerEntry.objects.filter(idempotency_reference=reference).count(),
            1,
        )

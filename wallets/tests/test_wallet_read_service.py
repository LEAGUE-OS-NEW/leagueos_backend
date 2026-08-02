from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import TestCase

from authentication.tests.factories import UserFactory
from wallets.models import Wallet
from wallets.services.wallet_service import WalletService


class WalletReadServiceTests(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.other_user = UserFactory()

    def test_list_wallets_is_user_scoped_and_deterministic(self):
        Wallet.objects.create(user=self.user, currency="USD")
        Wallet.objects.create(user=self.user, currency="UGX")
        Wallet.objects.create(user=self.other_user, currency="EUR")

        from wallets.services.wallet_read_service import WalletReadService

        wallets = list(WalletReadService.list_wallets(user=self.user))

        self.assertEqual([wallet.currency for wallet in wallets], ["UGX", "USD"])

    def test_get_wallet_normalizes_currency_and_is_user_scoped(self):
        wallet = Wallet.objects.create(user=self.user, currency="UGX")
        Wallet.objects.create(user=self.other_user, currency="USD")

        from wallets.services.wallet_read_service import WalletReadService

        self.assertEqual(WalletReadService.get_wallet(user=self.user, currency=" ugx "), wallet)
        self.assertIsNone(WalletReadService.get_wallet(user=self.user, currency="usd"))

    def test_invalid_currency_is_rejected(self):
        from wallets.services.wallet_read_service import WalletReadService

        for currency in ("UG", "UG12", "1GX"):
            with self.subTest(currency=currency), self.assertRaises(ValidationError):
                WalletReadService.get_wallet(user=self.user, currency=currency)

    def test_ledger_entries_are_scoped_filtered_and_newest_first(self):
        credit = WalletService.credit(
            user=self.user,
            currency="UGX",
            amount=Decimal("25.0000"),
            idempotency_reference=uuid4(),
        )
        reserve = WalletService.reserve(
            user=self.user,
            currency="UGX",
            amount=Decimal("5.0000"),
            idempotency_reference=uuid4(),
        )
        WalletService.credit(
            user=self.other_user,
            currency="UGX",
            amount=Decimal("99.0000"),
            idempotency_reference=uuid4(),
        )

        from wallets.services.wallet_read_service import WalletReadService

        wallet, entries = WalletReadService.list_ledger_entries(
            user=self.user,
            currency="ugx",
            filters={"entry_type": "RESERVE"},
        )

        self.assertEqual(wallet.user, self.user)
        self.assertEqual(list(entries), [reserve])
        self.assertNotEqual(reserve.id, credit.id)

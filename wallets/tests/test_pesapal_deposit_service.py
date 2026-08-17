from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import TestCase

from authentication.tests.factories import (
    UserFactory,
)
from wallets.models import (
    DepositIntent,
    LedgerEntry,
    PaymentProvider,
    PesapalDeposit,
    Wallet,
    WalletTransaction,
)
from wallets.services.pesapal_config import (
    PesapalConfig,
    SANDBOX_BASE_URL,
)
from wallets.services.pesapal_deposit_service import (
    PesapalDepositService,
)


def sandbox_config():
    return PesapalConfig(
        environment="SANDBOX",
        base_url=SANDBOX_BASE_URL,
        consumer_key="sandbox-key",
        consumer_secret="sandbox-secret",
        ipn_id="sandbox-ipn-id",
        callback_url=(
            "https://backend.example.test/" "api/v1/wallets/deposits/" "pesapal/callback/"
        ),
        ipn_url=("https://backend.example.test/" "api/v1/wallets/deposits/" "pesapal/ipn/"),
        frontend_return_url=("https://frontend.example.test/" "fan/wallet"),
        is_sandbox=True,
    )


class PesapalDepositServiceTests(TestCase):
    def setUp(self):
        self.user = UserFactory(
            email="fan@example.com",
            first_name="Test",
            last_name="Fan",
            phone_number="+256772123456",
        )

        self.provider, _ = PaymentProvider.objects.update_or_create(
            code="PESAPAL_SANDBOX",
            defaults={
                "name": "Pesapal Sandbox",
                "provider_type": PaymentProvider.ProviderType.GENERIC,
                "is_active": True,
            },
        )

        self.client = Mock()
        self.client.config = sandbox_config()

        self.client.submit_order.return_value = {
            "order_tracking_id": "tracking-123",
            "merchant_reference": "",
            "redirect_url": "https://cybqa.pesapal.com/" "pesapaliframe/test",
            "status": "200",
        }

    def start_deposit(self):
        key = uuid4()

        expected_reference = None

        def submit(payload):
            nonlocal expected_reference
            expected_reference = payload["id"]

            return {
                "order_tracking_id": "tracking-123",
                "merchant_reference": payload["id"],
                "redirect_url": "https://cybqa.pesapal.com/" "pesapaliframe/test",
                "status": "200",
            }

        self.client.submit_order.side_effect = submit

        deposit = PesapalDepositService.start_deposit(
            user=self.user,
            amount=Decimal("10000.0000"),
            currency="UGX",
            idempotency_key=key,
            client=self.client,
        )

        self.assertEqual(
            deposit.merchant_reference,
            expected_reference,
        )

        return deposit, key

    def test_start_creates_sandbox_checkout(self):
        deposit, _ = self.start_deposit()

        self.assertEqual(
            deposit.environment,
            PesapalDeposit.Environment.SANDBOX,
        )

        self.assertEqual(
            deposit.order_tracking_id,
            "tracking-123",
        )

        payload = self.client.submit_order.call_args.args[0]

        self.assertEqual(
            payload["currency"],
            "UGX",
        )

        self.assertEqual(
            payload["amount"],
            10000.0,
        )

        self.assertEqual(
            payload["notification_id"],
            "sandbox-ipn-id",
        )

        self.assertEqual(
            payload["billing_address"]["email_address"],
            self.user.email,
        )

    def test_repeated_start_is_idempotent(self):
        deposit, key = self.start_deposit()

        self.client.submit_order.reset_mock()

        replay = PesapalDepositService.start_deposit(
            user=self.user,
            amount=Decimal("10000.0000"),
            currency="UGX",
            idempotency_key=key,
            client=self.client,
        )

        self.assertEqual(
            replay.id,
            deposit.id,
        )

        self.client.submit_order.assert_not_called()

        self.assertEqual(
            DepositIntent.objects.count(),
            1,
        )

        self.assertEqual(
            PesapalDeposit.objects.count(),
            1,
        )

    def test_completed_status_credits_once(self):
        deposit, _ = self.start_deposit()

        self.client.get_transaction_status.return_value = {
            "payment_method": "Visa",
            "amount": 10000,
            "confirmation_code": "CONF123",
            "payment_status_description": "Completed",
            "description": "",
            "payment_account": "4761****0010",
            "status_code": 1,
            "merchant_reference": deposit.merchant_reference,
            "currency": "UGX",
            "status": "200",
        }

        first = PesapalDepositService.reconcile_notification(
            order_tracking_id="tracking-123",
            merchant_reference=deposit.merchant_reference,
            client=self.client,
        )

        second = PesapalDepositService.reconcile_notification(
            order_tracking_id="tracking-123",
            merchant_reference=deposit.merchant_reference,
            client=self.client,
        )

        self.assertTrue(first["credited"])

        self.assertFalse(second["credited"])

        wallet = Wallet.objects.get(
            user=self.user,
            currency="UGX",
        )

        self.assertEqual(
            wallet.available_balance,
            Decimal("10000.0000"),
        )

        self.assertEqual(
            WalletTransaction.objects.filter(
                transaction_type=WalletTransaction.TransactionType.DEPOSIT
            ).count(),
            1,
        )

        self.assertEqual(
            LedgerEntry.objects.filter(entry_type=LedgerEntry.EntryType.CREDIT).count(),
            1,
        )

    def test_amount_mismatch_never_credits(self):
        deposit, _ = self.start_deposit()

        self.client.get_transaction_status.return_value = {
            "amount": 9999,
            "payment_status_description": "Completed",
            "status_code": 1,
            "merchant_reference": deposit.merchant_reference,
            "currency": "UGX",
            "status": "200",
        }

        with self.assertRaises(ValidationError):
            (
                PesapalDepositService.reconcile_notification(
                    order_tracking_id="tracking-123",
                    merchant_reference=deposit.merchant_reference,
                    client=self.client,
                )
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

    def test_failed_payment_never_credits(self):
        deposit, _ = self.start_deposit()

        self.client.get_transaction_status.return_value = {
            "amount": 10000,
            "payment_status_description": "Failed",
            "status_code": 2,
            "merchant_reference": deposit.merchant_reference,
            "currency": "UGX",
            "status": "200",
        }

        result = PesapalDepositService.reconcile_notification(
            order_tracking_id="tracking-123",
            merchant_reference=deposit.merchant_reference,
            client=self.client,
        )

        self.assertFalse(result["credited"])

        deposit.intent.refresh_from_db()

        self.assertEqual(
            deposit.intent.status,
            DepositIntent.Status.FAILED,
        )

        self.assertEqual(
            LedgerEntry.objects.count(),
            0,
        )

    def test_tracking_mismatch_never_queries_status(self):
        deposit, _ = self.start_deposit()

        self.client.get_transaction_status.reset_mock()

        with self.assertRaises(ValidationError):
            (
                PesapalDepositService.reconcile_notification(
                    order_tracking_id="wrong-tracking",
                    merchant_reference=deposit.merchant_reference,
                    client=self.client,
                )
            )

        (self.client.get_transaction_status.assert_not_called())

        self.assertEqual(
            LedgerEntry.objects.count(),
            0,
        )

    def test_reversal_after_credit_is_flagged(self):
        deposit, _ = self.start_deposit()

        completed = {
            "amount": 10000,
            "payment_status_description": "Completed",
            "status_code": 1,
            "merchant_reference": deposit.merchant_reference,
            "currency": "UGX",
            "status": "200",
        }

        self.client.get_transaction_status.return_value = completed

        (
            PesapalDepositService.reconcile_notification(
                order_tracking_id="tracking-123",
                merchant_reference=deposit.merchant_reference,
                client=self.client,
            )
        )

        reversed_status = {
            **completed,
            "payment_status_description": "Reversed",
            "status_code": 3,
        }

        self.client.get_transaction_status.return_value = reversed_status

        result = PesapalDepositService.reconcile_notification(
            order_tracking_id="tracking-123",
            merchant_reference=deposit.merchant_reference,
            client=self.client,
        )

        self.assertTrue(result["requires_manual_reconciliation"])

        wallet = Wallet.objects.get(
            user=self.user,
            currency="UGX",
        )

        self.assertEqual(
            wallet.available_balance,
            Decimal("10000.0000"),
        )

        self.assertEqual(
            LedgerEntry.objects.count(),
            1,
        )

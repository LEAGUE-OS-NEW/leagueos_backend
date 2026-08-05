"""Factories for wallet tests."""

import factory
from django.utils import timezone

from authentication.tests.factories import UserFactory
from wallets.models import (
    DepositIntent,
    LedgerEntry,
    PaymentProvider,
    Receipt,
    Wallet,
    WalletTransaction,
    WithdrawalRequest,
)


class PaymentProviderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PaymentProvider

    code = factory.Sequence(lambda n: f"PROVIDER_{n}")
    name = factory.Sequence(lambda n: f"Provider {n}")
    provider_type = PaymentProvider.ProviderType.MOCK
    is_active = True


class WalletFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Wallet

    user = factory.SubFactory(UserFactory)
    currency = "UGX"
    available_balance = 0
    reserved_balance = 0
    status = Wallet.Status.ACTIVE


class WalletTransactionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WalletTransaction

    wallet = factory.SubFactory(WalletFactory)
    reference = factory.Sequence(lambda n: f"TXN-{n}")
    transaction_type = WalletTransaction.TransactionType.DEPOSIT
    amount = 1000
    currency = "UGX"
    status = WalletTransaction.Status.PENDING


class LedgerEntryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LedgerEntry

    transaction = factory.SubFactory(WalletTransactionFactory)
    debit_account = LedgerEntry.AccountType.USER_WALLET
    credit_account = LedgerEntry.AccountType.REVENUE
    amount = 1000
    currency = "UGX"


class DepositIntentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DepositIntent

    user = factory.SubFactory(UserFactory)
    provider = factory.SubFactory(PaymentProviderFactory)
    amount = 1000
    currency = "UGX"
    status = DepositIntent.Status.PENDING
    expires_at = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(hours=1))


class WithdrawalRequestFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WithdrawalRequest

    wallet = factory.SubFactory(WalletFactory)
    amount = 1000
    destination = {"mobile_money_number": "0777123456"}
    status = WithdrawalRequest.Status.PENDING_APPROVAL


class ReceiptFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Receipt

    transaction = factory.SubFactory(WalletTransactionFactory)
    receipt_number = factory.Sequence(lambda n: f"RCPT-{n}")

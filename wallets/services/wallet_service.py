"""Service for core wallet balance and state management."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from wallets.models import (
    DepositIntent,
    LedgerEntry,
    PaymentProvider,
    Wallet,
    WithdrawalRequest,
)

IDEMPOTENCY_ERROR = "This reference has already been used for a different operation."


class WalletService:
    @classmethod
    @transaction.atomic
    def get_or_create_wallet(cls, user, currency: str) -> Wallet:
        """Get or create a wallet for a user and currency."""
        wallet, _ = Wallet.objects.get_or_create(user=user, currency=currency.upper())
        return wallet

    @classmethod
    @transaction.atomic
    def credit(cls, *, user, currency: str, amount, idempotency_reference) -> LedgerEntry:
        """Credit funds to available balance."""
        if amount <= 0:
            raise ValidationError({"amount": "Amount must be positive."})

        currency = currency.strip().upper()

        # Idempotency check first (before locking to avoid lock ordering issues)
        existing = LedgerEntry.objects.filter(idempotency_reference=idempotency_reference).first()
        if existing:
            # Verify the wallet matches
            try:
                wallet = Wallet.objects.get(id=existing.wallet_id)
                if wallet.user_id != user.id or wallet.currency != currency:
                    raise ValidationError({"idempotency_reference": IDEMPOTENCY_ERROR})
            except Wallet.DoesNotExist:
                raise ValidationError({"idempotency_reference": IDEMPOTENCY_ERROR}) from None
            return existing

        # Now get or create wallet with lock
        try:
            wallet = Wallet.objects.select_for_update().get(user=user, currency=currency)
        except Wallet.DoesNotExist:
            wallet = Wallet.objects.create(user=user, currency=currency)

        available_before = wallet.available_balance
        reserved_before = wallet.reserved_balance
        available_after = available_before + Decimal(str(amount))

        entry = LedgerEntry(
            wallet=wallet,
            entry_type=LedgerEntry.EntryType.CREDIT,
            debit_account=LedgerEntry.AccountType.USER_WALLET,
            credit_account=LedgerEntry.AccountType.PROVIDER_PAYABLE,
            amount=Decimal(str(amount)),
            currency=currency,
            available_balance_before=available_before,
            available_balance_after=available_after,
            reserved_balance_before=reserved_before,
            reserved_balance_after=reserved_before,
            idempotency_reference=idempotency_reference,
        )
        entry.save()

        wallet.available_balance = available_after
        wallet.save(update_fields=["available_balance", "updated_at"])

        return entry

    @classmethod
    @transaction.atomic
    def reserve(cls, *, user, currency: str, amount, idempotency_reference) -> LedgerEntry:
        """Move funds from available to reserved balance."""
        if amount <= 0:
            raise ValidationError({"amount": "Amount must be positive."})

        currency = currency.strip().upper()
        wallet = Wallet.objects.select_for_update().get(user=user, currency=currency)

        # Idempotency check
        existing = LedgerEntry.objects.filter(idempotency_reference=idempotency_reference).first()
        if existing:
            if existing.wallet_id != wallet.id:
                raise ValidationError({"idempotency_reference": IDEMPOTENCY_ERROR})
            if existing.entry_type != LedgerEntry.EntryType.RESERVE:
                raise ValidationError({"idempotency_reference": IDEMPOTENCY_ERROR})
            return existing

        available_before = wallet.available_balance
        reserved_before = wallet.reserved_balance

        if available_before < Decimal(str(amount)):
            raise ValidationError({"available_balance": "Insufficient available balance."})

        available_after = available_before - Decimal(str(amount))
        reserved_after = reserved_before + Decimal(str(amount))

        entry = LedgerEntry(
            wallet=wallet,
            entry_type=LedgerEntry.EntryType.RESERVE,
            debit_account=LedgerEntry.AccountType.USER_WALLET,
            credit_account=LedgerEntry.AccountType.USER_WALLET,
            amount=Decimal(str(amount)),
            currency=currency,
            available_balance_before=available_before,
            available_balance_after=available_after,
            reserved_balance_before=reserved_before,
            reserved_balance_after=reserved_after,
            idempotency_reference=idempotency_reference,
        )
        entry.save()

        wallet.available_balance = available_after
        wallet.reserved_balance = reserved_after
        wallet.save(update_fields=["available_balance", "reserved_balance", "updated_at"])

        return entry

    @classmethod
    @transaction.atomic
    def release(cls, *, user, currency: str, amount, idempotency_reference) -> LedgerEntry:
        """Move funds from reserved to available balance."""
        if amount <= 0:
            raise ValidationError({"amount": "Amount must be positive."})

        currency = currency.strip().upper()
        wallet = Wallet.objects.select_for_update().get(user=user, currency=currency)

        # Idempotency check
        existing = LedgerEntry.objects.filter(idempotency_reference=idempotency_reference).first()
        if existing:
            if existing.wallet_id != wallet.id:
                raise ValidationError({"idempotency_reference": IDEMPOTENCY_ERROR})
            if existing.entry_type != LedgerEntry.EntryType.RELEASE:
                raise ValidationError({"idempotency_reference": IDEMPOTENCY_ERROR})
            return existing

        available_before = wallet.available_balance
        reserved_before = wallet.reserved_balance

        if reserved_before < Decimal(str(amount)):
            raise ValidationError({"reserved_balance": "Insufficient reserved balance."})

        available_after = available_before + Decimal(str(amount))
        reserved_after = reserved_before - Decimal(str(amount))

        entry = LedgerEntry(
            wallet=wallet,
            entry_type=LedgerEntry.EntryType.RELEASE,
            debit_account=LedgerEntry.AccountType.USER_WALLET,
            credit_account=LedgerEntry.AccountType.USER_WALLET,
            amount=Decimal(str(amount)),
            currency=currency,
            available_balance_before=available_before,
            available_balance_after=available_after,
            reserved_balance_before=reserved_before,
            reserved_balance_after=reserved_after,
            idempotency_reference=idempotency_reference,
        )
        entry.save()

        wallet.available_balance = available_after
        wallet.reserved_balance = reserved_after
        wallet.save(update_fields=["available_balance", "reserved_balance", "updated_at"])

        return entry

    @classmethod
    @transaction.atomic
    def debit_available(cls, *, user, currency: str, amount, idempotency_reference) -> LedgerEntry:
        """Debit funds from available balance."""
        if amount <= 0:
            raise ValidationError({"amount": "Amount must be positive."})

        currency = currency.strip().upper()
        wallet = Wallet.objects.select_for_update().get(user=user, currency=currency)

        # Idempotency check
        existing = LedgerEntry.objects.filter(idempotency_reference=idempotency_reference).first()
        if existing:
            if existing.wallet_id != wallet.id:
                raise ValidationError({"idempotency_reference": IDEMPOTENCY_ERROR})
            if existing.entry_type != LedgerEntry.EntryType.DEBIT:
                raise ValidationError({"idempotency_reference": IDEMPOTENCY_ERROR})
            return existing

        available_before = wallet.available_balance
        reserved_before = wallet.reserved_balance

        if available_before < Decimal(str(amount)):
            raise ValidationError({"available_balance": "Insufficient available balance."})

        available_after = available_before - Decimal(str(amount))

        entry = LedgerEntry(
            wallet=wallet,
            entry_type=LedgerEntry.EntryType.DEBIT,
            debit_account=LedgerEntry.AccountType.USER_WALLET,
            credit_account=LedgerEntry.AccountType.REVENUE,
            amount=Decimal(str(amount)),
            currency=currency,
            available_balance_before=available_before,
            available_balance_after=available_after,
            reserved_balance_before=reserved_before,
            reserved_balance_after=reserved_before,
            idempotency_reference=idempotency_reference,
        )
        entry.save()

        wallet.available_balance = available_after
        wallet.save(update_fields=["available_balance", "updated_at"])

        return entry

    @classmethod
    @transaction.atomic
    def consume_reserved(cls, *, user, currency: str, amount, idempotency_reference) -> LedgerEntry:
        """Debit funds from reserved balance."""
        if amount <= 0:
            raise ValidationError({"amount": "Amount must be positive."})

        currency = currency.strip().upper()
        wallet = Wallet.objects.select_for_update().get(user=user, currency=currency)

        # Idempotency check
        existing = LedgerEntry.objects.filter(idempotency_reference=idempotency_reference).first()
        if existing:
            if (
                existing.wallet_id != wallet.id
                or existing.entry_type != LedgerEntry.EntryType.DEBIT
            ):
                raise ValidationError({"idempotency_reference": IDEMPOTENCY_ERROR})
            return existing

        available_before = wallet.available_balance
        reserved_before = wallet.reserved_balance

        if reserved_before < Decimal(str(amount)):
            raise ValidationError({"reserved_balance": "Insufficient reserved balance."})

        reserved_after = reserved_before - Decimal(str(amount))

        entry = LedgerEntry(
            wallet=wallet,
            entry_type=LedgerEntry.EntryType.DEBIT,
            debit_account=LedgerEntry.AccountType.USER_WALLET,
            credit_account=LedgerEntry.AccountType.REVENUE,
            amount=Decimal(str(amount)),
            currency=currency,
            available_balance_before=available_before,
            available_balance_after=available_before,
            reserved_balance_before=reserved_before,
            reserved_balance_after=reserved_after,
            idempotency_reference=idempotency_reference,
        )
        entry.save()

        wallet.reserved_balance = reserved_after
        wallet.save(update_fields=["reserved_balance", "updated_at"])

        return entry

    @staticmethod
    @transaction.atomic
    def reserve_funds(wallet: Wallet, amount: Decimal) -> None:
        """Atomically move funds from available to reserved balance."""
        if amount <= 0:
            raise ValidationError("Amount must be positive.")

        wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)

        if wallet.available_balance < amount:
            raise ValidationError("Insufficient available balance.")

        wallet.available_balance -= amount
        wallet.reserved_balance += amount
        wallet.save(update_fields=["available_balance", "reserved_balance", "updated_at"])

    @staticmethod
    @transaction.atomic
    def release_funds(wallet: Wallet, amount: Decimal) -> None:
        """Atomically move funds from reserved to available balance."""
        if amount <= 0:
            raise ValidationError("Amount must be positive.")

        wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)

        if wallet.reserved_balance < amount:
            raise ValidationError("Insufficient reserved balance.")

        wallet.reserved_balance -= amount
        wallet.available_balance += amount
        wallet.save(update_fields=["reserved_balance", "available_balance", "updated_at"])

    @staticmethod
    @transaction.atomic
    def debit_reserved_funds(wallet: Wallet, amount: Decimal) -> None:
        """Atomically debit funds from the reserved balance."""
        if amount <= 0:
            raise ValidationError("Amount must be positive.")

        wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)

        if wallet.reserved_balance < amount:
            raise ValidationError("Insufficient reserved balance.")

        wallet.reserved_balance -= amount
        wallet.save(update_fields=["reserved_balance", "updated_at"])

    @classmethod
    @transaction.atomic
    def create_deposit_intent(
        cls, *, user, provider_code: str, amount, currency: str
    ) -> DepositIntent:
        """Create a deposit intent for the given user and provider."""
        try:
            provider = PaymentProvider.objects.get(code=provider_code.upper(), is_active=True)
        except PaymentProvider.DoesNotExist:
            raise ValidationError(
                {"provider_code": "Invalid or inactive payment provider."}
            ) from None

        decimal_amount = Decimal(str(amount))
        if decimal_amount <= 0:
            raise ValidationError({"amount": "Amount must be positive."})

        currency = currency.strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValidationError(
                {"currency": "Currency must be exactly three alphabetic characters."}
            )

        intent = DepositIntent.objects.create(
            user=user,
            provider=provider,
            amount=decimal_amount,
            currency=currency,
            expires_at=timezone.now() + timedelta(hours=2),
        )
        return intent

    @classmethod
    @transaction.atomic
    def get_deposit_intent(cls, *, user, intent_id) -> DepositIntent:
        """Get a deposit intent scoped to the user."""
        try:
            return DepositIntent.objects.get(id=intent_id, user=user)
        except DepositIntent.DoesNotExist:
            from django.http import Http404

            raise Http404 from None

    @classmethod
    @transaction.atomic
    def process_deposit_callback(cls, *, provider_code: str, payload: dict) -> None:
        """Process a provider deposit callback."""
        # Implementation would verify the callback payload and update
        # the deposit intent and wallet if payment was successful.
        # For now, this is a stub to satisfy the API contract.
        return None

    @classmethod
    @transaction.atomic
    def create_withdrawal_request(
        cls, *, user, amount, currency: str, destination: dict
    ) -> WithdrawalRequest:
        """Create a withdrawal request for the given user."""
        currency = currency.strip().upper()
        try:
            wallet = Wallet.objects.get(user=user, currency=currency)
        except Wallet.DoesNotExist:
            raise ValidationError(
                {"currency": "No wallet exists for the specified currency."}
            ) from None

        decimal_amount = Decimal(str(amount))
        if decimal_amount <= 0:
            raise ValidationError({"amount": "Amount must be positive."})

        if wallet.available_balance < decimal_amount:
            raise ValidationError({"amount": "Insufficient available balance."})

        withdrawal = WithdrawalRequest.objects.create(
            wallet=wallet,
            amount=decimal_amount,
            destination=destination,
        )
        return withdrawal

    @classmethod
    @transaction.atomic
    def get_withdrawal_request(cls, *, user, request_id) -> WithdrawalRequest:
        """Get a withdrawal request scoped to the user."""
        try:
            return WithdrawalRequest.objects.get(id=request_id, wallet__user=user)
        except WithdrawalRequest.DoesNotExist:
            from django.http import Http404

            raise Http404 from None

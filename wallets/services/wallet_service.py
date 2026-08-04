"""Service for core wallet balance and state management."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from wallets.models import (
    DepositIntent,
    PaymentProvider,
    Wallet,
    WithdrawalRequest,
)


class WalletService:
    @classmethod
    @transaction.atomic
    def get_or_create_wallet(cls, user, currency: str) -> Wallet:
        """Get or create a wallet for a user and currency."""
        wallet, _ = Wallet.objects.get_or_create(user=user, currency=currency.upper())
        return wallet

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

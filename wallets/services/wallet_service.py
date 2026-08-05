"""Service for core wallet balance and state management."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
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
    OPERATION_CREDIT = "CREDIT_AVAILABLE"
    OPERATION_RESERVE = "RESERVE_AVAILABLE"
    OPERATION_RELEASE = "RELEASE_RESERVED"
    OPERATION_DEBIT_AVAILABLE = "DEBIT_AVAILABLE"
    OPERATION_CONSUME_RESERVED = "CONSUME_RESERVED"

    @classmethod
    @transaction.atomic
    def get_or_create_wallet(cls, user, currency: str) -> Wallet:
        """Get or create a wallet for a user and currency."""
        wallet, _ = Wallet.objects.get_or_create(user=user, currency=currency.upper())
        return wallet

    @classmethod
    def credit(
        cls,
        *,
        user,
        currency: str,
        amount,
        idempotency_reference,
        market=None,
        order=None,
        fill=None,
        transaction=None,
    ) -> LedgerEntry:
        """Credit funds to available balance."""
        return cls._execute(
            user=user,
            currency=currency,
            amount=amount,
            idempotency_reference=idempotency_reference,
            operation=cls.OPERATION_CREDIT,
            create_wallet=True,
            market=market,
            order=order,
            fill=fill,
            wallet_transaction=transaction,
        )

    @classmethod
    def reserve(
        cls,
        *,
        user,
        currency: str,
        amount,
        idempotency_reference,
        market=None,
        order=None,
        fill=None,
        transaction=None,
    ) -> LedgerEntry:
        """Move funds from available to reserved balance."""
        return cls._execute(
            user=user,
            currency=currency,
            amount=amount,
            idempotency_reference=idempotency_reference,
            operation=cls.OPERATION_RESERVE,
            market=market,
            order=order,
            fill=fill,
            wallet_transaction=transaction,
        )

    @classmethod
    def release(
        cls,
        *,
        user,
        currency: str,
        amount,
        idempotency_reference,
        market=None,
        order=None,
        fill=None,
        transaction=None,
    ) -> LedgerEntry:
        """Move funds from reserved to available balance."""
        return cls._execute(
            user=user,
            currency=currency,
            amount=amount,
            idempotency_reference=idempotency_reference,
            operation=cls.OPERATION_RELEASE,
            market=market,
            order=order,
            fill=fill,
            wallet_transaction=transaction,
        )

    @classmethod
    def debit_available(
        cls,
        *,
        user,
        currency: str,
        amount,
        idempotency_reference,
        market=None,
        order=None,
        fill=None,
        transaction=None,
    ) -> LedgerEntry:
        """Debit funds from available balance."""
        return cls._execute(
            user=user,
            currency=currency,
            amount=amount,
            idempotency_reference=idempotency_reference,
            operation=cls.OPERATION_DEBIT_AVAILABLE,
            market=market,
            order=order,
            fill=fill,
            wallet_transaction=transaction,
        )

    @classmethod
    def consume_reserved(
        cls,
        *,
        user,
        currency: str,
        amount,
        idempotency_reference,
        market=None,
        order=None,
        fill=None,
        transaction=None,
    ) -> LedgerEntry:
        """Debit funds from reserved balance."""
        return cls._execute(
            user=user,
            currency=currency,
            amount=amount,
            idempotency_reference=idempotency_reference,
            operation=cls.OPERATION_CONSUME_RESERVED,
            market=market,
            order=order,
            fill=fill,
            wallet_transaction=transaction,
        )

    @classmethod
    @transaction.atomic
    def _execute(
        cls,
        *,
        user,
        currency,
        amount,
        idempotency_reference,
        operation,
        create_wallet=False,
        market=None,
        order=None,
        fill=None,
        wallet_transaction=None,
    ) -> LedgerEntry:
        currency = cls._normalize_currency(currency)
        amount = cls._normalize_amount(amount)
        reference = cls._normalize_reference(idempotency_reference)
        context = {
            "market": market,
            "order": order,
            "fill": fill,
            "transaction": wallet_transaction,
        }

        existing = cls._get_existing_entry(reference)
        if existing is not None:
            cls._require_matching_replay(
                entry=existing,
                user=user,
                currency=currency,
                amount=amount,
                operation=operation,
                **context,
            )
            return existing

        cls._lock_user(user)
        existing = cls._get_existing_entry(reference)
        if existing is not None:
            cls._require_matching_replay(
                entry=existing,
                user=user,
                currency=currency,
                amount=amount,
                operation=operation,
                **context,
            )
            return existing

        wallet = cls._get_locked_wallet(user=user, currency=currency)
        if wallet is None:
            if not create_wallet:
                raise ValidationError({"wallet": "A wallet for this currency does not exist."})
            wallet = Wallet(user=user, currency=currency)
            wallet.full_clean()
            wallet.save(force_insert=True)

        existing = cls._get_existing_entry(reference)
        if existing is not None:
            cls._require_matching_replay(
                entry=existing,
                user=user,
                currency=currency,
                amount=amount,
                operation=operation,
                **context,
            )
            return existing

        available_before = wallet.available_balance
        reserved_before = wallet.reserved_balance
        available_after, reserved_after, entry_type = cls._calculate_transition(
            operation=operation,
            amount=amount,
            available_balance=available_before,
            reserved_balance=reserved_before,
        )
        wallet.available_balance = available_after
        wallet.reserved_balance = reserved_after
        wallet.full_clean()
        wallet.save(update_fields=["available_balance", "reserved_balance", "updated_at"])

        internal = entry_type in (LedgerEntry.EntryType.RESERVE, LedgerEntry.EntryType.RELEASE)
        entry = LedgerEntry(
            wallet=wallet,
            entry_type=entry_type,
            debit_account=LedgerEntry.AccountType.USER_WALLET,
            credit_account=(
                LedgerEntry.AccountType.USER_WALLET
                if internal
                else (
                    LedgerEntry.AccountType.PROVIDER_PAYABLE
                    if operation == cls.OPERATION_CREDIT
                    else LedgerEntry.AccountType.REVENUE
                )
            ),
            amount=amount,
            currency=currency,
            available_balance_before=available_before,
            available_balance_after=available_after,
            reserved_balance_before=reserved_before,
            reserved_balance_after=reserved_after,
            idempotency_reference=reference,
            **context,
        )
        entry.full_clean(validate_unique=False, validate_constraints=False)
        try:
            with transaction.atomic():
                entry.save(force_insert=True)
        except IntegrityError as error:
            raise ValidationError({"idempotency_reference": IDEMPOTENCY_ERROR}) from error
        return entry

    @staticmethod
    def _normalize_currency(currency) -> str:
        normalized = str(currency or "").strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValidationError({"currency": "Currency must be a three-letter code."})
        return normalized

    @staticmethod
    def _normalize_amount(amount) -> Decimal:
        try:
            normalized = Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValidationError({"amount": "Amount must be a valid decimal value."}) from error
        if not normalized.is_finite() or normalized <= Decimal("0.0000"):
            raise ValidationError({"amount": "Amount must be greater than zero."})
        return normalized

    @staticmethod
    def _normalize_reference(reference) -> UUID:
        try:
            return reference if isinstance(reference, UUID) else UUID(str(reference))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValidationError(
                {"idempotency_reference": "A valid idempotency reference is required."}
            ) from error

    @staticmethod
    def _lock_user(user) -> None:
        type(user).objects.select_for_update(of=("self",)).get(pk=user.pk)

    @staticmethod
    def _get_locked_wallet(*, user, currency) -> Wallet | None:
        return (
            Wallet.objects.select_for_update(of=("self",))
            .filter(user=user, currency=currency)
            .first()
        )

    @staticmethod
    def _get_existing_entry(reference) -> LedgerEntry | None:
        return (
            LedgerEntry.objects.select_related("wallet", "wallet__user")
            .filter(idempotency_reference=reference)
            .first()
        )

    @classmethod
    def _calculate_transition(
        cls, *, operation, amount, available_balance, reserved_balance
    ) -> tuple[Decimal, Decimal, str]:
        if operation == cls.OPERATION_CREDIT:
            return available_balance + amount, reserved_balance, LedgerEntry.EntryType.CREDIT
        if operation == cls.OPERATION_RESERVE:
            if available_balance < amount:
                raise ValidationError({"available_balance": "Insufficient available balance."})
            return (
                available_balance - amount,
                reserved_balance + amount,
                LedgerEntry.EntryType.RESERVE,
            )
        if operation == cls.OPERATION_RELEASE:
            if reserved_balance < amount:
                raise ValidationError({"reserved_balance": "Insufficient reserved balance."})
            return (
                available_balance + amount,
                reserved_balance - amount,
                LedgerEntry.EntryType.RELEASE,
            )
        if operation == cls.OPERATION_DEBIT_AVAILABLE:
            if available_balance < amount:
                raise ValidationError({"available_balance": "Insufficient available balance."})
            return available_balance - amount, reserved_balance, LedgerEntry.EntryType.DEBIT
        if operation == cls.OPERATION_CONSUME_RESERVED:
            if reserved_balance < amount:
                raise ValidationError({"reserved_balance": "Insufficient reserved balance."})
            return available_balance, reserved_balance - amount, LedgerEntry.EntryType.DEBIT
        raise ValidationError({"operation": "Unsupported wallet operation."})

    @classmethod
    def _require_matching_replay(
        cls,
        *,
        entry,
        user,
        currency,
        amount,
        operation,
        market=None,
        order=None,
        fill=None,
        transaction=None,
    ) -> None:
        matches = all(
            (
                entry.wallet.user_id == user.pk,
                entry.wallet.currency == currency,
                entry.amount == amount,
                cls._entry_matches_operation(entry, operation),
                entry.market_id == getattr(market, "pk", None),
                entry.order_id == getattr(order, "pk", None),
                entry.fill_id == getattr(fill, "pk", None),
                entry.transaction_id == getattr(transaction, "pk", None),
            )
        )
        if not matches:
            raise ValidationError({"idempotency_reference": IDEMPOTENCY_ERROR})

    @classmethod
    def _entry_matches_operation(cls, entry, operation) -> bool:
        amount = entry.amount
        before_a, after_a = entry.available_balance_before, entry.available_balance_after
        before_r, after_r = entry.reserved_balance_before, entry.reserved_balance_after
        expected = {
            cls.OPERATION_CREDIT: (LedgerEntry.EntryType.CREDIT, before_a + amount, before_r),
            cls.OPERATION_RESERVE: (
                LedgerEntry.EntryType.RESERVE,
                before_a - amount,
                before_r + amount,
            ),
            cls.OPERATION_RELEASE: (
                LedgerEntry.EntryType.RELEASE,
                before_a + amount,
                before_r - amount,
            ),
            cls.OPERATION_DEBIT_AVAILABLE: (
                LedgerEntry.EntryType.DEBIT,
                before_a - amount,
                before_r,
            ),
            cls.OPERATION_CONSUME_RESERVED: (
                LedgerEntry.EntryType.DEBIT,
                before_a,
                before_r - amount,
            ),
        }.get(operation)
        return expected is not None and (entry.entry_type, after_a, after_r) == expected

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

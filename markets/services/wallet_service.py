from __future__ import annotations

import logging
from decimal import Decimal

from django.db import transaction

from accounts.models import User
from wallets.exceptions import (
    InsufficientFundsError,
    WalletOperationError,
)
from wallets.models import LedgerEntry, Wallet

logger = logging.getLogger(__name__)


class WalletService:
    """Service for atomic, idempotent wallet operations."""

    @staticmethod
    def _get_locked_wallet(user: User, currency: str) -> Wallet | None:
        """Get a wallet for a user and currency, locking the row."""
        return (
            Wallet.objects.select_for_update()
            .filter(
                user=user,
                currency=currency.upper(),
            )
            .first()
        )

    @staticmethod
    @transaction.atomic
    def credit(
        user: User,
        currency: str,
        amount: Decimal,
        entry_type: str,
        idempotency_reference: str,
        metadata: dict | None = None,
    ) -> LedgerEntry:
        """Credit a user's wallet, creating it if it doesn't exist."""
        if amount <= 0:
            raise WalletOperationError("Credit amount must be positive.")

        wallet = WalletService._get_locked_wallet(user, currency)

        if wallet:
            # Existing wallet: update balance
            before_available = wallet.available_balance
            before_reserved = wallet.reserved_balance
            wallet.available_balance += amount
            wallet.save(update_fields=["available_balance", "updated_at"])
        else:
            # New wallet: create with initial balance
            before_available = Decimal("0.0")
            before_reserved = Decimal("0.0")
            wallet = Wallet.objects.create(
                user=user,
                currency=currency.upper(),
                available_balance=amount,
            )

        return LedgerEntry.objects.create_entry(
            wallet=wallet,
            entry_type=entry_type,
            amount=amount,
            idempotency_reference=idempotency_reference,
            before_available=before_available,
            after_available=wallet.available_balance,
            before_reserved=before_reserved,
            after_reserved=wallet.reserved_balance,
            metadata=metadata,
        )

    @staticmethod
    @transaction.atomic
    def debit_available(
        user: User,
        currency: str,
        amount: Decimal,
        entry_type: str,
        idempotency_reference: str,
        metadata: dict | None = None,
    ) -> LedgerEntry:
        """Debit a user's available balance."""
        if amount <= 0:
            raise WalletOperationError("Debit amount must be positive.")

        wallet = WalletService._get_locked_wallet(user, currency)
        if not wallet or wallet.available_balance < amount:
            raise InsufficientFundsError("Insufficient available balance.")

        before_available = wallet.available_balance
        before_reserved = wallet.reserved_balance
        wallet.available_balance -= amount
        wallet.save(update_fields=["available_balance", "updated_at"])

        return LedgerEntry.objects.create_entry(
            wallet=wallet,
            entry_type=entry_type,
            amount=-amount,
            idempotency_reference=idempotency_reference,
            before_available=before_available,
            after_available=wallet.available_balance,
            before_reserved=before_reserved,
            after_reserved=wallet.reserved_balance,
            metadata=metadata,
        )

    @staticmethod
    @transaction.atomic
    def reserve(
        user: User,
        currency: str,
        amount: Decimal,
        idempotency_reference: str,
        metadata: dict | None = None,
    ) -> LedgerEntry:
        """Move funds from available to reserved balance."""
        if amount <= 0:
            raise WalletOperationError("Reserve amount must be positive.")

        wallet = WalletService._get_locked_wallet(user, currency)
        if not wallet or wallet.available_balance < amount:
            raise InsufficientFundsError("Insufficient available balance for reservation.")

        before_available = wallet.available_balance
        before_reserved = wallet.reserved_balance
        wallet.available_balance -= amount
        wallet.reserved_balance += amount
        wallet.save(update_fields=["available_balance", "reserved_balance", "updated_at"])

        return LedgerEntry.objects.create_entry(
            wallet=wallet,
            entry_type=LedgerEntry.EntryType.RESERVE,
            amount=amount,
            idempotency_reference=idempotency_reference,
            before_available=before_available,
            after_available=wallet.available_balance,
            before_reserved=before_reserved,
            after_reserved=wallet.reserved_balance,
            metadata=metadata,
        )

    @staticmethod
    @transaction.atomic
    def release(
        user: User,
        currency: str,
        amount: Decimal,
        idempotency_reference: str,
        metadata: dict | None = None,
    ) -> LedgerEntry:
        """Move funds from reserved to available balance."""
        if amount <= 0:
            raise WalletOperationError("Release amount must be positive.")

        wallet = WalletService._get_locked_wallet(user, currency)
        if not wallet or wallet.reserved_balance < amount:
            raise InsufficientFundsError("Insufficient reserved balance for release.")

        before_available = wallet.available_balance
        before_reserved = wallet.reserved_balance
        wallet.reserved_balance -= amount
        wallet.available_balance += amount
        wallet.save(update_fields=["available_balance", "reserved_balance", "updated_at"])

        return LedgerEntry.objects.create_entry(
            wallet=wallet,
            entry_type=LedgerEntry.EntryType.RELEASE,
            amount=amount,
            idempotency_reference=idempotency_reference,
            before_available=before_available,
            after_available=wallet.available_balance,
            before_reserved=before_reserved,
            after_reserved=wallet.reserved_balance,
            metadata=metadata,
        )

    @staticmethod
    @transaction.atomic
    def consume_reserved(
        user: User,
        currency: str,
        amount: Decimal,
        idempotency_reference: str,
        metadata: dict | None = None,
    ) -> LedgerEntry:
        """Consume (debit) funds from the reserved balance."""
        if amount <= 0:
            raise WalletOperationError("Consume amount must be positive.")

        wallet = WalletService._get_locked_wallet(user, currency)
        if not wallet or wallet.reserved_balance < amount:
            raise InsufficientFundsError("Insufficient reserved balance for consumption.")

        before_available = wallet.available_balance
        before_reserved = wallet.reserved_balance
        wallet.reserved_balance -= amount
        wallet.save(update_fields=["reserved_balance", "updated_at"])

        return LedgerEntry.objects.create_entry(
            wallet=wallet,
            entry_type=LedgerEntry.EntryType.CONSUME,
            amount=-amount,
            idempotency_reference=idempotency_reference,
            before_available=before_available,
            after_available=wallet.available_balance,
            before_reserved=before_reserved,
            after_reserved=wallet.reserved_balance,
            metadata=metadata,
        )
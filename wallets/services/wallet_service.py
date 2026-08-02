from decimal import (
    Decimal,
    InvalidOperation,
)
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import (
    IntegrityError,
    transaction,
)

from wallets.models import (
    LedgerEntry,
    Wallet,
)


class WalletService:
    OPERATION_CREDIT = "CREDIT_AVAILABLE"
    OPERATION_RESERVE = "RESERVE_AVAILABLE"
    OPERATION_RELEASE = "RELEASE_RESERVED"
    OPERATION_DEBIT_AVAILABLE = "DEBIT_AVAILABLE"
    OPERATION_CONSUME_RESERVED = "CONSUME_RESERVED"

    @classmethod
    def credit(
        cls,
        *,
        user,
        currency,
        amount,
        idempotency_reference,
        market=None,
        order=None,
        fill=None,
    ) -> LedgerEntry:
        return cls._execute(
            user=user,
            currency=currency,
            amount=amount,
            idempotency_reference=(idempotency_reference),
            operation=cls.OPERATION_CREDIT,
            create_wallet=True,
            market=market,
            order=order,
            fill=fill,
        )

    @classmethod
    def reserve(
        cls,
        *,
        user,
        currency,
        amount,
        idempotency_reference,
        market=None,
        order=None,
        fill=None,
    ) -> LedgerEntry:
        return cls._execute(
            user=user,
            currency=currency,
            amount=amount,
            idempotency_reference=(idempotency_reference),
            operation=cls.OPERATION_RESERVE,
            market=market,
            order=order,
            fill=fill,
        )

    @classmethod
    def release(
        cls,
        *,
        user,
        currency,
        amount,
        idempotency_reference,
        market=None,
        order=None,
        fill=None,
    ) -> LedgerEntry:
        return cls._execute(
            user=user,
            currency=currency,
            amount=amount,
            idempotency_reference=(idempotency_reference),
            operation=cls.OPERATION_RELEASE,
            market=market,
            order=order,
            fill=fill,
        )

    @classmethod
    def debit_available(
        cls,
        *,
        user,
        currency,
        amount,
        idempotency_reference,
    ) -> LedgerEntry:
        return cls._execute(
            user=user,
            currency=currency,
            amount=amount,
            idempotency_reference=(idempotency_reference),
            operation=(cls.OPERATION_DEBIT_AVAILABLE),
        )

    @classmethod
    def consume_reserved(
        cls,
        *,
        user,
        currency,
        amount,
        idempotency_reference,
        market=None,
        order=None,
        fill=None,
    ) -> LedgerEntry:
        return cls._execute(
            user=user,
            currency=currency,
            amount=amount,
            idempotency_reference=(idempotency_reference),
            operation=(cls.OPERATION_CONSUME_RESERVED),
            market=market,
            order=order,
            fill=fill,
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
    ) -> LedgerEntry:
        normalized_currency = cls._normalize_currency(currency)
        normalized_amount = cls._normalize_amount(amount)
        normalized_reference = cls._normalize_reference(idempotency_reference)

        existing_entry = cls._get_existing_entry(normalized_reference)

        if existing_entry is not None:
            cls._require_matching_replay(
                entry=existing_entry,
                user=user,
                currency=normalized_currency,
                amount=normalized_amount,
                operation=operation,
                market=market,
                order=order,
                fill=fill,
            )
            return existing_entry

        cls._lock_user(user)

        # The reference may have been committed
        # while this transaction waited for the
        # user lock.
        existing_entry = cls._get_existing_entry(normalized_reference)

        if existing_entry is not None:
            cls._require_matching_replay(
                entry=existing_entry,
                user=user,
                currency=normalized_currency,
                amount=normalized_amount,
                operation=operation,
                market=market,
                order=order,
                fill=fill,
            )
            return existing_entry

        wallet = cls._get_locked_wallet(
            user=user,
            currency=normalized_currency,
        )

        if wallet is None:
            if not create_wallet:
                raise ValidationError({"wallet": ("A wallet for this " "currency does not exist.")})

            wallet = Wallet(
                user=user,
                currency=normalized_currency,
            )
            wallet.full_clean()
            wallet.save(force_insert=True)

        # A transaction using another user lock
        # may have committed this global reference.
        existing_entry = cls._get_existing_entry(normalized_reference)

        if existing_entry is not None:
            cls._require_matching_replay(
                entry=existing_entry,
                user=user,
                currency=normalized_currency,
                amount=normalized_amount,
                operation=operation,
                market=market,
                order=order,
                fill=fill,
            )
            return existing_entry

        available_before = wallet.available_balance
        reserved_before = wallet.reserved_balance

        (
            available_after,
            reserved_after,
            entry_type,
        ) = cls._calculate_transition(
            operation=operation,
            amount=normalized_amount,
            available_balance=(available_before),
            reserved_balance=reserved_before,
        )

        wallet.available_balance = available_after
        wallet.reserved_balance = reserved_after
        wallet.full_clean()
        wallet.save(
            update_fields=[
                "available_balance",
                "reserved_balance",
                "updated_at",
            ]
        )

        entry = LedgerEntry(
            wallet=wallet,
            entry_type=entry_type,
            amount=normalized_amount,
            available_balance_before=(available_before),
            available_balance_after=(available_after),
            reserved_balance_before=(reserved_before),
            reserved_balance_after=(reserved_after),
            idempotency_reference=(normalized_reference),
            market=market,
            order=order,
            fill=fill,
        )
        entry.full_clean(
            validate_unique=False,
        )

        try:
            # The inner savepoint keeps the outer
            # transaction usable long enough to
            # translate a uniqueness race.
            with transaction.atomic():
                entry.save(force_insert=True)
        except IntegrityError as error:
            raise ValidationError(
                {"idempotency_reference": ("This idempotency reference " "has already been used.")}
            ) from error

        return entry

    @staticmethod
    def _normalize_currency(
        currency,
    ) -> str:
        normalized_currency = str(currency or "").strip().upper()

        if len(normalized_currency) != 3:
            raise ValidationError({"currency": ("Currency must be a " "three-letter code.")})

        return normalized_currency

    @staticmethod
    def _normalize_amount(
        amount,
    ) -> Decimal:
        try:
            normalized_amount = Decimal(str(amount))
        except (
            InvalidOperation,
            TypeError,
            ValueError,
        ) as error:
            raise ValidationError(
                {"amount": ("Amount must be a valid " "decimal value.")}
            ) from error

        if not normalized_amount.is_finite() or normalized_amount <= Decimal("0.0000"):
            raise ValidationError({"amount": ("Amount must be greater " "than zero.")})

        return normalized_amount

    @staticmethod
    def _normalize_reference(
        idempotency_reference,
    ) -> UUID:
        try:
            if isinstance(
                idempotency_reference,
                UUID,
            ):
                return idempotency_reference

            return UUID(str(idempotency_reference))
        except (
            TypeError,
            ValueError,
            AttributeError,
        ) as error:
            raise ValidationError(
                {"idempotency_reference": ("A valid idempotency " "reference is required.")}
            ) from error

    @staticmethod
    def _lock_user(user) -> None:
        type(user).objects.select_for_update(
            of=("self",),
        ).get(pk=user.pk)

    @staticmethod
    def _get_locked_wallet(
        *,
        user,
        currency,
    ) -> Wallet | None:
        return (
            Wallet.objects.select_for_update(
                of=("self",),
            )
            .filter(
                user=user,
                currency=currency,
            )
            .first()
        )

    @staticmethod
    def _get_existing_entry(
        idempotency_reference,
    ) -> LedgerEntry | None:
        return (
            LedgerEntry.objects.select_related(
                "wallet",
                "wallet__user",
            )
            .filter(idempotency_reference=(idempotency_reference))
            .first()
        )

    @classmethod
    def _calculate_transition(
        cls,
        *,
        operation,
        amount,
        available_balance,
        reserved_balance,
    ) -> tuple[
        Decimal,
        Decimal,
        str,
    ]:
        if operation == cls.OPERATION_CREDIT:
            return (
                available_balance + amount,
                reserved_balance,
                LedgerEntry.EntryType.CREDIT,
            )

        if operation == cls.OPERATION_RESERVE:
            cls._require_sufficient_available(
                available_balance=(available_balance),
                amount=amount,
            )
            return (
                available_balance - amount,
                reserved_balance + amount,
                LedgerEntry.EntryType.RESERVE,
            )

        if operation == cls.OPERATION_RELEASE:
            cls._require_sufficient_reserved(
                reserved_balance=(reserved_balance),
                amount=amount,
            )
            return (
                available_balance + amount,
                reserved_balance - amount,
                LedgerEntry.EntryType.RELEASE,
            )

        if operation == cls.OPERATION_DEBIT_AVAILABLE:
            cls._require_sufficient_available(
                available_balance=(available_balance),
                amount=amount,
            )
            return (
                available_balance - amount,
                reserved_balance,
                LedgerEntry.EntryType.DEBIT,
            )

        if operation == cls.OPERATION_CONSUME_RESERVED:
            cls._require_sufficient_reserved(
                reserved_balance=(reserved_balance),
                amount=amount,
            )
            return (
                available_balance,
                reserved_balance - amount,
                LedgerEntry.EntryType.DEBIT,
            )

        raise ValidationError({"operation": ("Unsupported wallet operation.")})

    @staticmethod
    def _require_sufficient_available(
        *,
        available_balance,
        amount,
    ) -> None:
        if available_balance < amount:
            raise ValidationError({"available_balance": ("Insufficient available " "balance.")})

    @staticmethod
    def _require_sufficient_reserved(
        *,
        reserved_balance,
        amount,
    ) -> None:
        if reserved_balance < amount:
            raise ValidationError({"reserved_balance": ("Insufficient reserved " "balance.")})

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
    ) -> None:
        matches = all(
            [
                entry.wallet.user_id == user.pk,
                entry.wallet.currency == currency,
                entry.amount == amount,
                cls._entry_matches_operation(
                    entry=entry,
                    operation=operation,
                ),
                entry.market_id
                == getattr(
                    market,
                    "pk",
                    None,
                ),
                entry.order_id
                == getattr(
                    order,
                    "pk",
                    None,
                ),
                entry.fill_id
                == getattr(
                    fill,
                    "pk",
                    None,
                ),
            ]
        )

        if not matches:
            raise ValidationError(
                {
                    "idempotency_reference": (
                        "This idempotency reference " "belongs to a different " "wallet operation."
                    )
                }
            )

    @classmethod
    def _entry_matches_operation(
        cls,
        *,
        entry,
        operation,
    ) -> bool:
        amount = entry.amount
        available_before = entry.available_balance_before
        available_after = entry.available_balance_after
        reserved_before = entry.reserved_balance_before
        reserved_after = entry.reserved_balance_after

        if operation == cls.OPERATION_CREDIT:
            return all(
                [
                    entry.entry_type == LedgerEntry.EntryType.CREDIT,
                    available_after == available_before + amount,
                    reserved_after == reserved_before,
                ]
            )

        if operation == cls.OPERATION_RESERVE:
            return all(
                [
                    entry.entry_type == LedgerEntry.EntryType.RESERVE,
                    available_after == available_before - amount,
                    reserved_after == reserved_before + amount,
                ]
            )

        if operation == cls.OPERATION_RELEASE:
            return all(
                [
                    entry.entry_type == LedgerEntry.EntryType.RELEASE,
                    available_after == available_before + amount,
                    reserved_after == reserved_before - amount,
                ]
            )

        if operation == cls.OPERATION_DEBIT_AVAILABLE:
            return all(
                [
                    entry.entry_type == LedgerEntry.EntryType.DEBIT,
                    available_after == available_before - amount,
                    reserved_after == reserved_before,
                ]
            )

        if operation == cls.OPERATION_CONSUME_RESERVED:
            return all(
                [
                    entry.entry_type == LedgerEntry.EntryType.DEBIT,
                    available_after == available_before,
                    reserved_after == reserved_before - amount,
                ]
            )

        return False

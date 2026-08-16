"""Service for core wallet balance and state management."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4, uuid5

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from wallets.services.withdrawal_risk_service import WithdrawalRiskService

from wallets.models import (
    AuditLog,
    DepositIntent,
    LedgerEntry,
    PaymentProvider,
    Wallet,
    WalletTransaction,
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
        counterparty_account=None,
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
            counterparty_account=counterparty_account,
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
        counterparty_account=None,
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
            counterparty_account=counterparty_account,
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
        counterparty_account=None,
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
            counterparty_account=counterparty_account,
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
        counterparty_account=None,
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
            counterparty_account=counterparty_account,
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
        counterparty_account=None,
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
            counterparty_account=counterparty_account,
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
        counterparty_account=None,
    ) -> LedgerEntry:
        currency = cls._normalize_currency(currency)
        amount = cls._normalize_amount(amount)
        reference = cls._normalize_reference(idempotency_reference)
        ledger_context = {
            "market": market,
            "order": order,
            "fill": fill,
            "transaction": wallet_transaction,
        }

        replay_context = {
            **ledger_context,
            "counterparty_account": counterparty_account,
        }

        existing = cls._get_existing_entry(reference)
        if existing is not None:
            cls._require_matching_replay(
                entry=existing,
                user=user,
                currency=currency,
                amount=amount,
                operation=operation,
                **replay_context,
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
                **replay_context,
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
                **replay_context,
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

        internal = entry_type in (
            LedgerEntry.EntryType.RESERVE,
            LedgerEntry.EntryType.RELEASE,
        )

        if internal:
            credit_account = LedgerEntry.AccountType.USER_WALLET
        elif counterparty_account is not None:
            valid_accounts = {choice for choice, _label in LedgerEntry.AccountType.choices}
            if counterparty_account not in valid_accounts:
                raise ValidationError({"counterparty_account": "Unsupported ledger account."})
            credit_account = counterparty_account
        elif operation == cls.OPERATION_CREDIT:
            credit_account = LedgerEntry.AccountType.PROVIDER_PAYABLE
        else:
            credit_account = LedgerEntry.AccountType.REVENUE

        entry = LedgerEntry(
            wallet=wallet,
            entry_type=entry_type,
            debit_account=LedgerEntry.AccountType.USER_WALLET,
            credit_account=credit_account,
            amount=amount,
            currency=currency,
            available_balance_before=available_before,
            available_balance_after=available_after,
            reserved_balance_before=reserved_before,
            reserved_balance_after=reserved_after,
            idempotency_reference=reference,
            **ledger_context,
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
        counterparty_account=None,
    ) -> None:
        if operation in (
            cls.OPERATION_RESERVE,
            cls.OPERATION_RELEASE,
        ):
            expected_credit_account = LedgerEntry.AccountType.USER_WALLET
        elif counterparty_account is not None:
            valid_accounts = {value for value, _label in LedgerEntry.AccountType.choices}
            if counterparty_account not in valid_accounts:
                raise ValidationError({"counterparty_account": "Unsupported ledger account."})
            expected_credit_account = counterparty_account
        elif operation == cls.OPERATION_CREDIT:
            expected_credit_account = LedgerEntry.AccountType.PROVIDER_PAYABLE
        else:
            expected_credit_account = LedgerEntry.AccountType.REVENUE

        matches = all(
            (
                entry.wallet.user_id == user.pk,
                entry.wallet.currency == currency,
                entry.amount == amount,
                cls._entry_matches_operation(entry, operation),
                entry.market_id == getattr(market, "pk", None),
                entry.order_id == getattr(order, "pk", None),
                entry.fill_id == getattr(fill, "pk", None),
                entry.transaction_id
                == getattr(
                    transaction,
                    "pk",
                    None,
                ),
                entry.credit_account == expected_credit_account,
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
        cls,
        *,
        user,
        provider_code: str,
        amount,
        currency: str,
        idempotency_key=None,
    ) -> DepositIntent:
        """Create an idempotent deposit intent."""

        provider_code = str(provider_code or "").strip().upper()

        try:
            provider = PaymentProvider.objects.get(
                code=provider_code,
                is_active=True,
            )
        except PaymentProvider.DoesNotExist:
            raise ValidationError(
                {"provider_code": "Invalid or inactive payment provider."}
            ) from None

        decimal_amount = cls._normalize_amount(amount)
        currency = cls._normalize_currency(currency)

        normalized_key = None

        if idempotency_key is not None:
            normalized_key = cls._normalize_reference(idempotency_key)

            existing = (
                DepositIntent.objects.select_related("provider")
                .filter(idempotency_key=normalized_key)
                .first()
            )

            if existing is not None:
                matches = all(
                    (
                        existing.user_id == user.pk,
                        existing.provider_id == provider.id,
                        existing.amount == decimal_amount,
                        existing.currency == currency,
                    )
                )

                if not matches:
                    raise ValidationError({"idempotency_key": IDEMPOTENCY_ERROR})

                return existing

        create_kwargs = {
            "user": user,
            "provider": provider,
            "amount": decimal_amount,
            "currency": currency,
            "expires_at": timezone.now() + timedelta(hours=2),
        }

        if normalized_key is not None:
            create_kwargs["idempotency_key"] = normalized_key

        return DepositIntent.objects.create(**create_kwargs)

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
        cls,
        *,
        user,
        amount,
        currency: str,
        destination: dict,
        idempotency_key=None,
    ) -> WithdrawalRequest:
        """Create a withdrawal and reserve its funds atomically."""

        if not getattr(user, "is_active", False):
            raise ValidationError(
                {"user": "An active account is required " "to request a withdrawal."}
            )

        if not getattr(user, "is_verified", False):
            raise ValidationError(
                {"user": "Identity verification is required " "before withdrawing funds."}
            )

        currency = cls._normalize_currency(currency)
        decimal_amount = cls._normalize_amount(amount)

        if not isinstance(destination, dict) or not destination:
            raise ValidationError({"destination": "A withdrawal destination " "is required."})

        try:
            request_key = UUID(str(idempotency_key)) if idempotency_key is not None else uuid4()
        except (
            TypeError,
            ValueError,
            AttributeError,
        ) as error:
            raise ValidationError({"idempotency_key": "A valid UUID is required."}) from error

        transaction_reference = f"WDR-{request_key.hex}"

        wallet = (
            Wallet.objects.select_for_update()
            .filter(
                user=user,
                currency=currency,
            )
            .first()
        )

        if wallet is None:
            raise ValidationError({"currency": "No wallet exists for " "the specified currency."})

        if wallet.status != Wallet.Status.ACTIVE:
            raise ValidationError({"wallet": "This wallet is not active."})

        existing_transaction = (
            WalletTransaction.objects.select_related(
                "wallet",
                "withdrawal_request",
            )
            .filter(reference=transaction_reference)
            .first()
        )

        if existing_transaction is not None:
            try:
                existing = existing_transaction.withdrawal_request
            except WithdrawalRequest.DoesNotExist:
                raise ValidationError(
                    {
                        "idempotency_key": "This reference belongs "
                        "to an incomplete financial "
                        "operation."
                    }
                ) from None

            matches = all(
                (
                    existing.wallet.user_id == user.pk,
                    existing.wallet.currency == currency,
                    existing.amount == decimal_amount,
                    existing.destination == destination,
                    existing_transaction.transaction_type
                    == WalletTransaction.TransactionType.WITHDRAWAL,
                )
            )

            if not matches:
                raise ValidationError({"idempotency_key": IDEMPOTENCY_ERROR})

            return existing

        if wallet.available_balance < decimal_amount:
            raise ValidationError({"amount": "Insufficient available balance."})

        wallet_transaction = WalletTransaction.objects.create(
            wallet=wallet,
            reference=transaction_reference,
            transaction_type=WalletTransaction.TransactionType.WITHDRAWAL,
            amount=decimal_amount,
            currency=currency,
            status=WalletTransaction.Status.PENDING,
            description=("Wallet withdrawal request"),
        )

        withdrawal = WithdrawalRequest.objects.create(
            wallet=wallet,
            amount=decimal_amount,
            destination=destination,
            transaction=wallet_transaction,
            status=WithdrawalRequest.Status.PENDING_APPROVAL,
        )

        reserve_reference = uuid5(
            request_key,
            "withdrawal-reserve",
        )

        cls.reserve(
            user=user,
            currency=currency,
            amount=decimal_amount,
            idempotency_reference=reserve_reference,
            transaction=wallet_transaction,
        )

        decision = WithdrawalRiskService.evaluate(withdrawal)

        withdrawal.risk_status = decision.risk_status
        withdrawal.risk_reasons = list(decision.reasons)
        withdrawal.approval_policy_version = decision.policy_version

        update_fields = [
            "risk_status",
            "risk_reasons",
            "approval_policy_version",
            "updated_at",
        ]

        if decision.auto_approve:
            withdrawal.status = WithdrawalRequest.Status.APPROVED
            withdrawal.approval_mode = WithdrawalRequest.ApprovalMode.AUTOMATIC
            withdrawal.approved_at = timezone.now()

            update_fields.extend(
                [
                    "status",
                    "approval_mode",
                    "approved_at",
                ]
            )

        withdrawal.save(update_fields=update_fields)

        AuditLog.objects.create(
            user=user,
            action="WITHDRAWAL_REQUESTED",
            related_object_id=withdrawal.id,
            metadata={
                "amount": str(decimal_amount),
                "currency": currency,
                "status": withdrawal.status,
                "transaction_id": str(wallet_transaction.id),
                "risk_status": withdrawal.risk_status,
                "risk_reasons": withdrawal.risk_reasons,
                "approval_mode": withdrawal.approval_mode,
                "approval_policy_version": withdrawal.approval_policy_version,
            },
        )

        if decision.auto_approve:
            AuditLog.objects.create(
                user=None,
                action="WITHDRAWAL_APPROVED",
                related_object_id=withdrawal.id,
                metadata={
                    "approval_mode": WithdrawalRequest.ApprovalMode.AUTOMATIC,
                    "policy_version": decision.policy_version,
                    "risk_status": decision.risk_status,
                    "risk_reasons": list(decision.reasons),
                    "amount": str(decimal_amount),
                    "currency": currency,
                    "transaction_id": str(wallet_transaction.id),
                },
            )

        return withdrawal

    @staticmethod
    def _require_withdrawal_actor(actor):
        if actor is None or not getattr(
            actor,
            "is_active",
            False,
        ):
            raise ValidationError(
                {"actor": ("An active user is required " "for this withdrawal action.")}
            )

    @staticmethod
    def _normalize_withdrawal_reason(
        reason,
        *,
        field_name,
    ) -> str:
        normalized = str(reason or "").strip()

        if not normalized:
            raise ValidationError({field_name: ("A reason is required.")})

        return normalized

    @staticmethod
    def _normalize_provider_reference(
        provider_reference,
    ) -> str:
        normalized = str(provider_reference or "").strip()

        if not normalized:
            raise ValidationError(
                {
                    "provider_reference": (
                        "A payout reference is " "required before completing " "a withdrawal."
                    )
                }
            )

        return normalized

    @classmethod
    def _get_locked_withdrawal(
        cls,
        *,
        withdrawal_id,
    ) -> WithdrawalRequest:
        try:
            withdrawal = (
                WithdrawalRequest.objects.select_for_update(of=("self",))
                .select_related(
                    "wallet",
                    "wallet__user",
                    "transaction",
                    "approved_by",
                )
                .get(
                    id=withdrawal_id,
                )
            )
        except WithdrawalRequest.DoesNotExist:
            raise ValidationError({"withdrawal": ("Withdrawal request not found.")}) from None

        if withdrawal.transaction_id is None:
            raise ValidationError({"withdrawal": ("Withdrawal has no financial " "transaction.")})

        if withdrawal.transaction.wallet_id != withdrawal.wallet_id:
            raise ValidationError(
                {"withdrawal": ("Withdrawal transaction does " "not match its wallet.")}
            )

        return withdrawal

    @classmethod
    @transaction.atomic
    def approve_withdrawal(
        cls,
        *,
        withdrawal_id,
        actor,
    ) -> WithdrawalRequest:
        """Manually approve a pending withdrawal."""
        cls._require_withdrawal_actor(
            actor,
        )

        withdrawal = cls._get_locked_withdrawal(
            withdrawal_id=withdrawal_id,
        )

        if withdrawal.status == WithdrawalRequest.Status.APPROVED:
            return withdrawal

        if withdrawal.status != WithdrawalRequest.Status.PENDING_APPROVAL:
            raise ValidationError({"status": ("Only a pending withdrawal " "can be approved.")})

        withdrawal.status = WithdrawalRequest.Status.APPROVED
        withdrawal.approval_mode = WithdrawalRequest.ApprovalMode.MANUAL
        withdrawal.approved_by = actor
        withdrawal.approved_at = timezone.now()

        withdrawal.save(
            update_fields=[
                "status",
                "approval_mode",
                "approved_by",
                "approved_at",
                "updated_at",
            ]
        )

        AuditLog.objects.create(
            user=actor,
            action="WITHDRAWAL_APPROVED",
            related_object_id=withdrawal.id,
            metadata={
                "approval_mode": (WithdrawalRequest.ApprovalMode.MANUAL),
                "amount": str(withdrawal.amount),
                "currency": (withdrawal.wallet.currency),
                "transaction_id": str(withdrawal.transaction_id),
            },
        )

        return withdrawal

    @classmethod
    @transaction.atomic
    def reject_withdrawal(
        cls,
        *,
        withdrawal_id,
        actor,
        reason,
    ) -> WithdrawalRequest:
        """Reject a pending withdrawal and release its funds."""
        cls._require_withdrawal_actor(
            actor,
        )

        normalized_reason = cls._normalize_withdrawal_reason(
            reason,
            field_name="reason",
        )

        withdrawal = cls._get_locked_withdrawal(
            withdrawal_id=withdrawal_id,
        )

        if withdrawal.status == WithdrawalRequest.Status.REJECTED:
            if withdrawal.rejection_reason != normalized_reason:
                raise ValidationError(
                    {
                        "reason": (
                            "This withdrawal was " "already rejected with a " "different reason."
                        )
                    }
                )

            return withdrawal

        if withdrawal.status != WithdrawalRequest.Status.PENDING_APPROVAL:
            raise ValidationError({"status": ("Only a pending withdrawal " "can be rejected.")})

        cls.release(
            user=withdrawal.wallet.user,
            currency=withdrawal.wallet.currency,
            amount=withdrawal.amount,
            idempotency_reference=uuid5(
                withdrawal.id,
                "withdrawal-reject-release",
            ),
            transaction=withdrawal.transaction,
        )

        withdrawal.transaction.status = WalletTransaction.Status.CANCELLED
        withdrawal.transaction.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        withdrawal.status = WithdrawalRequest.Status.REJECTED
        withdrawal.rejection_reason = normalized_reason

        withdrawal.save(
            update_fields=[
                "status",
                "rejection_reason",
                "updated_at",
            ]
        )

        AuditLog.objects.create(
            user=actor,
            action="WITHDRAWAL_REJECTED",
            related_object_id=withdrawal.id,
            metadata={
                "reason": normalized_reason,
                "amount": str(withdrawal.amount),
                "currency": (withdrawal.wallet.currency),
                "transaction_id": str(withdrawal.transaction_id),
            },
        )

        return withdrawal

    @classmethod
    @transaction.atomic
    def mark_withdrawal_processing(
        cls,
        *,
        withdrawal_id,
        actor,
    ) -> WithdrawalRequest:
        """Move an approved withdrawal into payout processing."""
        cls._require_withdrawal_actor(
            actor,
        )

        withdrawal = cls._get_locked_withdrawal(
            withdrawal_id=withdrawal_id,
        )

        if withdrawal.status == WithdrawalRequest.Status.PROCESSING:
            return withdrawal

        if withdrawal.status != WithdrawalRequest.Status.APPROVED:
            raise ValidationError(
                {"status": ("Only an approved withdrawal " "can enter processing.")}
            )

        withdrawal.status = WithdrawalRequest.Status.PROCESSING
        withdrawal.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        AuditLog.objects.create(
            user=actor,
            action="WITHDRAWAL_PROCESSING",
            related_object_id=withdrawal.id,
            metadata={
                "amount": str(withdrawal.amount),
                "currency": (withdrawal.wallet.currency),
                "transaction_id": str(withdrawal.transaction_id),
            },
        )

        return withdrawal

    @classmethod
    @transaction.atomic
    def complete_withdrawal(
        cls,
        *,
        withdrawal_id,
        actor,
        provider_reference,
    ) -> WithdrawalRequest:
        """Complete a paid withdrawal and consume reserved funds."""
        cls._require_withdrawal_actor(
            actor,
        )

        normalized_reference = cls._normalize_provider_reference(provider_reference)

        withdrawal = cls._get_locked_withdrawal(
            withdrawal_id=withdrawal_id,
        )

        if withdrawal.status == WithdrawalRequest.Status.COMPLETED:
            if withdrawal.transaction.provider_reference != normalized_reference:
                raise ValidationError(
                    {
                        "provider_reference": (
                            "This withdrawal was "
                            "already completed with a "
                            "different payout reference."
                        )
                    }
                )

            return withdrawal

        if withdrawal.status != WithdrawalRequest.Status.PROCESSING:
            raise ValidationError({"status": ("Only a processing withdrawal " "can be completed.")})

        cls.consume_reserved(
            user=withdrawal.wallet.user,
            currency=withdrawal.wallet.currency,
            amount=withdrawal.amount,
            idempotency_reference=uuid5(
                withdrawal.id,
                "withdrawal-complete-debit",
            ),
            transaction=withdrawal.transaction,
            counterparty_account=(LedgerEntry.AccountType.PROVIDER_PAYABLE),
        )

        completed_at = timezone.now()

        withdrawal.transaction.status = WalletTransaction.Status.COMPLETED
        withdrawal.transaction.provider_reference = normalized_reference
        withdrawal.transaction.completed_at = completed_at
        withdrawal.transaction.save(
            update_fields=[
                "status",
                "provider_reference",
                "completed_at",
                "updated_at",
            ]
        )

        withdrawal.status = WithdrawalRequest.Status.COMPLETED
        withdrawal.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        AuditLog.objects.create(
            user=actor,
            action="WITHDRAWAL_COMPLETED",
            related_object_id=withdrawal.id,
            metadata={
                "provider_reference": (normalized_reference),
                "amount": str(withdrawal.amount),
                "currency": (withdrawal.wallet.currency),
                "transaction_id": str(withdrawal.transaction_id),
            },
        )

        return withdrawal

    @classmethod
    @transaction.atomic
    def fail_withdrawal(
        cls,
        *,
        withdrawal_id,
        actor,
        reason,
    ) -> WithdrawalRequest:
        """Fail an uncompleted payout and return reserved funds."""
        cls._require_withdrawal_actor(
            actor,
        )

        normalized_reason = cls._normalize_withdrawal_reason(
            reason,
            field_name="reason",
        )

        withdrawal = cls._get_locked_withdrawal(
            withdrawal_id=withdrawal_id,
        )

        if withdrawal.status == WithdrawalRequest.Status.FAILED:
            if withdrawal.failure_reason != normalized_reason:
                raise ValidationError(
                    {"reason": ("This withdrawal already " "failed with a different " "reason.")}
                )

            return withdrawal

        if withdrawal.status not in (
            WithdrawalRequest.Status.APPROVED,
            WithdrawalRequest.Status.PROCESSING,
        ):
            raise ValidationError(
                {
                    "status": (
                        "Only an approved or " "processing withdrawal can " "be marked failed."
                    )
                }
            )

        cls.release(
            user=withdrawal.wallet.user,
            currency=withdrawal.wallet.currency,
            amount=withdrawal.amount,
            idempotency_reference=uuid5(
                withdrawal.id,
                "withdrawal-fail-release",
            ),
            transaction=withdrawal.transaction,
        )

        withdrawal.transaction.status = WalletTransaction.Status.FAILED
        withdrawal.transaction.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )

        withdrawal.status = WithdrawalRequest.Status.FAILED
        withdrawal.failure_reason = normalized_reason
        withdrawal.save(
            update_fields=[
                "status",
                "failure_reason",
                "updated_at",
            ]
        )

        AuditLog.objects.create(
            user=actor,
            action="WITHDRAWAL_FAILED",
            related_object_id=withdrawal.id,
            metadata={
                "reason": normalized_reason,
                "amount": str(withdrawal.amount),
                "currency": (withdrawal.wallet.currency),
                "transaction_id": str(withdrawal.transaction_id),
            },
        )

        return withdrawal

    @classmethod
    @transaction.atomic
    def get_withdrawal_request(cls, *, user, request_id) -> WithdrawalRequest:
        """Get a withdrawal request scoped to the user."""
        try:
            return WithdrawalRequest.objects.select_related(
                "wallet",
                "transaction",
                "approved_by",
            ).get(
                id=request_id,
                wallet__user=user,
            )
        except WithdrawalRequest.DoesNotExist:
            from django.http import Http404

            raise Http404 from None

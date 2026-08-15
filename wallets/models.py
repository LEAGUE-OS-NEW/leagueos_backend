"""Wallet, transaction, and ledger models."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class TimeStampedUUIDModel(models.Model):
    """Abstract base with a UUID primary key and timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Wallet(TimeStampedUUIDModel):
    """Represents a user's wallet for a specific currency."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", _("Active")
        SUSPENDED = "SUSPENDED", _("Suspended")
        CLOSED = "CLOSED", _("Closed")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="wallets",
    )
    currency = models.CharField(max_length=3, default="UGX", db_index=True)
    available_balance = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    reserved_balance = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )

    class Meta:
        ordering = ["currency"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "currency"], name="unique_user_currency_wallet"
            ),
            models.CheckConstraint(
                condition=models.Q(available_balance__gte=0),
                name="available_balance_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_balance__gte=0),
                name="reserved_balance_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user}'s {self.currency} Wallet"

    def save(self, *args, **kwargs):
        self.currency = self.currency.upper()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if self.available_balance is None or self.available_balance < Decimal("0.0000"):
            errors["available_balance"] = "Available balance cannot be negative."
        if self.reserved_balance is None or self.reserved_balance < Decimal("0.0000"):
            errors["reserved_balance"] = "Reserved balance cannot be negative."
        if errors:
            raise ValidationError(errors)

    @property
    def total_balance(self) -> models.Decimal:
        return self.available_balance + self.reserved_balance


class PaymentProvider(TimeStampedUUIDModel):
    """Configurable payment provider."""

    class ProviderType(models.TextChoices):
        GENERIC = "GENERIC", _("Generic")
        MOCK = "MOCK", _("Mock Provider")

    code = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    provider_type = models.CharField(
        max_length=50,
        choices=ProviderType.choices,
        default=ProviderType.GENERIC,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    config = models.JSONField(default=dict, blank=True, help_text="Provider-specific configuration")

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class WalletTransaction(TimeStampedUUIDModel):
    """A single financial transaction against a wallet."""

    class TransactionType(models.TextChoices):
        DEPOSIT = "DEPOSIT", _("Deposit")
        WITHDRAWAL = "WITHDRAWAL", _("Withdrawal")
        ADJUSTMENT = "ADJUSTMENT", _("Adjustment")

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        COMPLETED = "COMPLETED", _("Completed")
        FAILED = "FAILED", _("Failed")
        CANCELLED = "CANCELLED", _("Cancelled")

    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="transactions")
    reference = models.CharField(max_length=255, unique=True, db_index=True, default=uuid.uuid4)
    transaction_type = models.CharField(
        max_length=20, choices=TransactionType.choices, db_index=True
    )
    amount = models.DecimalField(max_digits=16, decimal_places=4)
    currency = models.CharField(max_length=3)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    provider = models.ForeignKey(
        PaymentProvider,
        on_delete=models.PROTECT,
        related_name="transactions",
        null=True,
        blank=True,
    )
    provider_reference = models.CharField(max_length=255, blank=True, db_index=True)
    description = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "status", "-created_at"]),
            models.Index(fields=["transaction_type", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.transaction_type} of {self.amount} {self.currency}"


class LedgerEntry(TimeStampedUUIDModel):
    """A single entry in the double-entry bookkeeping ledger."""

    class EntryType(models.TextChoices):
        CREDIT = "CREDIT", _("Credit")
        DEBIT = "DEBIT", _("Debit")
        RESERVE = "RESERVE", _("Reserve")
        RELEASE = "RELEASE", _("Release")

    class AccountType(models.TextChoices):
        USER_WALLET = "USER_WALLET", _("User Wallet")
        PROVIDER_PAYABLE = "PROVIDER_PAYABLE", _("Provider Payable")
        REVENUE = "REVENUE", _("Revenue")
        # Add other internal accounts as needed

    wallet = models.ForeignKey(
        Wallet, on_delete=models.PROTECT, related_name="ledger_entries", null=True, blank=True
    )
    transaction = models.ForeignKey(
        WalletTransaction,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        null=True,
        blank=True,
    )
    entry_type = models.CharField(
        max_length=20,
        choices=EntryType.choices,
        db_index=True,
        default=EntryType.CREDIT,
    )
    debit_account = models.CharField(max_length=50, choices=AccountType.choices)
    credit_account = models.CharField(max_length=50, choices=AccountType.choices)
    amount = models.DecimalField(max_digits=16, decimal_places=4)
    currency = models.CharField(max_length=3)
    available_balance_before = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    available_balance_after = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    reserved_balance_before = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    reserved_balance_after = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    idempotency_reference = models.UUIDField(null=True, blank=True, db_index=True)

    # Optional references for market operations
    market = models.ForeignKey(
        "markets.Market",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    order = models.ForeignKey(
        "markets.MarketOrder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    fill = models.ForeignKey(
        "markets.MarketFill",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Ledger entries"
        constraints = [
            models.UniqueConstraint(
                fields=["idempotency_reference"],
                name="unique_idempotency_reference",
                condition=models.Q(idempotency_reference__isnull=False),
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="ledger_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(available_balance_before__gte=0),
                name="ledger_available_before_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(available_balance_after__gte=0),
                name="ledger_available_after_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_balance_before__gte=0),
                name="ledger_reserved_before_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(reserved_balance_after__gte=0),
                name="ledger_reserved_after_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"Ledger {self.id}: {self.debit_account} -> {self.credit_account} ({self.amount})"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Ledger entries are immutable and cannot be updated.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Ledger entries are immutable and cannot be deleted.")

    def clean(self):
        super().clean()
        errors = {}
        # Allow same debit/credit account for internal wallet operations
        if self.debit_account == self.credit_account and self.entry_type not in (
            LedgerEntry.EntryType.RESERVE,
            LedgerEntry.EntryType.RELEASE,
        ):
            errors["credit_account"] = (
                "Debit and credit accounts cannot be the same for this entry type."
            )
        if self.amount is None or self.amount <= Decimal("0.0000"):
            errors["amount"] = "Amount must be positive."
        for field_name in (
            "available_balance_before",
            "available_balance_after",
            "reserved_balance_before",
            "reserved_balance_after",
        ):
            value = getattr(self, field_name)
            if value is None or value < Decimal("0.0000"):
                errors[field_name] = "Balance snapshots cannot be negative."
        if (
            self.idempotency_reference is not None
            and type(self)
            .objects.exclude(pk=self.pk)
            .filter(idempotency_reference=self.idempotency_reference)
            .exists()
        ):
            errors["idempotency_reference"] = "This idempotency reference has already been used."
        if errors:
            raise ValidationError(errors)


class DepositIntent(TimeStampedUUIDModel):
    """An intent to deposit funds, created by a user."""

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        COMPLETED = "COMPLETED", _("Completed")
        FAILED = "FAILED", _("Failed")
        EXPIRED = "EXPIRED", _("Expired")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="deposit_intents"
    )
    provider = models.ForeignKey(
        PaymentProvider,
        on_delete=models.PROTECT,
        related_name="deposit_intents",
    )
    amount = models.DecimalField(max_digits=16, decimal_places=4)
    currency = models.CharField(max_length=3)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    idempotency_key = models.UUIDField(unique=True, default=uuid.uuid4)
    transaction = models.OneToOneField(
        WalletTransaction,
        on_delete=models.SET_NULL,
        related_name="deposit_intent",
        null=True,
        blank=True,
    )
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Deposit intent for {self.amount} {self.currency} by {self.user}"


class PesapalDeposit(TimeStampedUUIDModel):
    """Pesapal API 3.0 state associated with one wallet deposit intent."""

    class Environment(models.TextChoices):
        SANDBOX = "SANDBOX", _("Sandbox")
        LIVE = "LIVE", _("Live")

    intent = models.OneToOneField(
        DepositIntent,
        on_delete=models.PROTECT,
        related_name="pesapal",
    )
    environment = models.CharField(
        max_length=10,
        choices=Environment.choices,
        default=Environment.SANDBOX,
        db_index=True,
    )
    merchant_reference = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
    )
    order_tracking_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
    )
    redirect_url = models.URLField(
        max_length=2048,
        blank=True,
    )
    provider_status = models.CharField(
        max_length=30,
        blank=True,
        db_index=True,
    )
    confirmation_code = models.CharField(
        max_length=255,
        blank=True,
    )
    payment_method = models.CharField(
        max_length=100,
        blank=True,
    )
    payment_account = models.CharField(
        max_length=255,
        blank=True,
    )
    status_description = models.TextField(
        blank=True,
    )
    last_checked_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["order_tracking_id"],
                condition=~models.Q(order_tracking_id=""),
                name="unique_pesapal_order_tracking_id",
            ),
        ]

    def __str__(self) -> str:
        return f"Pesapal {self.environment} " f"{self.merchant_reference}"


class WithdrawalRequest(TimeStampedUUIDModel):
    """A user's request to withdraw funds."""

    class Status(models.TextChoices):
        PENDING_APPROVAL = "PENDING_APPROVAL", _("Pending Approval")
        APPROVED = "APPROVED", _("Approved")
        REJECTED = "REJECTED", _("Rejected")
        PROCESSING = "PROCESSING", _("Processing")
        COMPLETED = "COMPLETED", _("Completed")
        FAILED = "FAILED", _("Failed")

    class RiskStatus(models.TextChoices):
        NOT_CHECKED = "NOT_CHECKED", _("Not Checked")
        PASSED = "PASSED", _("Passed")
        FLAGGED = "FLAGGED", _("Flagged for Review")
        FAILED = "FAILED", _("Failed")

    class ApprovalMode(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        AUTOMATIC = "AUTOMATIC", _("Automatic")
        MANUAL = "MANUAL", _("Manual")

    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="withdrawal_requests")
    amount = models.DecimalField(max_digits=16, decimal_places=4)
    destination = models.JSONField(
        help_text="Provider-specific destination details, e.g., bank account"
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING_APPROVAL, db_index=True
    )
    risk_status = models.CharField(
        max_length=20,
        choices=RiskStatus.choices,
        default=RiskStatus.NOT_CHECKED,
        db_index=True,
    )
    transaction = models.OneToOneField(
        WalletTransaction,
        on_delete=models.SET_NULL,
        related_name="withdrawal_request",
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_withdrawals",
        null=True,
        blank=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    approval_mode = models.CharField(
        max_length=20,
        choices=ApprovalMode.choices,
        default=ApprovalMode.PENDING,
        db_index=True,
    )
    risk_reasons = models.JSONField(
        default=list,
        blank=True,
    )
    approval_policy_version = models.CharField(
        max_length=50,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Withdrawal request for {self.amount} {self.wallet.currency}"


class Receipt(TimeStampedUUIDModel):
    """A receipt for a completed financial transaction."""

    transaction = models.OneToOneField(
        WalletTransaction, on_delete=models.PROTECT, related_name="receipt"
    )
    receipt_number = models.CharField(max_length=255, unique=True, db_index=True)
    file_url = models.URLField(max_length=1024, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self) -> str:
        return f"Receipt {self.receipt_number} for transaction {self.transaction_id}"


class AuditLog(TimeStampedUUIDModel):
    """Generic audit log for wallet actions."""

    ACTION_CHOICES = [
        # Deposits
        ("DEPOSIT_INTENT_CREATED", "Deposit intent created"),
        ("DEPOSIT_COMPLETED", "Deposit completed"),
        ("DEPOSIT_FAILED", "Deposit failed"),
        # Withdrawals
        ("WITHDRAWAL_REQUESTED", "Withdrawal requested"),
        ("WITHDRAWAL_APPROVED", "Withdrawal approved"),
        ("WITHDRAWAL_REJECTED", "Withdrawal rejected"),
        ("WITHDRAWAL_COMPLETED", "Withdrawal completed"),
        ("WITHDRAWAL_FAILED", "Withdrawal failed"),
        # Ledger & Transactions
        ("LEDGER_ENTRY_CREATED", "Ledger entry created"),
        ("TRANSACTION_VIEWED", "Transaction viewed"),
        # Receipts
        ("RECEIPT_GENERATED", "Receipt generated"),
        ("RECEIPT_DOWNLOADED", "Receipt downloaded"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="wallet_audit_logs",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES, db_index=True)
    related_object_id = models.UUIDField(null=True, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "action", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} by {self.user} at {self.created_at.isoformat()}"

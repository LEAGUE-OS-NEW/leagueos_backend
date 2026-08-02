import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class TimeStampedUUIDModel(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        abstract = True


class Wallet(TimeStampedUUIDModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="wallets",
    )
    currency = models.CharField(
        max_length=3,
        default="UGX",
        db_index=True,
    )
    available_balance = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    reserved_balance = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=Decimal("0.0000"),
    )

    class Meta:
        ordering = [
            "user_id",
            "currency",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "user",
                    "currency",
                ],
                name="wallet_user_currency_unique",
            ),
            models.CheckConstraint(
                condition=Q(
                    available_balance__gte=0,
                ),
                name=("wallet_available_balance_" "non_negative"),
            ),
            models.CheckConstraint(
                condition=Q(
                    reserved_balance__gte=0,
                ),
                name=("wallet_reserved_balance_" "non_negative"),
            ),
        ]
        indexes = [
            models.Index(
                fields=[
                    "user",
                    "currency",
                ],
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.user_id}: {self.currency} "
            f"({self.available_balance} available, "
            f"{self.reserved_balance} reserved)"
        )

    def save(self, *args, **kwargs):
        if self.currency:
            self.currency = self.currency.strip().upper()

        return super().save(
            *args,
            **kwargs,
        )

    def clean(self):
        super().clean()

        errors = {}

        if self.available_balance is None or self.available_balance < Decimal("0.0000"):
            errors["available_balance"] = "Available balance cannot be " "negative."

        if self.reserved_balance is None or self.reserved_balance < Decimal("0.0000"):
            errors["reserved_balance"] = "Reserved balance cannot be " "negative."

        if errors:
            raise ValidationError(errors)


class LedgerEntry(TimeStampedUUIDModel):
    class EntryType(models.TextChoices):
        CREDIT = "CREDIT", "Credit"
        DEBIT = "DEBIT", "Debit"
        RESERVE = "RESERVE", "Reserve"
        RELEASE = "RELEASE", "Release"

    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    entry_type = models.CharField(
        max_length=20,
        choices=EntryType.choices,
        db_index=True,
    )
    amount = models.DecimalField(
        max_digits=20,
        decimal_places=4,
    )
    available_balance_before = models.DecimalField(
        max_digits=20,
        decimal_places=4,
    )
    available_balance_after = models.DecimalField(
        max_digits=20,
        decimal_places=4,
    )
    reserved_balance_before = models.DecimalField(
        max_digits=20,
        decimal_places=4,
    )
    reserved_balance_after = models.DecimalField(
        max_digits=20,
        decimal_places=4,
    )
    idempotency_reference = models.UUIDField(
        unique=True,
    )
    market = models.ForeignKey(
        "markets.Market",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        null=True,
        blank=True,
    )
    order = models.ForeignKey(
        "markets.MarketOrder",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        null=True,
        blank=True,
    )
    fill = models.ForeignKey(
        "markets.MarketFill",
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = [
            "-created_at",
            "-id",
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="ledger_entry_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(
                    available_balance_before__gte=0,
                ),
                name=("ledger_available_before_" "non_negative"),
            ),
            models.CheckConstraint(
                condition=Q(
                    available_balance_after__gte=0,
                ),
                name=("ledger_available_after_" "non_negative"),
            ),
            models.CheckConstraint(
                condition=Q(
                    reserved_balance_before__gte=0,
                ),
                name=("ledger_reserved_before_" "non_negative"),
            ),
            models.CheckConstraint(
                condition=Q(
                    reserved_balance_after__gte=0,
                ),
                name=("ledger_reserved_after_" "non_negative"),
            ),
        ]
        indexes = [
            models.Index(
                fields=[
                    "wallet",
                    "created_at",
                ],
            ),
            models.Index(
                fields=[
                    "entry_type",
                    "created_at",
                ],
            ),
            models.Index(
                fields=[
                    "market",
                    "created_at",
                ],
            ),
            models.Index(
                fields=[
                    "order",
                    "created_at",
                ],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.idempotency_reference}: " f"{self.entry_type} {self.amount}"

    def save(self, *args, **kwargs):
        if (
            self.pk
            and type(self)
            .objects.filter(
                pk=self.pk,
            )
            .exists()
        ):
            raise ValidationError("Ledger entries are immutable " "and cannot be updated.")

        return super().save(
            *args,
            **kwargs,
        )

    def delete(self, *args, **kwargs):
        raise ValidationError("Ledger entries are immutable " "and cannot be deleted.")

    def clean(self):
        super().clean()

        errors = {}

        if self.amount is None or self.amount <= Decimal("0.0000"):
            errors["amount"] = "Ledger entry amount must be " "positive."

        snapshot_fields = (
            "available_balance_before",
            "available_balance_after",
            "reserved_balance_before",
            "reserved_balance_after",
        )

        for field_name in snapshot_fields:
            value = getattr(
                self,
                field_name,
            )

            if value is None or value < Decimal("0.0000"):
                errors[field_name] = "Ledger balance snapshots " "cannot be negative."

        if errors:
            raise ValidationError(errors)

from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from wallets.models import (
    LedgerEntry,
    Wallet,
    WithdrawalRequest,
)


class WalletReadSerializer(serializers.ModelSerializer):
    total_balance = serializers.SerializerMethodField()

    class Meta:
        model = Wallet
        fields = (
            "id",
            "currency",
            "available_balance",
            "reserved_balance",
            "total_balance",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(
        serializers.DecimalField(
            max_digits=18,
            decimal_places=4,
        )
    )
    def get_total_balance(self, wallet):
        total = wallet.available_balance + wallet.reserved_balance
        return f"{total.quantize(Decimal('0.0000')):.4f}"


class LedgerEntryReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerEntry
        fields = (
            "id",
            "debit_account",
            "credit_account",
            "amount",
            "currency",
            "created_at",
        )
        read_only_fields = fields


class LedgerEntryFilterSerializer(serializers.Serializer):
    debit_account = serializers.ChoiceField(choices=LedgerEntry.AccountType.choices, required=False)
    credit_account = serializers.ChoiceField(
        choices=LedgerEntry.AccountType.choices, required=False
    )
    created_from = serializers.DateTimeField(required=False)
    created_to = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        created_from = attrs.get("created_from")
        created_to = attrs.get("created_to")
        if created_from and created_to and created_from > created_to:
            raise serializers.ValidationError(
                {"created_from": "Must be earlier than or equal to created_to."}
            )
        return attrs


class DepositIntentSerializer(serializers.Serializer):
    provider_code = serializers.CharField()
    amount = serializers.DecimalField(
        max_digits=16,
        decimal_places=4,
        min_value=Decimal("0.01"),
    )
    currency = serializers.CharField(max_length=3)
    idempotency_key = serializers.UUIDField(required=False)


class DepositIntentReadSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=16, decimal_places=4)
    currency = serializers.CharField(max_length=3)
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
    payment_url = serializers.CharField(required=False)
    provider_code = serializers.CharField(required=False)
    order_tracking_id = serializers.CharField(required=False)
    provider_status = serializers.CharField(required=False)


class WithdrawalRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=16,
        decimal_places=4,
        min_value=Decimal("0.01"),
    )
    currency = serializers.CharField(max_length=3)
    destination = serializers.JSONField()
    idempotency_key = serializers.UUIDField(required=False)


class WalletSpendSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=16,
        decimal_places=4,
        min_value=Decimal("0.01"),
    )
    currency = serializers.CharField(max_length=3)
    description = serializers.CharField(
        allow_blank=True,
        required=False,
        max_length=500,
    )
    idempotency_key = serializers.UUIDField(required=False)


class WalletSpendReadSerializer(serializers.Serializer):
    transaction_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=16, decimal_places=4)
    currency = serializers.CharField()
    available_balance = serializers.DecimalField(max_digits=16, decimal_places=4)
    reference = serializers.CharField()


class WithdrawalRequestFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=WithdrawalRequest.Status.choices,
        required=False,
    )
    currency = serializers.CharField(
        max_length=3,
        required=False,
    )
    created_from = serializers.DateTimeField(
        required=False,
    )
    created_to = serializers.DateTimeField(
        required=False,
    )

    def validate(self, attrs):
        created_from = attrs.get("created_from")
        created_to = attrs.get("created_to")

        if created_from and created_to and created_from > created_to:
            raise serializers.ValidationError(
                {"created_from": ("Must be earlier than or equal " "to created_to.")}
            )

        return attrs


class WithdrawalRequestReadSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    amount = serializers.DecimalField(
        max_digits=16,
        decimal_places=4,
    )
    currency = serializers.SerializerMethodField()
    destination = serializers.JSONField()
    status = serializers.CharField()
    risk_status = serializers.CharField()
    risk_reasons = serializers.JSONField()
    approval_mode = serializers.CharField()
    approval_policy_version = serializers.CharField()
    approved_at = serializers.DateTimeField(allow_null=True)
    rejection_reason = serializers.CharField()
    failure_reason = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    transaction_id = serializers.UUIDField(allow_null=True)

    @extend_schema_field(serializers.CharField())
    def get_currency(self, withdrawal):
        if isinstance(withdrawal, dict):
            return withdrawal.get("currency")
        return withdrawal.wallet.currency


class WalletTransactionReadSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    reference = serializers.CharField()
    transaction_type = serializers.CharField()
    amount = serializers.DecimalField(
        max_digits=16,
        decimal_places=4,
    )
    currency = serializers.CharField()
    status = serializers.CharField()
    provider_code = serializers.SerializerMethodField()
    provider_reference = serializers.CharField()
    description = serializers.CharField()
    completed_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_provider_code(self, transaction):
        if transaction.provider_id is None:
            return None
        return transaction.provider.code


class DepositCallbackSerializer(serializers.Serializer):
    """Provider callback payload - intentionally permissive."""


class PesapalNotificationSerializer(serializers.Serializer):
    OrderTrackingId = serializers.CharField()
    OrderMerchantReference = serializers.CharField()
    OrderNotificationType = serializers.CharField(required=False)


class PesapalIpnAcknowledgementSerializer(serializers.Serializer):
    orderNotificationType = serializers.CharField()
    orderTrackingId = serializers.CharField()
    orderMerchantReference = serializers.CharField()
    status = serializers.IntegerField()


class PesapalCallbackResultSerializer(serializers.Serializer):
    deposit = serializers.CharField(allow_blank=True)
    status = serializers.CharField()

from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from wallets.models import LedgerEntry, Wallet


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
    amount = serializers.DecimalField(max_digits=16, decimal_places=4, min_value=Decimal("0.01"))
    currency = serializers.CharField(max_length=3)


class DepositIntentReadSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=16, decimal_places=4)
    currency = serializers.CharField(max_length=3)
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
    payment_url = serializers.CharField(required=False)


class WithdrawalRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=16, decimal_places=4, min_value=Decimal("0.01"))
    currency = serializers.CharField(max_length=3)
    destination = serializers.JSONField()


class DepositCallbackSerializer(serializers.Serializer):
    """Provider callback payload - intentionally permissive."""

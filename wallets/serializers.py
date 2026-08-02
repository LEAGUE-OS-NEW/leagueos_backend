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
    market_id = serializers.UUIDField(read_only=True, allow_null=True)
    order_id = serializers.UUIDField(read_only=True, allow_null=True)
    fill_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = LedgerEntry
        fields = (
            "id",
            "entry_type",
            "amount",
            "available_balance_before",
            "available_balance_after",
            "reserved_balance_before",
            "reserved_balance_after",
            "idempotency_reference",
            "market_id",
            "order_id",
            "fill_id",
            "created_at",
        )
        read_only_fields = fields


class LedgerEntryFilterSerializer(serializers.Serializer):
    entry_type = serializers.ChoiceField(choices=LedgerEntry.EntryType.choices, required=False)
    market_id = serializers.UUIDField(required=False)
    order_id = serializers.UUIDField(required=False)
    fill_id = serializers.UUIDField(required=False)
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

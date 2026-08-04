from decimal import Decimal

from django.utils import timezone
from rest_framework import serializers

from markets.models import (
    MarketFill,
    MarketOrder,
    MarketPosition,
)


class MarketOrderCreateSerializer(serializers.Serializer):
    outcome_id = serializers.UUIDField()
    side = serializers.ChoiceField(
        choices=MarketOrder.Side.choices,
    )
    quantity = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0.0001"),
    )
    limit_price = serializers.DecimalField(
        max_digits=6,
        decimal_places=5,
        min_value=Decimal("0.00001"),
        max_value=Decimal("0.99999"),
    )
    time_in_force = serializers.ChoiceField(
        choices=MarketOrder.TimeInForce.choices,
        default=MarketOrder.TimeInForce.GTC,
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate(self, attrs):
        time_in_force = attrs.get("time_in_force", MarketOrder.TimeInForce.GTC)
        expires_at = attrs.get("expires_at")
        if time_in_force == MarketOrder.TimeInForce.GTD:
            if expires_at is None:
                raise serializers.ValidationError(
                    {"expires_at": "GTD orders require an expiry time."}
                )
            if expires_at <= timezone.now():
                raise serializers.ValidationError(
                    {"expires_at": "The order expiry time must be in the future."}
                )
        elif expires_at is not None:
            raise serializers.ValidationError(
                {"expires_at": "Only GTD orders may define an expiry time."}
            )
        return attrs


class MarketOrderReadSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(
        read_only=True,
    )
    user = serializers.UUIDField(
        source="user_id",
        read_only=True,
    )
    market = serializers.UUIDField(
        source="market_id",
        read_only=True,
    )
    outcome = serializers.UUIDField(
        source="outcome_id",
        read_only=True,
    )

    class Meta:
        model = MarketOrder
        fields = [
            "id",
            "user",
            "market",
            "outcome",
            "side",
            "quantity",
            "limit_price",
            "filled_quantity",
            "average_fill_price",
            "status",
            "time_in_force",
            "expires_at",
            "expired_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class MarketPositionReadSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(
        read_only=True,
    )
    user = serializers.UUIDField(
        source="user_id",
        read_only=True,
    )
    market = serializers.UUIDField(
        source="market_id",
        read_only=True,
    )
    outcome = serializers.UUIDField(
        source="outcome_id",
        read_only=True,
    )

    class Meta:
        model = MarketPosition
        fields = [
            "id",
            "user",
            "market",
            "outcome",
            "quantity",
            "reserved_quantity",
            "average_entry_price",
            "total_cost",
            "realized_pnl",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class MarketFillReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketFill
        fields = (
            "id",
            "market",
            "outcome",
            "buy_order",
            "sell_order",
            "maker_order",
            "taker_order",
            "quantity",
            "price",
            "created_at",
        )
        read_only_fields = fields

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
    order_type = serializers.ChoiceField(
        choices=MarketOrder.OrderType.choices,
        default=MarketOrder.OrderType.LIMIT,
    )
    quantity = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        required=False,
    )
    amount = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        required=False,
    )
    limit_price = serializers.DecimalField(
        max_digits=6,
        decimal_places=5,
        min_value=Decimal("0.00001"),
        max_value=Decimal("0.99999"),
        required=False,
    )
    time_in_force = serializers.ChoiceField(
        choices=MarketOrder.TimeInForce.choices,
        default=MarketOrder.TimeInForce.GTC,
    )
    expires_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate(self, attrs):
        order_type = attrs.get("order_type", MarketOrder.OrderType.LIMIT)
        side = attrs["side"]
        quantity = attrs.get("quantity")
        amount = attrs.get("amount")
        limit_price = attrs.get("limit_price")

        if order_type == MarketOrder.OrderType.MARKET:
            if side == MarketOrder.Side.BUY:
                if amount is None or quantity is not None:
                    raise serializers.ValidationError(
                        {"amount": "BUY MARKET orders require amount and must not set quantity."}
                    )
            else:
                if quantity is None:
                    raise serializers.ValidationError(
                        {"quantity": "SELL MARKET orders require quantity."}
                    )
                if limit_price is not None:
                    raise serializers.ValidationError(
                        {"limit_price": "MARKET orders must not set limit_price."}
                    )
        else:
            if quantity is None:
                raise serializers.ValidationError(
                    {"quantity": "LIMIT orders require quantity."}
                )
            if limit_price is None:
                raise serializers.ValidationError(
                    {"limit_price": "LIMIT orders require limit_price."}
                )

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
            "order_type",
            "quantity",
            "amount",
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
    available_shares = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        read_only=True,
    )
    locked_shares = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
        read_only=True,
    )
    current_value = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
        read_only=True,
    )
    unrealized_profit = serializers.DecimalField(
        max_digits=20,
        decimal_places=4,
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
            "available_shares",
            "locked_shares",
            "average_entry_price",
            "total_cost",
            "current_value",
            "unrealized_profit",
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

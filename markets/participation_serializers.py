from decimal import Decimal

from rest_framework import serializers

from markets.models import MarketOrder, MarketPosition


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
            "average_entry_price",
            "total_cost",
            "realized_pnl",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

from rest_framework import serializers

from markets.models import MarketVoidRefund


class MarketVoidRefundRequestSerializer(serializers.Serializer):
    def validate(self, attrs):
        if self.initial_data:
            raise serializers.ValidationError(
                {
                    field: "This field is not accepted by the void-refund endpoint."
                    for field in sorted(self.initial_data)
                }
            )
        return attrs


class MarketVoidRefundSerializer(serializers.ModelSerializer):
    market_id = serializers.UUIDField(read_only=True)
    currency = serializers.CharField(source="refund_currency", read_only=True)
    total_released_buy_reservation_amount = serializers.DecimalField(
        max_digits=20, decimal_places=4, read_only=True
    )
    total_released_sell_reservation_quantity = serializers.DecimalField(
        max_digits=20, decimal_places=4, read_only=True
    )
    total_refunded_position_quantity = serializers.DecimalField(
        max_digits=20, decimal_places=4, read_only=True
    )
    total_position_refund_amount = serializers.DecimalField(
        max_digits=20, decimal_places=4, read_only=True
    )

    class Meta:
        model = MarketVoidRefund
        fields = [
            "id",
            "market_id",
            "currency",
            "total_cancelled_order_count",
            "cancelled_buy_order_count",
            "cancelled_sell_order_count",
            "total_released_buy_reservation_amount",
            "total_released_sell_reservation_quantity",
            "refunded_position_count",
            "total_refunded_position_quantity",
            "total_position_refund_amount",
            "executed_at",
        ]
        read_only_fields = fields

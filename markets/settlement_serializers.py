from rest_framework import serializers

from markets.models import MarketSettlement


class MarketSettlementRequestSerializer(serializers.Serializer):
    def validate(self, attrs):
        if self.initial_data:
            raise serializers.ValidationError(
                {
                    field_name: "This field is not accepted by the settlement endpoint."
                    for field_name in sorted(self.initial_data)
                }
            )
        return attrs


class MarketSettlementSerializer(serializers.ModelSerializer):
    market_id = serializers.UUIDField(read_only=True)
    winning_outcome_id = serializers.UUIDField(read_only=True)
    payout_per_unit = serializers.DecimalField(max_digits=20, decimal_places=4, read_only=True)
    currency = serializers.CharField(source="settlement_currency", read_only=True)
    total_winning_quantity = serializers.DecimalField(
        max_digits=20, decimal_places=4, read_only=True
    )
    total_payout_amount = serializers.DecimalField(max_digits=20, decimal_places=4, read_only=True)

    class Meta:
        model = MarketSettlement
        fields = [
            "id",
            "market_id",
            "winning_outcome_id",
            "payout_per_unit",
            "currency",
            "total_position_count",
            "winning_position_count",
            "losing_position_count",
            "total_winning_quantity",
            "total_payout_amount",
            "executed_at",
        ]
        read_only_fields = fields

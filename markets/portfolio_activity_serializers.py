from rest_framework import serializers


class MarketPortfolioActivityFilterSerializer(serializers.Serializer):
    market_id = serializers.UUIDField(required=False)
    outcome_id = serializers.UUIDField(required=False)
    event_type = serializers.ChoiceField(
        required=False,
        choices=(
            "BUY_FILL",
            "SELL_FILL",
            "ORDER_CANCELLED",
            "SETTLEMENT_WIN",
            "SETTLEMENT_LOSS",
            "VOID_REFUND",
        ),
    )
    occurred_from = serializers.DateTimeField(required=False)
    occurred_to = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        occurred_from = attrs.get("occurred_from")
        occurred_to = attrs.get("occurred_to")
        if occurred_from and occurred_to and occurred_from > occurred_to:
            raise serializers.ValidationError({"occurred_to": "Must be on or after occurred_from."})
        return attrs


class MarketPortfolioActivitySerializer(serializers.Serializer):
    id = serializers.CharField()
    event_type = serializers.ChoiceField(
        choices=MarketPortfolioActivityFilterSerializer().fields["event_type"].choices
    )
    occurred_at = serializers.DateTimeField()
    currency = serializers.CharField()
    market_id = serializers.UUIDField()
    outcome_id = serializers.UUIDField()
    market_question = serializers.CharField()
    outcome_label = serializers.CharField()
    side = serializers.ChoiceField(choices=("BUY", "SELL"), allow_null=True)
    order_id = serializers.UUIDField(allow_null=True)
    fill_id = serializers.UUIDField(allow_null=True)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True)
    price = serializers.DecimalField(max_digits=6, decimal_places=5, allow_null=True)
    notional_amount = serializers.DecimalField(max_digits=20, decimal_places=4, allow_null=True)
    wallet_amount = serializers.DecimalField(max_digits=20, decimal_places=4, allow_null=True)
    realized_pnl_delta = serializers.DecimalField(max_digits=20, decimal_places=4, allow_null=True)
    released_wallet_amount = serializers.DecimalField(
        max_digits=20, decimal_places=4, allow_null=True
    )
    released_position_quantity = serializers.DecimalField(
        max_digits=18, decimal_places=4, allow_null=True
    )
    cancellation_reason = serializers.ChoiceField(
        choices=("MANUAL", "MARKET_CLOSE", "MARKET_VOID"), allow_null=True
    )

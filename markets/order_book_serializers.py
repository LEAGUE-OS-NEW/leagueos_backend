from rest_framework import serializers


class MarketOrderBookQuerySerializer(serializers.Serializer):
    levels = serializers.IntegerField(default=20, min_value=1, max_value=100)
    trades = serializers.IntegerField(default=20, min_value=0, max_value=100)


class OrderBookOutcomeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    side = serializers.CharField()
    label = serializers.CharField()


class OrderBookLevelSerializer(serializers.Serializer):
    price = serializers.DecimalField(max_digits=6, decimal_places=5)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    order_count = serializers.IntegerField()


class RecentTradeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    price = serializers.DecimalField(max_digits=6, decimal_places=5)
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    executed_at = serializers.DateTimeField(source="created_at")


class MarketOrderBookSerializer(serializers.Serializer):
    market_id = serializers.UUIDField()
    outcome = OrderBookOutcomeSerializer()
    best_bid = serializers.DecimalField(max_digits=6, decimal_places=5, allow_null=True)
    best_ask = serializers.DecimalField(max_digits=6, decimal_places=5, allow_null=True)
    spread = serializers.DecimalField(max_digits=6, decimal_places=5, allow_null=True)
    total_bid_quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    total_ask_quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    bids = OrderBookLevelSerializer(many=True)
    asks = OrderBookLevelSerializer(many=True)
    recent_trades = RecentTradeSerializer(many=True)

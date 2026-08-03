from rest_framework import serializers


class MarketPortfolioFilterSerializer(serializers.Serializer):
    market_id = serializers.UUIDField(required=False)


class WalletPortfolioSummarySerializer(serializers.Serializer):
    exists = serializers.BooleanField(read_only=True)
    available_balance = serializers.DecimalField(20, 4, read_only=True)
    reserved_balance = serializers.DecimalField(20, 4, read_only=True)
    total_balance = serializers.DecimalField(20, 4, read_only=True)


class MarkSourceSummarySerializer(serializers.Serializer):
    resolution = serializers.IntegerField(read_only=True)
    void_cost_basis = serializers.IntegerField(read_only=True)
    best_bid = serializers.IntegerField(read_only=True)
    last_trade = serializers.IntegerField(read_only=True)
    unpriced = serializers.IntegerField(read_only=True)


class PositionPortfolioSummarySerializer(serializers.Serializer):
    open_position_count = serializers.IntegerField(read_only=True)
    market_count = serializers.IntegerField(read_only=True)
    total_quantity = serializers.DecimalField(18, 4, read_only=True)
    reserved_quantity = serializers.DecimalField(18, 4, read_only=True)
    available_quantity = serializers.DecimalField(18, 4, read_only=True)
    total_cost_basis = serializers.DecimalField(20, 4, read_only=True)
    marked_position_count = serializers.IntegerField(read_only=True)
    unpriced_position_count = serializers.IntegerField(read_only=True)
    marked_cost_basis = serializers.DecimalField(20, 4, read_only=True)
    unpriced_cost_basis = serializers.DecimalField(20, 4, read_only=True)
    marked_market_value = serializers.DecimalField(20, 4, read_only=True)
    realized_pnl = serializers.DecimalField(20, 4, read_only=True)
    marked_unrealized_pnl = serializers.DecimalField(20, 4, read_only=True)
    total_pnl = serializers.DecimalField(20, 4, read_only=True, allow_null=True)
    valuation_complete = serializers.BooleanField(read_only=True)
    mark_sources = MarkSourceSummarySerializer(read_only=True)


class OrderPortfolioSummarySerializer(serializers.Serializer):
    open_order_count = serializers.IntegerField(read_only=True)
    open_buy_order_count = serializers.IntegerField(read_only=True)
    open_sell_order_count = serializers.IntegerField(read_only=True)
    remaining_order_quantity = serializers.DecimalField(18, 4, read_only=True)
    reserved_buy_amount = serializers.DecimalField(20, 4, read_only=True)
    reserved_sell_quantity = serializers.DecimalField(18, 4, read_only=True)


class PortfolioScopeSerializer(serializers.Serializer):
    market_id = serializers.UUIDField(read_only=True, allow_null=True)


class MarketPortfolioSummarySerializer(serializers.Serializer):
    currency = serializers.CharField(read_only=True)
    scope = PortfolioScopeSerializer(read_only=True)
    wallet = WalletPortfolioSummarySerializer(read_only=True)
    positions = PositionPortfolioSummarySerializer(read_only=True)
    orders = OrderPortfolioSummarySerializer(read_only=True)
    as_of = serializers.DateTimeField(read_only=True)

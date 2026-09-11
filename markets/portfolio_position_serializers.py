from decimal import Decimal

from rest_framework import serializers

from markets.models import Market, MarketPosition
from markets.services.portfolio_service import MarketPortfolioService


class MarketPortfolioPositionFilterSerializer(serializers.Serializer):
    market_id = serializers.UUIDField(required=False)
    outcome_id = serializers.UUIDField(required=False)
    market_status = serializers.ChoiceField(choices=Market.Status.choices, required=False)
    mark_source = serializers.ChoiceField(
        choices=MarketPortfolioService.MARK_SOURCES, required=False
    )
    valuation_complete = serializers.ChoiceField(choices=("true", "false"), required=False)

    def validate_valuation_complete(self, value):
        return value == "true"


class MarketPortfolioPositionSerializer(serializers.ModelSerializer):
    market_id = serializers.UUIDField(read_only=True)
    outcome_id = serializers.UUIDField(read_only=True)
    market_question = serializers.CharField(source="market.question", read_only=True)
    outcome_label = serializers.CharField(source="outcome.label", read_only=True)
    market_status = serializers.CharField(source="market.status", read_only=True)
    available_quantity = serializers.SerializerMethodField()
    quantity = serializers.SerializerMethodField()
    reserved_quantity = serializers.SerializerMethodField()
    average_entry_price = serializers.SerializerMethodField()
    total_cost_basis = serializers.SerializerMethodField()
    realized_pnl = serializers.SerializerMethodField()
    mark_price = serializers.DecimalField(
        max_digits=6, decimal_places=5, read_only=True, allow_null=True
    )
    mark_source = serializers.CharField(read_only=True)
    market_value = serializers.DecimalField(
        max_digits=20, decimal_places=4, read_only=True, allow_null=True
    )
    unrealized_pnl = serializers.DecimalField(
        max_digits=20, decimal_places=4, read_only=True, allow_null=True
    )
    total_position_pnl = serializers.DecimalField(
        max_digits=20, decimal_places=4, read_only=True, allow_null=True
    )
    valuation_complete = serializers.BooleanField(read_only=True)
    open_sell_order_count = serializers.IntegerField(read_only=True)
    reserved_sell_order_quantity = serializers.DecimalField(
        max_digits=18, decimal_places=4, read_only=True
    )

    class Meta:
        model = MarketPosition
        fields = (
            "id",
            "market_id",
            "outcome_id",
            "market_question",
            "outcome_label",
            "market_status",
            "quantity",
            "reserved_quantity",
            "available_quantity",
            "average_entry_price",
            "total_cost_basis",
            "realized_pnl",
            "mark_price",
            "mark_source",
            "market_value",
            "unrealized_pnl",
            "total_position_pnl",
            "valuation_complete",
            "open_sell_order_count",
            "reserved_sell_order_quantity",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_available_quantity(self, position: MarketPosition) -> str:
        if self._settlement_record(position) is not None:
            return "0.0000"
        available = position.quantity - position.reserved_quantity
        if available < 0:
            raise serializers.ValidationError(
                "Position contains invalid historical reservation data."
            )
        return format(available.quantize(Decimal("0.0001")), ".4f")

    def get_quantity(self, position: MarketPosition) -> str:
        settlement = self._settlement_record(position)
        value = settlement.settled_quantity if settlement is not None else position.quantity
        return format(value.quantize(Decimal("0.0001")), ".4f")

    def get_reserved_quantity(self, position: MarketPosition) -> str:
        if self._settlement_record(position) is not None:
            return "0.0000"
        return format(position.reserved_quantity.quantize(Decimal("0.0001")), ".4f")

    def get_average_entry_price(self, position: MarketPosition) -> str:
        settlement = self._settlement_record(position)
        if settlement is not None and settlement.settled_quantity > Decimal("0.0000"):
            value = settlement.cost_basis / settlement.settled_quantity
        else:
            value = position.average_entry_price
        return format(value.quantize(Decimal("0.00001")), ".5f")

    def get_total_cost_basis(self, position: MarketPosition) -> str:
        settlement = self._settlement_record(position)
        value = settlement.cost_basis if settlement is not None else position.total_cost
        return format(value.quantize(Decimal("0.0001")), ".4f")

    def get_realized_pnl(self, position: MarketPosition) -> str:
        settlement = self._settlement_record(position)
        if settlement is not None:
            value = settlement.net_payout_amount - settlement.cost_basis
        else:
            value = position.realized_pnl
        return format(value.quantize(Decimal("0.0001")), ".4f")

    @staticmethod
    def _settlement_record(position: MarketPosition):
        return getattr(position, "settlement_record", None)

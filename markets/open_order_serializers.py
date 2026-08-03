from decimal import ROUND_HALF_UP, Decimal

from rest_framework import serializers

from markets.models import MarketOrder
from markets.services.open_order_service import ParticipantOpenOrderService
from markets.services.participation_service import MarketParticipationService


class ParticipantOpenOrderFilterSerializer(serializers.Serializer):
    market_id = serializers.UUIDField(required=False)
    outcome_id = serializers.UUIDField(required=False)
    side = serializers.ChoiceField(choices=MarketOrder.Side.choices, required=False)
    status = serializers.ChoiceField(
        choices=ParticipantOpenOrderService.ACTIVE_STATUSES,
        required=False,
    )


class ParticipantOpenOrderSerializer(serializers.ModelSerializer):
    market_id = serializers.UUIDField(read_only=True)
    outcome_id = serializers.UUIDField(read_only=True)
    market_question = serializers.CharField(source="market.question", read_only=True)
    outcome_label = serializers.CharField(source="outcome.label", read_only=True)
    status = serializers.CharField(read_only=True)
    remaining_quantity = serializers.SerializerMethodField()
    fill_percentage = serializers.SerializerMethodField()
    reserved_wallet_amount = serializers.SerializerMethodField()
    reserved_position_quantity = serializers.SerializerMethodField()
    is_cancellable = serializers.SerializerMethodField()

    class Meta:
        model = MarketOrder
        fields = (
            "id",
            "market_id",
            "outcome_id",
            "market_question",
            "outcome_label",
            "side",
            "status",
            "quantity",
            "filled_quantity",
            "remaining_quantity",
            "fill_percentage",
            "limit_price",
            "average_fill_price",
            "reserved_wallet_amount",
            "reserved_position_quantity",
            "is_cancellable",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @staticmethod
    def _remaining(order) -> Decimal:
        remaining = order.quantity - order.filled_quantity
        if order.quantity <= 0 or remaining < 0:
            raise serializers.ValidationError(
                "Active order contains invalid historical quantity data."
            )
        return remaining.quantize(Decimal("0.0001"))

    def get_remaining_quantity(self, order) -> str:
        return format(self._remaining(order), ".4f")

    def get_fill_percentage(self, order) -> str:
        remaining = self._remaining(order)
        filled = order.quantity - remaining
        percentage = (filled / order.quantity * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return format(percentage, ".2f")

    def get_reserved_wallet_amount(self, order) -> str:
        amount = Decimal("0.0000")
        if order.side == MarketOrder.Side.BUY:
            amount = MarketParticipationService.calculate_buy_cancellation_release(order)
        return format(amount, ".4f")

    def get_reserved_position_quantity(self, order) -> str:
        quantity = Decimal("0.0000")
        if order.side == MarketOrder.Side.SELL:
            quantity = self._remaining(order)
        return format(quantity, ".4f")

    def get_is_cancellable(self, order) -> bool:
        return MarketParticipationService.is_order_cancellable(order)

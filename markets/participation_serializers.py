from decimal import Decimal

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from markets.models import (
    MarketFill,
    MarketOrder,
    MarketPosition,
    MarketPositionExit,
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


class MarketParticipationHistorySerializer(serializers.ModelSerializer):
    market_id = serializers.UUIDField(source="market.id", read_only=True)
    market_question = serializers.CharField(source="market.question", read_only=True)
    market_state = serializers.CharField(source="market.status", read_only=True)
    outcome = serializers.CharField(source="outcome.side", read_only=True)
    outcome_id = serializers.UUIDField(source="outcome.id", read_only=True)
    outcome_label = serializers.CharField(source="outcome.label", read_only=True)
    participation_status = serializers.SerializerMethodField()
    participated_quantity = serializers.SerializerMethodField()
    current_open_quantity = serializers.DecimalField(
        source="quantity", max_digits=18, decimal_places=4, read_only=True
    )
    total_cost = serializers.SerializerMethodField()
    average_price = serializers.SerializerMethodField()
    gross_payout = serializers.SerializerMethodField()
    fees = serializers.SerializerMethodField()
    net_payout = serializers.SerializerMethodField()
    realized_pnl = serializers.SerializerMethodField()
    settled_at = serializers.SerializerMethodField()
    opened_at = serializers.SerializerMethodField()
    closed_at = serializers.SerializerMethodField()
    exited_quantity = serializers.SerializerMethodField()
    realized_proceeds = serializers.SerializerMethodField()

    class Meta:
        model = MarketPosition
        fields = (
            "id",
            "market_id",
            "market_question",
            "market_state",
            "outcome",
            "outcome_id",
            "outcome_label",
            "participation_status",
            "participated_quantity",
            "current_open_quantity",
            "total_cost",
            "average_price",
            "gross_payout",
            "fees",
            "net_payout",
            "realized_pnl",
            "settled_at",
            "opened_at",
            "closed_at",
            "exited_quantity",
            "realized_proceeds",
            "created_at",
        )

    @staticmethod
    def _record(obj):
        return getattr(obj, "settlement_record", None) or getattr(obj, "void_refund_record", None)

    @extend_schema_field(serializers.CharField())
    def get_participation_status(self, obj):
        if isinstance(obj, MarketPositionExit):
            return "EXITED"
        if hasattr(obj, "void_refund_record"):
            return "REFUNDED"
        settlement = getattr(obj, "settlement_record", None)
        if settlement:
            return "WON" if settlement.was_winner else "LOST"
        if obj.market.status == "RESOLVED":
            return "PENDING_SETTLEMENT"
        # A zero position backed by prior matched activity is a completely exited
        # position, not an open holding.  The position row is retained as the
        # authoritative participation record after a sell-out.
        if obj.quantity == 0:
            return "EXITED"
        return "OPEN"

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_participated_quantity(self, obj):
        if isinstance(obj, MarketPositionExit):
            return obj.acquired_quantity
        record = self._record(obj)
        return (
            record.settled_quantity
            if hasattr(record, "settled_quantity")
            else (record.refunded_quantity if record else obj.quantity)
        )

    @extend_schema_field(serializers.DecimalField(max_digits=20, decimal_places=4))
    def get_total_cost(self, obj):
        if isinstance(obj, MarketPositionExit):
            return obj.cost_basis
        record = self._record(obj)
        return record.cost_basis if record else obj.total_cost

    @extend_schema_field(serializers.DecimalField(max_digits=20, decimal_places=5))
    def get_average_price(self, obj):
        quantity = self.get_participated_quantity(obj)
        cost = self.get_total_cost(obj)
        return cost / quantity if quantity else obj.average_entry_price

    @extend_schema_field(serializers.DecimalField(max_digits=20, decimal_places=4))
    def get_gross_payout(self, obj):
        if isinstance(obj, MarketPositionExit):
            return obj.realized_proceeds
        record = self._record(obj)
        return (
            getattr(record, "payout_amount", getattr(record, "refund_amount", 0)) if record else 0
        )

    @extend_schema_field(serializers.DecimalField(max_digits=20, decimal_places=4))
    def get_fees(self, obj):
        if isinstance(obj, MarketPositionExit):
            return 0
        record = self._record(obj)
        return (
            getattr(record, "payout_fee_amount", getattr(record, "refund_fee_amount", 0))
            if record
            else 0
        )

    @extend_schema_field(serializers.DecimalField(max_digits=20, decimal_places=4))
    def get_net_payout(self, obj):
        if isinstance(obj, MarketPositionExit):
            return obj.realized_proceeds
        record = self._record(obj)
        return (
            getattr(record, "net_payout_amount", getattr(record, "net_refund_amount", 0))
            if record
            else 0
        )

    @extend_schema_field(serializers.DecimalField(max_digits=20, decimal_places=4))
    def get_realized_pnl(self, obj):
        if isinstance(obj, MarketPositionExit):
            return obj.realized_pnl
        record = self._record(obj)
        return record.realized_pnl_delta if record else obj.realized_pnl

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_settled_at(self, obj):
        if isinstance(obj, MarketPositionExit):
            return obj.exited_at
        record = self._record(obj)
        return record.created_at if record else None

    @extend_schema_field(serializers.DateTimeField())
    def get_opened_at(self, obj):
        return obj.opened_at if isinstance(obj, MarketPositionExit) else obj.created_at

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_closed_at(self, obj):
        return obj.exited_at if isinstance(obj, MarketPositionExit) else self.get_settled_at(obj)

    @extend_schema_field(serializers.DecimalField(max_digits=18, decimal_places=4))
    def get_exited_quantity(self, obj):
        return obj.exited_quantity if isinstance(obj, MarketPositionExit) else 0

    @extend_schema_field(serializers.DecimalField(max_digits=20, decimal_places=4))
    def get_realized_proceeds(self, obj):
        return (
            obj.realized_proceeds
            if isinstance(obj, MarketPositionExit)
            else self.get_gross_payout(obj)
        )


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

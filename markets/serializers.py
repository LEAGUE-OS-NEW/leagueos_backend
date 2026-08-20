from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from markets.models import (
    Market,
    MarketCategory,
    MarketEventGroup,
    MarketOutcome,
    MarketScope,
    MarketTemplate,
)
from sports.serializers import (
    CompetitionPublicSerializer,
    ParticipantPublicSerializer,
    SportingEventPublicSerializer,
    SportPublicSerializer,
)

PUBLIC_MARKET_STATUSES = (
    Market.Status.APPROVED,
    Market.Status.OPEN,
    Market.Status.SUSPENDED,
    Market.Status.CLOSED,
    Market.Status.RESOLVED,
    Market.Status.VOIDED,
)

NORMALIZED_PRICE_QUANTUM = Decimal("0.00001")


def format_normalized_price(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(NORMALIZED_PRICE_QUANTUM), ".5f")


class MarketCategoryPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketCategory
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "display_order",
        ]


class MarketTemplatePublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketTemplate
        fields = [
            "id",
            "name",
            "code",
            "slug",
            "scope_type",
        ]


class MarketOutcomePublicSerializer(serializers.ModelSerializer):
    opening_probability_pct = serializers.SerializerMethodField()
    opening_price_ugx = serializers.SerializerMethodField()

    class Meta:
        model = MarketOutcome
        fields = [
            "id",
            "side",
            "position",
            "label",
            "description",
            "opening_price",
            "opening_probability_pct",
            "opening_price_ugx",
        ]

    @extend_schema_field(serializers.DecimalField(max_digits=8, decimal_places=5, allow_null=True))
    def get_opening_probability_pct(self, obj):
        return None if obj.opening_price is None else obj.opening_price * Decimal("100")

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_opening_price_ugx(self, obj):
        if obj.opening_price is None:
            return None
        return int(obj.opening_price * obj.market.face_value_ugx)


class MarketSubjectSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=MarketScope.choices,
    )
    id = serializers.UUIDField(
        allow_null=True,
    )
    name = serializers.CharField()


class MarketEventSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketEventGroup
        fields = ["id", "title", "slug", "event_type", "scheduled_at"]


class MarketPublicSerializer(serializers.ModelSerializer):
    opening_liquidity_available = serializers.SerializerMethodField()
    opening_reference = serializers.SerializerMethodField()
    opening_liquidity = serializers.SerializerMethodField()
    is_watchlisted = serializers.BooleanField(read_only=True, default=False)
    event_group = MarketEventSummarySerializer(read_only=True)
    sport = SportPublicSerializer(
        read_only=True,
    )
    category = MarketCategoryPublicSerializer(
        read_only=True,
    )
    template = MarketTemplatePublicSerializer(
        read_only=True,
    )
    sporting_event = SportingEventPublicSerializer(
        read_only=True,
    )
    competition = CompetitionPublicSerializer(
        read_only=True,
    )
    participant = ParticipantPublicSerializer(
        read_only=True,
    )
    outcomes = MarketOutcomePublicSerializer(
        many=True,
        read_only=True,
    )
    subject = serializers.SerializerMethodField()
    winning_outcome = serializers.UUIDField(
        source="winning_outcome_id",
        read_only=True,
        allow_null=True,
    )
    trading_snapshot = serializers.SerializerMethodField()
    is_settled = serializers.SerializerMethodField()
    is_refunded = serializers.SerializerMethodField()

    class Meta:
        model = Market
        fields = [
            "id",
            "question",
            "description",
            "rules",
            "resolution_source",
            "resolution_criteria",
            "face_value_ugx",
            "scope_type",
            "status",
            "opens_at",
            "closes_at",
            "settles_by",
            "is_featured",
            "sport",
            "category",
            "template",
            "event_group",
            "sporting_event",
            "competition",
            "participant",
            "custom_subject",
            "subject",
            "outcomes",
            "winning_outcome",
            "created_at",
            "updated_at",
            "is_watchlisted",
            "trading_snapshot",
            "opening_liquidity_available",
            "opening_reference",
            "opening_liquidity",
            "is_settled",
            "is_refunded",
        ]

    @extend_schema_field(serializers.BooleanField())
    def get_is_settled(self, obj):
        return hasattr(obj, "settlement")

    @extend_schema_field(serializers.BooleanField())
    def get_is_refunded(self, obj):
        return hasattr(obj, "void_refund")

    @extend_schema_field(serializers.DictField())
    def get_opening_liquidity(self, obj):
        config = getattr(
            obj,
            "liquidity_configuration",
            None,
        )

        if not config:
            return {
                "initial_liquidity_ugx": "0.0000",
                "opening_spread_bps": 0,
                "activation_status": "UNCONFIGURED",
            }

        return {
            "initial_liquidity_ugx": format(
                config.initial_liquidity_ugx,
                ".4f",
            ),
            "opening_spread_bps": config.opening_spread_bps,
            "activation_status": config.status,
        }

    @extend_schema_field(serializers.BooleanField())
    def get_opening_liquidity_available(self, obj):
        config = getattr(obj, "liquidity_configuration", None)
        if not config or config.status != "ACTIVE" or not config.provider_id:
            return False
        prefetched = getattr(obj, "snapshot_orders", None)
        if prefetched is not None:
            return any(
                order.user_id == config.provider.user_id
                and order.side == "SELL"
                and order.status in {"OPEN", "PARTIALLY_FILLED"}
                for order in prefetched
            )
        return obj.orders.filter(
            user_id=config.provider.user_id,
            side="SELL",
            status__in=("OPEN", "PARTIALLY_FILLED"),
        ).exists()

    @extend_schema_field(serializers.DictField())
    def get_opening_reference(self, obj):
        return {
            outcome.side: format_normalized_price(outcome.opening_price)
            for outcome in obj.outcomes.all()
        }

    def get_trading_snapshot(self, obj) -> dict:
        active_statuses = {"PENDING", "OPEN", "PARTIALLY_FILLED"}
        orders = [
            order
            for order in getattr(obj, "snapshot_orders", ())
            if order.status in active_statuses
        ]
        fills = list(getattr(obj, "snapshot_fills", ()))
        outcomes = {}
        for outcome in obj.outcomes.all():
            outcome_orders = [order for order in orders if order.outcome_id == outcome.id]
            bids = [order.limit_price for order in outcome_orders if order.side == "BUY"]
            asks = [order.limit_price for order in outcome_orders if order.side == "SELL"]
            outcome_fills = [fill for fill in fills if fill.outcome_id == outcome.id]
            last_trade = outcome_fills[0].price if outcome_fills else None
            best_bid = max(bids) if bids else None
            best_ask = min(asks) if asks else None
            if last_trade is not None:
                mark_price = last_trade
                mark_source = "LAST_TRADE"
            elif best_bid is not None and best_ask is not None:
                mark_price = (best_bid + best_ask) / Decimal("2")
                mark_source = "MIDPOINT"
            elif best_bid is not None or best_ask is not None:
                mark_price = best_bid if best_bid is not None else best_ask
                mark_source = "BEST_QUOTE"
            elif outcome.opening_price is not None:
                mark_price = outcome.opening_price
                mark_source = "OPENING_REFERENCE"
            else:
                mark_price = None
                mark_source = "NO_LIQUIDITY"
            outcomes[str(outcome.id)] = {
                "best_bid": format_normalized_price(best_bid),
                "best_ask": format_normalized_price(best_ask),
                "last_trade": format_normalized_price(last_trade),
                "mark_price": format_normalized_price(mark_price),
                "opening_price": format_normalized_price(outcome.opening_price),
                "mark_source": mark_source,
            }
        traders = {order.user_id for order in orders}
        for fill in fills:
            traders.update((fill.buy_order.user_id, fill.sell_order.user_id))
        return {
            "outcomes": outcomes,
            "volume": sum((fill.quantity * fill.price for fill in fills), Decimal("0")),
            "trader_count": len(traders),
        }

    @extend_schema_field(MarketSubjectSerializer)
    def get_subject(self, obj) -> dict:
        if obj.scope_type == MarketScope.EVENT:
            return {
                "type": MarketScope.EVENT,
                "id": str(obj.sporting_event_id),
                "name": obj.sporting_event.name,
            }

        if obj.scope_type == MarketScope.COMPETITION:
            return {
                "type": MarketScope.COMPETITION,
                "id": str(obj.competition_id),
                "name": obj.competition.name,
            }

        if obj.scope_type == MarketScope.PARTICIPANT:
            return {
                "type": MarketScope.PARTICIPANT,
                "id": str(obj.participant_id),
                "name": obj.participant.name,
            }

        return {
            "type": MarketScope.CUSTOM,
            "id": None,
            "name": obj.custom_subject,
        }


class MarketListQuerySerializer(serializers.Serializer):
    event_group_id = serializers.UUIDField(required=False)
    sporting_event_id = serializers.UUIDField(required=False)
    sport = serializers.UUIDField(
        required=False,
    )
    category = serializers.UUIDField(
        required=False,
    )
    scope_type = serializers.ChoiceField(
        choices=MarketScope.choices,
        required=False,
    )
    status = serializers.ChoiceField(
        choices=PUBLIC_MARKET_STATUSES,
        required=False,
        default=Market.Status.OPEN,
    )
    is_featured = serializers.BooleanField(
        required=False,
    )
    search = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=255,
    )

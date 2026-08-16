from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from markets.models import (
    Market,
    MarketCategory,
    MarketOutcome,
    MarketScope,
    MarketStatusTransition,
    MarketTemplate,
)
from markets.serializers import MarketPublicSerializer
from markets.services.catalog_service import (
    MarketCatalogService,
)
from markets.services.opening_pricing_service import MarketOpeningPricingService
from sports.models import (
    Competition,
    Participant,
    Sport,
    SportingEvent,
)

User = get_user_model()


class MarketAdminUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
        ]


class MarketStatusTransitionSerializer(serializers.ModelSerializer):
    actor = MarketAdminUserSerializer(
        read_only=True,
    )

    class Meta:
        model = MarketStatusTransition
        fields = [
            "id",
            "action",
            "from_status",
            "to_status",
            "actor",
            "actor_email",
            "notes",
            "metadata",
            "created_at",
        ]


class MarketAdminReadSerializer(MarketPublicSerializer):
    liquidity = serializers.SerializerMethodField()
    created_by = MarketAdminUserSerializer(
        read_only=True,
    )
    approved_by = MarketAdminUserSerializer(
        read_only=True,
    )
    resolved_by = MarketAdminUserSerializer(
        read_only=True,
    )
    status_transitions = MarketStatusTransitionSerializer(
        many=True,
        read_only=True,
    )

    class Meta(MarketPublicSerializer.Meta):
        fields = [
            *MarketPublicSerializer.Meta.fields,
            "created_by",
            "approved_by",
            "approved_at",
            "approval_notes",
            "resolved_by",
            "resolved_at",
            "winning_outcome",
            "resolution_notes",
            "resolution_evidence",
            "status_transitions",
            "liquidity",
        ]

    @extend_schema_field(serializers.DictField())
    def get_liquidity(self, obj):
        config = getattr(obj, "liquidity_configuration", None)
        pool = getattr(obj, "collateral_pool", None)
        outcomes = {o.side: o for o in obj.outcomes.all()}
        half = Decimal(config.opening_spread_bps) / Decimal("20000") if config else Decimal("0")
        return {
            "liquidity_source": getattr(config, "source", None),
            "initial_liquidity_ugx": getattr(config, "initial_liquidity_ugx", Decimal("0")),
            "opening_spread_bps": getattr(config, "opening_spread_bps", 0),
            "activation_status": getattr(config, "status", "UNCONFIGURED"),
            "locked_collateral": getattr(pool, "locked_collateral", Decimal("0")),
            "issued_complete_sets": sum(
                (x.quantity for x in obj.complete_set_issuances.all()), Decimal("0")
            ),
            "opening_yes_ask": (
                outcomes.get("YES").opening_price + half
                if outcomes.get("YES") and outcomes.get("YES").opening_price is not None
                else None
            ),
            "opening_no_ask": (
                outcomes.get("NO").opening_price + half
                if outcomes.get("NO") and outcomes.get("NO").opening_price is not None
                else None
            ),
            "provider": getattr(getattr(config, "provider", None), "display_name", None),
        }


class MarketAdminListQuerySerializer(serializers.Serializer):
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
        choices=Market.Status.choices,
        required=False,
    )
    search = serializers.CharField(
        required=False,
        allow_blank=False,
        max_length=255,
    )


class MarketAdminWriteSerializer(serializers.Serializer):
    id = serializers.UUIDField(
        read_only=True,
    )
    sport_id = serializers.PrimaryKeyRelatedField(
        source="sport",
        queryset=Sport.objects.filter(
            is_active=True,
        ),
    )
    category_id = serializers.PrimaryKeyRelatedField(
        source="category",
        queryset=MarketCategory.objects.filter(
            is_active=True,
        ),
    )
    template_id = serializers.PrimaryKeyRelatedField(
        source="template",
        queryset=MarketTemplate.objects.filter(
            is_active=True,
        ),
        required=False,
        allow_null=True,
    )
    scope_type = serializers.ChoiceField(
        choices=MarketScope.choices,
    )
    sporting_event_id = serializers.PrimaryKeyRelatedField(
        source="sporting_event",
        queryset=SportingEvent.objects.all(),
        required=False,
        allow_null=True,
    )
    competition_id = serializers.PrimaryKeyRelatedField(
        source="competition",
        queryset=Competition.objects.all(),
        required=False,
        allow_null=True,
    )
    participant_id = serializers.PrimaryKeyRelatedField(
        source="participant",
        queryset=Participant.objects.all(),
        required=False,
        allow_null=True,
    )
    custom_subject = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=255,
    )
    question = serializers.CharField(
        max_length=500,
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    rules = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    resolution_source = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=255,
    )
    resolution_criteria = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    opens_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
    )
    closes_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
    )
    settles_by = serializers.DateTimeField(
        required=False,
        allow_null=True,
    )
    is_featured = serializers.BooleanField(
        required=False,
        default=False,
    )
    yes_label = serializers.CharField(
        required=False,
        default="Yes",
        max_length=120,
    )
    no_label = serializers.CharField(
        required=False,
        default="No",
        max_length=120,
    )
    face_value_ugx = serializers.IntegerField(required=False, min_value=1, default=5000)
    settlement_unit = serializers.IntegerField(required=False, min_value=1, default=5000)
    yes_probability = serializers.DecimalField(
        required=False, max_digits=7, decimal_places=5, min_value=0, max_value=100, default="50"
    )
    max_market_amount = serializers.DecimalField(
        required=False,
        max_digits=20,
        decimal_places=4,
        min_value=0,
        default=0,
    )
    initial_liquidity_ugx = serializers.DecimalField(
        required=False, max_digits=20, decimal_places=4, min_value=0, default=0
    )
    liquidity_source = serializers.ChoiceField(
        required=False,
        choices=["PLATFORM_TREASURY", "EXTERNAL_MARKET_MAKER"],
        default="PLATFORM_TREASURY",
    )
    opening_spread_bps = serializers.IntegerField(
        required=False, min_value=0, max_value=5000, default=0
    )

    def validate(self, attrs):
        unknown_fields = set(self.initial_data) - set(self.fields)

        if unknown_fields:
            raise serializers.ValidationError(
                {
                    field_name: (
                        "This field is not accepted " "by the market catalogue " "endpoint."
                    )
                    for field_name in sorted(unknown_fields)
                }
            )

        instance = self.instance
        scope_type = attrs.get("scope_type", getattr(instance, "scope_type", None))
        sporting_event = attrs.get("sporting_event", getattr(instance, "sporting_event", None))

        if scope_type == MarketScope.EVENT:
            if sporting_event is None:
                raise serializers.ValidationError(
                    {"sporting_event_id": "An event-scoped market requires a sporting event."}
                )

            event_is_new = instance is None or (
                "sporting_event" in attrs
                and sporting_event.pk != getattr(instance, "sporting_event_id", None)
            )
            if event_is_new:
                event_error = None
                if not sporting_event.is_verified:
                    event_error = "Only verified sporting events may be used."
                elif sporting_event.status != SportingEvent.Status.SCHEDULED:
                    event_error = "Only scheduled sporting events may be used."
                elif sporting_event.starts_at <= timezone.now():
                    event_error = "The sporting event must start in the future."

                if event_error:
                    raise serializers.ValidationError({"sporting_event_id": event_error})

                closes_at = attrs.get("closes_at", getattr(instance, "closes_at", None))
                if closes_at is not None and closes_at > sporting_event.starts_at:
                    raise serializers.ValidationError(
                        {
                            "closes_at": (
                                "An event-scoped market cannot close after "
                                "the sporting event starts."
                            )
                        }
                    )

        return attrs

    def create(self, validated_data):
        initial_liquidity = validated_data.pop("initial_liquidity_ugx", 0)
        liquidity_source = validated_data.pop("liquidity_source", "PLATFORM_TREASURY")
        opening_spread = validated_data.pop("opening_spread_bps", 0)
        face_value_ugx = validated_data.pop("face_value_ugx", 5000)
        settlement_unit = validated_data.pop("settlement_unit", face_value_ugx)
        max_market_amount = validated_data.pop("max_market_amount", None)
        yes_probability = validated_data.pop("yes_probability", 50)
        yes_label = validated_data.pop(
            "yes_label",
            "Yes",
        )
        no_label = validated_data.pop(
            "no_label",
            "No",
        )

        validated_data.update(
            {
                "status": Market.Status.DRAFT,
                "created_by": (self.context["request"].user),
                "settlement_unit": settlement_unit,
            }
        )
        if max_market_amount:
            validated_data["max_market_amount"] = max_market_amount

        try:
            with transaction.atomic():
                market = MarketCatalogService.create_market(
                    yes_label=yes_label,
                    no_label=no_label,
                    **validated_data,
                )
                market = MarketOpeningPricingService.configure(
                    market=market,
                    actor=self.context["request"].user,
                    face_value_ugx=face_value_ugx,
                    yes_probability=yes_probability,
                )
                from markets.services.liquidity_service import MarketLiquidityService

                MarketLiquidityService.configure(
                    market=market,
                    actor=self.context["request"].user,
                    initial_liquidity_ugx=initial_liquidity,
                    source=liquidity_source,
                    opening_spread_bps=opening_spread,
                )
                return market
        except DjangoValidationError as error:
            self._raise_serializer_validation_error(error)

    def update(
        self,
        instance,
        validated_data,
    ):
        if instance.status not in {
            Market.Status.DRAFT,
            Market.Status.REJECTED,
        }:
            raise serializers.ValidationError(
                {"status": ("Only draft or rejected " "markets can be edited.")}
            )

        liquidity_values = {
            key: validated_data.pop(key)
            for key in ("initial_liquidity_ugx", "liquidity_source", "opening_spread_bps")
            if key in validated_data
        }
        face_value_ugx = validated_data.pop("face_value_ugx", None)
        yes_probability = validated_data.pop("yes_probability", None)
        yes_label = validated_data.pop(
            "yes_label",
            None,
        )
        no_label = validated_data.pop(
            "no_label",
            None,
        )

        try:
            with transaction.atomic():
                for field_name, value in validated_data.items():
                    setattr(
                        instance,
                        field_name,
                        value,
                    )

                instance.full_clean()
                instance.save()

                self._update_outcome_label(
                    instance,
                    MarketOutcome.Side.YES,
                    yes_label,
                )
                self._update_outcome_label(
                    instance,
                    MarketOutcome.Side.NO,
                    no_label,
                )
                if face_value_ugx is not None or yes_probability is not None:
                    yes_outcome = instance.outcomes.get(side=MarketOutcome.Side.YES)
                    MarketOpeningPricingService.configure(
                        market=instance,
                        actor=self.context["request"].user,
                        face_value_ugx=face_value_ugx or instance.face_value_ugx,
                        yes_probability=(
                            yes_probability
                            if yes_probability is not None
                            else yes_outcome.opening_price * 100
                        ),
                    )
                if liquidity_values:
                    from markets.services.liquidity_service import MarketLiquidityService

                    current = getattr(instance, "liquidity_configuration", None)
                    MarketLiquidityService.configure(
                        market=instance,
                        actor=self.context["request"].user,
                        initial_liquidity_ugx=liquidity_values.get(
                            "initial_liquidity_ugx", getattr(current, "initial_liquidity_ugx", 0)
                        ),
                        source=liquidity_values.get(
                            "liquidity_source", getattr(current, "source", "PLATFORM_TREASURY")
                        ),
                        opening_spread_bps=liquidity_values.get(
                            "opening_spread_bps", getattr(current, "opening_spread_bps", 0)
                        ),
                        provider=getattr(current, "provider", None),
                    )
        except DjangoValidationError as error:
            self._raise_serializer_validation_error(error)

        if hasattr(
            instance,
            "_prefetched_objects_cache",
        ):
            instance._prefetched_objects_cache = {}

        return instance

    @staticmethod
    def _update_outcome_label(
        market: Market,
        side: str,
        label: str | None,
    ) -> None:
        if label is None:
            return

        outcome = market.outcomes.get(
            side=side,
        )
        outcome.label = label
        outcome.full_clean()
        outcome.save(
            update_fields=[
                "label",
                "updated_at",
            ]
        )

    @staticmethod
    def _raise_serializer_validation_error(
        error: DjangoValidationError,
    ) -> None:
        if hasattr(error, "message_dict"):
            raise serializers.ValidationError(error.message_dict) from error

        raise serializers.ValidationError(
            {
                "non_field_errors": (error.messages),
            }
        ) from error


class MarketOpeningPricingSerializer(serializers.Serializer):
    face_value_ugx = serializers.IntegerField(min_value=1)
    yes_probability = serializers.DecimalField(max_digits=7, decimal_places=5)

    def save(self, **kwargs):
        try:
            return MarketOpeningPricingService.configure(
                market=self.context["market"],
                actor=self.context["request"].user,
                **self.validated_data,
            )
        except DjangoValidationError as error:
            detail = getattr(error, "message_dict", {"detail": error.messages})
            raise serializers.ValidationError(detail) from error


class MarketLifecycleActionSerializer(serializers.Serializer):
    notes = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )


class MarketResolveSerializer(serializers.Serializer):
    winning_outcome_id = serializers.UUIDField()
    notes = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )
    evidence = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )


class MarketVoidSerializer(serializers.Serializer):
    notes = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )
    evidence = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )

from django.contrib.auth import get_user_model
from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.db import transaction
from rest_framework import serializers

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
            "created_at",
        ]


class MarketAdminReadSerializer(MarketPublicSerializer):
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
            "resolution_notes",
            "status_transitions",
        ]


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

        return attrs

    def create(self, validated_data):
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
            }
        )

        try:
            return MarketCatalogService.create_market(
                yes_label=yes_label,
                no_label=no_label,
                **validated_data,
            )
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

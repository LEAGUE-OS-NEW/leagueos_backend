from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from markets.models import (
    Market,
    MarketCategory,
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
    Market.Status.OPEN,
    Market.Status.SUSPENDED,
    Market.Status.CLOSED,
    Market.Status.RESOLVED,
    Market.Status.VOIDED,
)


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
    class Meta:
        model = MarketOutcome
        fields = [
            "id",
            "side",
            "position",
            "label",
            "description",
        ]


class MarketSubjectSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=MarketScope.choices,
    )
    id = serializers.UUIDField(
        allow_null=True,
    )
    name = serializers.CharField()


class MarketPublicSerializer(serializers.ModelSerializer):
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

    class Meta:
        model = Market
        fields = [
            "id",
            "question",
            "description",
            "rules",
            "resolution_source",
            "resolution_criteria",
            "scope_type",
            "status",
            "opens_at",
            "closes_at",
            "is_featured",
            "sport",
            "category",
            "template",
            "sporting_event",
            "competition",
            "participant",
            "custom_subject",
            "subject",
            "outcomes",
            "winning_outcome",
            "created_at",
            "updated_at",
        ]

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

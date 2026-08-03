from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from markets.models import MarketCategory, MarketEventGroup
from markets.serializers import MarketCategoryPublicSerializer
from markets.services.event_service import MarketEventService
from sports.models import SportingEvent


class SportingEventSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = SportingEvent
        fields = ["id", "name", "starts_at", "status"]


class MarketEventSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketEventGroup
        fields = ["id", "title", "slug", "event_type", "scheduled_at"]


class MarketEventPublicSerializer(serializers.ModelSerializer):
    category = MarketCategoryPublicSerializer(read_only=True)
    sporting_event = SportingEventSummarySerializer(read_only=True)
    market_count = serializers.IntegerField(read_only=True)
    open_market_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = MarketEventGroup
        fields = [
            "id",
            "title",
            "slug",
            "description",
            "event_type",
            "category",
            "sporting_event",
            "scheduled_at",
            "market_count",
            "open_market_count",
            "created_at",
            "updated_at",
        ]


class MarketEventWriteSerializer(serializers.ModelSerializer):
    category_id = serializers.PrimaryKeyRelatedField(
        source="category", queryset=MarketCategory.objects.all(), required=False, allow_null=True
    )
    sporting_event_id = serializers.PrimaryKeyRelatedField(
        source="sporting_event",
        queryset=SportingEvent.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = MarketEventGroup
        fields = [
            "id",
            "title",
            "slug",
            "description",
            "event_type",
            "category_id",
            "sporting_event_id",
            "scheduled_at",
            "status",
        ]
        read_only_fields = ["id", "status"]

    def create(self, validated_data):
        return MarketEventService.create(actor=self.context["request"].user, **validated_data)

    def update(self, instance, validated_data):
        try:
            return MarketEventService.update(event_id=instance.id, **validated_data)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error


class MarketAttachmentSerializer(serializers.Serializer):
    market_id = serializers.UUIDField()


class MarketEventErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField(required=False)


class MarketEventListQuerySerializer(serializers.Serializer):
    event_type = serializers.ChoiceField(choices=MarketEventGroup.EventType.choices, required=False)
    category_id = serializers.UUIDField(required=False)
    sporting_event_id = serializers.UUIDField(required=False)
    scheduled_from = serializers.DateTimeField(required=False)
    scheduled_to = serializers.DateTimeField(required=False)
    search = serializers.CharField(required=False, max_length=255)

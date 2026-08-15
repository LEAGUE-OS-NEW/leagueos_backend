from django.utils import timezone
from rest_framework import serializers

from markets.models import (
    MarketProvisionalEvidence,
    MarketProvisionalResult,
)
from markets.serializers import MarketOutcomePublicSerializer
from markets.services.provisional_result_service import (
    MarketProvisionalResultService,
)


class MarketProvisionalEvidenceWriteSerializer(serializers.Serializer):
    evidence_type = serializers.ChoiceField(
        choices=MarketProvisionalEvidence.EvidenceType.choices,
    )
    label = serializers.CharField(
        max_length=255,
        allow_blank=False,
        trim_whitespace=True,
    )
    reference = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )


class MarketProvisionalResultPublishSerializer(serializers.Serializer):
    winning_outcome_id = serializers.UUIDField()
    notes = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )
    dispute_window_hours = serializers.IntegerField(
        min_value=(MarketProvisionalResultService.MIN_DISPUTE_WINDOW_HOURS),
        max_value=(MarketProvisionalResultService.MAX_DISPUTE_WINDOW_HOURS),
        default=(MarketProvisionalResultService.DEFAULT_DISPUTE_WINDOW_HOURS),
    )
    evidence_items = MarketProvisionalEvidenceWriteSerializer(
        many=True,
        allow_empty=False,
    )


class MarketProvisionalEvidenceReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketProvisionalEvidence
        fields = [
            "id",
            "evidence_type",
            "label",
            "reference",
            "recorded_at",
        ]


class MarketProvisionalResultReadSerializer(serializers.ModelSerializer):
    market_id = serializers.UUIDField(read_only=True)
    winning_outcome = MarketOutcomePublicSerializer(
        read_only=True,
    )
    evidence_items = MarketProvisionalEvidenceReadSerializer(
        many=True,
        read_only=True,
    )
    dispute_status = serializers.SerializerMethodField()
    financial_finalisation_blocked = serializers.SerializerMethodField()

    class Meta:
        model = MarketProvisionalResult
        fields = [
            "id",
            "market_id",
            "winning_outcome",
            "notes",
            "published_at",
            "dispute_deadline",
            "dispute_status",
            "financial_finalisation_blocked",
            "evidence_items",
        ]

    def get_dispute_status(
        self,
        obj: MarketProvisionalResult,
    ) -> str:
        if timezone.now() < obj.dispute_deadline and not hasattr(obj, "development_acceleration"):
            return "OPEN"

        return "CLOSED"

    def get_financial_finalisation_blocked(
        self,
        obj: MarketProvisionalResult,
    ) -> bool:
        return timezone.now() < obj.dispute_deadline and not hasattr(
            obj, "development_acceleration"
        )

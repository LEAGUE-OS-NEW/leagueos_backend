from rest_framework import serializers

from markets.models import (
    MarketResultDispute,
    MarketResultDisputeEvidence,
)


class MarketResultDisputeEvidenceWriteSerializer(serializers.Serializer):
    label = serializers.CharField(
        max_length=255,
        allow_blank=False,
        trim_whitespace=True,
    )
    reference = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )


class MarketResultDisputeSubmitSerializer(serializers.Serializer):
    category = serializers.ChoiceField(
        choices=MarketResultDispute.Category.choices,
    )
    explanation = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )
    evidence_items = MarketResultDisputeEvidenceWriteSerializer(
        many=True,
        allow_empty=False,
    )


class MarketResultDisputeEvidenceReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketResultDisputeEvidence
        fields = [
            "id",
            "label",
            "reference",
            "recorded_at",
        ]


class MarketResultDisputeParticipantSerializer(serializers.ModelSerializer):
    market_id = serializers.UUIDField(
        source="provisional_result.market_id",
        read_only=True,
    )
    provisional_result_id = serializers.UUIDField(
        read_only=True,
    )
    evidence_items = MarketResultDisputeEvidenceReadSerializer(
        many=True,
        read_only=True,
    )

    class Meta:
        model = MarketResultDispute
        fields = [
            "id",
            "market_id",
            "provisional_result_id",
            "category",
            "explanation",
            "submitted_at",
            "evidence_items",
        ]


class MarketResultDisputeAdminSerializer(serializers.ModelSerializer):
    market_id = serializers.UUIDField(
        source="provisional_result.market_id",
        read_only=True,
    )
    provisional_result_id = serializers.UUIDField(
        read_only=True,
    )
    participant_id = serializers.UUIDField(
        read_only=True,
    )
    evidence_items = MarketResultDisputeEvidenceReadSerializer(
        many=True,
        read_only=True,
    )

    class Meta:
        model = MarketResultDispute
        fields = [
            "id",
            "market_id",
            "provisional_result_id",
            "participant_id",
            "category",
            "explanation",
            "submitted_at",
            "evidence_items",
        ]

from rest_framework import serializers

from markets.models import MarketResultDisputeDecision
from markets.serializers import MarketOutcomePublicSerializer
from markets.services.result_dispute_decision_service import (
    MarketResultDisputeDecisionService,
)


class MarketResultDisputeDecisionCreateSerializer(serializers.Serializer):
    decision_type = serializers.ChoiceField(
        choices=MarketResultDisputeDecision.DecisionType.choices,
    )
    winning_outcome_id = serializers.UUIDField(
        required=False,
        allow_null=True,
    )
    review_extension_hours = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=(MarketResultDisputeDecisionService.MIN_REVIEW_EXTENSION_HOURS),
        max_value=(MarketResultDisputeDecisionService.MAX_REVIEW_EXTENSION_HOURS),
    )
    notes = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )
    evidence = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )


class MarketResultDisputeDecisionPublicSerializer(serializers.ModelSerializer):
    market_id = serializers.UUIDField(
        source="provisional_result.market_id",
        read_only=True,
    )
    provisional_result_id = serializers.UUIDField(
        read_only=True,
    )
    winning_outcome = MarketOutcomePublicSerializer(
        read_only=True,
        allow_null=True,
    )
    is_final = serializers.BooleanField(
        read_only=True,
    )

    class Meta:
        model = MarketResultDisputeDecision
        fields = [
            "id",
            "market_id",
            "provisional_result_id",
            "sequence",
            "decision_type",
            "winning_outcome",
            "review_extended_until",
            "covered_dispute_count",
            "notes",
            "evidence",
            "decided_at",
            "is_final",
        ]


class MarketResultDisputeDecisionAdminSerializer(MarketResultDisputeDecisionPublicSerializer):
    decision_maker_id = serializers.UUIDField(
        source="decided_by_id",
        read_only=True,
    )

    class Meta(MarketResultDisputeDecisionPublicSerializer.Meta):
        fields = [
            *MarketResultDisputeDecisionPublicSerializer.Meta.fields,
            "decision_maker_id",
        ]

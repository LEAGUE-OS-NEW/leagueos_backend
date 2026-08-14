from rest_framework import serializers

from markets.models import (
    ComplianceDecisionProposal,
    MarketComplianceReview,
    MarketRiskAssessment,
    MarketRiskProfile,
)


class RiskProfileSerializer(serializers.ModelSerializer):
    participant_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = MarketRiskProfile
        fields = (
            "id",
            "participant_id",
            "current_score",
            "risk_band",
            "restriction_recommendation",
            "reason_codes",
            "last_assessed_at",
            "assessment_source",
            "manual_override_state",
            "override_at",
            "revision",
        )


class RiskAssessmentSerializer(serializers.ModelSerializer):
    participant_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = MarketRiskAssessment
        fields = (
            "id",
            "participant_id",
            "score",
            "band",
            "reason_codes",
            "recommended_action",
            "assessment_source",
            "input_digest",
            "created_at",
        )


class SafeComplianceReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketComplianceReview
        exclude = ("notes_snapshot",)


class ComplianceDecisionSerializer(serializers.ModelSerializer):
    participant_id = serializers.UUIDField(read_only=True)
    proposer_id = serializers.UUIDField(read_only=True)
    decided_by_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = ComplianceDecisionProposal
        fields = (
            "id",
            "participant_id",
            "decision_type",
            "requested_change",
            "reason",
            "before_snapshot",
            "proposed_after_snapshot",
            "proposer_id",
            "status",
            "decided_by_id",
            "decision_reason",
            "proposed_at",
            "decided_at",
        )


class ReassessmentRequestSerializer(serializers.Serializer):
    participant_id = serializers.UUIDField()


class DecisionProposalRequestSerializer(serializers.Serializer):
    participant_id = serializers.UUIDField()
    decision_type = serializers.ChoiceField(choices=ComplianceDecisionProposal.DecisionType.choices)
    requested_change = serializers.JSONField(default=dict)
    reason = serializers.CharField(allow_blank=False, trim_whitespace=True)


class DecisionRequestSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    reason = serializers.CharField(allow_blank=False, trim_whitespace=True)

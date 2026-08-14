from rest_framework import serializers

from markets.models import MarketComplianceReview, MarketParticipantCompliance


class EligibilityResponseSerializer(serializers.Serializer):
    eligible = serializers.BooleanField()
    evaluated_at = serializers.DateTimeField()
    requirements = serializers.DictField()
    reason_codes = serializers.ListField(child=serializers.CharField())
    next_actions = serializers.ListField(child=serializers.CharField())


class AdminComplianceDetailSerializer(EligibilityResponseSerializer):
    participant_id = serializers.UUIDField()
    date_of_birth = serializers.DateField(allow_null=True)
    reviewed_at = serializers.DateTimeField(allow_null=True)
    reviewed_by = serializers.UUIDField(allow_null=True)
    jurisdiction_override_reason = serializers.CharField(allow_blank=True)
    internal_review_notes = serializers.CharField(allow_blank=True)


class IneligibleOrderResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
    code = serializers.CharField()
    eligible = serializers.BooleanField()
    reason_codes = serializers.ListField(child=serializers.CharField())
    next_actions = serializers.ListField(child=serializers.CharField())


class ComplianceUpdateSerializer(serializers.Serializer):
    restriction_status = serializers.ChoiceField(
        choices=MarketParticipantCompliance.RestrictionStatus.choices, required=False
    )
    jurisdiction_override = serializers.ChoiceField(
        choices=MarketParticipantCompliance.JurisdictionOverride.choices, required=False
    )
    jurisdiction_override_reason = serializers.CharField(required=False, allow_blank=True)
    internal_review_notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        instance = self.context.get("compliance")
        override = attrs.get(
            "jurisdiction_override", getattr(instance, "jurisdiction_override", "NONE")
        )
        reason = attrs.get(
            "jurisdiction_override_reason", getattr(instance, "jurisdiction_override_reason", "")
        )
        restriction = attrs.get(
            "restriction_status", getattr(instance, "restriction_status", "CLEAR")
        )
        notes = attrs.get("internal_review_notes", getattr(instance, "internal_review_notes", ""))
        if override in ("ALLOW", "BLOCK") and not reason.strip():
            raise serializers.ValidationError(
                {"jurisdiction_override_reason": "A reason is required for an override."}
            )
        if restriction in ("RESTRICTED", "SUSPENDED") and not (reason.strip() or notes.strip()):
            raise serializers.ValidationError(
                {"internal_review_notes": "Notes or a reason are required for a restriction."}
            )
        return attrs


class ComplianceReviewSerializer(serializers.ModelSerializer):
    actor = serializers.UUIDField(source="actor_id", read_only=True)

    class Meta:
        model = MarketComplianceReview
        fields = (
            "id",
            "participant",
            "actor",
            "previous_restriction_status",
            "new_restriction_status",
            "previous_jurisdiction_override",
            "new_jurisdiction_override",
            "reason",
            "notes_snapshot",
            "created_at",
        )
        read_only_fields = fields

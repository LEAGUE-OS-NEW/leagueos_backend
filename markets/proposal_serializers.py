from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from markets.models import (
    Market,
    MarketCategory,
    MarketEventGroup,
    MarketProposal,
    MarketProposalReview,
    MarketScope,
)
from markets.services.proposal_service import MarketProposalService, normalize_market_question
from sports.models import SportingEvent


class MarketProposalParticipantSerializer(serializers.ModelSerializer):
    scope_type = serializers.ChoiceField(
        choices=[MarketScope.EVENT],
        required=False,
        default=MarketScope.EVENT,
        error_messages={"invalid_choice": "market_proposal_scope_unsupported"},
    )
    category_id = serializers.PrimaryKeyRelatedField(
        source="category", queryset=MarketCategory.objects.all()
    )
    sporting_event_id = serializers.PrimaryKeyRelatedField(
        source="sporting_event",
        queryset=SportingEvent.objects.all(),
        required=False,
        allow_null=True,
    )
    proposed_event_group_id = serializers.PrimaryKeyRelatedField(
        source="proposed_event_group",
        queryset=MarketEventGroup.objects.all(),
        required=False,
        allow_null=True,
    )
    duplicate_candidates = serializers.SerializerMethodField()

    class Meta:
        model = MarketProposal
        fields = [
            "id",
            "question",
            "description",
            "category_id",
            "scope_type",
            "sporting_event_id",
            "proposed_event_group_id",
            "proposed_event_title",
            "proposed_closes_at",
            "proposed_resolution_source",
            "status",
            "duplicate_status",
            "duplicate_candidates",
            "submitted_at",
            "withdrawn_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "duplicate_status",
            "duplicate_candidates",
            "submitted_at",
            "withdrawn_at",
            "created_at",
            "updated_at",
        ]

    def validate_question(self, value):
        value = value.strip()
        if not normalize_market_question(value):
            raise serializers.ValidationError("Question cannot be blank.")
        return value

    def create(self, validated_data):
        try:
            return MarketProposalService.submit(
                proposer=self.context["request"].user, **validated_data
            )
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error

    def update(self, instance, validated_data):
        try:
            return MarketProposalService.update(
                proposal_id=instance.id,
                proposer=self.context["request"].user,
                **validated_data,
            )
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error

    @extend_schema_field(serializers.DictField)
    def get_duplicate_candidates(self, obj):
        if obj.duplicate_status == MarketProposal.DuplicateStatus.CLEAR:
            return {"proposals": [], "markets": []}
        candidates = MarketProposalService.duplicate_candidates(obj)
        return {
            "proposals": [
                {"id": str(pk), "question": question} for pk, question in candidates["proposals"]
            ],
            "markets": [
                {"id": str(pk), "question": question} for pk, question in candidates["markets"]
            ],
        }


class MarketProposalAdminSerializer(serializers.ModelSerializer):
    proposer_id = serializers.UUIDField(read_only=True)
    reviewed_by_id = serializers.UUIDField(read_only=True, allow_null=True)
    approved_market_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = MarketProposal
        fields = [
            field.name
            for field in MarketProposal._meta.fields
            if field.name not in ("proposer", "reviewed_by", "approved_market")
        ] + ["proposer_id", "reviewed_by_id", "approved_market_id"]


class MarketProposalReviewActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=MarketProposalReview.Action.choices)
    reason = serializers.CharField(required=False, allow_blank=True)
    duplicate_of_market = serializers.PrimaryKeyRelatedField(
        queryset=Market.objects.all(), required=False, allow_null=True
    )
    duplicate_of_proposal = serializers.PrimaryKeyRelatedField(
        queryset=MarketProposal.objects.all(), required=False, allow_null=True
    )


class MarketProposalErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField(required=False)


class MarketProposalReviewSerializer(serializers.ModelSerializer):
    actor_id = serializers.UUIDField(read_only=True)
    duplicate_market_id = serializers.UUIDField(read_only=True, allow_null=True)
    duplicate_proposal_id = serializers.UUIDField(read_only=True, allow_null=True)
    approved_market_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = MarketProposalReview
        fields = [
            "id",
            "action",
            "previous_status",
            "new_status",
            "reason",
            "actor_id",
            "duplicate_market_id",
            "duplicate_proposal_id",
            "approved_market_id",
            "created_at",
        ]


class MarketProposalAdminQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=MarketProposal.Status.choices, required=False)
    duplicate_status = serializers.ChoiceField(
        choices=MarketProposal.DuplicateStatus.choices, required=False
    )
    category_id = serializers.UUIDField(required=False)
    sporting_event_id = serializers.UUIDField(required=False)
    proposer_id = serializers.UUIDField(required=False)
    submitted_from = serializers.DateTimeField(required=False)
    submitted_to = serializers.DateTimeField(required=False)
    search = serializers.CharField(required=False, max_length=500)

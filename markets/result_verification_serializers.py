from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from markets.admin_serializers import MarketAdminReadSerializer


class MarketResultAccelerationRequestSerializer(serializers.Serializer):
    pass


class MarketResultAccelerationResponseSerializer(serializers.Serializer):
    development_only = serializers.BooleanField()
    created = serializers.BooleanField()
    effective_dispute_window_closed = serializers.BooleanField()
    accelerated_at = serializers.DateTimeField()
    message = serializers.CharField()


class MarketResultExposureOutcomeSerializer(serializers.Serializer):
    outcome_id = serializers.UUIDField()
    side = serializers.CharField()
    label = serializers.CharField()
    position_count = serializers.IntegerField()
    total_quantity = serializers.DecimalField(max_digits=18, decimal_places=4)
    total_stake = serializers.DecimalField(max_digits=18, decimal_places=4)


class MarketResultExposureResponseSerializer(serializers.Serializer):
    outcomes = MarketResultExposureOutcomeSerializer(many=True)


class MarketResultVerificationSerializer(MarketAdminReadSerializer):
    workflow_state = serializers.SerializerMethodField()
    provisional_result = serializers.SerializerMethodField()
    open_dispute_count = serializers.SerializerMethodField()
    can_publish_provisional = serializers.SerializerMethodField()
    can_resolve = serializers.SerializerMethodField()
    can_settle = serializers.SerializerMethodField()
    can_close = serializers.SerializerMethodField()
    can_void = serializers.SerializerMethodField()
    can_refund = serializers.SerializerMethodField()
    settlement = serializers.SerializerMethodField()
    void_refund = serializers.SerializerMethodField()

    class Meta(MarketAdminReadSerializer.Meta):
        fields = [
            *MarketAdminReadSerializer.Meta.fields,
            "workflow_state",
            "provisional_result",
            "open_dispute_count",
            "can_publish_provisional",
            "can_resolve",
            "can_settle",
            "can_close",
            "can_void",
            "can_refund",
            "settlement",
            "void_refund",
        ]

    def _facts(self, obj):
        provisional = obj.provisional_result if hasattr(obj, "provisional_result") else None
        disputes = list(getattr(provisional, "disputes", []).all()) if provisional else []
        decisions = list(getattr(provisional, "decisions", []).all()) if provisional else []
        final_decision = next((item for item in decisions if item.is_final), None)
        return provisional, disputes, final_decision

    @extend_schema_field(serializers.CharField())
    def get_workflow_state(self, obj):
        if obj.status == obj.Status.VOIDED:
            return "REFUNDED" if hasattr(obj, "void_refund") else "VOIDED"
        if obj.status == obj.Status.RESOLVED:
            return "SETTLED" if hasattr(obj, "settlement") else "READY_TO_SETTLE"
        if (
            obj.status in (obj.Status.OPEN, obj.Status.SUSPENDED)
            and obj.closes_at <= timezone.now()
        ):
            return "READY_TO_CLOSE"

        provisional, disputes, final_decision = self._facts(obj)
        if provisional is None:
            return "AWAITING_RESULT"
        if disputes and final_decision is None:
            return "DISPUTED"
        if final_decision is not None:
            return "READY_TO_RESOLVE"
        if timezone.now() < provisional.dispute_deadline and not hasattr(
            provisional, "development_acceleration"
        ):
            return "DISPUTE_WINDOW"
        return "READY_TO_RESOLVE"

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_provisional_result(self, obj):
        provisional = obj.provisional_result if hasattr(obj, "provisional_result") else None
        if provisional is None:
            return None
        return {
            "winning_outcome_id": str(provisional.winning_outcome_id),
            "published_at": provisional.published_at,
            "dispute_deadline": provisional.dispute_deadline,
            "development_window_ended_at": (
                provisional.development_acceleration.accelerated_at
                if hasattr(provisional, "development_acceleration")
                else None
            ),
            "evidence_items": [
                {
                    "evidence_type": item.evidence_type,
                    "label": item.label,
                    "reference": item.reference,
                }
                for item in provisional.evidence_items.all()
            ],
        }

    @extend_schema_field(serializers.IntegerField())
    def get_open_dispute_count(self, obj):
        _, disputes, final_decision = self._facts(obj)
        return 0 if final_decision else len(disputes)

    @extend_schema_field(serializers.BooleanField())
    def get_can_publish_provisional(self, obj):
        return obj.status == obj.Status.CLOSED and not hasattr(obj, "provisional_result")

    @extend_schema_field(serializers.BooleanField())
    def get_can_resolve(self, obj):
        return self.get_workflow_state(obj) == "READY_TO_RESOLVE"

    @extend_schema_field(serializers.BooleanField())
    def get_can_settle(self, obj):
        return self.get_workflow_state(obj) == "READY_TO_SETTLE"

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_settlement(self, obj):
        settlement = obj.settlement if hasattr(obj, "settlement") else None
        if settlement is None:
            return None
        return {
            "reference": str(settlement.id),
            "status": "SETTLED",
            "executed_at": settlement.executed_at,
        }

    @extend_schema_field(serializers.BooleanField())
    def get_can_close(self, obj):
        return self.get_workflow_state(obj) == "READY_TO_CLOSE"

    @extend_schema_field(serializers.BooleanField())
    def get_can_void(self, obj):
        # Mirrors MarketResolutionService.VOIDABLE_STATUSES exactly — a market
        # can be voided any time before it's actually resolved (event
        # cancelled, no dispute ever needed to have been raised).
        return obj.status in (
            obj.Status.APPROVED,
            obj.Status.OPEN,
            obj.Status.SUSPENDED,
            obj.Status.CLOSED,
        )

    @extend_schema_field(serializers.BooleanField())
    def get_can_refund(self, obj):
        return self.get_workflow_state(obj) == "VOIDED"

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_void_refund(self, obj):
        refund = obj.void_refund if hasattr(obj, "void_refund") else None
        if refund is None:
            return None
        return {
            "reference": str(refund.id),
            "status": "REFUNDED",
            "executed_at": refund.executed_at,
        }

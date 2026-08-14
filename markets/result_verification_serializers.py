from django.utils import timezone
from rest_framework import serializers

from markets.admin_serializers import MarketAdminReadSerializer


class MarketResultVerificationSerializer(MarketAdminReadSerializer):
    workflow_state = serializers.SerializerMethodField()
    provisional_result = serializers.SerializerMethodField()
    open_dispute_count = serializers.SerializerMethodField()
    can_publish_provisional = serializers.SerializerMethodField()
    can_resolve = serializers.SerializerMethodField()
    can_settle = serializers.SerializerMethodField()

    class Meta(MarketAdminReadSerializer.Meta):
        fields = [
            *MarketAdminReadSerializer.Meta.fields,
            "workflow_state",
            "provisional_result",
            "open_dispute_count",
            "can_publish_provisional",
            "can_resolve",
            "can_settle",
        ]

    def _facts(self, obj):
        provisional = obj.provisional_result if hasattr(obj, "provisional_result") else None
        disputes = list(getattr(provisional, "disputes", []).all()) if provisional else []
        decisions = list(getattr(provisional, "decisions", []).all()) if provisional else []
        final_decision = next((item for item in decisions if item.is_final), None)
        return provisional, disputes, final_decision

    def get_workflow_state(self, obj):
        if obj.status == obj.Status.VOIDED:
            return "VOIDED_REFUNDED" if hasattr(obj, "void_refund") else "VOIDED"
        if obj.status == obj.Status.RESOLVED:
            return "SETTLED" if hasattr(obj, "settlement") else "READY_TO_SETTLE"

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

    def get_provisional_result(self, obj):
        provisional = obj.provisional_result if hasattr(obj, "provisional_result") else None
        if provisional is None:
            return None
        return {
            "winning_outcome_id": str(provisional.winning_outcome_id),
            "notes": provisional.notes,
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

    def get_open_dispute_count(self, obj):
        _, disputes, final_decision = self._facts(obj)
        return 0 if final_decision else len(disputes)

    def get_can_publish_provisional(self, obj):
        return obj.status == obj.Status.CLOSED and not hasattr(obj, "provisional_result")

    def get_can_resolve(self, obj):
        return self.get_workflow_state(obj) == "READY_TO_RESOLVE"

    def get_can_settle(self, obj):
        return self.get_workflow_state(obj) == "READY_TO_SETTLE"

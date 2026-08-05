import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from authentication.services.permission_service import PermissionService
from markets.models import (
    ComplianceDecisionProposal,
    MarketParticipantCompliance,
    MarketRiskAssessment,
    MarketRiskProfile,
)
from markets.services.compliance_service import MarketComplianceService


class ComplianceDecisionService:
    PERMISSION = "manage_compliance"

    @classmethod
    def _permission(cls, actor):
        if not PermissionService.has_permission(actor, cls.PERMISSION):
            raise PermissionDenied("You do not have the manage_compliance permission.")

    @staticmethod
    def _snapshot(compliance, profile):
        return {
            "restriction_status": compliance.restriction_status,
            "jurisdiction_override": compliance.jurisdiction_override,
            "risk_band": profile.risk_band,
            "restriction_recommendation": profile.restriction_recommendation,
            "manual_override_state": profile.manual_override_state,
        }

    @classmethod
    @transaction.atomic
    def propose(cls, *, participant, decision_type, requested_change, reason, actor):
        cls._permission(actor)
        if not reason or not reason.strip():
            raise ValidationError("A proposal reason is required.")
        compliance, _ = MarketParticipantCompliance.objects.get_or_create(participant=participant)
        profile, _ = MarketRiskProfile.objects.get_or_create(participant=participant)
        before = cls._snapshot(compliance, profile)
        after = dict(before)
        kind = ComplianceDecisionProposal.DecisionType
        if decision_type == kind.CLEAR_CRITICAL_RISK_BLOCK:
            if profile.risk_band != "CRITICAL":
                raise ValidationError("Participant does not have a CRITICAL risk block.")
            after.update(restriction_recommendation="NONE", manual_override_state="CLEAR")
        elif decision_type == kind.REMOVE_SUSPENDED_RESTRICTION:
            if compliance.restriction_status != "SUSPENDED":
                raise ValidationError("Participant is not suspended.")
            after["restriction_status"] = "CLEAR"
        elif decision_type == kind.JURISDICTION_BLOCK_TO_ALLOW:
            if compliance.jurisdiction_override != "BLOCK":
                raise ValidationError("Jurisdiction is not blocked.")
            after["jurisdiction_override"] = "ALLOW"
        elif decision_type == kind.APPLY_RISK_OVERRIDE:
            state = requested_change.get("manual_override_state")
            if state not in {"CLEAR", "REVIEW", "BLOCK"}:
                raise ValidationError("Invalid manual risk override state.")
            after["manual_override_state"] = state
        elif decision_type == kind.CLEAR_RISK_OVERRIDE:
            after["manual_override_state"] = "NONE"
        else:
            raise ValidationError("Unsupported compliance decision type.")
        proposal = ComplianceDecisionProposal.objects.create(
            participant=participant,
            decision_type=decision_type,
            requested_change=requested_change,
            reason=reason.strip(),
            before_snapshot=before,
            proposed_after_snapshot=after,
            proposer=actor,
        )
        cls._pending_alert(proposal)
        return proposal

    @classmethod
    @transaction.atomic
    def decide(cls, *, proposal_id, approve, reason, actor):
        cls._permission(actor)
        proposal = ComplianceDecisionProposal.objects.select_for_update().get(pk=proposal_id)
        target = proposal.Status.APPROVED if approve else proposal.Status.REJECTED
        if proposal.status == target:
            return proposal, False
        if proposal.status != proposal.Status.PENDING:
            raise ValidationError("The proposal has already received the opposite decision.")
        if proposal.proposer_id == actor.id:
            raise ValidationError("The proposer cannot decide their own proposal.")
        if not reason or not reason.strip():
            raise ValidationError("A decision reason is required.")
        if approve:
            cls._apply(proposal, actor)
        proposal.status = target
        proposal.decided_by = actor
        proposal.decision_reason = reason.strip()
        proposal.decided_at = timezone.now()
        proposal._allow_finalize = True
        proposal.save()
        return proposal, True

    @classmethod
    def _apply(cls, proposal, actor):
        kind = ComplianceDecisionProposal.DecisionType
        if proposal.decision_type == kind.REMOVE_SUSPENDED_RESTRICTION:
            MarketComplianceService.update(
                participant=proposal.participant,
                actor=actor,
                source="ADMIN",
                changes={"restriction_status": "CLEAR"},
                reason=proposal.reason,
            )
        elif proposal.decision_type == kind.JURISDICTION_BLOCK_TO_ALLOW:
            MarketComplianceService.update(
                participant=proposal.participant,
                actor=actor,
                source="ADMIN",
                changes={"jurisdiction_override": "ALLOW"},
                reason=proposal.reason,
            )
        else:
            profile = MarketRiskProfile.objects.select_for_update().get(
                participant=proposal.participant
            )
            state = proposal.proposed_after_snapshot["manual_override_state"]
            profile.manual_override_state = state
            profile.manual_override_reason = proposal.reason if state != "NONE" else ""
            profile.override_actor = actor if state != "NONE" else None
            profile.override_at = timezone.now() if state != "NONE" else None
            profile.restriction_recommendation = proposal.proposed_after_snapshot[
                "restriction_recommendation"
            ]
            profile.revision += 1
            profile.save()
            summary = {**proposal.proposed_after_snapshot, "decision_id": str(proposal.id)}
            digest = hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest()
            MarketRiskAssessment.objects.create(
                participant=proposal.participant,
                score=profile.current_score,
                band=profile.risk_band,
                reason_codes=profile.reason_codes,
                input_summary=summary,
                recommended_action=profile.restriction_recommendation,
                assessment_source="ADMIN",
                actor=actor,
                input_digest=digest,
            )

    @staticmethod
    def _pending_alert(proposal):
        from notifications.services.operational_alert_service import OperationalAlertService

        OperationalAlertService.create(
            permissions=("manage_compliance",),
            event_type="COMPLIANCE_DECISION_PENDING",
            title="Compliance decision awaiting approval",
            message="A compliance proposal requires an independent checker.",
            source_key=f"compliance-decision:{proposal.id}:pending",
            data={"proposal_id": str(proposal.id), "decision_type": proposal.decision_type},
        )

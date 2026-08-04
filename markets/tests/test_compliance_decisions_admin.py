import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from authentication.models import Permission, Role, RolePermission, UserRole
from markets.models import (
    ComplianceDecisionProposal,
    MarketParticipantCompliance,
    MarketRiskProfile,
)
from markets.services.compliance_decision_service import ComplianceDecisionService


def user(email):
    return get_user_model().objects.create_user(email=email, username=email, password="test")


def grant_manage_compliance(actor, suffix):
    permission, _ = Permission.objects.get_or_create(
        name="manage_compliance", defaults={"resource": "compliance", "action": "manage"}
    )
    role = Role.objects.create(name=f"compliance_{suffix}", display_name="Compliance")
    RolePermission.objects.create(role=role, permission=permission)
    UserRole.objects.create(user=actor, role=role)


@pytest.mark.django_db(transaction=True)
def test_maker_checker_approval_is_atomic_idempotent_and_immutable():
    call_command("seed_notification_data")
    maker, checker, participant = (
        user("maker@example.com"),
        user("checker@example.com"),
        user("p@example.com"),
    )
    grant_manage_compliance(maker, "maker")
    grant_manage_compliance(checker, "checker")
    compliance = MarketParticipantCompliance.objects.create(
        participant=participant, restriction_status="SUSPENDED"
    )
    MarketRiskProfile.objects.create(participant=participant)
    proposal = ComplianceDecisionService.propose(
        participant=participant,
        decision_type="REMOVE_SUSPENDED_RESTRICTION",
        requested_change={"restriction_status": "CLEAR"},
        reason="Verified remediation",
        actor=maker,
    )
    with pytest.raises(ValidationError):
        ComplianceDecisionService.decide(
            proposal_id=proposal.id, approve=True, reason="Self", actor=maker
        )
    decided, changed = ComplianceDecisionService.decide(
        proposal_id=proposal.id, approve=True, reason="Independent check", actor=checker
    )
    compliance.refresh_from_db()
    assert changed and decided.status == "APPROVED" and compliance.restriction_status == "CLEAR"
    replay, changed = ComplianceDecisionService.decide(
        proposal_id=proposal.id, approve=True, reason="Replay", actor=checker
    )
    assert replay.status == "APPROVED" and not changed
    with pytest.raises(ValidationError):
        ComplianceDecisionService.decide(
            proposal_id=proposal.id, approve=False, reason="Opposite", actor=checker
        )
    with pytest.raises(ValidationError):
        ComplianceDecisionProposal.objects.filter(pk=proposal.pk).update(status="REJECTED")
    decided.reason = "mutated"
    with pytest.raises(ValidationError):
        decided.save()
    with pytest.raises(ValidationError):
        decided.delete()


@pytest.mark.django_db
def test_admin_kyc_and_risk_endpoints_are_permission_protected():
    actor, outsider = user("admin@example.com"), user("outsider@example.com")
    grant_manage_compliance(actor, "api")
    MarketRiskProfile.objects.create(
        participant=outsider, risk_band="HIGH", reason_codes=["KYC_REJECTED"]
    )
    client = APIClient()
    client.force_authenticate(outsider)
    assert client.get("/api/v1/admin/compliance/risk-profiles/").status_code == 403
    client.force_authenticate(actor)
    response = client.get("/api/v1/admin/compliance/risk-profiles/?band=HIGH")
    assert response.status_code == 200
    item = response.data["results"][0]
    assert item["participant_id"] == str(outsider.id)
    assert "email" not in item and "manual_override_reason" not in item
    assert client.get("/api/v1/admin/compliance/risk-profiles/?band=UNKNOWN").status_code == 400


@pytest.mark.django_db
def test_decision_reasons_are_required():
    maker, participant = user("m2@example.com"), user("p2@example.com")
    grant_manage_compliance(maker, "required")
    MarketParticipantCompliance.objects.create(
        participant=participant, restriction_status="SUSPENDED"
    )
    MarketRiskProfile.objects.create(participant=participant)
    with pytest.raises(ValidationError):
        ComplianceDecisionService.propose(
            participant=participant,
            decision_type="REMOVE_SUSPENDED_RESTRICTION",
            requested_change={},
            reason=" ",
            actor=maker,
        )


@pytest.mark.django_db(transaction=True)
def test_all_compliance_decision_types_and_rejection():
    call_command("seed_notification_data")
    maker = user("all-maker@example.com")
    checker = user("all-checker@example.com")
    participant = user("all-p@example.com")
    grant_manage_compliance(maker, "all-maker")
    grant_manage_compliance(checker, "all-checker")
    compliance = MarketParticipantCompliance.objects.create(
        participant=participant, jurisdiction_override="BLOCK"
    )
    profile = MarketRiskProfile.objects.create(
        participant=participant, risk_band="CRITICAL", restriction_recommendation="BLOCK"
    )
    with pytest.raises(PermissionDenied):
        ComplianceDecisionService.propose(
            participant=participant,
            decision_type="CLEAR_RISK_OVERRIDE",
            requested_change={},
            reason="No",
            actor=participant,
        )
    critical = ComplianceDecisionService.propose(
        participant=participant,
        decision_type="CLEAR_CRITICAL_RISK_BLOCK",
        requested_change={},
        reason="Clear critical",
        actor=maker,
    )
    ComplianceDecisionService.decide(
        proposal_id=critical.id, approve=True, reason="Checked", actor=checker
    )
    profile.refresh_from_db()
    assert profile.manual_override_state == "CLEAR"
    jurisdiction = ComplianceDecisionService.propose(
        participant=participant,
        decision_type="JURISDICTION_BLOCK_TO_ALLOW",
        requested_change={},
        reason="Allow",
        actor=maker,
    )
    ComplianceDecisionService.decide(
        proposal_id=jurisdiction.id, approve=True, reason="Checked", actor=checker
    )
    compliance.refresh_from_db()
    assert compliance.jurisdiction_override == "ALLOW"
    override = ComplianceDecisionService.propose(
        participant=participant,
        decision_type="APPLY_RISK_OVERRIDE",
        requested_change={"manual_override_state": "REVIEW"},
        reason="Review",
        actor=maker,
    )
    ComplianceDecisionService.decide(
        proposal_id=override.id, approve=True, reason="Checked", actor=checker
    )
    clear = ComplianceDecisionService.propose(
        participant=participant,
        decision_type="CLEAR_RISK_OVERRIDE",
        requested_change={},
        reason="Clear",
        actor=maker,
    )
    rejected, changed = ComplianceDecisionService.decide(
        proposal_id=clear.id, approve=False, reason="Keep", actor=checker
    )
    assert changed and rejected.status == "REJECTED"
    with pytest.raises(ValidationError):
        ComplianceDecisionService.propose(
            participant=participant,
            decision_type="APPLY_RISK_OVERRIDE",
            requested_change={"manual_override_state": "BAD"},
            reason="Bad",
            actor=maker,
        )

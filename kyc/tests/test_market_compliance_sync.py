import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from authentication.models import Permission, UserPermission
from kyc.models import KYCVerification
from kyc.services.market_compliance_sync import KYCMarketComplianceSyncService
from markets.models import MarketComplianceReview, MarketParticipantCompliance

User = get_user_model()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("canonical_status", "market_status"),
    [
        (KYCVerification.Status.NOT_STARTED, MarketParticipantCompliance.KYCStatus.NOT_STARTED),
        (KYCVerification.Status.PENDING, MarketParticipantCompliance.KYCStatus.PENDING),
        (KYCVerification.Status.PROCESSING, MarketParticipantCompliance.KYCStatus.PENDING),
        (KYCVerification.Status.REVIEW, MarketParticipantCompliance.KYCStatus.PENDING),
        (KYCVerification.Status.RETRY_REQUIRED, MarketParticipantCompliance.KYCStatus.PENDING),
        (KYCVerification.Status.VERIFIED, MarketParticipantCompliance.KYCStatus.VERIFIED),
        (KYCVerification.Status.REJECTED, MarketParticipantCompliance.KYCStatus.REJECTED),
        (KYCVerification.Status.EXPIRED, MarketParticipantCompliance.KYCStatus.EXPIRED),
    ],
)
def test_canonical_status_mapping_is_audited(canonical_status, market_status):
    user = User.objects.create_user(username=f"sync-{canonical_status}")
    verification = KYCVerification.objects.create(user=user, status=canonical_status)

    compliance, changed = KYCMarketComplianceSyncService.sync(verification=verification)

    assert compliance.kyc_status == market_status
    assert changed is (market_status != MarketParticipantCompliance.KYCStatus.NOT_STARTED)
    assert MarketComplianceReview.objects.filter(participant=user).count() == int(changed)


@pytest.mark.django_db
def test_canonical_sync_is_idempotent():
    user = User.objects.create_user(username="sync-idempotent")
    verification = KYCVerification.objects.create(user=user, status=KYCVerification.Status.VERIFIED)
    KYCMarketComplianceSyncService.sync(verification=verification)

    _, changed = KYCMarketComplianceSyncService.sync(verification=verification)

    assert changed is False
    assert MarketComplianceReview.objects.filter(participant=user).count() == 1


@pytest.mark.django_db
def test_compliance_specialist_can_review_and_decision_synchronizes():
    fan = User.objects.create_user(username="sync-fan", email="sync-fan@example.test")
    reviewer = User.objects.create_user(
        username="sync-reviewer", email="sync-reviewer@example.test", is_staff=False
    )
    permission = Permission.objects.create(
        code="manage_compliance", name="Manage compliance", resource="compliance", action="manage"
    )
    UserPermission.objects.create(user=reviewer, permission=permission)
    verification = KYCVerification.objects.create(user=fan, status=KYCVerification.Status.REVIEW)
    client = APIClient()
    client.force_authenticate(reviewer)

    response = client.post(
        f"/api/v1/admin/kyc/verifications/{verification.id}/review/",
        {"decision": "VERIFIED", "notes": "Checks confirmed."},
        format="json",
    )

    assert response.status_code == 200
    assert MarketParticipantCompliance.objects.get(participant=fan).kyc_status == "VERIFIED"
    assert MarketComplianceReview.objects.get(participant=fan).actor == reviewer

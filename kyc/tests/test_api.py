import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient
from kyc.models import KYCVerification
from kyc.tests.helpers import create_test_image_bytes

User = get_user_model()


@pytest.mark.django_db
def test_unauthenticated_kyc_submission_rejected():
    client = APIClient()
    response = client.post("/api/v1/fans/kyc/", {})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_fan_kyc_submission_success():
    user = User.objects.create_user(
        username="fan1", email="fan1@example.com", password="Pass123!Password"
    )
    client = APIClient()
    client.force_authenticate(user=user)

    doc_bytes = create_test_image_bytes(width=800, height=600)
    selfie_bytes = create_test_image_bytes(width=600, height=600)

    doc_file = SimpleUploadedFile("passport.jpg", doc_bytes, content_type="image/jpeg")
    selfie_file = SimpleUploadedFile("selfie.jpg", selfie_bytes, content_type="image/jpeg")

    payload = {
        "document_type": "PASSPORT",
        "document_country": "UGA",
        "document_image": doc_file,
        "selfie_image": selfie_file,
    }

    response = client.post("/api/v1/fans/kyc/", payload, format="multipart")
    assert response.status_code == status.HTTP_202_ACCEPTED
    assert response.data["success"] is True
    assert response.data["data"]["status"] in [
        KYCVerification.Status.PROCESSING,
        KYCVerification.Status.VERIFIED,
    ]

    # Verify database record
    verification = KYCVerification.objects.get(user=user)
    assert verification.attempts.count() == 1


@pytest.mark.django_db
def test_fan_kyc_status_endpoint():
    user = User.objects.create_user(
        username="fan2", email="fan2@example.com", password="Pass123!Password"
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/v1/fans/kyc/status/")
    assert response.status_code == status.HTTP_200_OK
    assert response.data["data"]["status"] == KYCVerification.Status.NOT_STARTED
    assert response.data["data"]["can_retry"] is True


@pytest.mark.django_db
def test_admin_kyc_list_permissions():
    normal_user = User.objects.create_user(
        username="user_normal", email="norm@example.com", password="Pass123!Password"
    )
    admin_user = User.objects.create_superuser(
        username="admin_user", email="admin@example.com", password="Pass123!Password"
    )

    client = APIClient()

    # Normal user forbidden
    client.force_authenticate(user=normal_user)
    res_forbidden = client.get("/api/v1/admin/kyc/verifications/")
    assert res_forbidden.status_code == status.HTTP_403_FORBIDDEN

    # Admin allowed
    client.force_authenticate(user=admin_user)
    res_ok = client.get("/api/v1/admin/kyc/verifications/")
    assert res_ok.status_code == status.HTTP_200_OK
    assert "verifications" in res_ok.data["data"]

# ---------------------------------------------------------------------------
# KYC approval → market eligibility synchronisation tests
# ---------------------------------------------------------------------------
from markets.models import KYCVerificationSession, MarketParticipantCompliance
from markets.services.eligibility_service import MarketEligibilityService


def _make_fan(username, email):
    """Helper: create an ordinary (non-admin) user."""
    return User.objects.create_user(
        username=username, email=email, password="Pass123!Password"
    )


def _make_admin(username, email):
    """Helper: create a staff/superuser for admin endpoints."""
    return User.objects.create_superuser(
        username=username, email=email, password="Pass123!Password"
    )


def _seed_pending_verification(fan):
    """Helper: create a KYCVerification in PENDING state for *fan*."""
    verification, _ = KYCVerification.objects.get_or_create(
        user=fan,
        defaults={"status": KYCVerification.Status.PENDING},
    )
    verification.status = KYCVerification.Status.PENDING
    verification.save(update_fields=["status"])
    return verification


# ---------------------------------------------------------------------------
# 1. Admin approves → canonical KYCVerification becomes VERIFIED
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_admin_approve_kyc_sets_canonical_verification_verified():
    fan = _make_fan("fan_appr1", "fan_appr1@example.com")
    admin = _make_admin("adm_appr1", "adm_appr1@example.com")
    verification = _seed_pending_verification(fan)

    client = APIClient()
    client.force_authenticate(user=admin)
    url = f"/api/v1/admin/kyc/verifications/{verification.id}/review/"
    resp = client.post(url, {"decision": "VERIFIED"}, format="json")

    assert resp.status_code == status.HTTP_200_OK, resp.data
    assert resp.data["data"]["status"] == "VERIFIED"

    verification.refresh_from_db()
    assert verification.status == KYCVerification.Status.VERIFIED
    assert verification.verified_at is not None


# ---------------------------------------------------------------------------
# 2. Admin approves → MarketParticipantCompliance.kyc_status becomes VERIFIED
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_admin_approve_kyc_updates_market_participant_compliance():
    fan = _make_fan("fan_appr2", "fan_appr2@example.com")
    admin = _make_admin("adm_appr2", "adm_appr2@example.com")
    verification = _seed_pending_verification(fan)

    client = APIClient()
    client.force_authenticate(user=admin)
    url = f"/api/v1/admin/kyc/verifications/{verification.id}/review/"
    client.post(url, {"decision": "VERIFIED"}, format="json")

    compliance = MarketParticipantCompliance.objects.get(participant=fan)
    assert compliance.kyc_status == MarketParticipantCompliance.KYCStatus.VERIFIED


# ---------------------------------------------------------------------------
# 3. Admin approves → GET /api/v1/fans/kyc/status/ returns VERIFIED
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_fan_kyc_status_reflects_verified_after_admin_approval():
    fan = _make_fan("fan_appr3", "fan_appr3@example.com")
    admin = _make_admin("adm_appr3", "adm_appr3@example.com")
    verification = _seed_pending_verification(fan)

    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)
    admin_client.post(
        f"/api/v1/admin/kyc/verifications/{verification.id}/review/",
        {"decision": "VERIFIED"},
        format="json",
    )

    fan_client = APIClient()
    fan_client.force_authenticate(user=fan)
    resp = fan_client.get("/api/v1/fans/kyc/status/")

    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["data"]["status"] == KYCVerification.Status.VERIFIED


# ---------------------------------------------------------------------------
# 4. Admin approves → GET /api/v1/markets/kyc/summary/ shows kyc_eligible=True
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_market_kyc_summary_reflects_verified_after_admin_approval():
    fan = _make_fan("fan_appr4", "fan_appr4@example.com")
    admin = _make_admin("adm_appr4", "adm_appr4@example.com")
    verification = _seed_pending_verification(fan)

    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)
    admin_client.post(
        f"/api/v1/admin/kyc/verifications/{verification.id}/review/",
        {"decision": "VERIFIED"},
        format="json",
    )

    fan_client = APIClient()
    fan_client.force_authenticate(user=fan)
    resp = fan_client.get("/api/v1/markets/kyc/summary/")

    assert resp.status_code == status.HTTP_200_OK
    # as_dict() nests eligibility details under "requirements"
    requirements = resp.data.get("requirements", {})
    assert requirements.get("kyc_status") == "VERIFIED"
    assert requirements.get("kyc_eligible") is True


# ---------------------------------------------------------------------------
# 5. MarketEligibilityService.evaluate() directly reflects compliance state
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_market_eligibility_service_kyc_eligible_after_approval():
    fan = _make_fan("fan_appr5", "fan_appr5@example.com")
    admin = _make_admin("adm_appr5", "adm_appr5@example.com")
    verification = _seed_pending_verification(fan)

    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)
    admin_client.post(
        f"/api/v1/admin/kyc/verifications/{verification.id}/review/",
        {"decision": "VERIFIED"},
        format="json",
    )

    result = MarketEligibilityService.evaluate(participant=fan)
    assert result.kyc_eligible is True
    assert "KYC_PENDING" not in result.reason_codes
    assert "KYC_NOT_STARTED" not in result.reason_codes


# ---------------------------------------------------------------------------
# 6. Admin rejects → compliance kyc_status becomes REJECTED, fan not eligible
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_admin_reject_kyc_updates_compliance_and_blocks_eligibility():
    fan = _make_fan("fan_rej1", "fan_rej1@example.com")
    admin = _make_admin("adm_rej1", "adm_rej1@example.com")
    verification = _seed_pending_verification(fan)

    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)
    admin_client.post(
        f"/api/v1/admin/kyc/verifications/{verification.id}/review/",
        {"decision": "REJECTED", "notes": "Document expired"},
        format="json",
    )

    verification.refresh_from_db()
    assert verification.status == KYCVerification.Status.REJECTED
    assert "Document expired" in verification.rejection_reason

    compliance = MarketParticipantCompliance.objects.get(participant=fan)
    assert compliance.kyc_status == MarketParticipantCompliance.KYCStatus.REJECTED

    fan_client = APIClient()
    fan_client.force_authenticate(user=fan)
    resp = fan_client.get("/api/v1/markets/kyc/summary/")
    assert resp.status_code == status.HTTP_200_OK
    requirements = resp.data.get("requirements", {})
    assert requirements.get("kyc_eligible") is False


# ---------------------------------------------------------------------------
# 7. Admin sets REVIEW → compliance stays PENDING, not yet eligible
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_admin_review_decision_keeps_compliance_pending():
    fan = _make_fan("fan_rev1", "fan_rev1@example.com")
    admin = _make_admin("adm_rev1", "adm_rev1@example.com")
    verification = _seed_pending_verification(fan)

    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)
    admin_client.post(
        f"/api/v1/admin/kyc/verifications/{verification.id}/review/",
        {"decision": "REVIEW"},
        format="json",
    )

    verification.refresh_from_db()
    assert verification.status == KYCVerification.Status.REVIEW

    compliance = MarketParticipantCompliance.objects.get(participant=fan)
    assert compliance.kyc_status == MarketParticipantCompliance.KYCStatus.PENDING

    result = MarketEligibilityService.evaluate(participant=fan)
    assert result.kyc_eligible is False


# ---------------------------------------------------------------------------
# 8. KYCVerificationSession is also moved to the terminal state on VERIFIED
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_admin_approve_kyc_closes_open_session():
    from markets.services.kyc_service import KYCService as _KYCService

    fan = _make_fan("fan_sess1", "fan_sess1@example.com")
    admin = _make_admin("adm_sess1", "adm_sess1@example.com")
    verification = _seed_pending_verification(fan)

    # Start a markets-side KYC session so there is an open session to close.
    session, _ = _KYCService.start(
        participant=fan,
        initiated_by=fan,
        idempotency_key="test-open-session",
    )
    assert session.status not in _KYCService.TERMINAL

    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)
    admin_client.post(
        f"/api/v1/admin/kyc/verifications/{verification.id}/review/",
        {"decision": "VERIFIED"},
        format="json",
    )

    session.refresh_from_db()
    assert session.status == "VERIFIED"


# ---------------------------------------------------------------------------
# 9. Non-admin cannot call the review endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_non_admin_cannot_review_kyc():
    fan = _make_fan("fan_nonadm", "fan_nonadm@example.com")
    verification = _seed_pending_verification(fan)

    client = APIClient()
    client.force_authenticate(user=fan)
    resp = client.post(
        f"/api/v1/admin/kyc/verifications/{verification.id}/review/",
        {"decision": "VERIFIED"},
        format="json",
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN

    # canonical record must be untouched
    verification.refresh_from_db()
    assert verification.status == KYCVerification.Status.PENDING

    # compliance must not have been created/updated
    assert not MarketParticipantCompliance.objects.filter(participant=fan).exists()


# ---------------------------------------------------------------------------
# 10. Approval is atomic — partial failure leaves both systems unchanged
#     (smoke test: 404 on unknown verification_id, nothing written)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_review_unknown_verification_id_returns_404():
    import uuid
    admin = _make_admin("adm_404", "adm_404@example.com")
    client = APIClient()
    client.force_authenticate(user=admin)
    resp = client.post(
        f"/api/v1/admin/kyc/verifications/{uuid.uuid4()}/review/",
        {"decision": "VERIFIED"},
        format="json",
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND

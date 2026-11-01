import pytest
from datetime import date
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient
from authentication.models import Permission, Role, RolePermission, UserRole
from authentication.services.permission_service import PermissionService
from profiles.models import Gender, Country
from markets.services.eligibility_service import MarketEligibilityService
from kyc.models import KYCVerification, KYCVerificationAttempt
from kyc.tests.helpers import create_test_image_bytes

User = get_user_model()


class _SyncThread:
    """Stand-in for threading.Thread that runs its target immediately, in
    the calling thread. FanKYCSubmitView's Celery-unavailable fallback
    spawns a real background thread (so the HTTP response isn't blocked
    on the pipeline), but a real thread can't see the just-created
    KYCVerificationAttempt row inside pytest-django's per-test transaction
    — so tests asserting the pipeline's outcome need it to run inline.
    """

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


@pytest.mark.django_db
def test_unauthenticated_kyc_submission_rejected():
    client = APIClient()
    response = client.post("/api/v1/fans/kyc/", {})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_fan_kyc_submission_success():
    Country.objects.get_or_create(name="Uganda", iso_code="UG", defaults={"is_active": True})
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
        "profile_country": "UG",
        "legal_name": "Test Fan",
        "identity_number": "CM12345678",
        "date_of_birth": "1990-01-01",
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
    assert "user" in response.data["data"]
    assert response.data["data"]["user"]["email"] == user.email

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
    assert "user" in response.data["data"]
    assert response.data["data"]["user"]["email"] == user.email


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


def _make_fan(username, email):
    """Helper: create an ordinary (non-admin) user."""
    return User.objects.create_user(username=username, email=email, password="Pass123!Password")


def _make_admin(username, email):
    """Helper: create a staff/superuser for admin endpoints."""
    return User.objects.create_superuser(
        username=username, email=email, password="Pass123!Password"
    )


def _seed_pending_verification(fan):
    """Helper: create a KYCVerification in REVIEW state for *fan*."""
    verification, _ = KYCVerification.objects.get_or_create(
        user=fan,
        defaults={"status": KYCVerification.Status.REVIEW},
    )
    verification.status = KYCVerification.Status.REVIEW
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
# 2. Admin approves → user.is_verified becomes True
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_admin_approve_kyc_verifies_user():
    fan = _make_fan("fan_appr2", "fan_appr2@example.com")
    admin = _make_admin("adm_appr2", "adm_appr2@example.com")
    verification = _seed_pending_verification(fan)

    client = APIClient()
    client.force_authenticate(user=admin)
    url = f"/api/v1/admin/kyc/verifications/{verification.id}/review/"
    client.post(url, {"decision": "VERIFIED"}, format="json")

    verification.refresh_from_db()
    assert verification.status == KYCVerification.Status.VERIFIED
    fan.refresh_from_db()
    assert fan.is_verified is True


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
    assert resp.data["data"]["is_verified"] is True


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
# 6. Admin rejects → KYCVerification becomes REJECTED, fan not eligible
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_admin_reject_kyc_blocks_eligibility():
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
    fan.refresh_from_db()
    assert fan.is_verified is False

    fan_client = APIClient()
    fan_client.force_authenticate(user=fan)
    resp = fan_client.get("/api/v1/fans/kyc/status/")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["data"]["status"] == KYCVerification.Status.REJECTED


# ---------------------------------------------------------------------------
# 7. Admin sets REVIEW → KYCVerification stays REVIEW, not yet eligible
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_manual_review_endpoint_rejects_non_decision_value():
    fan = _make_fan("fan_rev1", "fan_rev1@example.com")
    admin = _make_admin("adm_rev1", "adm_rev1@example.com")
    verification = _seed_pending_verification(fan)

    admin_client = APIClient()
    admin_client.force_authenticate(user=admin)
    response = admin_client.post(
        f"/api/v1/admin/kyc/verifications/{verification.id}/review/",
        {"decision": "REVIEW"},
        format="json",
    )

    verification.refresh_from_db()
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert verification.status == KYCVerification.Status.REVIEW

    result = MarketEligibilityService.evaluate(participant=fan)
    assert result.kyc_eligible is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("initial_status", "decision"),
    [
        (KYCVerification.Status.REJECTED, "VERIFIED"),
        (KYCVerification.Status.VERIFIED, "REJECTED"),
        (KYCVerification.Status.RETRY_REQUIRED, "VERIFIED"),
    ],
)
def test_manual_review_rejects_illegal_state_transition(initial_status, decision):
    fan = _make_fan(f"fan_{initial_status.lower()}", f"{initial_status.lower()}@example.com")
    admin = _make_admin(
        f"admin_{initial_status.lower()}", f"admin_{initial_status.lower()}@example.com"
    )
    verification = KYCVerification.objects.create(user=fan, status=initial_status)
    client = APIClient()
    client.force_authenticate(user=admin)

    response = client.post(
        f"/api/v1/admin/kyc/verifications/{verification.id}/review/",
        {"decision": decision, "notes": "Must remain unchanged"},
        format="json",
    )

    assert response.status_code == status.HTTP_409_CONFLICT
    verification.refresh_from_db()
    assert verification.status == initial_status


@pytest.mark.django_db(transaction=True)
def test_retry_only_succeeds_for_retry_required_with_attempts_remaining():
    fan = _make_fan("fan_retry", "fan_retry@example.com")
    verification = KYCVerification.objects.create(
        user=fan, status=KYCVerification.Status.RETRY_REQUIRED
    )
    KYCVerificationAttempt.objects.create(
        kyc_verification=verification,
        attempt_number=1,
        document_type=KYCVerification.DocumentType.PASSPORT,
        document_image=SimpleUploadedFile("doc.jpg", create_test_image_bytes()),
        selfie_image=SimpleUploadedFile("selfie.jpg", create_test_image_bytes()),
    )
    client = APIClient()
    client.force_authenticate(user=fan)

    response = client.post("/api/v1/fans/kyc/retry/")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["data"]["can_retry"] is True


@pytest.mark.django_db(transaction=True)
def test_retry_cap_and_terminal_rejection_are_enforced():
    fan = _make_fan("fan_retry_cap", "fan_retry_cap@example.com")
    verification = KYCVerification.objects.create(
        user=fan, status=KYCVerification.Status.RETRY_REQUIRED
    )
    for number in range(1, 4):
        KYCVerificationAttempt.objects.create(
            kyc_verification=verification,
            attempt_number=number,
            document_type=KYCVerification.DocumentType.PASSPORT,
            document_image=SimpleUploadedFile(f"doc-{number}.jpg", create_test_image_bytes()),
            selfie_image=SimpleUploadedFile(f"selfie-{number}.jpg", create_test_image_bytes()),
        )
    client = APIClient()
    client.force_authenticate(user=fan)

    assert client.post("/api/v1/fans/kyc/retry/").status_code == status.HTTP_400_BAD_REQUEST
    verification.status = KYCVerification.Status.REJECTED
    verification.save(update_fields=["status"])
    response = client.get("/api/v1/fans/kyc/status/")
    assert response.data["data"]["can_retry"] is False
    assert client.post("/api/v1/fans/kyc/retry/").status_code == status.HTTP_400_BAD_REQUEST


def _seed_verified_market_role():
    role = Role.objects.create(name="Verified Market User", display_name="Verified Market User")
    participate = Permission.objects.create(
        code="participate_market",
        name="Participate market",
        resource="market",
        action="participate",
    )
    RolePermission.objects.create(role=role, permission=participate)
    for code in ("manage_market", "approve_market", "verify_results"):
        Permission.objects.create(code=code, name=code, resource="market", action=code)
    return role


@pytest.mark.django_db(transaction=True)
def test_manual_approval_grants_only_verified_market_user_role_idempotently():
    role = _seed_verified_market_role()
    fan = _make_fan("fan_market_role", "fan_market_role@example.com")
    admin = _make_admin("admin_market_role", "admin_market_role@example.com")
    verification = _seed_pending_verification(fan)
    client = APIClient()
    client.force_authenticate(user=admin)

    response = client.post(
        f"/api/v1/admin/kyc/verifications/{verification.id}/review/",
        {"decision": "VERIFIED"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert UserRole.objects.filter(user=fan, role=role, is_active=True).count() == 1
    assert PermissionService.has_permission(fan, "participate_market") is True
    assert PermissionService.has_permission(fan, "manage_market") is False
    assert PermissionService.has_permission(fan, "approve_market") is False
    assert PermissionService.has_permission(fan, "verify_results") is False


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 8. Non-admin cannot call the review endpoint
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
    assert verification.status == KYCVerification.Status.REVIEW


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


@pytest.mark.django_db
def test_kyc_submission_persists_dob_and_gender():
    user = User.objects.create_user(
        username="fan_dob", email="fan_dob@example.com", password="Pass123!Password"
    )
    client = APIClient()
    client.force_authenticate(user=user)

    gender = Gender.objects.create(name="Male", code="M", is_active=True)
    Country.objects.create(name="Uganda", iso_code="UG", is_active=True)

    doc_bytes = create_test_image_bytes(width=800, height=600)
    selfie_bytes = create_test_image_bytes(width=600, height=600)
    doc_file = SimpleUploadedFile("passport.jpg", doc_bytes, content_type="image/jpeg")
    selfie_file = SimpleUploadedFile("selfie.jpg", selfie_bytes, content_type="image/jpeg")

    payload = {
        "document_type": "PASSPORT",
        "document_country": "UGA",
        "profile_country": "UG",
        "legal_name": "Test Fan",
        "identity_number": "CM22345678",
        "document_image": doc_file,
        "selfie_image": selfie_file,
        "date_of_birth": "1990-01-01",
        "gender": str(gender.id),
    }

    response = client.post("/api/v1/fans/kyc/", payload, format="multipart")
    assert response.status_code == status.HTTP_202_ACCEPTED

    user.profile.refresh_from_db()
    assert user.profile.date_of_birth == date(1990, 1, 1)
    assert user.profile.gender_id == gender.id


@pytest.mark.django_db
@patch("kyc.views.threading.Thread", _SyncThread)
def test_kyc_submission_creates_verification():
    Country.objects.get_or_create(name="Uganda", iso_code="UG", defaults={"is_active": True})
    user = User.objects.create_user(
        username="fan_market", email="fan_market@example.com", password="Pass123!Password"
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
        "profile_country": "UG",
        "legal_name": "Test Fan",
        "identity_number": "CM32345678",
        "date_of_birth": "1990-01-01",
        "document_image": doc_file,
        "selfie_image": selfie_file,
    }

    response = client.post("/api/v1/fans/kyc/", payload, format="multipart")
    assert response.status_code == status.HTTP_202_ACCEPTED

    verification = KYCVerification.objects.get(user=user)
    assert verification.status in {
        KYCVerification.Status.PENDING,
        KYCVerification.Status.REVIEW,
    }


@pytest.mark.django_db
@patch("kyc.views.threading.Thread", _SyncThread)
def test_kyc_multistep_preserves_earlier_information():
    Country.objects.get_or_create(name="Uganda", iso_code="UG", defaults={"is_active": True})
    user = User.objects.create_user(
        username="fan_multi", email="fan_multi@example.com", password="Pass123!Password"
    )
    client = APIClient()
    client.force_authenticate(user=user)

    gender = Gender.objects.create(name="Female", code="F", is_active=True)

    doc_bytes = create_test_image_bytes(width=800, height=600)
    selfie_bytes = create_test_image_bytes(width=600, height=600)
    doc_file = SimpleUploadedFile("passport.jpg", doc_bytes, content_type="image/jpeg")
    selfie_file = SimpleUploadedFile("selfie.jpg", selfie_bytes, content_type="image/jpeg")

    payload = {
        "document_type": "NATIONAL_ID",
        "document_country": "UGA",
        "profile_country": "UG",
        "legal_name": "Test Fan",
        "identity_number": "CM42345678",
        "document_image": doc_file,
        "selfie_image": selfie_file,
        "date_of_birth": "1992-06-15",
        "gender": str(gender.id),
    }

    response = client.post("/api/v1/fans/kyc/", payload, format="multipart")
    assert response.status_code == status.HTTP_202_ACCEPTED

    verification = KYCVerification.objects.get(user=user)
    assert verification.document_type == "NATIONAL_ID"

    user.profile.refresh_from_db()
    assert user.profile.date_of_birth == date(1992, 6, 15)
    assert user.profile.gender_id == gender.id

    verification.refresh_from_db()
    assert verification.status in {
        KYCVerification.Status.PENDING,
        KYCVerification.Status.REVIEW,
    }


@pytest.mark.django_db
def test_kyc_admin_review_verifies_user():
    user = User.objects.create_user(
        username="fan_admin", email="fan_admin@example.com", password="Pass123!Password"
    )
    admin_user = User.objects.create_superuser(
        username="admin_sync", email="admin_sync@example.com", password="Pass123!Password"
    )
    client = APIClient()

    verification = KYCVerification.objects.create(user=user, status=KYCVerification.Status.REVIEW)
    doc_bytes = create_test_image_bytes(width=800, height=600)
    selfie_bytes = create_test_image_bytes(width=600, height=600)
    KYCVerificationAttempt.objects.create(
        kyc_verification=verification,
        attempt_number=1,
        document_type=KYCVerification.DocumentType.PASSPORT,
        document_image=SimpleUploadedFile("doc.jpg", doc_bytes),
        selfie_image=SimpleUploadedFile("selfie.jpg", selfie_bytes),
    )

    client.force_authenticate(user=admin_user)
    response = client.post(
        f"/api/v1/admin/kyc/verifications/{verification.id}/review/",
        {"decision": "VERIFIED", "notes": "All good"},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK

    user.refresh_from_db()
    assert user.is_verified is True


@pytest.mark.django_db
def test_kyc_decision_service_verifies_user():
    from kyc.services.decision_service import KYCDecisionService

    user = User.objects.create_user(
        username="fan_decision", email="fan_decision@example.com", password="Pass123!Password"
    )
    verification = KYCVerification.objects.create(user=user)
    doc_bytes = create_test_image_bytes(width=800, height=600)
    selfie_bytes = create_test_image_bytes(width=600, height=600)
    attempt = KYCVerificationAttempt.objects.create(
        kyc_verification=verification,
        attempt_number=1,
        document_type=KYCVerification.DocumentType.PASSPORT,
        document_image=SimpleUploadedFile("doc.jpg", doc_bytes),
        selfie_image=SimpleUploadedFile("selfie.jpg", selfie_bytes),
    )

    KYCDecisionService.make_decision(
        attempt, KYCVerification.Status.VERIFIED, "automated_checks_passed"
    )

    user.refresh_from_db()
    assert user.is_verified is True

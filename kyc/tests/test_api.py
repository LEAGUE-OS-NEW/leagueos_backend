import pytest
from datetime import date
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient
from profiles.models import Gender, Country
from markets.models import MarketParticipantCompliance
from markets.services.eligibility_service import MarketEligibilityService
from kyc.models import KYCVerification, KYCVerificationAttempt
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


@pytest.mark.django_db
def test_kyc_submission_persists_dob_and_gender():
    user = User.objects.create_user(
        username="fan_dob", email="fan_dob@example.com", password="Pass123!Password"
    )
    client = APIClient()
    client.force_authenticate(user=user)

    gender = Gender.objects.create(name="Male", code="M", is_active=True)
    country = Country.objects.create(name="Uganda", iso_code="UG", is_active=True)

    doc_bytes = create_test_image_bytes(width=800, height=600)
    selfie_bytes = create_test_image_bytes(width=600, height=600)
    doc_file = SimpleUploadedFile("passport.jpg", doc_bytes, content_type="image/jpeg")
    selfie_file = SimpleUploadedFile("selfie.jpg", selfie_bytes, content_type="image/jpeg")

    payload = {
        "document_type": "PASSPORT",
        "document_country": "UGA",
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
def test_kyc_submission_creates_compliance_record():
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
        "document_image": doc_file,
        "selfie_image": selfie_file,
    }

    response = client.post("/api/v1/fans/kyc/", payload, format="multipart")
    assert response.status_code == status.HTTP_202_ACCEPTED

    compliance = MarketParticipantCompliance.objects.filter(participant=user).first()
    assert compliance is not None


@pytest.mark.django_db
def test_kyc_multistep_preserves_earlier_information():
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

    compliance = MarketParticipantCompliance.objects.filter(participant=user).first()
    assert compliance is not None


@pytest.mark.django_db
def test_kyc_admin_review_verifies_user():
    user = User.objects.create_user(
        username="fan_admin", email="fan_admin@example.com", password="Pass123!Password"
    )
    admin_user = User.objects.create_superuser(
        username="admin_sync", email="admin_sync@example.com", password="Pass123!Password"
    )
    client = APIClient()

    verification = KYCVerification.objects.create(user=user)
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

    KYCDecisionService.make_decision(attempt, KYCVerification.Status.VERIFIED, "automated_checks_passed")

    user.refresh_from_db()
    assert user.is_verified is True

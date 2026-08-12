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

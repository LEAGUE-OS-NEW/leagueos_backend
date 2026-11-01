"""Compatibility and private evidence checks for the deployed KYC clients."""

from datetime import date
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from authentication.tests.factories import UserFactory
from kyc.models import KYCVerification, KYCVerificationAttempt
from kyc.tests.helpers import create_test_image_bytes
from markets.services.eligibility_service import MarketEligibilityService
from profiles.models import Country, Profile


def upload(name):
    return SimpleUploadedFile(name, create_test_image_bytes(), content_type="image/jpeg")


@pytest.mark.django_db
@pytest.mark.parametrize("has_birth_date", [False, True])
def test_existing_four_field_client_can_upload_without_new_metadata(has_birth_date):
    fan = UserFactory()
    country, _ = Country.objects.get_or_create(name="Uganda", iso_code="UG")
    Profile.objects.update_or_create(
        user=fan,
        defaults={
            "country": country,
            "date_of_birth": date(1990, 1, 1) if has_birth_date else None,
        },
    )
    client = APIClient()
    client.force_authenticate(fan)
    with patch("kyc.views.process_kyc_attempt.delay"):
        response = client.post(
            "/api/v1/fans/kyc/",
            {
                "document_type": "NATIONAL_ID",
                "document_country": "UGA",
                "document_image": upload("document.jpg"),
                "selfie_image": upload("selfie.jpg"),
            },
            format="multipart",
        )
    assert response.status_code == 202
    verification = KYCVerification.objects.get(user=fan)
    assert verification.attempts.count() == 1
    assert verification.status == "PENDING"
    fan.profile.refresh_from_db()
    assert bool(fan.profile.date_of_birth) is has_birth_date
    assert MarketEligibilityService.evaluate(participant=fan).eligible is False


@pytest.mark.django_db
def test_private_evidence_requires_admin_and_is_not_cacheable():
    fan = UserFactory()
    admin = UserFactory(is_superuser=True, is_staff=True)
    verification = KYCVerification.objects.create(user=fan, status="REVIEW")
    KYCVerificationAttempt.objects.create(
        kyc_verification=verification,
        attempt_number=1,
        document_type="NATIONAL_ID",
        document_country="UGA",
        document_image=upload("document.jpg"),
        selfie_image=upload("selfie.jpg"),
    )
    client = APIClient()
    detail = f"/api/v1/admin/kyc/verifications/{verification.pk}/"
    client.force_authenticate(admin)
    signed = client.get(detail + "document-url/").data["data"]
    params = {"target": "document", "token": signed["token"]}
    client.force_authenticate(fan)
    assert client.get(detail + "document/", params).status_code == 403
    client.force_authenticate(admin)
    response = client.get(detail + "document/", params)
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert response["Content-Type"] == "image/jpeg"
    response.close()
    assert client.get(detail + "document/", {**params, "token": "invalid"}).status_code == 400
    assert client.get(detail + "document/", {**params, "target": "selfie"}).status_code == 403

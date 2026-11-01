"""Regression tests for observed submission, worker and identity-check failures."""

import json
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from authentication.tests.factories import UserFactory
from kyc.document_validation.national_id import NationalIDValidator
from kyc.models import KYCConfiguration, KYCVerification, KYCVerificationAttempt
from kyc.services.decision_service import KYCDecisionService
from kyc.services.duplicate_service import DuplicateService
from kyc.services.face_service import FaceService
from kyc.services.ocr_service import OCRService
from kyc.tasks import _mark_kyc_failed
from kyc.tests.helpers import create_test_image_bytes
from profiles.models import Country


def upload(name):
    return SimpleUploadedFile(name, create_test_image_bytes(), content_type="image/jpeg")


def make_attempt(verification, number=1):
    return KYCVerificationAttempt.objects.create(
        kyc_verification=verification,
        attempt_number=number,
        document_type="NATIONAL_ID",
        document_country="UGA",
        document_image=upload("document.jpg"),
        selfie_image=upload("selfie.jpg"),
    )


def submit(client):
    Country.objects.get_or_create(name="Uganda", iso_code="UG")
    return client.post(
        "/api/v1/fans/kyc/",
        {
            "document_type": "NATIONAL_ID",
            "document_country": "UGA",
            "profile_country": "UG",
            "legal_name": "Audit Fan",
            "identity_number": "AB12CD34EF5678",
            "date_of_birth": "1990-01-01",
            "document_image": upload("document.jpg"),
            "selfie_image": upload("selfie.jpg"),
        },
        format="multipart",
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "old_status", ["PENDING", "PROCESSING", "REVIEW", "REJECTED", "VERIFIED", "EXPIRED"]
)
def test_submission_cannot_replace_queued_reviewed_or_final_case(old_status):
    fan = UserFactory(first_name="Audit", last_name="Fan")
    verification = KYCVerification.objects.create(user=fan, status=old_status)
    make_attempt(verification)
    client = APIClient()
    client.force_authenticate(fan)
    with patch("kyc.views.process_kyc_attempt.delay") as queue:
        response = submit(client)
    assert response.status_code == 400
    verification.refresh_from_db()
    assert verification.status == old_status
    assert verification.attempts.count() == 1
    queue.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize("old_status", [None, "NOT_STARTED", "RETRY_REQUIRED"])
def test_submission_uses_same_fingerprint_as_ocr_when_ocr_cannot_read_id(old_status):
    fingerprint = DuplicateService.generate_document_hash("NATIONAL_ID", "UGA", "ab12-cd34 ef5678")
    KYCVerification.objects.create(
        user=UserFactory(), status="VERIFIED", document_number_hash=fingerprint
    )
    fan = UserFactory(first_name="Audit", last_name="Fan")
    if old_status:
        KYCVerification.objects.create(user=fan, status=old_status)
    client = APIClient()
    client.force_authenticate(fan)
    with patch("kyc.views.process_kyc_attempt.delay"):
        response = submit(client)
    assert response.status_code == 202
    verification = KYCVerification.objects.get(user=fan)
    assert verification.document_number_hash == fingerprint
    result = DuplicateService.check_for_duplicates(verification.attempts.get())
    assert result["is_unique"] is False


@pytest.mark.parametrize("number", ["AB12CD34EF5678", "ab12cd34ef5678"])
def test_uganda_nin_accepts_fourteen_alphanumeric_characters(number):
    fields = NationalIDValidator("UGA").parse_fields(f"NIN: {number}")
    assert fields["document_number"] == number.upper()


@pytest.mark.parametrize("number", ["CM1234567890123", "AB12CD34EF567", "NATIONALNUMBER"])
def test_uganda_nin_rejects_wrong_length_or_words(number):
    assert NationalIDValidator("UGA").parse_fields(f"NIN: {number}")["document_number"] is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "final_status", ["VERIFIED", "REJECTED", "REVIEW", "RETRY_REQUIRED", "EXPIRED"]
)
def test_late_worker_decision_preserves_current_parent_decision(final_status):
    verification = KYCVerification.objects.create(user=UserFactory(), status="PROCESSING")
    attempt = make_attempt(verification)
    KYCVerification.objects.filter(pk=verification.pk).update(status=final_status)
    decision = KYCDecisionService.make_decision(attempt, "REVIEW", "automated_checks_passed")
    assert decision.status == final_status
    verification.refresh_from_db()
    assert verification.status == final_status


@pytest.mark.django_db
def test_old_attempt_cannot_finish_or_fail_a_newer_attempt():
    verification = KYCVerification.objects.create(user=UserFactory(), status="PROCESSING")
    old_attempt = make_attempt(verification)
    make_attempt(verification, number=2)
    KYCDecisionService.make_decision(old_attempt, "REVIEW", "automated_checks_passed")
    _mark_kyc_failed(str(old_attempt.pk))
    verification.refresh_from_db()
    assert verification.status == "PROCESSING"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "error, reason",
    [
        (subprocess.TimeoutExpired("face-worker", 1), "face_match_timeout"),
        (subprocess.CalledProcessError(1, "face-worker"), "face_match_unavailable"),
        (ValueError("invalid JSON"), "face_match_unavailable"),
    ],
)
def test_unavailable_face_engine_never_reports_a_match(settings, error, reason):
    settings.KYC_FACE_MATCH_TIMEOUT_SECONDS = 7
    verification = KYCVerification.objects.create(
        user=UserFactory(is_verified=False), status="PROCESSING"
    )
    attempt = make_attempt(verification)
    with patch("kyc.services.face_service.subprocess.run", side_effect=error) as run:
        result = FaceService.compare_faces(attempt)
    assert run.call_args.kwargs["timeout"] == 7
    assert run.call_args.kwargs["check"] is True
    assert result == {"passed": False, "status": "UNCERTAIN", "reason": reason}
    check = attempt.checks.get(check_type="FACE_MATCH")
    assert check.status == "UNCERTAIN"
    assert check.score is None
    assert check.result_code == reason
    decision = KYCDecisionService.run_decision_engine(attempt)
    assert decision.status == "REVIEW"
    verification.user.refresh_from_db()
    assert verification.user.is_verified is False


@pytest.mark.django_db
@pytest.mark.parametrize("verified, expected", [(True, "PASSED"), (False, "FAILED")])
def test_face_match_uses_real_engine_evidence_and_keeps_human_approval(verified, expected):
    verification = KYCVerification.objects.create(user=UserFactory(), status="PROCESSING")
    attempt = make_attempt(verification)
    result = SimpleNamespace(stdout=json.dumps({"distance": 0.05, "verified": verified}).encode())
    with patch("kyc.services.face_service.subprocess.run", return_value=result):
        assert FaceService.compare_faces(attempt)["status"] == expected
    assert KYCDecisionService.run_decision_engine(attempt).status == "REVIEW"


@pytest.mark.django_db
@pytest.mark.parametrize("hang", [False, True])
def test_isolated_face_process_returns_evidence_or_stops_at_deadline(
    settings, tmp_path, monkeypatch, hang
):
    # Exercise the real process boundary without downloading biometric models.
    # A fake engine checks that detection stays enabled and can simulate a hang.
    (tmp_path / "numpy.py").write_text("def array(value):\n    return value\n")
    (tmp_path / "deepface.py").write_text(
        "import time\n"
        "class DeepFace:\n"
        "    @staticmethod\n"
        "    def verify(**kwargs):\n"
        "        assert kwargs['enforce_detection'] is True\n"
        "        assert kwargs['img1_path'].size == (800, 600)\n"
        "        assert kwargs['img2_path'].size == (800, 600)\n"
        f"        time.sleep({60 if hang else 0})\n"
        "        return {'distance': 0.05, 'verified': True}\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    settings.KYC_FACE_MATCH_TIMEOUT_SECONDS = 1 if hang else 10
    verification = KYCVerification.objects.create(
        user=UserFactory(is_verified=False), status="PROCESSING"
    )
    attempt = make_attempt(verification)
    started = time.monotonic()
    result = FaceService.compare_faces(attempt)
    assert time.monotonic() - started < 10
    assert result["status"] == ("UNCERTAIN" if hang else "PASSED")
    if hang:
        assert result["reason"] == "face_match_timeout"


@pytest.mark.django_db
def test_ocr_cannot_overwrite_admin_decision_while_processing(settings):
    settings.KYC_OCR_TIMEOUT_SECONDS = 3
    verification = KYCVerification.objects.create(user=UserFactory(), status="PROCESSING")
    attempt = make_attempt(verification)

    def finish_ocr(*args, **kwargs):
        assert kwargs["timeout"] == 3
        KYCVerification.objects.filter(pk=verification.pk).update(status="VERIFIED")
        return "NIN: AB12CD34EF5678"

    with patch("pytesseract.image_to_string", side_effect=finish_ocr):
        OCRService.process_document(attempt)
    verification.refresh_from_db()
    assert verification.status == "VERIFIED"
    assert verification.ocr_status == "PASSED"


@pytest.mark.django_db
def test_last_attempt_server_failure_reaches_review_instead_of_unusable_retry():
    config = KYCConfiguration.load()
    verification = KYCVerification.objects.create(user=UserFactory(), status="PROCESSING")
    attempt = make_attempt(verification, number=config.max_attempts)
    _mark_kyc_failed(str(attempt.pk))
    verification.refresh_from_db()
    assert verification.status == "REVIEW"
    assert verification.rejection_reason == "processing_failed_after_max_retries"
    assert verification.retry_reason == ""

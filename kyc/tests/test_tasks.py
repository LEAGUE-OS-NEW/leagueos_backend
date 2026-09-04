from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from kyc.models import KYCVerification, KYCVerificationAttempt
from kyc.tasks import (
    PROCESSING_FAILURE_REASON,
    _handle_kyc_task_failure,
    _mark_kyc_failed,
    process_kyc_attempt,
)
from kyc.tests.helpers import create_test_image_bytes

User = get_user_model()


def _create_attempt(*, verification_status, attempt_status):
    sequence = User.objects.count()

    user = User.objects.create_user(
        username=f"task-{sequence}",
        email=f"task-{sequence}@example.com",
        password="Pass123!Password",
    )

    verification = KYCVerification.objects.create(
        user=user,
        status=verification_status,
    )

    img_bytes = create_test_image_bytes()

    attempt = KYCVerificationAttempt.objects.create(
        kyc_verification=verification,
        attempt_number=1,
        status=attempt_status,
        document_type=KYCVerification.DocumentType.PASSPORT,
        document_image=SimpleUploadedFile(
            "doc.jpg",
            img_bytes,
        ),
        selfie_image=SimpleUploadedFile(
            "selfie.jpg",
            img_bytes,
        ),
    )

    return verification, attempt


@pytest.mark.django_db
def test_task_does_not_downgrade_verified_parent():
    verification, attempt = _create_attempt(
        verification_status=KYCVerification.Status.VERIFIED,
        attempt_status=KYCVerificationAttempt.Status.PROCESSING,
    )

    with patch("kyc.tasks.DocumentService.analyze_document_quality") as quality_check:
        process_kyc_attempt.apply(args=[str(attempt.id)])

    verification.refresh_from_db()
    attempt.refresh_from_db()

    assert verification.status == KYCVerification.Status.VERIFIED

    assert attempt.status == KYCVerificationAttempt.Status.PROCESSING

    quality_check.assert_not_called()


@pytest.mark.django_db
def test_mark_kyc_failed_makes_processing_failure_retryable():
    verification, attempt = _create_attempt(
        verification_status=KYCVerification.Status.PROCESSING,
        attempt_status=KYCVerificationAttempt.Status.PROCESSING,
    )

    _mark_kyc_failed(str(attempt.id))

    verification.refresh_from_db()
    attempt.refresh_from_db()

    assert attempt.status == KYCVerificationAttempt.Status.FAILED

    assert attempt.failure_reason == PROCESSING_FAILURE_REASON

    assert attempt.retry_reason == PROCESSING_FAILURE_REASON

    assert attempt.completed_at is not None

    assert verification.status == KYCVerification.Status.RETRY_REQUIRED

    assert verification.retry_reason == PROCESSING_FAILURE_REASON

    assert verification.rejection_reason == ""
    assert verification.verification_completed_at is not None


@pytest.mark.django_db
def test_mark_kyc_failed_preserves_verified_parent():
    verification, attempt = _create_attempt(
        verification_status=KYCVerification.Status.VERIFIED,
        attempt_status=KYCVerificationAttempt.Status.PROCESSING,
    )

    _mark_kyc_failed(str(attempt.id))

    verification.refresh_from_db()
    attempt.refresh_from_db()

    assert verification.status == KYCVerification.Status.VERIFIED

    assert attempt.status == KYCVerificationAttempt.Status.PROCESSING


def test_failure_hook_extracts_attempt_id_from_celery_args():
    attempt_id = "11111111-1111-1111-1111-111111111111"

    with patch("kyc.tasks._mark_kyc_failed") as mark_failed:
        _handle_kyc_task_failure(
            None,
            RuntimeError("boom"),
            "celery-task-id",
            (attempt_id,),
            {},
            None,
        )

    mark_failed.assert_called_once_with(attempt_id)

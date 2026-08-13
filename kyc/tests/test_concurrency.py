import pytest
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from kyc.models import KYCVerification, KYCVerificationAttempt
from kyc.tasks import process_kyc_attempt
from kyc.tests.helpers import create_test_image_bytes

User = get_user_model()


@pytest.mark.django_db
def test_task_idempotency_and_duplicate_job_execution():
    user = User.objects.create_user(
        username="concuser", email="conc@example.com", password="Pass123!Password"
    )
    verification = KYCVerification.objects.create(user=user, status=KYCVerification.Status.PENDING)
    img_bytes = create_test_image_bytes()

    attempt = KYCVerificationAttempt.objects.create(
        kyc_verification=verification,
        attempt_number=1,
        status=KYCVerificationAttempt.Status.PENDING,
        document_type=KYCVerification.DocumentType.PASSPORT,
        document_image=SimpleUploadedFile("doc.jpg", img_bytes),
        selfie_image=SimpleUploadedFile("selfie.jpg", img_bytes),
    )

    with (
        patch(
            "kyc.services.ocr_service.OCRService.process_document",
            return_value={
                "raw_text": "PASSPORT\nNAME: TEST",
                "extracted": {"full_name": "TEST USER", "document_number": "A12345678"},
                "ocr_status": "PASSED",
                "expiry_status": "PASSED",
            },
        ),
        patch(
            "kyc.services.document_service.DocumentService.analyze_document_quality",
            return_value={"passed": True, "score": 0.9, "check": None},
        ),
        patch(
            "kyc.services.document_service.DocumentService.analyze_tampering",
            return_value={"passed": True},
        ),
        patch(
            "kyc.services.barcode_service.BarcodeService.process_barcode",
            return_value={"found": False, "status": "NOT_APPLICABLE"},
        ),
        patch(
            "kyc.services.face_service.FaceService.validate_selfie",
            return_value={"passed": True, "face_count": 1, "quality": 0.9},
        ),
        patch(
            "kyc.services.face_service.FaceService.compare_faces",
            return_value={"passed": True, "status": "PASSED", "similarity": 0.95},
        ),
        patch(
            "kyc.services.face_service.FaceService.check_liveness",
            return_value={"passed": True, "status": "PASSED", "score": 0.9},
        ),
        patch(
            "kyc.services.duplicate_service.DuplicateService.check_for_duplicates",
            return_value={"is_unique": True, "status": "PASSED"},
        ),
        patch(
            "kyc.services.risk_engine.KYCRiskEngine.evaluate_risk",
            return_value={"score": 0.1, "level": "LOW", "signals": []},
        ),
    ):
        # First task run
        process_kyc_attempt.apply(args=[str(attempt.id)])
        attempt.refresh_from_db()
        assert attempt.status == KYCVerificationAttempt.Status.COMPLETED

        # Second task run on same completed attempt
        process_kyc_attempt.apply(args=[str(attempt.id)])
        attempt.refresh_from_db()
        assert attempt.status == KYCVerificationAttempt.Status.COMPLETED
        assert verification.attempts.count() == 1

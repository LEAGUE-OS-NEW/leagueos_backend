import pytest
from datetime import date
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from kyc.models import KYCVerification, KYCVerificationAttempt, KYCCheckResult
from kyc.services.duplicate_service import DuplicateService
from kyc.services.risk_engine import KYCRiskEngine
from kyc.services.decision_service import KYCDecisionService
from kyc.services.ocr_service import OCRService
from kyc.tests.helpers import create_test_image_bytes

User = get_user_model()


@pytest.mark.django_db
def test_duplicate_service_hash_and_detection():
    user1 = User.objects.create_user(
        username="dupuser1", email="dupuser1@example.com", password="Pass123!Password"
    )
    user2 = User.objects.create_user(
        username="dupuser2", email="dupuser2@example.com", password="Pass123!Password"
    )

    hash1 = DuplicateService.generate_document_hash("PASSPORT", "UGA", "A12345678")
    hash2 = DuplicateService.generate_document_hash("PASSPORT", "UGA", "a12345678")
    assert hash1 == hash2

    KYCVerification.objects.create(
        user=user1,
        status=KYCVerification.Status.VERIFIED,
        document_number_hash=hash1,
    )

    kyc2 = KYCVerification.objects.create(user=user2, status=KYCVerification.Status.PENDING)
    img_bytes = create_test_image_bytes()
    attempt2 = KYCVerificationAttempt.objects.create(
        kyc_verification=kyc2,
        attempt_number=1,
        document_type=KYCVerification.DocumentType.PASSPORT,
        document_image=SimpleUploadedFile("doc.jpg", img_bytes),
        selfie_image=SimpleUploadedFile("selfie.jpg", img_bytes),
    )

    res = DuplicateService.check_for_duplicates(attempt2, extracted_doc_number="A12345678")
    assert res["is_unique"] is False
    assert res["status"] == KYCCheckResult.Status.FAILED


@pytest.mark.django_db
def test_risk_engine_and_decision_service():
    user = User.objects.create_user(
        username="riskuser", email="riskuser@example.com", password="Pass123!Password"
    )
    verification = KYCVerification.objects.create(user=user)
    img_bytes = create_test_image_bytes()
    attempt = KYCVerificationAttempt.objects.create(
        kyc_verification=verification,
        attempt_number=1,
        document_type=KYCVerification.DocumentType.PASSPORT,
        document_image=SimpleUploadedFile("doc.jpg", img_bytes),
        selfie_image=SimpleUploadedFile("selfie.jpg", img_bytes),
    )

    # Add passing checks
    KYCCheckResult.objects.create(
        kyc_verification=verification,
        kyc_attempt=attempt,
        check_type=KYCCheckResult.CheckType.IMAGE_QUALITY,
        status=KYCCheckResult.Status.PASSED,
    )
    KYCCheckResult.objects.create(
        kyc_verification=verification,
        kyc_attempt=attempt,
        check_type=KYCCheckResult.CheckType.FACE_DETECTION,
        status=KYCCheckResult.Status.PASSED,
    )
    KYCCheckResult.objects.create(
        kyc_verification=verification,
        kyc_attempt=attempt,
        check_type=KYCCheckResult.CheckType.FACE_MATCH,
        status=KYCCheckResult.Status.PASSED,
        score=0.92,
    )

    eval_res = KYCRiskEngine.evaluate_risk(attempt)
    assert eval_res["level"] == KYCVerification.RiskLevel.LOW

    decision = KYCDecisionService.run_decision_engine(attempt)
    assert decision.status == KYCVerification.Status.VERIFIED
    assert user.is_verified is True


@pytest.mark.django_db
def test_ocr_service_stores_extracted_date_of_birth_as_date():
    user = User.objects.create_user(
        username="ocr_date_user", email="ocr_date_user@example.com", password="Pass123!Password"
    )
    verification = KYCVerification.objects.create(user=user)
    img_bytes = create_test_image_bytes()
    attempt = KYCVerificationAttempt.objects.create(
        kyc_verification=verification,
        attempt_number=1,
        document_type=KYCVerification.DocumentType.PASSPORT,
        document_image=SimpleUploadedFile("doc.jpg", img_bytes),
        selfie_image=SimpleUploadedFile("selfie.jpg", img_bytes),
    )

    fake_extracted = {
        "full_name": "Test User",
        "date_of_birth": "1990-01-01",
        "nationality": "UGA",
        "document_number": "A12345678",
        "expiry_date": "2030-01-01",
        "mrz_result": {
            "valid": True,
            "status": KYCCheckResult.Status.PASSED,
        },
    }

    from unittest.mock import patch

    with patch(
        "kyc.services.ocr_service.get_document_validator"
    ) as mock_validator:
        validator_instance = mock_validator.return_value
        validator_instance.validate_structure.return_value = {}
        validator_instance.parse_fields.return_value = fake_extracted
        validator_instance.validate_expiry.return_value = {
            "status": KYCCheckResult.Status.PASSED,
            "expiry_date": None,
            "is_expired": False,
        }
        OCRService.process_document(attempt)

    verification.refresh_from_db()
    assert verification.extracted_date_of_birth == date(1990, 1, 1)

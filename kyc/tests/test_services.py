import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from kyc.models import KYCVerification, KYCVerificationAttempt, KYCCheckResult
from kyc.services.duplicate_service import DuplicateService
from kyc.services.risk_engine import KYCRiskEngine
from kyc.services.decision_service import KYCDecisionService
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

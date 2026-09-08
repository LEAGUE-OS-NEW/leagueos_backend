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
from authentication.models import Permission, Role, RolePermission, UserRole
from authentication.services.permission_service import PermissionService

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

    with patch("kyc.services.ocr_service.get_document_validator") as mock_validator:
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


@pytest.mark.django_db
def test_auto_verify_high_risk_passing_checks():
    user = User.objects.create_user(
        username="highrisk_user", email="highrisk@example.com", password="Pass123!Password"
    )
    verification = KYCVerification.objects.create(
        user=user, risk_level=KYCVerification.RiskLevel.HIGH, risk_score=0.55
    )
    img_bytes = create_test_image_bytes()
    attempt = KYCVerificationAttempt.objects.create(
        kyc_verification=verification,
        attempt_number=1,
        document_type=KYCVerification.DocumentType.PASSPORT,
        document_image=SimpleUploadedFile("doc.jpg", img_bytes),
        selfie_image=SimpleUploadedFile("selfie.jpg", img_bytes),
    )

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
        score=0.88,
    )

    decision = KYCDecisionService.run_decision_engine(attempt)
    assert decision.status == KYCVerification.Status.REVIEW
    assert user.is_verified is False


@pytest.mark.django_db
def test_uncertain_face_match_requires_review():
    user = User.objects.create_user(
        username="uncertain_user", email="uncertain@example.com", password="Pass123!Password"
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
        status=KYCCheckResult.Status.UNCERTAIN,
        score=0.60,
    )

    decision = KYCDecisionService.run_decision_engine(attempt)
    assert decision.status == KYCVerification.Status.REVIEW
    assert user.is_verified is False


@pytest.mark.django_db
def test_incomplete_checks_fallback_to_review():
    user = User.objects.create_user(
        username="fallback_user", email="fallback@example.com", password="Pass123!Password"
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

    decision = KYCDecisionService.run_decision_engine(attempt)
    assert decision.status == KYCVerification.Status.REVIEW
    assert user.is_verified is False


@pytest.mark.django_db
def test_recoverable_quality_failure_requires_retry_before_attempt_cap():
    user = User.objects.create_user(
        username="quality_retry", email="quality_retry@example.com", password="Pass123!Password"
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
    KYCCheckResult.objects.create(
        kyc_verification=verification,
        kyc_attempt=attempt,
        check_type=KYCCheckResult.CheckType.IMAGE_QUALITY,
        status=KYCCheckResult.Status.FAILED,
    )

    decision = KYCDecisionService.run_decision_engine(attempt)

    assert decision.status == KYCVerification.Status.RETRY_REQUIRED
    assert decision.retry_reason == "poor_image_quality"


@pytest.mark.django_db
def test_automated_verification_grants_participant_role_idempotently_without_admin_access():
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
    user = User.objects.create_user(
        username="automated_role", email="automated_role@example.com", password="Pass123!Password"
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

    KYCDecisionService.make_decision(
        attempt, KYCVerification.Status.VERIFIED, "automated_checks_passed"
    )
    KYCDecisionService.make_decision(
        attempt, KYCVerification.Status.VERIFIED, "automated_checks_passed"
    )

    assert UserRole.objects.filter(user=user, role=role, is_active=True).count() == 1
    assert PermissionService.has_permission(user, "participate_market") is True
    assert PermissionService.has_permission(user, "manage_market") is False
    assert PermissionService.has_permission(user, "approve_market") is False
    assert PermissionService.has_permission(user, "verify_results") is False

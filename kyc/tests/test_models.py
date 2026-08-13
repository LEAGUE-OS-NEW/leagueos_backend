import pytest
from django.db import IntegrityError
from django.contrib.auth import get_user_model
from kyc.models import KYCVerification, KYCVerificationAttempt, KYCCheckResult, KYCConfiguration

User = get_user_model()


@pytest.mark.django_db
def test_kyc_verification_creation_and_defaults():
    user = User.objects.create_user(
        username="kycuser1", email="kycuser1@example.com", password="Pass123!Password"
    )
    verification = KYCVerification.objects.create(user=user)

    assert verification.status == KYCVerification.Status.NOT_STARTED
    assert verification.risk_level == KYCVerification.RiskLevel.LOW
    assert verification.document_country == "UGA"
    assert verification.user == user


@pytest.mark.django_db
def test_kyc_verification_attempt_unique_constraint():
    user = User.objects.create_user(
        username="kycuser2", email="kycuser2@example.com", password="Pass123!Password"
    )
    verification = KYCVerification.objects.create(user=user)

    attempt1 = KYCVerificationAttempt.objects.create(
        kyc_verification=verification,
        attempt_number=1,
        document_type=KYCVerification.DocumentType.PASSPORT,
    )
    assert attempt1.attempt_number == 1

    with pytest.raises(IntegrityError):
        KYCVerificationAttempt.objects.create(
            kyc_verification=verification,
            attempt_number=1,
            document_type=KYCVerification.DocumentType.PASSPORT,
        )


@pytest.mark.django_db
def test_kyc_check_results_relationship():
    user = User.objects.create_user(
        username="kycuser3", email="kycuser3@example.com", password="Pass123!Password"
    )
    verification = KYCVerification.objects.create(user=user)
    attempt = KYCVerificationAttempt.objects.create(
        kyc_verification=verification,
        attempt_number=1,
        document_type=KYCVerification.DocumentType.NATIONAL_ID,
    )

    check = KYCCheckResult.objects.create(
        kyc_verification=verification,
        kyc_attempt=attempt,
        check_type=KYCCheckResult.CheckType.IMAGE_QUALITY,
        status=KYCCheckResult.Status.PASSED,
        score=0.95,
    )

    assert check in verification.checks.all()
    assert check in attempt.checks.all()


@pytest.mark.django_db
def test_kyc_configuration_singleton():
    config1 = KYCConfiguration.load()
    assert config1.max_attempts == 3

    config1.max_attempts = 5
    config1.save()

    config2 = KYCConfiguration.load()
    assert config2.max_attempts == 5

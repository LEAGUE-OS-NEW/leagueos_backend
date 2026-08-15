import uuid

from django.conf import settings
from django.db import models

from config.storage_backends import get_private_storage


def kyc_private_document_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"kyc_private/documents/{instance.kyc_verification.user_id}/{uuid.uuid4().hex}.{ext}"


def kyc_private_selfie_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"kyc_private/selfies/{instance.kyc_verification.user_id}/{uuid.uuid4().hex}.{ext}"


class KYCVerification(models.Model):
    """Primary KYC verification record linked to a User."""

    class Status(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", "Not Started"
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        VERIFIED = "VERIFIED", "Verified"
        RETRY_REQUIRED = "RETRY_REQUIRED", "Retry Required"
        REJECTED = "REJECTED", "Rejected"
        REVIEW = "REVIEW", "Review"
        EXPIRED = "EXPIRED", "Expired"

    class DocumentType(models.TextChoices):
        PASSPORT = "PASSPORT", "Passport"
        NATIONAL_ID = "NATIONAL_ID", "National ID"
        DRIVING_LICENCE = "DRIVING_LICENCE", "Driving Licence"

    class CheckStatus(models.TextChoices):
        NOT_RUN = "NOT_RUN", "Not Run"
        PROCESSING = "PROCESSING", "Processing"
        PASSED = "PASSED", "Passed"
        FAILED = "FAILED", "Failed"
        UNCERTAIN = "UNCERTAIN", "Uncertain"
        NOT_APPLICABLE = "NOT_APPLICABLE", "Not Applicable"

    class RiskLevel(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    class VerificationSource(models.TextChoices):
        PROVIDER = "PROVIDER", "Provider"
        MANUAL = "MANUAL", "Manual"
        DEVELOPMENT_BYPASS = "DEVELOPMENT_BYPASS", "Development bypass"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="kyc_verification",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NOT_STARTED,
        db_index=True,
    )
    verification_source = models.CharField(
        max_length=24,
        choices=VerificationSource.choices,
        default=VerificationSource.PROVIDER,
        db_index=True,
    )
    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        blank=True,
        default="",
    )
    document_country = models.CharField(max_length=3, default="UGA", db_index=True)
    document_number_hash = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
    )
    document_number_last4 = models.CharField(max_length=4, blank=True, default="")
    document_expiry_date = models.DateField(null=True, blank=True)

    extracted_full_name = models.CharField(max_length=255, blank=True, default="")
    extracted_date_of_birth = models.DateField(null=True, blank=True)
    extracted_nationality = models.CharField(max_length=3, blank=True, default="")

    document_authenticity_status = models.CharField(
        max_length=20,
        choices=CheckStatus.choices,
        default=CheckStatus.NOT_RUN,
    )
    document_quality_status = models.CharField(
        max_length=20,
        choices=CheckStatus.choices,
        default=CheckStatus.NOT_RUN,
    )
    ocr_status = models.CharField(
        max_length=20,
        choices=CheckStatus.choices,
        default=CheckStatus.NOT_RUN,
    )
    mrz_status = models.CharField(
        max_length=20,
        choices=CheckStatus.choices,
        default=CheckStatus.NOT_RUN,
    )
    barcode_status = models.CharField(
        max_length=20,
        choices=CheckStatus.choices,
        default=CheckStatus.NOT_RUN,
    )
    face_detection_status = models.CharField(
        max_length=20,
        choices=CheckStatus.choices,
        default=CheckStatus.NOT_RUN,
    )
    face_match_status = models.CharField(
        max_length=20,
        choices=CheckStatus.choices,
        default=CheckStatus.NOT_RUN,
    )
    liveness_status = models.CharField(
        max_length=20,
        choices=CheckStatus.choices,
        default=CheckStatus.NOT_RUN,
    )
    duplicate_check_status = models.CharField(
        max_length=20,
        choices=CheckStatus.choices,
        default=CheckStatus.NOT_RUN,
    )

    risk_level = models.CharField(
        max_length=20,
        choices=RiskLevel.choices,
        default=RiskLevel.LOW,
        db_index=True,
    )
    risk_score = models.FloatField(default=0.0)
    rejection_reason = models.CharField(max_length=100, blank=True, default="")
    retry_reason = models.CharField(max_length=100, blank=True, default="")
    auto_verified = models.BooleanField(default=False)

    verification_started_at = models.DateTimeField(null=True, blank=True)
    verification_completed_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["document_number_hash"]),
            models.Index(fields=["risk_level"]),
        ]

    def __str__(self) -> str:
        return f"KYC for User {self.user_id} - {self.status}"


class KYCVerificationAttempt(models.Model):
    """Tracks each individual KYC verification attempt."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kyc_verification = models.ForeignKey(
        KYCVerification,
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    attempt_number = models.IntegerField(default=1)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    document_type = models.CharField(
        max_length=30,
        choices=KYCVerification.DocumentType.choices,
    )
    document_country = models.CharField(max_length=3, default="UGA")
    document_image = models.FileField(
        upload_to=kyc_private_document_path,
        storage=get_private_storage,
    )
    selfie_image = models.FileField(
        upload_to=kyc_private_selfie_path,
        storage=get_private_storage,
    )

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=100, blank=True, default="")
    retry_reason = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-attempt_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["kyc_verification", "attempt_number"],
                name="unique_kyc_verification_attempt_number",
            )
        ]

    def __str__(self) -> str:
        return f"Attempt #{self.attempt_number} for KYC {self.kyc_verification_id}"


class KYCCheckResult(models.Model):
    """Granular results for individual verification checks executed during an attempt."""

    class CheckType(models.TextChoices):
        DOCUMENT_TYPE = "DOCUMENT_TYPE", "Document Type"
        IMAGE_QUALITY = "IMAGE_QUALITY", "Image Quality"
        OCR = "OCR", "OCR Extraction"
        DOCUMENT_STRUCTURE = "DOCUMENT_STRUCTURE", "Document Structure"
        DOCUMENT_EXPIRY = "DOCUMENT_EXPIRY", "Document Expiry"
        MRZ = "MRZ", "Machine Readable Zone"
        BARCODE = "BARCODE", "Barcode Reading"
        QR = "QR", "QR Code Reading"
        DOCUMENT_MANIPULATION = "DOCUMENT_MANIPULATION", "Document Tampering Analysis"
        FACE_DETECTION = "FACE_DETECTION", "Face Detection"
        FACE_MATCH = "FACE_MATCH", "Face Match Comparison"
        LIVENESS = "LIVENESS", "Selfie Anti-Spoof Liveness"
        DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY", "Duplicate Identity Detection"
        DATA_CONSISTENCY = "DATA_CONSISTENCY", "Identity Data Consistency"
        RISK_ASSESSMENT = "RISK_ASSESSMENT", "Risk Assessment"

    class Status(models.TextChoices):
        NOT_RUN = "NOT_RUN", "Not Run"
        PROCESSING = "PROCESSING", "Processing"
        PASSED = "PASSED", "Passed"
        FAILED = "FAILED", "Failed"
        UNCERTAIN = "UNCERTAIN", "Uncertain"
        NOT_APPLICABLE = "NOT_APPLICABLE", "Not Applicable"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kyc_verification = models.ForeignKey(
        KYCVerification,
        on_delete=models.CASCADE,
        related_name="checks",
    )
    kyc_attempt = models.ForeignKey(
        KYCVerificationAttempt,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="checks",
    )
    check_type = models.CharField(max_length=35, choices=CheckType.choices, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NOT_RUN,
        db_index=True,
    )
    score = models.FloatField(null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    result_code = models.CharField(max_length=64, blank=True, default="")
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Check {self.check_type} ({self.status}) for KYC {self.kyc_verification_id}"


class KYCConfiguration(models.Model):
    """System-wide configuration settings for KYC thresholds and policies."""

    max_attempts = models.PositiveIntegerField(default=3)
    max_document_size_mb = models.PositiveIntegerField(default=10)
    face_match_pass_threshold = models.FloatField(default=0.70)
    face_match_review_threshold = models.FloatField(default=0.50)
    risk_review_threshold = models.FloatField(default=0.40)
    risk_reject_threshold = models.FloatField(default=0.75)
    document_retention_days = models.PositiveIntegerField(default=30)
    selfie_retention_days = models.PositiveIntegerField(default=30)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"KYCConfiguration (max_attempts={self.max_attempts})"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

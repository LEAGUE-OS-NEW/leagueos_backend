import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.db.models.manager
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="KYCVerification",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("NOT_STARTED", "Not Started"),
                            ("PENDING", "Pending"),
                            ("PROCESSING", "Processing"),
                            ("VERIFIED", "Verified"),
                            ("RETRY_REQUIRED", "Retry Required"),
                            ("REJECTED", "Rejected"),
                            ("REVIEW", "Review"),
                            ("EXPIRED", "Expired"),
                        ],
                        db_index=True,
                        default="NOT_STARTED",
                        max_length=20,
                    ),
                ),
                (
                    "document_type",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("PASSPORT", "Passport"),
                            ("NATIONAL_ID", "National ID"),
                            ("DRIVING_LICENCE", "Driving Licence"),
                        ],
                        max_length=30,
                        null=True,
                    ),
                ),
                ("document_country", models.CharField(default="UGA", db_index=True, max_length=3)),
                (
                    "document_number_hash",
                    models.CharField(blank=True, db_index=True, max_length=64, null=True),
                ),
                ("document_number_last4", models.CharField(blank=True, max_length=4, null=True)),
                ("document_expiry_date", models.DateField(blank=True, null=True)),
                ("extracted_full_name", models.CharField(blank=True, max_length=255, null=True)),
                ("extracted_date_of_birth", models.DateField(blank=True, null=True)),
                ("extracted_nationality", models.CharField(blank=True, max_length=3, null=True)),
                (
                    "document_authenticity_status",
                    models.CharField(
                        choices=[
                            ("NOT_RUN", "Not Run"),
                            ("PROCESSING", "Processing"),
                            ("PASSED", "Passed"),
                            ("FAILED", "Failed"),
                            ("UNCERTAIN", "Uncertain"),
                            ("NOT_APPLICABLE", "Not Applicable"),
                        ],
                        default="NOT_RUN",
                        max_length=20,
                    ),
                ),
                (
                    "document_quality_status",
                    models.CharField(
                        choices=[
                            ("NOT_RUN", "Not Run"),
                            ("PROCESSING", "Processing"),
                            ("PASSED", "Passed"),
                            ("FAILED", "Failed"),
                            ("UNCERTAIN", "Uncertain"),
                            ("NOT_APPLICABLE", "Not Applicable"),
                        ],
                        default="NOT_RUN",
                        max_length=20,
                    ),
                ),
                (
                    "ocr_status",
                    models.CharField(
                        choices=[
                            ("NOT_RUN", "Not Run"),
                            ("PROCESSING", "Processing"),
                            ("PASSED", "Passed"),
                            ("FAILED", "Failed"),
                            ("UNCERTAIN", "Uncertain"),
                            ("NOT_APPLICABLE", "Not Applicable"),
                        ],
                        default="NOT_RUN",
                        max_length=20,
                    ),
                ),
                (
                    "mrz_status",
                    models.CharField(
                        choices=[
                            ("NOT_RUN", "Not Run"),
                            ("PROCESSING", "Processing"),
                            ("PASSED", "Passed"),
                            ("FAILED", "Failed"),
                            ("UNCERTAIN", "Uncertain"),
                            ("NOT_APPLICABLE", "Not Applicable"),
                        ],
                        default="NOT_RUN",
                        max_length=20,
                    ),
                ),
                (
                    "barcode_status",
                    models.CharField(
                        choices=[
                            ("NOT_RUN", "Not Run"),
                            ("PROCESSING", "Processing"),
                            ("PASSED", "Passed"),
                            ("FAILED", "Failed"),
                            ("UNCERTAIN", "Uncertain"),
                            ("NOT_APPLICABLE", "Not Applicable"),
                        ],
                        default="NOT_RUN",
                        max_length=20,
                    ),
                ),
                (
                    "face_detection_status",
                    models.CharField(
                        choices=[
                            ("NOT_RUN", "Not Run"),
                            ("PROCESSING", "Processing"),
                            ("PASSED", "Passed"),
                            ("FAILED", "Failed"),
                            ("UNCERTAIN", "Uncertain"),
                            ("NOT_APPLICABLE", "Not Applicable"),
                        ],
                        default="NOT_RUN",
                        max_length=20,
                    ),
                ),
                (
                    "face_match_status",
                    models.CharField(
                        choices=[
                            ("NOT_RUN", "Not Run"),
                            ("PROCESSING", "Processing"),
                            ("PASSED", "Passed"),
                            ("FAILED", "Failed"),
                            ("UNCERTAIN", "Uncertain"),
                            ("NOT_APPLICABLE", "Not Applicable"),
                        ],
                        default="NOT_RUN",
                        max_length=20,
                    ),
                ),
                (
                    "liveness_status",
                    models.CharField(
                        choices=[
                            ("NOT_RUN", "Not Run"),
                            ("PROCESSING", "Processing"),
                            ("PASSED", "Passed"),
                            ("FAILED", "Failed"),
                            ("UNCERTAIN", "Uncertain"),
                            ("NOT_APPLICABLE", "Not Applicable"),
                        ],
                        default="NOT_RUN",
                        max_length=20,
                    ),
                ),
                (
                    "duplicate_check_status",
                    models.CharField(
                        choices=[
                            ("NOT_RUN", "Not Run"),
                            ("PROCESSING", "Processing"),
                            ("PASSED", "Passed"),
                            ("FAILED", "Failed"),
                            ("UNCERTAIN", "Uncertain"),
                            ("NOT_APPLICABLE", "Not Applicable"),
                        ],
                        default="NOT_RUN",
                        max_length=20,
                    ),
                ),
                (
                    "risk_level",
                    models.CharField(
                        choices=[
                            ("LOW", "Low"),
                            ("MEDIUM", "Medium"),
                            ("HIGH", "High"),
                            ("CRITICAL", "Critical"),
                        ],
                        db_index=True,
                        default="LOW",
                        max_length=20,
                    ),
                ),
                ("risk_score", models.FloatField(default=0.0)),
                ("rejection_reason", models.CharField(blank=True, max_length=100, null=True)),
                ("retry_reason", models.CharField(blank=True, max_length=100, null=True)),
                ("verification_started_at", models.DateTimeField(blank=True, null=True)),
                ("verification_completed_at", models.DateTimeField(blank=True, null=True)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="kyc_verification",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
                "indexes": [
                    models.Index(fields=["status"], name="kyc_kycverif_status_idx"),
                    models.Index(fields=["document_number_hash"], name="kyc_kycverif_docnum_idx"),
                    models.Index(fields=["risk_level"], name="kyc_kycverif_risk_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="KYCVerificationAttempt",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("attempt_number", models.IntegerField(default=1)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("PROCESSING", "Processing"),
                            ("COMPLETED", "Completed"),
                            ("FAILED", "Failed"),
                            ("CANCELLED", "Cancelled"),
                        ],
                        db_index=True,
                        default="PENDING",
                        max_length=20,
                    ),
                ),
                (
                    "document_type",
                    models.CharField(
                        choices=[
                            ("PASSPORT", "Passport"),
                            ("NATIONAL_ID", "National ID"),
                            ("DRIVING_LICENCE", "Driving Licence"),
                        ],
                        max_length=30,
                    ),
                ),
                ("document_country", models.CharField(default="UGA", max_length=3)),
                (
                    "document_image",
                    models.FileField(
                        upload_to="kyc_private/documents/%(kyc_verification)s/%(uuid)s"
                    ),
                ),
                (
                    "selfie_image",
                    models.FileField(upload_to="kyc_private/selfies/%(kyc_verification)s/%(uuid)s"),
                ),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("failure_reason", models.CharField(blank=True, max_length=100, null=True)),
                ("retry_reason", models.CharField(blank=True, max_length=100, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "kyc_verification",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attempts",
                        to="kyc.kycverification",
                    ),
                ),
            ],
            options={
                "ordering": ["-attempt_number"],
            },
            managers=[
                ("objects", django.db.models.manager.Manager()),
            ],
        ),
        migrations.CreateModel(
            name="KYCCheckResult",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                (
                    "check_type",
                    models.CharField(
                        choices=[
                            ("DOCUMENT_TYPE", "Document Type"),
                            ("IMAGE_QUALITY", "Image Quality"),
                            ("OCR", "OCR Extraction"),
                            ("DOCUMENT_STRUCTURE", "Document Structure"),
                            ("DOCUMENT_EXPIRY", "Document Expiry"),
                            ("MRZ", "Machine Readable Zone"),
                            ("BARCODE", "Barcode Reading"),
                            ("QR", "QR Code Reading"),
                            ("DOCUMENT_MANIPULATION", "Document Tampering Analysis"),
                            ("FACE_DETECTION", "Face Detection"),
                            ("FACE_MATCH", "Face Match Comparison"),
                            ("LIVENESS", "Selfie Anti-Spoof Liveness"),
                            ("DUPLICATE_IDENTITY", "Duplicate Identity Detection"),
                            ("DATA_CONSISTENCY", "Identity Data Consistency"),
                            ("RISK_ASSESSMENT", "Risk Assessment"),
                        ],
                        db_index=True,
                        max_length=35,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("NOT_RUN", "Not Run"),
                            ("PROCESSING", "Processing"),
                            ("PASSED", "Passed"),
                            ("FAILED", "Failed"),
                            ("UNCERTAIN", "Uncertain"),
                            ("NOT_APPLICABLE", "Not Applicable"),
                        ],
                        db_index=True,
                        default="NOT_RUN",
                        max_length=20,
                    ),
                ),
                ("score", models.FloatField(blank=True, null=True)),
                ("confidence", models.FloatField(blank=True, null=True)),
                ("result_code", models.CharField(blank=True, max_length=64, null=True)),
                ("details", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "kyc_attempt",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="checks",
                        to="kyc.kycverificationattempt",
                    ),
                ),
                (
                    "kyc_verification",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="checks",
                        to="kyc.kycverification",
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
            },
        ),
        migrations.CreateModel(
            name="KYCConfiguration",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("max_attempts", models.PositiveIntegerField(default=3)),
                ("max_document_size_mb", models.PositiveIntegerField(default=10)),
                ("face_match_pass_threshold", models.FloatField(default=0.7)),
                ("face_match_review_threshold", models.FloatField(default=0.5)),
                ("risk_review_threshold", models.FloatField(default=0.4)),
                ("risk_reject_threshold", models.FloatField(default=0.75)),
                ("document_retention_days", models.PositiveIntegerField(default=30)),
                ("selfie_retention_days", models.PositiveIntegerField(default=30)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name="kycverificationattempt",
            constraint=models.UniqueConstraint(
                fields=["kyc_verification", "attempt_number"],
                name="unique_kyc_verification_attempt_number",
            ),
        ),
    ]

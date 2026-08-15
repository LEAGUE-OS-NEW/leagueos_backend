import logging
from uuid import UUID

try:
    from celery import shared_task
    from celery.exceptions import MaxRetriesExceededError
except ImportError:
    MaxRetriesExceededError = Exception

    def shared_task(*args, **kwargs):
        bind = kwargs.get("bind", False)

        def decorator(func):
            def bound_func(self, *a, **kw):
                return func(self, *a, **kw)

            def unbound_func(*a, **kw):
                return func(*a, **kw)

            def delay_func(*a, **kw):
                if bind:
                    return func(None, *a, **kw)
                return func(*a, **kw)

            def apply(args=(), kwargs=None, **kw):
                if kwargs is None:
                    kwargs = {}
                if bind:
                    return func(None, *args, **{**kwargs, **kw})
                return func(*args, **{**kwargs, **kw})

            wrapped = bound_func if bind else unbound_func
            wrapped.delay = delay_func
            wrapped.apply = apply
            return wrapped

        if len(args) == 1 and callable(args[0]):
            return decorator(args[0])
        return decorator


from django.db import transaction
from django.db.utils import OperationalError
from django.utils import timezone

from kyc.models import KYCVerificationAttempt, KYCVerification
from kyc.services.barcode_service import BarcodeService
from kyc.services.decision_service import KYCDecisionService
from kyc.services.document_service import DocumentService
from kyc.services.duplicate_service import DuplicateService
from kyc.services.face_service import FaceService
from kyc.services.ocr_service import OCRService
from kyc.services.risk_engine import KYCRiskEngine

logger = logging.getLogger(__name__)


def _mark_kyc_failed(attempt_id_str: str) -> None:
    """Mark an attempt and its parent verification as FAILED after unrecoverable errors."""
    try:
        attempt_id = UUID(attempt_id_str) if isinstance(attempt_id_str, str) else attempt_id_str
        attempt = KYCVerificationAttempt.objects.select_related("kyc_verification").get(
            id=attempt_id
        )
        verification = attempt.kyc_verification

        now = timezone.now()
        if attempt.status not in (
            KYCVerificationAttempt.Status.COMPLETED,
            KYCVerificationAttempt.Status.FAILED,
            KYCVerificationAttempt.Status.CANCELLED,
        ):
            attempt.status = KYCVerificationAttempt.Status.FAILED
            attempt.failure_reason = "processing_failed_after_max_retries"
            attempt.completed_at = now
            attempt.save(update_fields=["status", "failure_reason", "completed_at", "updated_at"])

        if verification.status not in (
            KYCVerification.Status.VERIFIED,
            KYCVerification.Status.REJECTED,
            KYCVerification.Status.EXPIRED,
        ):
            verification.status = KYCVerification.Status.REJECTED
            verification.rejection_reason = "Automated processing failed. Please contact support."
            verification.verification_completed_at = now
            verification.save(
                update_fields=[
                    "status",
                    "rejection_reason",
                    "verification_completed_at",
                    "updated_at",
                ]
            )

        logger.error(
            "Marked KYC attempt %s and verification %s as FAILED after unrecoverable error.",
            attempt_id,
            verification.id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to mark KYC attempt %s as failed: %s", attempt_id_str, exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, on_failure=_mark_kyc_failed)
def process_kyc_attempt(self, attempt_id_str: str):
    """Asynchronous pipeline task orchestrating all internal automated KYC checks."""
    try:
        attempt_id = UUID(attempt_id_str) if isinstance(attempt_id_str, str) else attempt_id_str

        with transaction.atomic():
            attempt = (
                KYCVerificationAttempt.objects.select_for_update()
                .select_related("kyc_verification", "kyc_verification__user")
                .get(id=attempt_id)
            )

            if attempt.status == KYCVerificationAttempt.Status.COMPLETED:
                logger.info(
                    "Skipping KYC attempt %s: already COMPLETED.",
                    attempt_id,
                )
                return

            if attempt.status == KYCVerificationAttempt.Status.FAILED:
                logger.info(
                    "Skipping KYC attempt %s: already FAILED.",
                    attempt_id,
                )
                return

            if attempt.status == KYCVerificationAttempt.Status.CANCELLED:
                logger.info(
                    "Skipping KYC attempt %s: already CANCELLED.",
                    attempt_id,
                )
                return

            attempt.status = KYCVerificationAttempt.Status.PROCESSING
            attempt.started_at = timezone.now()
            attempt.save(update_fields=["status", "started_at"])

            verification = attempt.kyc_verification
            verification.status = KYCVerification.Status.PROCESSING
            verification.verification_started_at = timezone.now()
            verification.save(update_fields=["status", "verification_started_at", "updated_at"])

        logger.info("Started internal automated KYC processing for attempt %s.", attempt_id)

        # 1. Document Image Quality Check
        DocumentService.analyze_document_quality(attempt)

        # 2. Document Manipulation / Tampering Analysis
        DocumentService.analyze_tampering(attempt)

        # 3. OCR, MRZ, Expiry & Field Extraction
        ocr_res = OCRService.process_document(attempt)

        # 4. Barcode / QR Scanning
        BarcodeService.process_barcode(attempt)

        # 5. Live Selfie Validation & Face Detection
        FaceService.validate_selfie(attempt)

        # 6. Face Comparison (ID Photo vs Live Selfie)
        FaceService.compare_faces(attempt)

        # 7. Liveness / Presentation Attack Check
        FaceService.check_liveness(attempt)

        # 8. Duplicate Identity Detection
        extracted_num = ocr_res.get("extracted", {}).get("document_number")
        DuplicateService.check_for_duplicates(attempt, extracted_doc_number=extracted_num)

        # 9. Risk Engine Assessment
        KYCRiskEngine.evaluate_risk(attempt)

        # 10. Automated Decision Engine
        KYCDecisionService.run_decision_engine(attempt)

        logger.info("Finished processing KYC attempt %s.", attempt_id)

    except KYCVerificationAttempt.DoesNotExist:
        logger.error("KYCVerificationAttempt with ID %s not found.", attempt_id_str)
    except OperationalError:
        logger.warning("KYC attempt %s row is locked. Retrying Celery task.", attempt_id_str)
        raise self.retry(countdown=5) from None
    except MaxRetriesExceededError:
        logger.error("KYC attempt %s failed after maximum retries.", attempt_id_str)
        _mark_kyc_failed(attempt_id_str)
    except Exception as exc:
        logger.exception("Error processing KYC attempt %s: %s", attempt_id_str, exc)
        raise self.retry(exc=exc) from None

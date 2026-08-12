import logging
from uuid import UUID

try:
    from celery import shared_task
except ImportError:
    # Fallback decorator when Celery package is not present in runtime environment
    def shared_task(*args, **kwargs):
        bind = kwargs.get("bind", False)

        def decorator(func):
            def delay_func(*a, **kw):
                if bind:
                    return func(None, *a, **kw)
                return func(*a, **kw)

            func.delay = delay_func
            return func

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


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_kyc_attempt(self, attempt_id_str: str):
    """Asynchronous pipeline task orchestrating all internal automated KYC checks."""
    try:
        attempt_id = UUID(attempt_id_str) if isinstance(attempt_id_str, str) else attempt_id_str

        with transaction.atomic():
            attempt = (
                KYCVerificationAttempt.objects.select_for_update(nowait=True)
                .select_related("kyc_verification", "kyc_verification__user")
                .get(id=attempt_id)
            )

            if attempt.status != KYCVerificationAttempt.Status.PENDING:
                logger.warning(
                    "Skipping KYC attempt %s processing: status is '%s', not 'PENDING'.",
                    attempt_id,
                    attempt.status,
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
    except Exception as exc:
        logger.exception("Error processing KYC attempt %s: %s", attempt_id_str, exc)
        raise self.retry(exc=exc) from None

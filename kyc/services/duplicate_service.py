import hashlib
import logging
import re
from typing import TYPE_CHECKING, Any

from kyc.models import KYCCheckResult, KYCVerification

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from kyc.models import KYCVerificationAttempt


class DuplicateService:
    """Service detecting duplicate identity usage across multiple fan accounts."""

    @classmethod
    def generate_document_hash(
        cls, document_type: str, country: str, raw_document_number: str
    ) -> str:
        """Generates a secure SHA-256 fingerprint hash for a document number."""
        if not raw_document_number:
            return ""
        norm_type = (document_type or "").upper().strip()
        norm_country = (country or "UGA").upper().strip()
        norm_number = re.sub(r"[^A-Z0-9]", "", raw_document_number.upper().strip())

        payload = f"{norm_type}:{norm_country}:{norm_number}".encode()
        return hashlib.sha256(payload).hexdigest()

    @classmethod
    def check_for_duplicates(
        cls, attempt: "KYCVerificationAttempt", extracted_doc_number: str | None = None
    ) -> dict[str, Any]:
        check_result, _ = KYCCheckResult.objects.update_or_create(
            kyc_verification=attempt.kyc_verification,
            kyc_attempt=attempt,
            check_type=KYCCheckResult.CheckType.DUPLICATE_IDENTITY,
            defaults={"status": KYCCheckResult.Status.PROCESSING},
        )

        verification = attempt.kyc_verification
        doc_type = attempt.document_type
        country = attempt.document_country

        if extracted_doc_number:
            doc_hash = cls.generate_document_hash(doc_type, country, extracted_doc_number)
            verification.document_number_hash = doc_hash
            clean_num = re.sub(r"[^A-Z0-9]", "", extracted_doc_number.upper())
            verification.document_number_last4 = (
                clean_num[-4:] if len(clean_num) >= 4 else clean_num
            )
            verification.save(
                update_fields=["document_number_hash", "document_number_last4", "updated_at"]
            )

        current_hash = verification.document_number_hash

        if not current_hash:
            check_result.status = KYCCheckResult.Status.NOT_APPLICABLE
            check_result.result_code = "no_document_number_hash"
            check_result.save()
            verification.duplicate_check_status = KYCCheckResult.Status.NOT_APPLICABLE
            verification.save(update_fields=["duplicate_check_status", "updated_at"])
            return {"is_unique": True, "status": KYCCheckResult.Status.NOT_APPLICABLE}

        # Query existing verified records with matching hash owned by a DIFFERENT user
        duplicate = (
            KYCVerification.objects.filter(
                document_number_hash=current_hash,
                status__in=[KYCVerification.Status.VERIFIED, KYCVerification.Status.REVIEW],
            )
            .exclude(user=verification.user)
            .exists()
        )

        if duplicate:
            logger.warning(
                "Duplicate identity detected for user %s matching existing hash.",
                verification.user_id,
            )
            check_result.status = KYCCheckResult.Status.FAILED
            check_result.result_code = "duplicate_identity_detected"
            check_result.details = {"duplicate_flagged": True}
            check_result.save()

            verification.duplicate_check_status = KYCCheckResult.Status.FAILED
            verification.save(update_fields=["duplicate_check_status", "updated_at"])

            return {"is_unique": False, "status": KYCCheckResult.Status.FAILED}
        else:
            check_result.status = KYCCheckResult.Status.PASSED
            check_result.result_code = "identity_unique"
            check_result.details = {"duplicate_flagged": False}
            check_result.save()

            verification.duplicate_check_status = KYCCheckResult.Status.PASSED
            verification.save(update_fields=["duplicate_check_status", "updated_at"])

            return {"is_unique": True, "status": KYCCheckResult.Status.PASSED}

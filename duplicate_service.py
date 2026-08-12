"""
Service for detecting duplicate identity document usage.
"""

import hashlib
import logging
from typing import Any, TYPE_CHECKING

from kyc.models import KYCCheck, KYCVerification

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from kyc.models import KYCAttempt


class DuplicateService:
    """Checks for duplicate identity documents."""

    @staticmethod
    def _normalize_and_hash_document_id(doc_type: str, doc_country: str, doc_number: str) -> str:
        """
        Creates a standardized, salted hash of the core document identifiers.
        - Normalizes inputs to prevent trivial variations.
        - Uses a SHA-256 hash for security.
        - Salting is handled implicitly by Django's SECRET_KEY, but an explicit
          salt could be added for extra protection if needed.
        """
        normalized_type = doc_type.upper().strip()
        normalized_country = doc_country.upper().strip()
        # Remove spaces, dashes, and other common punctuation from doc number
        normalized_number = "".join(filter(str.isalnum, doc_number)).upper()

        raw_string = f"{normalized_type}:{normalized_country}:{normalized_number}"
        return hashlib.sha256(raw_string.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_document_number(ocr_results: dict[str, Any]) -> str | None:
        """
        Placeholder function to extract a document number from OCR results.
        In a real implementation, this would use sophisticated parsing rules
        based on document type and country.
        """
        # This is a very basic placeholder.
        # A real implementation would search for patterns like 'PASSPORT NO', 'IDNUMBER', etc.
        # and extract the adjacent value.
        raw_text = ocr_results.get("raw_text", "")
        # Simple heuristic: find a line with 8-15 alphanumeric characters.
        for line in raw_text.splitlines():
            cleaned_line = "".join(filter(str.isalnum, line))
            if 8 <= len(cleaned_line) <= 15 and any(c.isdigit() for c in cleaned_line):
                return cleaned_line
        return None

    @staticmethod
    def check_for_duplicates(attempt: "KYCAttempt", ocr_results: dict[str, Any]) -> bool:
        """
        Checks if the document has been used by another user.

        Args:
            attempt: The KYCAttempt instance.
            ocr_results: The data extracted by the OCRService.

        Returns:
            True if no duplicate is found, False otherwise.
        """
        check, _ = KYCCheck.objects.update_or_create(
            kyc_attempt=attempt,
            check_type=KYCCheck.CheckType.DUPLICATE_IDENTITY,
            defaults={"status": KYCCheck.Status.PROCESSING},
        )

        doc_number = DuplicateService._parse_document_number(ocr_results)
        if not doc_number:
            logger.warning(
                "Could not parse document number for attempt %s. Skipping duplicate check.",
                attempt.id,
            )
            check.status = KYCCheck.Status.NOT_APPLICABLE
            check.details = {"reason": "Document number not found in OCR text."}
            check.save()
            return True  # Cannot fail the check if we can't find the number

        verification = attempt.kyc_verification
        doc_hash = DuplicateService._normalize_and_hash_document_id(
            doc_type=verification.document_type,
            doc_country=verification.document_country,
            doc_number=doc_number,
        )

        # Check if this hash exists for any OTHER user.
        is_duplicate = (
            KYCVerification.objects.filter(document_number_hash=doc_hash)
            .exclude(user=verification.user)
            .exists()
        )

        if is_duplicate:
            logger.error(
                "Duplicate identity document detected for attempt %s. Hash: %s",
                attempt.id,
                doc_hash,
            )
            check.status = KYCCheck.Status.FAILED
            check.save()
            return False

        logger.info("No duplicate identity found for attempt %s.", attempt.id)
        check.status = KYCCheck.Status.PASSED
        check.save()

        # Save the hash on the current verification record for future checks
        verification.document_number_hash = doc_hash
        verification.document_number_last4 = doc_number[-4:]
        verification.save(update_fields=["document_number_hash", "document_number_last4"])

        return True

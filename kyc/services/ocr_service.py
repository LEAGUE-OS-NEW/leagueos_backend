import io
import logging
import re
from datetime import date
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageEnhance, ImageFilter

from kyc.document_validation import get_document_validator
from kyc.models import KYCCheckResult

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from kyc.models import KYCVerificationAttempt


class OCRService:
    """Service performing Optical Character Recognition (OCR) and document field extraction."""

    @classmethod
    def _preprocess_image(cls, raw_bytes: bytes) -> Image.Image:
        """Applies grayscale, contrast enhancement, and sharpness filters for OCR accuracy."""
        img = Image.open(io.BytesIO(raw_bytes)).convert("L")
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.8)
        img = img.filter(ImageFilter.SHARPEN)
        return img

    @classmethod
    def process_document(cls, attempt: "KYCVerificationAttempt") -> dict[str, Any]:
        """Runs OCR extraction, parses structured fields, validates MRZ & document expiry."""
        ocr_check, _ = KYCCheckResult.objects.update_or_create(
            kyc_verification=attempt.kyc_verification,
            kyc_attempt=attempt,
            check_type=KYCCheckResult.CheckType.OCR,
            defaults={"status": KYCCheckResult.Status.PROCESSING},
        )

        verification = attempt.kyc_verification
        doc_type = attempt.document_type
        country = attempt.document_country

        validator = get_document_validator(doc_type, country)

        try:
            with attempt.document_image.open("rb") as f:
                raw_bytes = f.read()

            processed_img = cls._preprocess_image(raw_bytes)

            raw_text = ""
            try:
                import pytesseract

                custom_config = r"--oem 3 --psm 6"
                raw_text = pytesseract.image_to_string(processed_img, config=custom_config)
            except Exception as tess_err:
                logger.warning("Tesseract execution error on attempt %s: %s", attempt.id, tess_err)
                # Fallback to standard pytesseract call
                try:
                    import pytesseract

                    raw_text = pytesseract.image_to_string(processed_img)
                except Exception:
                    raw_text = ""

            # Structural layout analysis
            with Image.open(io.BytesIO(raw_bytes)) as orig:
                meta = {"width": orig.width, "height": orig.height}
            struct_result = validator.validate_structure(meta, raw_text)

            # Parsed field extraction
            extracted = validator.parse_fields(raw_text)

            ocr_success = bool(raw_text and not raw_text.isspace())

            ocr_check.status = (
                KYCCheckResult.Status.PASSED if ocr_success else KYCCheckResult.Status.FAILED
            )
            ocr_check.score = 0.9 if ocr_success else 0.0
            ocr_check.confidence = 0.85
            ocr_check.result_code = "ocr_passed" if ocr_success else "ocr_no_text"
            ocr_check.details = {
                "raw_text_length": len(raw_text),
                "extracted_fields": {
                    k: v for k, v in extracted.items() if k != "mrz_result" and v is not None
                },
                "structure_check": struct_result,
            }
            ocr_check.save()

            verification.ocr_status = ocr_check.status

            # Handle MRZ check result if passport
            if doc_type == "PASSPORT" and "mrz_result" in extracted:
                mrz_info = extracted["mrz_result"]
                mrz_check, _ = KYCCheckResult.objects.update_or_create(
                    kyc_verification=verification,
                    kyc_attempt=attempt,
                    check_type=KYCCheckResult.CheckType.MRZ,
                    defaults={"status": mrz_info.get("status", KYCCheckResult.Status.NOT_RUN)},
                )
                mrz_check.status = mrz_info.get("status", KYCCheckResult.Status.FAILED)
                mrz_check.result_code = "mrz_valid" if mrz_info.get("valid") else "mrz_invalid"
                mrz_check.details = mrz_info
                mrz_check.save()
                verification.mrz_status = mrz_check.status
            else:
                verification.mrz_status = KYCCheckResult.Status.NOT_APPLICABLE

            # Update verification extracted fields
            if extracted.get("full_name"):
                verification.extracted_full_name = extracted["full_name"]
            if extracted.get("date_of_birth"):
                dob_match = re.search(r"(\d{4})[/-](\d{2})[/-](\d{2})", extracted["date_of_birth"])
                if dob_match:
                    verification.extracted_date_of_birth = date(
                        int(dob_match.group(1)),
                        int(dob_match.group(2)),
                        int(dob_match.group(3)),
                    )
            if extracted.get("nationality"):
                verification.extracted_nationality = extracted["nationality"][:3].upper()

            # Handle document expiry check
            expiry_str = extracted.get("expiry_date")
            expiry_check_res = validator.validate_expiry(expiry_str)
            exp_check, _ = KYCCheckResult.objects.update_or_create(
                kyc_verification=verification,
                kyc_attempt=attempt,
                check_type=KYCCheckResult.CheckType.DOCUMENT_EXPIRY,
                defaults={"status": expiry_check_res["status"]},
            )
            exp_check.status = expiry_check_res["status"]
            exp_check.result_code = (
                "document_expired" if expiry_check_res.get("is_expired") else "document_valid"
            )
            exp_check.details = expiry_check_res
            exp_check.save()

            if expiry_check_res.get("expiry_date"):
                try:
                    verification.document_expiry_date = expiry_check_res["expiry_date"]
                except Exception:
                    pass

            verification.save()

            return {
                "raw_text": raw_text,
                "extracted": extracted,
                "ocr_status": ocr_check.status,
                "expiry_status": exp_check.status,
            }

        except Exception as e:
            logger.error("OCR Service failed for attempt %s: %s", attempt.id, e)
            ocr_check.status = KYCCheckResult.Status.FAILED
            ocr_check.result_code = "ocr_error"
            ocr_check.details = {"error": str(e)}
            ocr_check.save()
            verification.ocr_status = KYCCheckResult.Status.FAILED
            verification.save(update_fields=["ocr_status", "updated_at"])
            return {"raw_text": "", "extracted": {}, "ocr_status": KYCCheckResult.Status.FAILED}

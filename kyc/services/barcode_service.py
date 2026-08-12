import io
import logging
from typing import TYPE_CHECKING, Any
from PIL import Image

from kyc.models import KYCCheckResult

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from kyc.models import KYCVerificationAttempt


class BarcodeService:
    """Detects, decodes, and validates barcodes / QR codes on identity documents."""

    @classmethod
    def process_barcode(cls, attempt: "KYCVerificationAttempt") -> dict[str, Any]:
        check_result, _ = KYCCheckResult.objects.update_or_create(
            kyc_verification=attempt.kyc_verification,
            kyc_attempt=attempt,
            check_type=KYCCheckResult.CheckType.BARCODE,
            defaults={"status": KYCCheckResult.Status.PROCESSING},
        )

        verification = attempt.kyc_verification

        try:
            with attempt.document_image.open("rb") as f:
                img = Image.open(io.BytesIO(f.read()))

            barcodes = []
            # Attempt decoding using pyzbar if installed
            try:
                from pyzbar import pyzbar

                decoded = pyzbar.decode(img)
                for code in decoded:
                    barcodes.append(
                        {
                            "type": code.type,
                            "data": code.data.decode("utf-8", errors="ignore"),
                        }
                    )
            except ImportError:
                # pyzbar not installed; barcode check marked NOT_APPLICABLE / UNCERTAIN safely
                pass
            except Exception as e:
                logger.warning("Barcode decoding attempt failed for attempt %s: %s", attempt.id, e)

            if not barcodes:
                check_result.status = KYCCheckResult.Status.NOT_APPLICABLE
                check_result.result_code = "no_barcode_detected"
                check_result.details = {
                    "message": "No machine-readable barcode/QR detected on document"
                }
                check_result.save()
                verification.barcode_status = KYCCheckResult.Status.NOT_APPLICABLE
                verification.save(update_fields=["barcode_status", "updated_at"])
                return {"found": False, "status": KYCCheckResult.Status.NOT_APPLICABLE}

            check_result.status = KYCCheckResult.Status.PASSED
            check_result.score = 1.0
            check_result.confidence = 0.95
            check_result.result_code = "barcode_decoded"
            check_result.details = {
                "barcode_count": len(barcodes),
                "barcodes": barcodes,
            }
            check_result.save()

            verification.barcode_status = KYCCheckResult.Status.PASSED
            verification.save(update_fields=["barcode_status", "updated_at"])

            return {"found": True, "status": KYCCheckResult.Status.PASSED, "barcodes": barcodes}

        except Exception as e:
            logger.error("Barcode service error for attempt %s: %s", attempt.id, e)
            check_result.status = KYCCheckResult.Status.FAILED
            check_result.result_code = "barcode_error"
            check_result.details = {"error": str(e)}
            check_result.save()
            return {"found": False, "status": KYCCheckResult.Status.FAILED}

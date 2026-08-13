import io
import logging
from PIL import Image, ImageStat
from typing import TYPE_CHECKING, Any

try:
    import numpy as np
except ImportError:
    np = None

from kyc.models import KYCCheckResult
from kyc.services.image_validation_service import KYCImageValidationService, KYCValidationError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from kyc.models import KYCVerificationAttempt


class DocumentService:
    """Service orchestrating quality, structural, expiry, and manipulation checks."""

    @staticmethod
    def _calculate_blur_score(img: Image.Image) -> float:
        """Calculates image focus/sharpness score."""
        if np is not None:
            gray_array = np.array(img)
            if gray_array.size == 0:
                return 0.0
            gy, gx = np.gradient(gray_array.astype(float))
            gnorm = np.sqrt(gx**2 + gy**2)
            return float(np.var(gnorm))
        else:
            stat = ImageStat.Stat(img)
            return float(stat.stddev[0]) if stat.stddev else 0.0

    @staticmethod
    def _calculate_glare_ratio(img: Image.Image) -> float:
        """Calculates proportion of overexposed / saturated pixels."""
        if np is not None:
            gray_array = np.array(img)
            if gray_array.size == 0:
                return 0.0
            oversaturated = np.sum(gray_array > 245)
            return float(oversaturated / gray_array.size)
        else:
            b = img.tobytes()
            return float(sum(1 for p in b if p > 245) / (len(b) or 1))

    @classmethod
    def analyze_document_quality(cls, attempt: "KYCVerificationAttempt") -> dict[str, Any]:
        check_result, _ = KYCCheckResult.objects.update_or_create(
            kyc_verification=attempt.kyc_verification,
            kyc_attempt=attempt,
            check_type=KYCCheckResult.CheckType.IMAGE_QUALITY,
            defaults={"status": KYCCheckResult.Status.PROCESSING},
        )

        try:
            with attempt.document_image.open("rb") as f:
                file_bytes = f.read()

            image_meta = KYCImageValidationService.validate_image(
                file_data=file_bytes,
                filename=attempt.document_image.name,
            )

            img = Image.open(io.BytesIO(file_bytes)).convert("L")

            blur_score = cls._calculate_blur_score(img)
            glare_ratio = cls._calculate_glare_ratio(img)

            stat = ImageStat.Stat(img)
            contrast_stddev = stat.stddev[0] if stat.stddev else 0.0

            is_sharp = blur_score >= 12.0 or (np is None and contrast_stddev >= 15.0)
            is_glare_free = glare_ratio <= 0.20
            is_contrast_ok = contrast_stddev >= 15.0

            passed = is_sharp and is_glare_free and is_contrast_ok

            quality_score = min(1.0, max(0.0, (blur_score / 100.0) * (1.0 - glare_ratio)))

            check_result.status = (
                KYCCheckResult.Status.PASSED if passed else KYCCheckResult.Status.FAILED
            )
            check_result.score = round(quality_score, 4)
            check_result.confidence = 0.95
            check_result.result_code = "quality_ok" if passed else "poor_image_quality"
            check_result.details = {
                "width": image_meta["width"],
                "height": image_meta["height"],
                "blur_score": round(blur_score, 2),
                "glare_ratio": round(glare_ratio, 4),
                "contrast_stddev": round(contrast_stddev, 2),
                "is_sharp": is_sharp,
                "is_glare_free": is_glare_free,
                "is_contrast_ok": is_contrast_ok,
            }
            check_result.save()

            attempt.kyc_verification.document_quality_status = check_result.status
            attempt.kyc_verification.save(update_fields=["document_quality_status", "updated_at"])

            return {"passed": passed, "score": quality_score, "check": check_result}

        except KYCValidationError as e:
            check_result.status = KYCCheckResult.Status.FAILED
            check_result.result_code = e.code
            check_result.details = {"reason": str(e)}
            check_result.save()
            attempt.kyc_verification.document_quality_status = KYCCheckResult.Status.FAILED
            attempt.kyc_verification.save(update_fields=["document_quality_status", "updated_at"])
            return {"passed": False, "score": 0.0, "reason": str(e)}
        except Exception as e:
            logger.error("Error analyzing document quality for attempt %s: %s", attempt.id, e)
            check_result.status = KYCCheckResult.Status.FAILED
            check_result.result_code = "quality_analysis_error"
            check_result.details = {"error": str(e)}
            check_result.save()
            return {"passed": False, "score": 0.0, "reason": str(e)}

    @classmethod
    def analyze_tampering(cls, attempt: "KYCVerificationAttempt") -> dict[str, Any]:
        check_result, _ = KYCCheckResult.objects.update_or_create(
            kyc_verification=attempt.kyc_verification,
            kyc_attempt=attempt,
            check_type=KYCCheckResult.CheckType.DOCUMENT_MANIPULATION,
            defaults={"status": KYCCheckResult.Status.PROCESSING},
        )

        try:
            with attempt.document_image.open("rb") as f:
                img = Image.open(f).convert("L")

            w, h = img.size
            if h < 20 or w < 20:
                check_result.status = KYCCheckResult.Status.FAILED
                check_result.save()
                return {
                    "passed": False,
                    "reason": "Image dimensions too small for manipulation check",
                }

            if np is not None:
                arr = np.array(img)
                q1 = arr[: h // 2, : w // 2]
                q2 = arr[: h // 2, w // 2 :]
                q3 = arr[h // 2 :, : w // 2]
                q4 = arr[h // 2 :, w // 2 :]
                stds = [np.std(q) for q in (q1, q2, q3, q4) if q.size > 0]
            else:
                q1 = ImageStat.Stat(img.crop((0, 0, w // 2, h // 2))).stddev[0]
                q2 = ImageStat.Stat(img.crop((w // 2, 0, w, h // 2))).stddev[0]
                q3 = ImageStat.Stat(img.crop((0, h // 2, w // 2, h))).stddev[0]
                q4 = ImageStat.Stat(img.crop((w // 2, h // 2, w, h))).stddev[0]
                stds = [q1, q2, q3, q4]

            max_std, min_std = max(stds), min(stds)
            std_ratio = (max_std / (min_std + 1e-5)) if min_std > 0 else 1.0

            tampered = bool(std_ratio > 10.0)

            check_result.status = (
                KYCCheckResult.Status.FAILED if tampered else KYCCheckResult.Status.PASSED
            )
            check_result.score = 1.0 if not tampered else 0.2
            check_result.confidence = 0.85
            check_result.result_code = (
                "tampering_detected" if tampered else "no_manipulation_detected"
            )
            check_result.details = {
                "quadrant_std_ratio": round(float(std_ratio), 2),
                "tampering_flagged": tampered,
            }
            check_result.save()

            return {"passed": not tampered, "tampered": tampered}

        except Exception as e:
            logger.warning(
                "Document manipulation analysis warning for attempt %s: %s", attempt.id, e
            )
            check_result.status = KYCCheckResult.Status.UNCERTAIN
            check_result.details = {"error": str(e)}
            check_result.save()
            return {"passed": True, "uncertain": True}

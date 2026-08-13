import io
import logging
from PIL import Image, ImageStat
from typing import TYPE_CHECKING, Any

try:
    import numpy as np
except ImportError:
    np = None

from kyc.models import KYCCheckResult, KYCConfiguration
from kyc.services.image_validation_service import KYCImageValidationService, KYCValidationError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from kyc.models import KYCVerificationAttempt


class FaceService:
    """Orchestrates face detection, selfie validation, face matching, and liveness."""

    @classmethod
    def _detect_face_bounding_regions(cls, img_bytes: bytes) -> tuple[int, float, list]:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        w, h = img.size

        if np is not None:
            img_np = np.array(img)

            try:
                import cv2

                gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
                cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                face_cascade = cv2.CascadeClassifier(cascade_path)
                faces = face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=5,
                    minSize=(int(w * 0.15), int(h * 0.15)),
                )
                if len(faces) > 0:
                    regions = [
                        {"x": int(x), "y": int(y), "w": int(fw), "h": int(fh)}
                        for (x, y, fw, fh) in faces
                    ]
                    quality = float(min(1.0, max(0.5, (faces[0][2] * faces[0][3]) / (w * h * 0.1))))
                    return len(faces), quality, regions
            except Exception:
                pass

            center_h_start, center_h_end = int(h * 0.15), int(h * 0.85)
            center_w_start, center_w_end = int(w * 0.15), int(w * 0.85)
            crop = img_np[center_h_start:center_h_end, center_w_start:center_w_end]

            if crop.size == 0:
                return 0, 0.0, []

            r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
            skin_mask = (
                (r > 60)
                & (g > 40)
                & (b > 20)
                & (r > g)
                & (r > b)
                & (np.abs(r.astype(int) - g.astype(int)) > 10)
            )
            skin_ratio = float(np.sum(skin_mask) / crop[:, :, 0].size)

            if skin_ratio >= 0.12:
                return (
                    1,
                    round(skin_ratio, 2),
                    [
                        {
                            "x": center_w_start,
                            "y": center_h_start,
                            "w": int(w * 0.7),
                            "h": int(h * 0.7),
                        }
                    ],
                )
            else:
                return 0, round(skin_ratio, 2), []
        else:
            # Pure PIL luminance/skin region fallback
            center_box = (int(w * 0.15), int(h * 0.15), int(w * 0.85), int(h * 0.85))
            crop = img.crop(center_box)
            stat = ImageStat.Stat(crop)
            r_m, g_m, b_m = stat.mean[:3] if len(stat.mean) >= 3 else (100, 100, 100)

            if r_m > g_m and r_m > b_m and (r_m - g_m) > 8:
                return (
                    1,
                    0.85,
                    [
                        {
                            "x": center_box[0],
                            "y": center_box[1],
                            "w": center_box[2] - center_box[0],
                            "h": center_box[3] - center_box[1],
                        }
                    ],
                )
            return 0, 0.0, []

    @classmethod
    def validate_selfie(cls, attempt: "KYCVerificationAttempt") -> dict[str, Any]:
        check_result, _ = KYCCheckResult.objects.update_or_create(
            kyc_verification=attempt.kyc_verification,
            kyc_attempt=attempt,
            check_type=KYCCheckResult.CheckType.FACE_DETECTION,
            defaults={"status": KYCCheckResult.Status.PROCESSING},
        )

        verification = attempt.kyc_verification

        try:
            with attempt.selfie_image.open("rb") as f:
                file_bytes = f.read()

            KYCImageValidationService.validate_image(
                file_data=file_bytes,
                filename=attempt.selfie_image.name,
            )

            face_count, quality_score, regions = cls._detect_face_bounding_regions(file_bytes)

            if face_count == 0:
                raise KYCValidationError(
                    "No face detected in selfie image.", code="no_face_detected"
                )
            if face_count > 1:
                raise KYCValidationError(
                    "Multiple faces detected in selfie image.", code="multiple_faces_detected"
                )

            check_result.status = KYCCheckResult.Status.PASSED
            check_result.score = quality_score
            check_result.confidence = 0.92
            check_result.result_code = "single_face_detected"
            check_result.details = {
                "face_count": face_count,
                "quality": quality_score,
                "regions": regions,
            }
            check_result.save()

            verification.face_detection_status = KYCCheckResult.Status.PASSED
            verification.save(update_fields=["face_detection_status", "updated_at"])

            return {"passed": True, "face_count": 1, "quality": quality_score}

        except KYCValidationError as e:
            check_result.status = KYCCheckResult.Status.FAILED
            check_result.result_code = e.code
            check_result.details = {"reason": str(e)}
            check_result.save()
            verification.face_detection_status = KYCCheckResult.Status.FAILED
            verification.save(update_fields=["face_detection_status", "updated_at"])
            return {"passed": False, "reason": str(e)}
        except Exception as e:
            logger.error("Selfie validation error for attempt %s: %s", attempt.id, e)
            check_result.status = KYCCheckResult.Status.FAILED
            check_result.result_code = "face_detection_error"
            check_result.details = {"error": str(e)}
            check_result.save()
            verification.face_detection_status = KYCCheckResult.Status.FAILED
            verification.save(update_fields=["face_detection_status", "updated_at"])
            return {"passed": False, "reason": str(e)}

    @classmethod
    def compare_faces(cls, attempt: "KYCVerificationAttempt") -> dict[str, Any]:
        check_result, _ = KYCCheckResult.objects.update_or_create(
            kyc_verification=attempt.kyc_verification,
            kyc_attempt=attempt,
            check_type=KYCCheckResult.CheckType.FACE_MATCH,
            defaults={"status": KYCCheckResult.Status.PROCESSING},
        )

        verification = attempt.kyc_verification
        config = KYCConfiguration.load()

        try:
            with attempt.document_image.open("rb") as f_doc:
                doc_bytes = f_doc.read()
            with attempt.selfie_image.open("rb") as f_selfie:
                selfie_bytes = f_selfie.read()

            similarity = 0.0
            confidence = 0.90
            used_deepface = False

            if np is not None:
                try:
                    from deepface import DeepFace

                    doc_img = Image.open(io.BytesIO(doc_bytes)).convert("RGB")
                    selfie_img = Image.open(io.BytesIO(selfie_bytes)).convert("RGB")

                    res = DeepFace.verify(
                        img1_path=np.array(doc_img),
                        img2_path=np.array(selfie_img),
                        model_name="VGG-Face",
                        enforce_detection=False,
                    )
                    distance = res.get("distance", 0.5)
                    similarity = max(0.0, min(1.0, 1.0 - float(distance)))
                    used_deepface = True
                except Exception:
                    pass

            if not used_deepface:
                doc_img = Image.open(io.BytesIO(doc_bytes)).convert("L").resize((128, 128))
                selfie_img = Image.open(io.BytesIO(selfie_bytes)).convert("L").resize((128, 128))

                if np is not None:
                    arr_doc = np.array(doc_img, dtype=float)
                    arr_selfie = np.array(selfie_img, dtype=float)
                    arr_doc -= np.mean(arr_doc)
                    arr_selfie -= np.mean(arr_selfie)
                    denom = np.linalg.norm(arr_doc) * np.linalg.norm(arr_selfie)
                    corr = np.sum(arr_doc * arr_selfie) / (denom + 1e-7)
                    similarity = float(max(0.0, min(1.0, (corr + 1.0) / 2.0)))
                else:
                    stat_doc = ImageStat.Stat(doc_img)
                    stat_selfie = ImageStat.Stat(selfie_img)
                    diff = abs(stat_doc.mean[0] - stat_selfie.mean[0]) / 255.0
                    similarity = float(max(0.0, min(1.0, 1.0 - diff)))

            pass_thresh = config.face_match_pass_threshold
            review_thresh = config.face_match_review_threshold

            passed = similarity >= pass_thresh
            uncertain = review_thresh <= similarity < pass_thresh

            if passed:
                status = KYCCheckResult.Status.PASSED
                result_code = "face_match_passed"
            elif uncertain:
                status = KYCCheckResult.Status.UNCERTAIN
                result_code = "face_match_borderline"
            else:
                status = KYCCheckResult.Status.FAILED
                result_code = "face_mismatch"

            check_result.status = status
            check_result.score = round(similarity, 4)
            check_result.confidence = confidence
            check_result.result_code = result_code
            check_result.details = {
                "similarity_score": round(similarity, 4),
                "pass_threshold": pass_thresh,
                "review_threshold": review_thresh,
                "algorithm": "DeepFace (VGG-Face)" if used_deepface else "Structural Correlation",
            }
            check_result.save()

            verification.face_match_status = status
            verification.save(update_fields=["face_match_status", "updated_at"])

            return {"passed": passed, "status": status, "similarity": similarity}

        except Exception as e:
            logger.error("Face matching error for attempt %s: %s", attempt.id, e)
            check_result.status = KYCCheckResult.Status.FAILED
            check_result.result_code = "face_match_error"
            check_result.details = {"error": str(e)}
            check_result.save()
            verification.face_match_status = KYCCheckResult.Status.FAILED
            verification.save(update_fields=["face_match_status", "updated_at"])
            return {"passed": False, "status": KYCCheckResult.Status.FAILED, "reason": str(e)}

    @classmethod
    def check_liveness(cls, attempt: "KYCVerificationAttempt") -> dict[str, Any]:
        check_result, _ = KYCCheckResult.objects.update_or_create(
            kyc_verification=attempt.kyc_verification,
            kyc_attempt=attempt,
            check_type=KYCCheckResult.CheckType.LIVENESS,
            defaults={"status": KYCCheckResult.Status.PROCESSING},
        )

        verification = attempt.kyc_verification

        try:
            with attempt.selfie_image.open("rb") as f:
                img_bytes = f.read()

            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

            if np is not None:
                gray = Image.open(io.BytesIO(img_bytes)).convert("L")
                gray_arr = np.array(gray)

                fft = np.fft.fft2(gray_arr)
                fft_shift = np.fft.fftshift(fft)
                magnitude_spectrum = 20 * np.log(np.abs(fft_shift) + 1e-5)
                h, w = gray_arr.shape
                center_h, center_w = h // 2, w // 2
                high_freq_energy = np.mean(magnitude_spectrum[: center_h - 20, : center_w - 20])

                r_stat, g_stat, b_stat = ImageStat.Stat(img).stddev
                color_variance = (r_stat + g_stat + b_stat) / 3.0

                is_screen_replay = bool(high_freq_energy > 180.0)
                is_flat_photo = bool(color_variance < 15.0)

                liveness_score = float(
                    max(0.0, min(1.0, (color_variance / 50.0) * (1.0 - (high_freq_energy / 250.0))))
                )
            else:
                stat = ImageStat.Stat(img)
                color_variance = float(sum(stat.stddev) / len(stat.stddev)) if stat.stddev else 20.0
                is_screen_replay = False
                is_flat_photo = bool(color_variance < 10.0)
                liveness_score = float(max(0.0, min(1.0, color_variance / 50.0)))
                high_freq_energy = 50.0

            if is_screen_replay or is_flat_photo:
                status = KYCCheckResult.Status.FAILED
                result_code = "presentation_attack_detected"
            elif liveness_score >= 0.40:
                status = KYCCheckResult.Status.PASSED
                result_code = "liveness_passed"
            else:
                status = KYCCheckResult.Status.UNCERTAIN
                result_code = "liveness_uncertain"

            check_result.status = status
            check_result.score = round(liveness_score, 4)
            check_result.confidence = 0.88
            check_result.result_code = result_code
            check_result.details = {
                "high_freq_energy": round(float(high_freq_energy), 2),
                "color_variance": round(float(color_variance), 2),
                "is_screen_replay": bool(is_screen_replay),
                "is_flat_photo": bool(is_flat_photo),
            }
            check_result.save()

            verification.liveness_status = status
            verification.save(update_fields=["liveness_status", "updated_at"])

            return {
                "passed": status == KYCCheckResult.Status.PASSED,
                "status": status,
                "score": liveness_score,
            }

        except Exception as e:
            logger.error("Liveness check error for attempt %s: %s", attempt.id, e)
            check_result.status = KYCCheckResult.Status.UNCERTAIN
            check_result.result_code = "liveness_check_uncertain"
            check_result.details = {"error": str(e)}
            check_result.save()
            verification.liveness_status = KYCCheckResult.Status.UNCERTAIN
            verification.save(update_fields=["liveness_status", "updated_at"])
            return {"passed": False, "status": KYCCheckResult.Status.UNCERTAIN, "reason": str(e)}

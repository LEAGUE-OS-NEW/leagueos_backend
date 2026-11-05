import base64
import io
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image

from kyc.models import KYCCheckResult, KYCVerification
from kyc.services import face_service
from kyc.services.face_match_worker import decode_bgr
from kyc.services.face_service import FaceService
from kyc.tests.test_reliability import make_attempt
from authentication.tests.factories import UserFactory


def picture(colour=(200, 80, 30), orientation=None):
    image = Image.new("RGB", (800, 600), colour)
    output = io.BytesIO()
    if orientation:
        exif = image.getexif()
        exif[274] = orientation
        image.save(output, format="JPEG", exif=exif)
    else:
        image.save(output, format="PNG")
    return output.getvalue()


def test_face_worker_converts_rgb_to_bgr():
    image = decode_bgr(base64.b64encode(picture()).decode())
    assert image.getpixel((0, 0)) == (30, 80, 200)


def test_face_worker_applies_phone_orientation_before_comparison():
    image = decode_bgr(base64.b64encode(picture(orientation=6)).decode())
    assert image.size == (600, 800)


@pytest.mark.parametrize("detected", [[], [(10, 20, 200, 250)]])
def test_opencv5_uses_cached_detector_and_does_not_guess_faces_from_colour(
    tmp_path, monkeypatch, detected
):
    cache = tmp_path / ".deepface/weights"
    cache.mkdir(parents=True)
    (cache / "haarcascade_frontalface_default.xml").write_text("fixture")
    classifier = SimpleNamespace(
        empty=lambda: False, detectMultiScale=lambda *args, **kwargs: detected
    )
    loaded = []

    def cascade(path):
        loaded.append(path)
        return classifier

    cv2 = SimpleNamespace(
        CascadeClassifier=cascade, COLOR_RGB2GRAY=1, cvtColor=lambda image, code: image
    )
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    monkeypatch.setattr(face_service, "np", SimpleNamespace(array=lambda image: image))
    monkeypatch.setenv("DEEPFACE_HOME", str(tmp_path))
    count, _, regions = FaceService._detect_face_bounding_regions(picture())
    assert count == len(detected)
    assert len(regions) == len(detected)
    assert loaded == [str(cache / "haarcascade_frontalface_default.xml")]


@pytest.mark.django_db
def test_missing_detector_records_uncertain_evidence_for_review():
    verification = KYCVerification.objects.create(user=UserFactory(), status="PROCESSING")
    attempt = make_attempt(verification)
    with patch.object(FaceService, "_detect_face_bounding_regions", return_value=(None, 0.0, [])):
        result = FaceService.validate_selfie(attempt)
    assert result["status"] == "UNCERTAIN"
    check = attempt.checks.get(check_type=KYCCheckResult.CheckType.FACE_DETECTION)
    assert check.result_code == "face_detection_unavailable"
    assert check.score is None and check.confidence is None
    verification.refresh_from_db()
    assert verification.face_detection_status == "UNCERTAIN"
    assert verification.status == "PROCESSING"

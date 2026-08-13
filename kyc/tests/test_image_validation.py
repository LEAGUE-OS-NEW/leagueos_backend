import pytest
from kyc.services.image_validation_service import KYCImageValidationService, KYCValidationError
from kyc.tests.helpers import create_test_image_bytes


def test_valid_image_pass():
    data = create_test_image_bytes(width=800, height=600, format_name="JPEG")
    res = KYCImageValidationService.validate_image(
        data, filename="passport.jpg", content_type="image/jpeg"
    )

    assert res["width"] == 800
    assert res["height"] == 600
    assert res["filename"] == "passport.jpg"


def test_empty_file_rejected():
    with pytest.raises(KYCValidationError) as exc:
        KYCImageValidationService.validate_image(b"", filename="empty.jpg")
    assert exc.value.code == "empty_file"


def test_invalid_extension_rejected():
    data = create_test_image_bytes()
    with pytest.raises(KYCValidationError) as exc:
        KYCImageValidationService.validate_image(data, filename="script.sh")
    assert exc.value.code == "unsupported_extension"


def test_magic_bytes_mismatch_rejected():
    fake_exe_bytes = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 500
    with pytest.raises(KYCValidationError) as exc:
        KYCImageValidationService.validate_image(fake_exe_bytes, filename="fake.jpg")
    assert exc.value.code in ["invalid_magic_bytes", "corrupted_image"]


def test_path_traversal_filename_sanitized():
    data = create_test_image_bytes()
    with pytest.raises(KYCValidationError) as exc:
        KYCImageValidationService.validate_image(data, filename="../../../etc/passwd.jpg")
    assert exc.value.code == "path_traversal"


def test_dimensions_too_small_rejected():
    small_data = create_test_image_bytes(width=100, height=100)
    with pytest.raises(KYCValidationError) as exc:
        KYCImageValidationService.validate_image(small_data, filename="small.jpg")
    assert exc.value.code == "dimensions_too_small"

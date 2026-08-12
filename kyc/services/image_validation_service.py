import io
import os
import re
from PIL import Image
from django.conf import settings


class KYCValidationError(Exception):
    def __init__(self, message: str, code: str = "invalid_image"):
        super().__init__(message)
        self.message = message
        self.code = code


class KYCImageValidationService:
    """Security and quality validator for uploaded KYC document and selfie media."""

    ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

    # Magic byte signatures
    MAGIC_SIGNATURES = {
        "jpeg": [b"\xff\xd8\xff"],
        "png": [b"\x89PNG\r\n\x1a\n"],
        "webp": [b"RIFF"],  # 'RIFF' header followed by 'WEBP' at offset 8
    }

    @classmethod
    def validate_image(
        cls,
        file_data: bytes,
        filename: str,
        content_type: str | None = None,
        max_size_mb: int | None = None,
    ) -> dict:
        """Validates file signature, mime type, size, dimensions, and path safety.

        Returns metadata dict on success or raises KYCValidationError.
        """
        if not file_data:
            raise KYCValidationError("Uploaded file is empty.", code="empty_file")

        # 1. File size check
        max_bytes = (max_size_mb or getattr(settings, "KYC_MAX_DOCUMENT_SIZE_MB", 10)) * 1024 * 1024
        if len(file_data) > max_bytes:
            raise KYCValidationError(
                f"File size exceeds maximum allowed limit of {max_bytes // (1024 * 1024)}MB.",
                code="file_too_large",
            )

        # 2. Filename and extension safety
        safe_filename = os.path.basename(filename)
        if re.search(r"[\x00-\x1f\x7f\\/]", safe_filename) or ".." in filename:
            raise KYCValidationError("Invalid or suspicious file path.", code="path_traversal")

        ext = os.path.splitext(safe_filename)[1].lower()
        if ext not in cls.ALLOWED_EXTENSIONS:
            raise KYCValidationError(
                f"Unsupported file extension '{ext}'. Allowed: "
                f"{', '.join(sorted(cls.ALLOWED_EXTENSIONS))}",
                code="unsupported_extension",
            )

        # 3. Content-Type check if provided
        if content_type and content_type.lower() not in cls.ALLOWED_MIME_TYPES:
            raise KYCValidationError(
                f"Unsupported MIME type '{content_type}'.",
                code="unsupported_mime_type",
            )

        # 4. Magic-byte signature verification
        is_magic_valid = False
        if file_data.startswith(b"\xff\xd8\xff"):
            is_magic_valid = True
        elif file_data.startswith(b"\x89PNG\r\n\x1a\n"):
            is_magic_valid = True
        elif file_data.startswith(b"RIFF") and len(file_data) >= 12 and file_data[8:12] == b"WEBP":
            is_magic_valid = True

        if not is_magic_valid:
            raise KYCValidationError(
                "File magic byte signature does not match supported image formats.",
                code="invalid_magic_bytes",
            )

        # 5. Image structure & dimension verification using PIL
        try:
            with Image.open(io.BytesIO(file_data)) as img:
                img.verify()
        except Exception as e:
            raise KYCValidationError(
                f"Corrupted or unreadable image file: {e}",
                code="corrupted_image",
            ) from e

        with Image.open(io.BytesIO(file_data)) as img:
            width, height = img.size
            format_name = img.format.upper() if img.format else ""

        min_dim = getattr(settings, "KYC_MIN_IMAGE_DIMENSION", 300)
        max_dim = getattr(settings, "KYC_MAX_IMAGE_DIMENSION", 6000)

        if width < min_dim or height < min_dim:
            raise KYCValidationError(
                f"Image dimensions ({width}x{height}) are too small. "
                f"Minimum is {min_dim}x{min_dim}.",
                code="dimensions_too_small",
            )
        if width > max_dim or height > max_dim:
            raise KYCValidationError(
                f"Image dimensions ({width}x{height}) exceed maximum allowed {max_dim}x{max_dim}.",
                code="dimensions_too_large",
            )

        return {
            "filename": safe_filename,
            "size_bytes": len(file_data),
            "width": width,
            "height": height,
            "format": format_name,
        }

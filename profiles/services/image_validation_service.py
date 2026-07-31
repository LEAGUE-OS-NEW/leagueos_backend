"""Image validation service for avatar uploads.

Validates uploaded images for file type, MIME type, size, dimensions,
integrity, and detects animated/malicious files.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Custom validation error for image validation failures."""

    pass


class ImageValidationService:
    """Service for validating uploaded avatar images.

    All validation is performed server-side. Client-side validation
    is never trusted.
    """

    ALLOWED_EXTENSIONS: list[str] = getattr(
        settings,
        "AVATAR_ALLOWED_EXTENSIONS",
        [".jpg", ".jpeg", ".png", ".webp"],
    )

    ALLOWED_MIME_TYPES: list[str] = getattr(
        settings,
        "AVATAR_ALLOWED_MIME_TYPES",
        ["image/jpeg", "image/png", "image/webp"],
    )

    MAX_UPLOAD_SIZE: int = getattr(settings, "AVATAR_MAX_UPLOAD_SIZE", 5 * 1024 * 1024)

    MAX_DIMENSION: int = getattr(settings, "AVATAR_MAX_DIMENSION", 4096)
    MIN_DIMENSION: int = getattr(settings, "AVATAR_MIN_DIMENSION", 256)

    @staticmethod
    def validate_file_size(file_size: int) -> None:
        """Validate that the file size does not exceed the maximum.

        Raises:
            ValidationError: If the file exceeds the maximum upload size.
        """
        if file_size > ImageValidationService.MAX_UPLOAD_SIZE:
            raise ValidationError(
                f"File size ({file_size} bytes) exceeds "
                f"maximum allowed ({ImageValidationService.MAX_UPLOAD_SIZE} bytes)."
            )
        if file_size == 0:
            raise ValidationError("File is empty (zero-byte file).")

    @staticmethod
    def validate_file_extension(filename: str) -> str:
        """Validate the file extension is in the allowed list.

        Returns the normalized extension (e.g., '.jpg').

        Raises:
            ValidationError: If the extension is not allowed.
        """
        if "." not in filename:
            raise ValidationError("File must have an extension.")

        ext = filename.rsplit(".", 1)[-1].lower()
        normalized_ext = f".{ext}"

        if normalized_ext not in ImageValidationService.ALLOWED_EXTENSIONS:
            raise ValidationError(
                f"File extension '{normalized_ext}' is not allowed. "
                f"Allowed extensions: {', '.join(ImageValidationService.ALLOWED_EXTENSIONS)}"
            )

        return normalized_ext

    @staticmethod
    def validate_mime_type(content_type: str | None) -> None:
        """Validate the MIME type is in the allowed list.

        Raises:
            ValidationError: If the MIME type is not allowed.
        """
        if not content_type:
            raise ValidationError("Content-Type header is missing.")

        if content_type not in ImageValidationService.ALLOWED_MIME_TYPES:
            raise ValidationError(
                f"MIME type '{content_type}' is not allowed. "
                f"Allowed types: {', '.join(ImageValidationService.ALLOWED_MIME_TYPES)}"
            )

    @staticmethod
    def validate_image_magic_bytes(file_data: bytes) -> str:
        """Validate the file's magic bytes to detect the actual image format.

        This check is independent of the client-provided Content-Type,
        preventing spoofing attacks.

        Returns:
            The detected MIME type.

        Raises:
            ValidationError: If the file is not a valid image.
        """
        if len(file_data) < 16:
            raise ValidationError("File is too small to be a valid image.")

        # JPEG: starts with FF D8 FF
        if file_data[:3] == b"\xff\xd8\xff":
            return "image/jpeg"

        # PNG: starts with 89 50 4E 47 0D 0A 1A 0A
        if file_data[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"

        # WebP: starts with 'RIFF'....'WEBP'
        if len(file_data) >= 16 and file_data[:4] == b"RIFF" and file_data[8:12] == b"WEBP":
            return "image/webp"

        raise ValidationError(
            "File does not have valid image magic bytes. "
            "File may be corrupted or in an unsupported format."
        )

    @staticmethod
    def validate_image_integrity(file_data: bytes) -> Any:
        """Validate the image file is not corrupted and can be opened.

        Uses Pillow to verify the image integrity. Detects corrupted files.

        Returns:
            The PIL Image object.

        Raises:
            ValidationError: If the image is corrupted or invalid.
        """
        from PIL import Image, UnidentifiedImageFile

        try:
            image = Image.open(io.BytesIO(file_data))
            image.verify()  # Verify image integrity
        except UnidentifiedImageFile as exc:
            raise ValidationError("Uploaded file is not a valid image.") from exc
        except Exception as exc:
            raise ValidationError(f"Image validation failed: {exc}") from exc

        # Re-open after verify() since verify() leaves the file pointer exhausted
        image = Image.open(io.BytesIO(file_data))
        return image

    @staticmethod
    def validate_image_dimensions(image: Any) -> tuple[int, int]:
        """Validate image dimensions are within allowed bounds.

        Raises:
            ValidationError: If dimensions are below minimum or above maximum.
        """
        width, height = image.size

        min_dim = ImageValidationService.MIN_DIMENSION
        max_dim = ImageValidationService.MAX_DIMENSION

        if width < min_dim or height < min_dim:
            raise ValidationError(
                f"Image dimensions ({width}x{height}) are below "
                f"minimum required ({min_dim}x{min_dim})."
            )

        if width > max_dim or height > max_dim:
            raise ValidationError(
                f"Image dimensions ({width}x{height}) exceed "
                f"maximum allowed ({max_dim}x{max_dim})."
            )

        return (width, height)

    @staticmethod
    def is_animated(image: Any) -> bool:
        """Check if an image is animated (has multiple frames).

        Raises:
            ValidationError: If the image is animated.
        """
        if getattr(image, "is_animated", False):
            raise ValidationError("Animated images are not allowed.")

        try:
            n_frames = getattr(image, "n_frames", 1)
            if n_frames > 1:
                raise ValidationError("Animated images are not allowed.")
        except Exception:
            pass

        return False

    @staticmethod
    def validate_image(
        file_data: bytes,
        content_type: str | None,
        filename: str,
    ) -> tuple[Any, str]:
        """Run full image validation pipeline.

        Performs the following checks in order:
        1. File size validation
        2. File extension validation
        3. MIME type validation
        4. Magic bytes validation
        5. Image integrity validation (corruption check)
        6. Dimension validation
        7. Animation check

        Args:
            file_data: Raw bytes of the uploaded file.
            content_type: The MIME type from the Content-Type header.
            filename: The original filename.

        Returns:
            A tuple of (PIL Image object, detected MIME type).

        Raises:
            ValidationError: If any validation check fails.
        """
        # 1. File size
        ImageValidationService.validate_file_size(len(file_data))

        # 2. Extension
        ImageValidationService.validate_file_extension(filename)

        # 3. MIME type from header
        ImageValidationService.validate_mime_type(content_type)

        # 4. Magic bytes (detects spoofed Content-Type)
        detected_mime = ImageValidationService.validate_image_magic_bytes(file_data)

        # Cross-check: detected MIME should match declared MIME
        if (
            content_type
            and detected_mime
            and not ImageValidationService._mime_matches(content_type, detected_mime)
        ):
            raise ValidationError(
                f"Declared MIME type '{content_type}' does not match "
                f"actual file format '{detected_mime}'."
            )

        # 5. Image integrity
        image = ImageValidationService.validate_image_integrity(file_data)

        # 6. Dimensions
        ImageValidationService.validate_image_dimensions(image)

        # 7. Animation check
        ImageValidationService.is_animated(image)

        return image, detected_mime

    @staticmethod
    def _mime_matches(declared: str, detected: str) -> bool:
        """Check if declared and detected MIME types are compatible.

        Allows jpeg and jpg to match, etc.
        """
        declared_norm = declared.lower()
        detected_norm = detected.lower()
        return declared_norm == detected_norm

    @staticmethod
    def _mime_to_pil_format(mime_type: str) -> str:
        """Convert a MIME type to a PIL format string for saving.

        Args:
            mime_type: e.g. 'image/jpeg', 'image/png', 'image/webp'.

        Returns:
            PIL format string: 'JPEG', 'PNG', or 'WEBP'.
        """
        format_map = {
            "image/jpeg": "JPEG",
            "image/jpg": "JPEG",
            "image/png": "PNG",
            "image/webp": "WEBP",
        }
        return format_map.get(mime_type.lower(), "PNG")

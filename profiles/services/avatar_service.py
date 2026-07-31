"""Avatar service for handling avatar upload, replacement, and deletion.

Manages the complete avatar lifecycle including image processing,
storage operations, and audit logging. Each user may have only one
active avatar.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from profiles.services.image_validation_service import ImageValidationService
from profiles.services.profile_service import ProfileService
from profiles.services.storage_service import StorageService

logger = logging.getLogger(__name__)
User = get_user_model()


class AvatarService:
    """Service for avatar management operations."""

    @staticmethod
    def upload_or_replace_avatar(
        user: User,
        file_data: bytes,
        content_type: str | None,
        filename: str,
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> dict[str, Any]:
        """Upload or replace the user's avatar.

        Validates the image, processes it (orientation correction, EXIF
        stripping, optimization), saves it to storage, and returns
        updated profile information.

        Args:
            user: The authenticated user.
            file_data: Raw bytes of the uploaded image.
            content_type: MIME type from the upload.
            filename: Original filename.
            ip_address: Request IP address for audit.
            user_agent: Request user agent for audit.

        Returns:
            Dict with avatar_url, updated_at, and success status.

        Raises:
            ValidationError: If image validation fails.
        """
        # Validate the image
        image, detected_mime = ImageValidationService.validate_image(
            file_data, content_type, filename
        )

        # Process the image: correct orientation, strip EXIF, optimize
        processed_data = AvatarService._process_image(image, detected_mime)

        with transaction.atomic():
            profile = ProfileService.get_or_create_profile(user)

            # Delete old avatar file if it exists
            if profile.avatar:
                AvatarService._delete_old_avatar(profile)

            # Save the new avatar
            storage_path = StorageService.save_avatar(
                file_data=processed_data,
                original_name=filename,
                user_id=user.id,
            )

            # Update the profile's avatar field
            profile.avatar.name = storage_path
            profile.avatar_updated_at = timezone.now()
            profile.save(update_fields=["avatar", "avatar_updated_at", "updated_at"])

            # Determine audit action: upload (no previous avatar) vs update
            prev_had_avatar = profile.avatar.name != storage_path

            audit_action = "AVATAR_UPDATED" if prev_had_avatar else "AVATAR_UPLOADED"
            ProfileService.record_audit_log(
                user=user,
                action=audit_action,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata_={
                    "mime_type": detected_mime,
                    "storage_backend": StorageService.get_storage_backend(),
                },
            )

            # Refresh profile from DB
            profile.refresh_from_db()

            return {
                "success": True,
                "message": (
                    "Profile picture updated successfully."
                    if audit_action == "AVATAR_UPDATED"
                    else "Profile picture uploaded successfully."
                ),
                "data": {
                    "avatar_url": profile.get_avatar_url(),
                    "updated_at": (
                        profile.avatar_updated_at.isoformat()
                        if profile.avatar_updated_at
                        else profile.updated_at.isoformat()
                    ),
                },
            }

    @staticmethod
    def _process_image(image: Any, mime_type: str) -> bytes:
        """Process an image: correct orientation, strip EXIF, optimize.

        Returns the processed image as bytes.
        """
        from PIL import Image

        # If the image mode is not RGB/L (e.g., RGBA for PNG), convert appropriately
        if image.mode not in ("RGB", "L"):
            if mime_type == "image/png":
                image = image.convert("RGBA")
            else:
                image = image.convert("RGB")

        # Auto-orient based on EXIF orientation tag
        try:
            from PIL import ImageOps

            image = ImageOps.exif_transpose(image)
        except Exception:
            logger.warning("Could not apply EXIF auto-orientation, using as-is.")

        # Strip EXIF metadata by creating a new image without metadata
        data = list(image.getdata())
        output = Image.new(image.mode, image.size)
        output.putdata(data)

        # Save to bytes with optimization
        output_buffer = io.BytesIO()
        save_format = ImageValidationService._mime_to_pil_format(mime_type)
        save_kwargs: dict[str, Any] = {"optimize": True}
        if save_format == "webp":
            save_kwargs["quality"] = 85
        elif save_format == "jpeg":
            save_kwargs["quality"] = 85
            save_kwargs["progressive"] = True

        output.save(output_buffer, format=save_format, **save_kwargs)
        processed = output_buffer.getvalue()

        logger.info(
            "Image processed: format=%s, size=%d bytes",
            save_format,
            len(processed),
        )

        return processed

    @staticmethod
    def delete_avatar(
        user: User,
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> dict[str, Any]:
        """Delete the user's avatar and revert to default.

        Removes the file from storage and clears the avatar field.
        The frontend or default URL will serve the platform's default avatar.
        """
        with transaction.atomic():
            profile = ProfileService.get_or_create_profile(user)
            had_avatar = bool(profile.avatar and profile.avatar.name)

            if had_avatar:
                AvatarService._delete_old_avatar(profile)

            profile.avatar = None
            profile.avatar_updated_at = timezone.now()
            profile.save(update_fields=["avatar", "avatar_updated_at", "updated_at"])

            ProfileService.record_audit_log(
                user=user,
                action="AVATAR_DELETED",
                ip_address=ip_address,
                user_agent=user_agent,
                metadata_={"had_avatar_before": had_avatar},
            )

            profile.refresh_from_db()

            return {
                "success": True,
                "message": "Profile picture deleted successfully.",
                "data": {
                    "avatar_url": profile.get_avatar_url(),
                    "updated_at": (
                        profile.avatar_updated_at.isoformat()
                        if profile.avatar_updated_at
                        else profile.updated_at.isoformat()
                    ),
                },
            }

    @staticmethod
    def get_avatar_info(user: User) -> dict[str, Any]:
        """Return avatar metadata and URL for the user.

        Args:
            user: The authenticated user.

        Returns:
            Dict with avatar_url, avatar_updated_at, and has_avatar flag.
        """
        profile = ProfileService.get_or_create_profile(user)

        return {
            "avatar_url": profile.get_avatar_url(),
            "avatar_updated_at": (
                profile.avatar_updated_at.isoformat() if profile.avatar_updated_at else None
            ),
            "has_avatar": bool(profile.avatar and profile.avatar.name),
            "updated_at": profile.updated_at.isoformat(),
        }

    @staticmethod
    def _delete_old_avatar(profile: Profile) -> None:
        """Delete the old avatar file from storage.

        Args:
            profile: The Profile instance with an existing avatar.
        """
        if not profile.avatar or not profile.avatar.name:
            return

        # Get the file name before deleting
        filename = profile.avatar.name

        # Delete from storage
        try:
            profile.avatar.delete(save=False)
            logger.info("Old avatar file deleted: %s", filename)
        except Exception as exc:
            logger.error("Failed to delete old avatar file %s: %s", filename, exc)

        # Also ensure deletion from raw storage path
        if filename:
            StorageService.delete_file(filename)

    @staticmethod
    def record_upload_failure(
        user: User,
        reason: str,
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> None:
        """Record an upload failure audit log entry."""
        ProfileService.record_audit_log(
            user=user,
            action="UPLOAD_FAILED",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata_={"failure_reason": reason},
        )

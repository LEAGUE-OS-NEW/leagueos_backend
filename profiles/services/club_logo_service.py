"""Club logo service — mirrors AvatarService's upload/replace/delete
lifecycle for the single club crest image, reusing the same
ImageValidationService/StorageService building blocks."""

from __future__ import annotations

import io
import logging
from typing import Any

from django.core.cache import cache
from django.utils import timezone

from profiles.models import Club
from profiles.services.image_validation_service import ImageValidationService
from profiles.services.storage_service import StorageService

logger = logging.getLogger(__name__)


class ClubLogoService:
    """Service for club logo upload/replace/delete."""

    @staticmethod
    def _bust_cache(club_id) -> None:
        cache.delete(f"club:{club_id}")

    @staticmethod
    def upload_or_replace_logo(
        club: Club,
        file_data: bytes,
        content_type: str | None,
        filename: str,
        actor,
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> dict[str, Any]:
        """Upload or replace a club's logo. Returns the new logo URL."""
        image, detected_mime = ImageValidationService.validate_image(
            file_data, content_type, filename
        )
        processed_data = ClubLogoService._process_image(image, detected_mime)

        had_logo = bool(club.logo and club.logo.name)
        if had_logo:
            ClubLogoService._delete_logo_file(club)

        storage_path = StorageService.save_file(
            file_data=processed_data,
            filename=StorageService.generate_filename(filename),
            folder=f"clubs/{club.id}/logo",
        )
        club.logo.name = storage_path
        club.save(update_fields=["logo", "updated_at"])

        from clubs.services.audit_service import club_audit_service

        club_audit_service.record(
            "BRANDING_CHANGED",
            club,
            actor,
            entity_type="club_logo",
            entity_id=club.id,
            request=None,
            metadata={"mime_type": detected_mime, "replaced": had_logo},
        )

        club.refresh_from_db()
        ClubLogoService._bust_cache(club.id)

        return {
            "logo_url": StorageService.get_public_url(club.logo.name),
            "updated_at": timezone.now().isoformat(),
        }

    @staticmethod
    def delete_logo(club: Club, actor, ip_address: str | None = None, user_agent: str = "") -> None:
        """Remove a club's logo entirely."""
        had_logo = bool(club.logo and club.logo.name)
        if had_logo:
            ClubLogoService._delete_logo_file(club)

        club.logo = None
        club.save(update_fields=["logo", "updated_at"])

        from clubs.services.audit_service import club_audit_service

        club_audit_service.record(
            "BRANDING_CHANGED",
            club,
            actor,
            entity_type="club_logo",
            entity_id=club.id,
            request=None,
            metadata={"had_logo_before": had_logo, "action": "removed"},
        )

        ClubLogoService._bust_cache(club.id)

    @staticmethod
    def _process_image(image: Any, mime_type: str) -> bytes:
        """Strip EXIF, correct orientation, optimize — same treatment as
        avatar uploads (AvatarService._process_image)."""
        from PIL import Image, ImageOps

        if image.mode not in ("RGB", "L"):
            image = image.convert("RGBA") if mime_type == "image/png" else image.convert("RGB")

        try:
            image = ImageOps.exif_transpose(image)
        except Exception:
            logger.warning("Could not apply EXIF auto-orientation to club logo, using as-is.")

        data = list(image.getdata())
        output = Image.new(image.mode, image.size)
        output.putdata(data)

        output_buffer = io.BytesIO()
        save_format = ImageValidationService._mime_to_pil_format(mime_type)
        save_kwargs: dict[str, Any] = {"optimize": True}
        if save_format in ("webp", "jpeg"):
            save_kwargs["quality"] = 85
        output.save(output_buffer, format=save_format, **save_kwargs)
        return output_buffer.getvalue()

    @staticmethod
    def _delete_logo_file(club: Club) -> None:
        if not club.logo or not club.logo.name:
            return
        filename = club.logo.name
        try:
            club.logo.delete(save=False)
        except Exception as exc:
            logger.error("Failed to delete old club logo file %s: %s", filename, exc)
        StorageService.delete_file(filename)


club_logo_service = ClubLogoService()

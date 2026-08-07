"""Media service for club media management."""

from __future__ import annotations

import logging
import mimetypes

from django.utils import timezone

from clubs.models import ClubAuditLog, ClubMedia

logger = logging.getLogger(__name__)


class MediaService:
    """Service for club media operations."""

    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
    ALLOWED_MIME_TYPES = {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
        "video/mp4",
        "video/webm",
        "application/pdf",
    }

    @staticmethod
    def validate_file(file):
        """Validate uploaded file."""
        if file.size > MediaService.MAX_FILE_SIZE:
            raise ValueError(f"File size exceeds {MediaService.MAX_FILE_SIZE} bytes.")

        mime_type, _ = mimetypes.guess_type(file.name)
        if mime_type and mime_type not in MediaService.ALLOWED_MIME_TYPES:
            raise ValueError(f"File type {mime_type} is not allowed.")

        return mime_type

    @staticmethod
    def create_media(club, user, file, **kwargs):
        """Create new media asset."""
        mime_type = MediaService.validate_file(file)

        media = ClubMedia.objects.create(
            club=club,
            file=file,
            mime_type=mime_type,
            file_size=file.size,
            uploaded_by=user,
            **kwargs,
        )

        ClubAuditLog.objects.create(
            club=club,
            user=user,
            action="MEDIA_UPLOADED",
            entity_type="ClubMedia",
            entity_id=media.id,
            metadata={"title": media.title, "media_type": media.media_type},
        )

        return media

    @staticmethod
    def publish_media(media, user):
        """Publish media asset."""
        if media.status == ClubMedia.Status.PUBLISHED:
            return media

        media.status = ClubMedia.Status.PUBLISHED
        media.published_at = timezone.now()
        media.published_by = user
        media.save(update_fields=["status", "published_at", "published_by"])

        ClubAuditLog.objects.create(
            club=media.club,
            user=user,
            action="BRANDING_CHANGED",
            entity_type="ClubMedia",
            entity_id=media.id,
            metadata={"action": "published"},
        )

        return media


media_service = MediaService()

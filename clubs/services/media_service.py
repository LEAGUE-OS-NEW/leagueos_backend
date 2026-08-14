"""Media service for club media management."""

from __future__ import annotations

import io
import logging
import mimetypes

from django.utils import timezone

from clubs.models import ClubAuditLog, ClubMedia

logger = logging.getLogger(__name__)

try:
    from PIL import Image

    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False


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
    def _strip_exif(file):
        """Strip EXIF metadata from image files.

        Returns a new file-like object with EXIF removed.
        """
        if not PILLOW_AVAILABLE:
            return file

        try:
            image = Image.open(io.BytesIO(file.read()))
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")

            try:
                from PIL import ImageOps

                image = ImageOps.exif_transpose(image)
            except Exception:
                pass

            output = Image.new(image.mode, image.size)
            output.putdata(list(image.getdata()))

            output_buffer = io.BytesIO()
            save_format = image.format or "JPEG"
            save_kwargs = {"optimize": True}
            if save_format == "JPEG":
                save_kwargs["quality"] = 85
                save_kwargs["progressive"] = True
            elif save_format == "WEBP":
                save_kwargs["quality"] = 85

            output.save(output_buffer, format=save_format, **save_kwargs)
            output_buffer.seek(0)

            return output_buffer
        except Exception:
            logger.exception("Failed to strip EXIF from image")
            file.seek(0)
            return file

    @staticmethod
    def create_media(club, user, file, **kwargs):
        """Create new media asset."""
        mime_type = MediaService.validate_file(file)

        if mime_type and mime_type.startswith("image/"):
            file = MediaService._strip_exif(file)

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
        media.scheduled_at = None
        media.save(update_fields=["status", "published_at", "published_by", "scheduled_at"])

        ClubAuditLog.objects.create(
            club=media.club,
            user=user,
            action="BRANDING_CHANGED",
            entity_type="ClubMedia",
            entity_id=media.id,
            metadata={"action": "published"},
        )

        MediaService._emit_notification(media, user)

        return media

    @staticmethod
    def schedule_media(media, scheduled_at, user):
        """Schedule media for future publication."""
        media.scheduled_at = scheduled_at
        media.status = ClubMedia.Status.PUBLISHED
        media.save(update_fields=["scheduled_at", "status"])

        ClubAuditLog.objects.create(
            club=media.club,
            user=user,
            action="MEDIA_UPLOADED",
            entity_type="ClubMedia",
            entity_id=media.id,
            metadata={"action": "scheduled", "scheduled_at": scheduled_at.isoformat()},
        )

        return media

    @staticmethod
    def get_scheduled_media():
        """Return media scheduled for publication that are due."""
        now = timezone.now()
        return ClubMedia.objects.filter(
            status=ClubMedia.Status.PUBLISHED,
            scheduled_at__lte=now,
        )

    @staticmethod
    def _emit_notification(media, user):
        """Emit notification when media is published."""
        try:
            from notifications.services.notification_service import NotificationService

            NotificationService.create(
                recipient=user,
                category_code="CLUB_NEWS",
                event_type="club.media.published",
                title=f"Media published: {media.title or media.media_type}",
                message=f"New media has been published for {media.club.name}.",
                deduplication_key=f"club-media-published-{media.id}",
                data={
                    "club_id": str(media.club_id),
                    "media_id": str(media.id),
                    "media_type": media.media_type,
                },
            )
        except Exception:
            logger.exception("Failed to emit media published notification")


media_service = MediaService()

"""Club profile service for managing club profile versions."""

from __future__ import annotations

import logging

from django.utils import timezone

from clubs.models import ClubAuditLog, ClubProfileVersion
from clubs.services.sanitisation import sanitise_html

logger = logging.getLogger(__name__)


class ClubProfileService:
    """Service for club profile operations."""

    @staticmethod
    def get_next_version(club):
        """Get next version number for club profile."""
        latest = ClubProfileVersion.objects.filter(club=club).order_by("-version").first()
        return 1 if not latest else latest.version + 1

    @staticmethod
    def create_profile(club, user, **kwargs):
        """Create new club profile version."""
        if "description" in kwargs and kwargs["description"]:
            kwargs["description"] = sanitise_html(kwargs["description"])

        version = ClubProfileService.get_next_version(club)
        profile = ClubProfileVersion.objects.create(
            club=club,
            version=version,
            created_by=user,
            **kwargs,
        )

        ClubAuditLog.objects.create(
            club=club,
            user=user,
            action="CLUB_PROFILE_UPDATED",
            entity_type="ClubProfileVersion",
            entity_id=profile.id,
            metadata={"version": version},
        )

        return profile

    @staticmethod
    def publish_profile(profile, user):
        """Publish a club profile."""
        if profile.status == ClubProfileVersion.ProfileStatus.PUBLISHED:
            return profile

        profile.status = ClubProfileVersion.ProfileStatus.PUBLISHED
        profile.published_at = timezone.now()
        profile.published_by = user
        profile.scheduled_at = None
        profile.save(update_fields=["status", "published_at", "published_by", "scheduled_at"])

        ClubAuditLog.objects.create(
            club=profile.club,
            user=user,
            action="CLUB_PROFILE_UPDATED",
            entity_type="ClubProfileVersion",
            entity_id=profile.id,
            metadata={"action": "published", "version": profile.version},
        )

        ClubProfileService._emit_notification(profile, user)

        return profile

    @staticmethod
    def schedule_profile(profile, scheduled_at, user):
        """Schedule a club profile for future publication."""
        profile.scheduled_at = scheduled_at
        profile.status = ClubProfileVersion.ProfileStatus.PENDING_APPROVAL
        profile.save(update_fields=["scheduled_at", "status"])

        ClubAuditLog.objects.create(
            club=profile.club,
            user=user,
            action="CLUB_PROFILE_UPDATED",
            entity_type="ClubProfileVersion",
            entity_id=profile.id,
            metadata={"action": "scheduled", "scheduled_at": scheduled_at.isoformat()},
        )

        return profile

    @staticmethod
    def get_published_profile(club):
        """Get current published profile for club."""
        return (
            ClubProfileVersion.objects.filter(
                club=club,
                status=ClubProfileVersion.ProfileStatus.PUBLISHED,
            )
            .order_by("-version")
            .first()
        )

    @staticmethod
    def get_latest_draft(club):
        """Get latest draft profile for club."""
        return (
            ClubProfileVersion.objects.filter(
                club=club,
                status=ClubProfileVersion.ProfileStatus.DRAFT,
            )
            .order_by("-version")
            .first()
        )

    @staticmethod
    def get_scheduled_profiles():
        """Return profiles scheduled for publication that are due."""
        now = timezone.now()
        return ClubProfileVersion.objects.filter(
            status=ClubProfileVersion.ProfileStatus.PENDING_APPROVAL,
            scheduled_at__lte=now,
        )

    @staticmethod
    def _emit_notification(profile, user):
        """Emit notification when profile is published."""
        try:
            from notifications.services.notification_service import NotificationService

            NotificationService.create(
                recipient=user,
                category_code="CLUB_NEWS",
                event_type="club.profile.published",
                title=f"Club profile published: {profile.club.name}",
                message=f"The profile for {profile.club.name} has been published.",
                deduplication_key=f"club-profile-published-{profile.id}",
                data={
                    "club_id": str(profile.club_id),
                    "profile_id": str(profile.id),
                    "version": profile.version,
                },
            )
        except Exception:
            logger.exception("Failed to emit profile published notification")


club_profile_service = ClubProfileService()

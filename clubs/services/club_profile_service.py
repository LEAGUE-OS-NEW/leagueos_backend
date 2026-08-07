"""Club profile service for managing club profile versions."""

from __future__ import annotations

import logging

from django.utils import timezone

from clubs.models import ClubAuditLog, ClubProfileVersion

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
        profile.save(update_fields=["status", "published_at", "published_by"])

        ClubAuditLog.objects.create(
            club=profile.club,
            user=user,
            action="CLUB_PROFILE_UPDATED",
            entity_type="ClubProfileVersion",
            entity_id=profile.id,
            metadata={"action": "published", "version": profile.version},
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


club_profile_service = ClubProfileService()

"""Club following service.

Reuses the canonical ``onboarding.UserClubPreference`` model which
already enforces a unique (user, club) constraint preventing duplicate
follows.  Following a club recalculates the user's dashboard feed,
updates recommendations, and updates notification subscriptions.
"""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.db import transaction

from dashboard.services.dashboard_cache_service import DashboardCacheService
from discovery.models import AuditLog
from onboarding.models import UserClubPreference
from profiles.models import Club

logger = logging.getLogger(__name__)
User = get_user_model()


class FollowingService:
    """Service for club following operations."""

    @staticmethod
    @transaction.atomic
    def follow_club(user: User, club_id: str, request=None) -> UserClubPreference:
        """Follow a club.

        Uses ``get_or_create`` which is safe against duplicate follows
        thanks to the unique (user, club) constraint.

        Returns:
            The created or existing UserClubPreference.

        Raises:
            Club.DoesNotExist: If the club does not exist or is inactive.
        """
        club = Club.objects.get(id=club_id, is_active=True)

        preference, created = UserClubPreference.objects.get_or_create(
            user=user,
            club=club,
        )

        # Recalculate personalization.
        DashboardCacheService.invalidate_all(user)

        # Record audit log.
        AuditLog.objects.create(
            user=user,
            action="CLUB_FOLLOWED",
            entity_type="club",
            entity_id=club_id,
            ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
            user_agent=getattr(request, "META", {}).get("HTTP_USER_AGENT", ""),
            metadata={"created": created},
        )

        return preference

    @staticmethod
    @transaction.atomic
    def unfollow_club(user: User, club_id: str, request=None) -> bool:
        """Unfollow a club.

        Returns:
            True if a follow was removed, False if none existed.
        """
        deleted, _ = UserClubPreference.objects.filter(
            user=user,
            club_id=club_id,
        ).delete()

        # Recalculate personalization.
        DashboardCacheService.invalidate_all(user)

        if deleted:
            AuditLog.objects.create(
                user=user,
                action="CLUB_UNFOLLOWED",
                entity_type="club",
                entity_id=club_id,
                ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
                user_agent=getattr(request, "META", {}).get("HTTP_USER_AGENT", ""),
            )

        return deleted > 0

    @staticmethod
    def get_followed_clubs(user: User):
        """Return the clubs a user follows."""
        return (
            UserClubPreference.objects.filter(user=user)
            .select_related("club", "club__sport", "club__competition")
            .order_by("club__name")
        )

    @staticmethod
    def is_following(user: User, club_id: str) -> bool:
        """Check whether a user follows a club."""
        return UserClubPreference.objects.filter(
            user=user,
            club_id=club_id,
        ).exists()


following_service = FollowingService()

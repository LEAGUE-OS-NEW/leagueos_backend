"""Club profile service."""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db.models import Q

from discovery.models import AuditLog
from profiles.models import Club

logger = logging.getLogger(__name__)


class ClubService:
    """Service for club profile operations."""

    @staticmethod
    def _cache_key(club_id: str) -> str:
        return f"club:{club_id}"

    @classmethod
    def get_public_clubs(cls, sport=None, country=None, search=None, ordering="name"):
        """Return published, verified, active clubs."""
        qs = Club.objects.filter(is_active=True).select_related("sport", "competition")

        if sport:
            qs = qs.filter(sport_id=sport)
        if country:
            qs = qs.filter(country_code=country)
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(slug__icontains=search))

        return qs.order_by(ordering)

    @classmethod
    def get_public_club(cls, club_id: str, request=None):
        """Return a single public club profile with cache."""
        cache_key = cls._cache_key(str(club_id))
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            club = (
                Club.objects.filter(id=club_id, is_active=True)
                .select_related("sport", "competition", "profile", "profile__country")
                .prefetch_related("news_articles")
                .get()
            )
        except Club.DoesNotExist:
            return None

        # Only expose published/verified profile data if present.
        profile = getattr(club, "profile", None)
        if profile and not (profile.is_published and profile.is_verified):
            profile = None

        data = {
            "id": str(club.id),
            "name": club.name,
            "slug": club.slug,
            "sport": str(club.sport_id) if club.sport_id else None,
            "competition": str(club.competition_id) if club.competition_id else None,
            "founded": club.founded,
            "profile": (
                {
                    "logo": profile.logo.url if profile and profile.logo else None,
                    "country": str(profile.country_id) if profile and profile.country_id else None,
                    "stadium": profile.stadium if profile else "",
                    "coach": profile.coach if profile else "",
                    "league": str(profile.league_id) if profile and profile.league_id else None,
                    "description": profile.description if profile else "",
                    "social_links": profile.social_links if profile else {},
                    "current_season": (
                        str(profile.current_season_id)
                        if profile and profile.current_season_id
                        else None
                    ),
                }
                if profile
                else None
            ),
        }

        cache.set(cache_key, data, timeout=300)
        return data

    @staticmethod
    def record_view(club_id: str, user=None, request=None) -> None:
        """Record a club view audit log."""
        try:
            AuditLog.objects.create(
                user=user if user and user.is_authenticated else None,
                action="CLUB_VIEWED",
                entity_type="club",
                entity_id=club_id,
                ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
                user_agent=getattr(request, "META", {}).get("HTTP_USER_AGENT", ""),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to record club view audit log")


club_service = ClubService()

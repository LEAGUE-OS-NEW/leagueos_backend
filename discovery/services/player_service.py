"""Player profile service."""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db.models import Q

from discovery.models import AuditLog
from sports.models import Participant

logger = logging.getLogger(__name__)


class PlayerService:
    """Service for player profile operations."""

    @staticmethod
    def _cache_key(player_id: str) -> str:
        return f"player:{player_id}"

    @classmethod
    def get_public_players(cls, sport=None, club=None, search=None, ordering="name"):
        """Return published, verified, active player profiles."""
        qs = (
            Participant.objects.filter(
                kind=Participant.Kind.ATHLETE,
                is_active=True,
                is_verified=True,
            )
            .select_related("sport")
            .prefetch_related("player_profile")
        )

        if sport:
            qs = qs.filter(sport_id=sport)
        if club:
            qs = qs.filter(player_profile__club_id=club)
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(short_name__icontains=search))

        return qs.order_by(ordering)

    @classmethod
    def get_public_player(cls, player_id: str, request=None):
        """Return a single public player profile with cache."""
        cache_key = cls._cache_key(str(player_id))
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            player = (
                Participant.objects.filter(
                    id=player_id,
                    kind=Participant.Kind.ATHLETE,
                    is_active=True,
                    is_verified=True,
                )
                .select_related("sport", "player_profile", "player_profile__club")
                .get()
            )
        except Participant.DoesNotExist:
            return None

        profile = getattr(player, "player_profile", None)
        if profile and not (profile.is_published and profile.is_verified):
            profile = None

        data = {
            "id": str(player.id),
            "name": player.name,
            "short_name": player.short_name,
            "slug": player.slug,
            "sport": str(player.sport_id) if player.sport_id else None,
            "country_code": player.country_code,
            "profile": (
                {
                    "club": str(profile.club_id) if profile and profile.club_id else None,
                    "position": profile.position if profile else "",
                    "shirt_number": profile.shirt_number if profile else None,
                    "nationality": (
                        str(profile.nationality_id) if profile and profile.nationality_id else None
                    ),
                    "biography": profile.biography if profile else "",
                    "career_history": profile.career_history if profile else [],
                    "statistics": profile.statistics if profile else {},
                    "status": profile.status if profile else "ACTIVE",
                }
                if profile
                else None
            ),
        }

        cache.set(cache_key, data, timeout=300)
        return data

    @staticmethod
    def record_view(player_id: str, user=None, request=None) -> None:
        """Record a player view audit log."""
        try:
            AuditLog.objects.create(
                user=user if user and user.is_authenticated else None,
                action="PLAYER_VIEWED",
                entity_type="player",
                entity_id=player_id,
                ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
                user_agent=getattr(request, "META", {}).get("HTTP_USER_AGENT", ""),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to record player view audit log")


player_service = PlayerService()

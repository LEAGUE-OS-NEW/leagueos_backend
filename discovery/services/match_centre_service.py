"""Match Centre service."""

from __future__ import annotations

import logging

from django.core.cache import cache

from discovery.models import (
    AuditLog,
    MatchCentre,
)
from sports.models import SportingEvent

logger = logging.getLogger(__name__)


class MatchCentreService:
    """Service for match centre aggregation."""

    @staticmethod
    def _cache_key(fixture_id: str) -> str:
        return f"match-centre:{fixture_id}"

    @classmethod
    def get_match_centre(cls, fixture_id: str, request=None):
        """Return the aggregated match centre for a canonical fixture."""
        cache_key = cls._cache_key(str(fixture_id))
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            fixture = SportingEvent.objects.filter(
                id=fixture_id,
                is_verified=True,
                sport__is_active=True,
            ).get()
        except SportingEvent.DoesNotExist:
            return None

        try:
            mc = (
                MatchCentre.objects.filter(fixture=fixture)
                .select_related("venue")
                .prefetch_related(
                    "lineups",
                    "player_statistics",
                    "team_statistics",
                    "timeline_events",
                    "officials",
                    "broadcasts",
                )
                .get()
            )
        except MatchCentre.DoesNotExist:
            mc = None

        data = {
            "fixture": {
                "id": str(fixture.id),
                "name": fixture.name,
                "status": fixture.status,
                "starts_at": fixture.starts_at.isoformat() if fixture.starts_at else None,
                "sport": str(fixture.sport_id) if fixture.sport_id else None,
                "competition": str(fixture.competition_id) if fixture.competition_id else None,
            },
            "result": mc.result if mc else "",
            "home_score": mc.home_score if mc else None,
            "away_score": mc.away_score if mc else None,
            "attendance": mc.attendance if mc else None,
            "venue": (
                {
                    "id": str(mc.venue.id),
                    "name": mc.venue.name,
                    "city": mc.venue.city,
                    "capacity": mc.venue.capacity,
                }
                if mc and mc.venue
                else None
            ),
            "lineups": (
                [
                    {
                        "id": str(lineup.id),
                        "side": lineup.side,
                        "position": lineup.position,
                        "shirt_number": lineup.shirt_number,
                        "is_starter": lineup.is_starter,
                        "player": str(lineup.player_id or lineup.participant_id),
                    }
                    for lineup in mc.lineups.all()
                ]
                if mc
                else []
            ),
            "player_statistics": (
                [
                    {
                        "participant": str(stat.participant_id),
                        "stat_type": stat.stat_type,
                        "value": str(stat.value),
                    }
                    for stat in mc.player_statistics.all()
                ]
                if mc
                else []
            ),
            "team_statistics": (
                [
                    {
                        "participant": str(stat.participant_id),
                        "stat_type": stat.stat_type,
                        "value": str(stat.value),
                    }
                    for stat in mc.team_statistics.all()
                ]
                if mc
                else []
            ),
            "timeline": (
                [
                    {
                        "id": str(event.id),
                        "event_type": event.event_type,
                        "minute": event.minute,
                        "participant": str(event.participant_id) if event.participant_id else None,
                        "player": str(event.player_id) if event.player_id else None,
                        "description": event.description,
                    }
                    for event in mc.timeline_events.all()
                ]
                if mc
                else []
            ),
            "officials": (
                [
                    {
                        "id": str(official.id),
                        "role": official.role,
                        "name": official.name,
                    }
                    for official in mc.officials.all()
                ]
                if mc
                else []
            ),
            "broadcasts": (
                [
                    {
                        "id": str(broadcast.id),
                        "provider": broadcast.provider,
                        "url": broadcast.url,
                        "country_code": broadcast.country_code,
                    }
                    for broadcast in mc.broadcasts.all()
                ]
                if mc
                else []
            ),
            "data_confidence": str(mc.data_confidence) if mc else "0.00",
            "feed_status": mc.feed_status if mc else "PENDING",
            "last_updated": mc.last_updated.isoformat() if mc else None,
        }

        cache.set(cache_key, data, timeout=300)
        return data

    @staticmethod
    def record_view(fixture_id: str, user=None, request=None) -> None:
        """Record a match centre view audit log."""
        try:
            AuditLog.objects.create(
                user=user if user and user.is_authenticated else None,
                action="MATCH_CENTRE_VIEWED",
                entity_type="fixture",
                entity_id=fixture_id,
                ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
                user_agent=getattr(request, "META", {}).get("HTTP_USER_AGENT", ""),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to record match centre view audit log")


match_centre_service = MatchCentreService()

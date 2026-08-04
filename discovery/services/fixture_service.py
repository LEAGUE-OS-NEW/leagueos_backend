"""Fixture service (canonical SportingEvent)."""

from __future__ import annotations

import logging

from django.core.cache import cache

from discovery.models import AuditLog
from sports.models import SportingEvent

logger = logging.getLogger(__name__)


class FixtureService:
    """Service for fixture operations."""

    @staticmethod
    def _cache_key(fixture_id: str) -> str:
        return f"fixture:{fixture_id}"

    @classmethod
    def get_public_fixtures(
        cls,
        sport=None,
        competition=None,
        club=None,
        status=None,
        date_from=None,
        date_to=None,
        ordering="starts_at",
    ):
        """Return verified fixtures with optimized queries."""
        qs = (
            SportingEvent.objects.filter(is_verified=True, sport__is_active=True)
            .select_related("sport", "competition", "competition__sport")
            .prefetch_related("event_participants__participant")
        )

        if sport:
            qs = qs.filter(sport_id=sport)
        if competition:
            qs = qs.filter(competition_id=competition)
        if club:
            qs = qs.filter(event_participants__participant_id=club)
        if status:
            qs = qs.filter(status=status)
        if date_from:
            qs = qs.filter(starts_at__gte=date_from)
        if date_to:
            qs = qs.filter(starts_at__lte=date_to)

        return qs.distinct().order_by(ordering)

    @classmethod
    def get_public_fixture(cls, fixture_id: str, request=None):
        """Return a single verified fixture with cache."""
        cache_key = cls._cache_key(str(fixture_id))
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            fixture = (
                SportingEvent.objects.filter(
                    id=fixture_id,
                    is_verified=True,
                    sport__is_active=True,
                )
                .select_related("sport", "competition", "competition__sport")
                .prefetch_related("event_participants__participant")
                .get()
            )
        except SportingEvent.DoesNotExist:
            return None

        data = {
            "id": str(fixture.id),
            "name": fixture.name,
            "event_type": fixture.event_type,
            "status": fixture.status,
            "starts_at": fixture.starts_at.isoformat() if fixture.starts_at else None,
            "ends_at": fixture.ends_at.isoformat() if fixture.ends_at else None,
            "venue": fixture.venue,
            "country_code": fixture.country_code,
            "sport": str(fixture.sport_id) if fixture.sport_id else None,
            "competition": str(fixture.competition_id) if fixture.competition_id else None,
            "participants": [
                {
                    "role": ep.role,
                    "position": ep.position,
                    "participant": {
                        "id": str(ep.participant.id),
                        "name": ep.participant.name,
                        "short_name": ep.participant.short_name,
                        "kind": ep.participant.kind,
                    },
                }
                for ep in fixture.event_participants.all()
            ],
        }

        cache.set(cache_key, data, timeout=300)
        return data

    @classmethod
    def get_results(
        cls,
        sport=None,
        competition=None,
        club=None,
        date_from=None,
        date_to=None,
        ordering="-starts_at",
    ):
        """Return completed fixtures (results)."""
        return cls.get_public_fixtures(
            sport=sport,
            competition=competition,
            club=club,
            status=SportingEvent.Status.COMPLETED,
            date_from=date_from,
            date_to=date_to,
            ordering=ordering,
        )

    @staticmethod
    def record_view(fixture_id: str, user=None, request=None) -> None:
        """Record a fixture view audit log."""
        try:
            AuditLog.objects.create(
                user=user if user and user.is_authenticated else None,
                action="FIXTURE_VIEWED",
                entity_type="fixture",
                entity_id=fixture_id,
                ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
                user_agent=getattr(request, "META", {}).get("HTTP_USER_AGENT", ""),
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to record fixture view audit log")


fixture_service = FixtureService()

"""Fixture service (canonical SportingEvent)."""

from __future__ import annotations

import logging

from discovery.models import AuditLog
from sports.models import SportingEvent

logger = logging.getLogger(__name__)


class FixtureService:
    """Service for fixture operations.

    Fixture detail/list are deliberately not cached (unlike ClubService) —
    they now carry live score/clock data via MatchCentre, and caching that
    for any meaningful TTL would show stale scores during a live match.
    """

    @classmethod
    def get_public_fixtures(
        cls,
        sport=None,
        competition=None,
        club=None,
        status=None,
        date_from=None,
        date_to=None,
        live_score_featured=None,
        ordering="starts_at",
    ):
        """Return verified fixtures with optimized queries."""
        qs = (
            SportingEvent.objects.filter(is_verified=True, sport__is_active=True)
            .select_related("sport", "competition", "competition__sport", "match_centre", "result_verification")
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
        if live_score_featured:
            qs = qs.filter(is_live_score_featured=True)

        return qs.distinct().order_by(ordering)

    @classmethod
    def get_public_fixture(cls, fixture_id: str, request=None):
        """Return a single verified fixture (model instance, matching
        get_public_fixtures' shape so one serializer handles both)."""
        try:
            return (
                SportingEvent.objects.filter(
                    id=fixture_id,
                    is_verified=True,
                    sport__is_active=True,
                )
                .select_related("sport", "competition", "competition__sport", "match_centre")
                .prefetch_related("event_participants__participant")
                .get()
            )
        except SportingEvent.DoesNotExist:
            return None

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

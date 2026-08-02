"""Fixtures aggregator for gathering upcoming fixtures data."""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.utils import timezone

from dashboard.aggregators.base_aggregator import BaseAggregator

User = get_user_model()
logger = logging.getLogger(__name__)


class FixturesAggregator(BaseAggregator):
    """Aggregates upcoming fixtures for the dashboard."""

    module_code = "fixtures"
    module_name = "Fixtures"

    def aggregate(self, user: User) -> dict:
        """Aggregate fixture data for the user.

        Args:
            user: The user to get fixtures for

        Returns:
            Fixtures data dictionary
        """
        try:
            # Check if sports app is available
            try:
                from sports.models import SportingEvent, Participant
            except ImportError:
                return self._error_response("Sports module not available.")

            # Get user's favourite clubs for personalization
            favourite_club_ids = []
            if hasattr(user, "club_preferences"):
                favourite_club_ids = list(
                    user.club_preferences.values_list("club_id", flat=True)[:20]
                )

            # Get upcoming fixtures
            now = timezone.now()
            upcoming_events = SportingEvent.objects.filter(
                status__in=["SCHEDULED", "LIVE"],
                starts_at__gte=now,
            ).select_related("sport", "competition").prefetch_related(
                "event_participants__participant"
            )

            # Personalize based on favourite clubs
            if favourite_club_ids:
                upcoming_events = upcoming_events.filter(
                    event_participants__participant_id__in=favourite_club_ids
                ).distinct()

            # Get top 10 upcoming fixtures
            events = upcoming_events.order_by("starts_at")[:10]

            fixtures_data = [
                {
                    "id": str(event.id),
                    "name": event.name,
                    "sport": event.sport.name,
                    "competition": event.competition.name if event.competition else None,
                    "starts_at": event.starts_at.isoformat(),
                    "status": event.status,
                    "venue": event.venue or "",
                }
                for event in events
            ]

            data = {
                "upcoming_fixtures": fixtures_data,
                "count": len(fixtures_data),
            }

            if not fixtures_data:
                return self._empty_response(data)

            return self._success_response(data)

        except Exception as e:  # noqa: BLE001
            logger.error("Fixtures aggregation failed for user %s: %s", user.id, str(e))
            return self._error_response("Fixtures service temporarily unavailable.")
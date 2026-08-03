"""Favourites aggregator for gathering favourite clubs and preferences."""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from dashboard.aggregators.base_aggregator import BaseAggregator

User = get_user_model()
logger = logging.getLogger(__name__)


class FavouritesAggregator(BaseAggregator):
    """Aggregates user favourites for the dashboard."""

    module_code = "favourites"
    module_name = "Favourite Clubs"

    def aggregate(self, user: User) -> dict:
        """Aggregate favourite data for the user.

        Args:
            user: The user to get favourites for

        Returns:
            Favourites data dictionary
        """
        try:
            # Get favourite clubs from onboarding preferences
            favourite_clubs = []
            if hasattr(user, "club_preferences"):
                favourite_clubs = [
                    {
                        "id": str(pref.club.id),
                        "name": pref.club.name,
                        "sport": str(pref.club.sport) if pref.club.sport else None,
                        "competition": str(pref.club.competition)
                        if pref.club.competition
                        else None,
                    }
                    for pref in user.club_preferences.select_related(
                        "club__sport", "club__competition"
                    )[:10]
                ]

            # Get favourite sports
            favourite_sports = []
            if hasattr(user, "sport_preferences"):
                favourite_sports = [
                    {
                        "id": str(pref.sport.id),
                        "name": pref.sport.name,
                        "code": pref.sport.code,
                    }
                    for pref in user.sport_preferences.select_related("sport")[:10]
                ]

            # Get favourite competitions
            favourite_competitions = []
            if hasattr(user, "competition_preferences"):
                favourite_competitions = [
                    {
                        "id": str(pref.competition.id),
                        "name": pref.competition.name,
                        "sport": str(pref.competition.sport) if pref.competition.sport else None,
                        "country_code": pref.competition.country_code,
                    }
                    for pref in user.competition_preferences.select_related("competition__sport")[
                        :10
                    ]
                ]

            data = {
                "clubs": favourite_clubs,
                "sports": favourite_sports,
                "competitions": favourite_competitions,
            }

            if not favourite_clubs and not favourite_sports and not favourite_competitions:
                return self._empty_response(data)

            return self._success_response(data)

        except Exception as e:  # noqa: BLE001
            logger.error("Favourites aggregation failed for user %s: %s", user.id, str(e))
            return self._error_response("Favourites service temporarily unavailable.")

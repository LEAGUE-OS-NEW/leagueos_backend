"""Profile aggregator for gathering user profile data."""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from dashboard.aggregators.base_aggregator import BaseAggregator

User = get_user_model()
logger = logging.getLogger(__name__)


class ProfileAggregator(BaseAggregator):
    """Aggregates user profile information for the dashboard."""

    module_code = "profile"
    module_name = "User Profile"

    def aggregate(self, user: User) -> dict:
        """Aggregate profile data for the user.

        Args:
            user: The user to get profile data for

        Returns:
            Profile data dictionary
        """
        try:
            profile = getattr(user, "profile", None)
            if not profile:
                return self._empty_response()

            data = {
                "display_name": profile.display_name or "",
                "avatar_url": profile.get_avatar_url(),
                "country": str(profile.country) if profile.country else None,
                "city": profile.city or "",
                "biography": profile.biography or "",
                "date_of_birth": profile.date_of_birth.isoformat()
                if profile.date_of_birth
                else None,
                "preferred_language": str(profile.preferred_language)
                if profile.preferred_language
                else None,
                "timezone": str(profile.timezone) if profile.timezone else None,
                "favourite_club": str(profile.favourite_club) if profile.favourite_club else None,
                "notification_preferences": profile.notification_preferences or {},
                "communication_preferences": profile.communication_preferences or {},
            }

            return self._success_response(data)

        except Exception as e:  # noqa: BLE001
            logger.error("Profile aggregation failed for user %s: %s", user.id, str(e))
            return self._error_response("Profile service temporarily unavailable.")

"""Dashboard configuration service for the Fan Onboarding module.

Generates the personalized dashboard configuration used to drive
dashboard widgets, news, fixtures, fantasy, notifications, and
recommendations.
"""

from __future__ import annotations

from accounts.models import AuditLog, User
from onboarding.models import OnboardingAnalyticsEvent
from onboarding.services.preference_service import PreferenceService


class DashboardConfigurationService:
    """Service for generating personalized dashboard configurations."""

    @staticmethod
    def generate_dashboard_configuration(user: User, ip_address: str | None = None) -> dict:
        """Generate the personalized dashboard configuration for a user.

        Returns a dict with preferred country, favourite sports,
        competitions, and clubs. Records audit log and analytics event.
        """
        preferred_country = PreferenceService.get_preferred_country(user)
        favourite_sports = list(PreferenceService.get_user_sports(user))
        favourite_competitions = list(PreferenceService.get_user_competitions(user))
        favourite_clubs = list(PreferenceService.get_user_clubs(user))

        onboarding = getattr(user, "onboarding", None)
        onboarding_completed = bool(onboarding and onboarding.completed)

        configuration = {
            "preferred_country": preferred_country,
            "favourite_sports": favourite_sports,
            "favourite_competitions": favourite_competitions,
            "favourite_clubs": favourite_clubs,
            "onboarding_completed": onboarding_completed,
        }

        AuditLog.objects.create(
            user=user,
            action="DASHBOARD_CONFIGURATION_GENERATED",
            ip_address=ip_address,
            metadata={
                "country_id": str(preferred_country.id) if preferred_country else None,
                "sport_ids": [str(s.id) for s in favourite_sports],
                "competition_ids": [str(c.id) for c in favourite_competitions],
                "club_ids": [str(c.id) for c in favourite_clubs],
            },
        )
        OnboardingAnalyticsEvent.objects.create(
            user=user,
            event_type=OnboardingAnalyticsEvent.EventType.DASHBOARD_GENERATED,
            metadata={
                "country_id": str(preferred_country.id) if preferred_country else None,
                "sport_ids": [str(s.id) for s in favourite_sports],
                "competition_ids": [str(c.id) for c in favourite_competitions],
                "club_ids": [str(c.id) for c in favourite_clubs],
            },
        )

        return configuration

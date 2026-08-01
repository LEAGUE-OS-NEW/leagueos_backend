"""Preference service for the Fan Onboarding module.

Handles selection, validation, and persistence of user preferences
for country, sports, competitions, and clubs.
"""

from __future__ import annotations

from uuid import UUID

from accounts.models import AuditLog, User
from onboarding.models import (
    OnboardingAnalyticsEvent,
    UserClubPreference,
    UserCompetitionPreference,
    UserSportPreference,
)
from profiles.models import Club, Country, Profile
from sports.models import Competition, Sport


class PreferenceService:
    """Service for managing user onboarding preferences."""

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    @staticmethod
    def get_user_sport_ids(user: User) -> list[UUID]:
        """Return the list of sport IDs the user has selected."""
        return list(
            UserSportPreference.objects.filter(user=user).values_list("sport_id", flat=True)
        )

    @staticmethod
    def get_user_competition_ids(user: User) -> list[UUID]:
        """Return the list of competition IDs the user has selected."""
        return list(
            UserCompetitionPreference.objects.filter(user=user).values_list(
                "competition_id", flat=True
            )
        )

    @staticmethod
    def get_user_club_ids(user: User) -> list[UUID]:
        """Return the list of club IDs the user has selected."""
        return list(UserClubPreference.objects.filter(user=user).values_list("club_id", flat=True))

    @staticmethod
    def get_user_sports(user: User):
        """Return the user's favourite sports queryset."""
        return Sport.objects.filter(user_preferences__user=user, is_active=True).order_by("name")

    @staticmethod
    def get_user_competitions(user: User):
        """Return the user's favourite competitions queryset."""
        return (
            Competition.objects.filter(user_preferences__user=user, is_active=True)
            .select_related("sport")
            .order_by("sport__name", "name")
        )

    @staticmethod
    def get_user_clubs(user: User):
        """Return the user's favourite clubs queryset."""
        return Club.objects.filter(user_preferences__user=user, is_active=True).order_by("name")

    @staticmethod
    def get_preferred_country(user: User) -> Country | None:
        """Return the user's preferred country from their profile."""
        profile = getattr(user, "profile", None)
        if profile and profile.country_id:
            return profile.country
        return None

    # ------------------------------------------------------------------
    # Selection methods
    # ------------------------------------------------------------------

    @staticmethod
    def select_country(user: User, country: Country, ip_address: str | None = None) -> None:
        """Set the user's preferred country on their profile.

        Records audit log and analytics event.
        """
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.country = country
        profile.save(update_fields=["country", "updated_at"])

        AuditLog.objects.create(
            user=user,
            action="COUNTRY_SELECTED",
            ip_address=ip_address,
            metadata={"country_id": str(country.id), "country_name": country.name},
        )
        OnboardingAnalyticsEvent.objects.create(
            user=user,
            event_type=OnboardingAnalyticsEvent.EventType.STEP_SELECTED,
            metadata={"step": "COUNTRY", "country_id": str(country.id)},
        )

    @staticmethod
    def select_sports(user: User, sports: list[Sport], ip_address: str | None = None) -> None:
        """Replace the user's favourite sports with the given list.

        Records audit log and analytics event.
        """
        UserSportPreference.objects.filter(user=user).delete()
        UserSportPreference.objects.bulk_create(
            [UserSportPreference(user=user, sport=sport) for sport in sports]
        )

        AuditLog.objects.create(
            user=user,
            action="SPORT_SELECTED",
            ip_address=ip_address,
            metadata={"sport_ids": [str(s.id) for s in sports]},
        )
        OnboardingAnalyticsEvent.objects.create(
            user=user,
            event_type=OnboardingAnalyticsEvent.EventType.STEP_SELECTED,
            metadata={"step": "SPORTS", "sport_ids": [str(s.id) for s in sports]},
        )

    @staticmethod
    def select_competitions(
        user: User, competitions: list[Competition], ip_address: str | None = None
    ) -> None:
        """Replace the user's favourite competitions with the given list.

        Records audit log and analytics event.
        """
        UserCompetitionPreference.objects.filter(user=user).delete()
        UserCompetitionPreference.objects.bulk_create(
            [
                UserCompetitionPreference(user=user, competition=competition)
                for competition in competitions
            ]
        )

        AuditLog.objects.create(
            user=user,
            action="COMPETITION_SELECTED",
            ip_address=ip_address,
            metadata={"competition_ids": [str(c.id) for c in competitions]},
        )
        OnboardingAnalyticsEvent.objects.create(
            user=user,
            event_type=OnboardingAnalyticsEvent.EventType.STEP_SELECTED,
            metadata={
                "step": "COMPETITIONS",
                "competition_ids": [str(c.id) for c in competitions],
            },
        )

    @staticmethod
    def select_clubs(user: User, clubs: list[Club], ip_address: str | None = None) -> None:
        """Replace the user's favourite clubs with the given list.

        Records audit log and analytics event.
        """
        UserClubPreference.objects.filter(user=user).delete()
        UserClubPreference.objects.bulk_create(
            [UserClubPreference(user=user, club=club) for club in clubs]
        )

        AuditLog.objects.create(
            user=user,
            action="CLUB_SELECTED",
            ip_address=ip_address,
            metadata={"club_ids": [str(c.id) for c in clubs]},
        )
        OnboardingAnalyticsEvent.objects.create(
            user=user,
            event_type=OnboardingAnalyticsEvent.EventType.STEP_SELECTED,
            metadata={"step": "CLUBS", "club_ids": [str(c.id) for c in clubs]},
        )

    @staticmethod
    def update_preferences_from_profile(
        user: User,
        country: Country | None = None,
        sports: list[Sport] | None = None,
        competitions: list[Competition] | None = None,
        clubs: list[Club] | None = None,
        ip_address: str | None = None,
    ) -> None:
        """Update preferences from the Profile update flow.

        Reuses the same validation and persistence logic as onboarding.
        """
        if country is not None:
            PreferenceService.select_country(user, country, ip_address)
        if sports is not None:
            PreferenceService.select_sports(user, sports, ip_address)
        if competitions is not None:
            PreferenceService.select_competitions(user, competitions, ip_address)
        if clubs is not None:
            PreferenceService.select_clubs(user, clubs, ip_address)

        AuditLog.objects.create(
            user=user,
            action="PREFERENCES_UPDATED",
            ip_address=ip_address,
            metadata={
                "country_id": str(country.id) if country else None,
                "sport_ids": [str(s.id) for s in sports] if sports else [],
                "competition_ids": [str(c.id) for c in competitions] if competitions else [],
                "club_ids": [str(c.id) for c in clubs] if clubs else [],
            },
        )
        OnboardingAnalyticsEvent.objects.create(
            user=user,
            event_type=OnboardingAnalyticsEvent.EventType.PREFERENCES_UPDATED,
            metadata={"source": "profile"},
        )

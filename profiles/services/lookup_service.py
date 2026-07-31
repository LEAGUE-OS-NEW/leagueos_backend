"""Service for retrieving lookup table data.

Provides a clean interface for querying Countries, Languages,
Timezones, Genders, and Clubs used in profile management.
"""

from __future__ import annotations

from profiles.models import Club, Country, Gender, Language, Timezone


class LookupService:
    """Service layer for lookup table queries."""

    @staticmethod
    def get_countries() -> list[Country]:
        """Return all active countries, ordered alphabetically."""
        return list(Country.objects.filter(is_active=True).order_by("name"))

    @staticmethod
    def get_languages() -> list[Language]:
        """Return all active languages, ordered alphabetically."""
        return list(Language.objects.filter(is_active=True).order_by("name"))

    @staticmethod
    def get_timezones() -> list[Timezone]:
        """Return all active timezones, ordered by name."""
        return list(Timezone.objects.filter(is_active=True).order_by("timezone_name"))

    @staticmethod
    def get_genders() -> list[Gender]:
        """Return all active genders, ordered by name."""
        return list(Gender.objects.filter(is_active=True).order_by("name"))

    @staticmethod
    def get_clubs() -> list[Club]:
        """Return all active clubs, ordered alphabetically."""
        return list(Club.objects.filter(is_active=True).order_by("name"))

    @staticmethod
    def get_country_by_id(country_id: str) -> Country | None:
        """Fetch a single active country by its UUID."""
        return Country.objects.filter(id=country_id, is_active=True).first()

    @staticmethod
    def get_language_by_id(language_id: str) -> Language | None:
        """Fetch a single active language by its UUID."""
        return Language.objects.filter(id=language_id, is_active=True).first()

    @staticmethod
    def get_timezone_by_id(timezone_id: str) -> Timezone | None:
        """Fetch a single active timezone by its UUID."""
        return Timezone.objects.filter(id=timezone_id, is_active=True).first()

    @staticmethod
    def get_gender_by_id(gender_id: str) -> Gender | None:
        """Fetch a single active gender by its UUID."""
        return Gender.objects.filter(id=gender_id, is_active=True).first()

    @staticmethod
    def get_club_by_id(club_id: str) -> Club | None:
        """Fetch a single active club by its UUID."""
        return Club.objects.filter(id=club_id, is_active=True).first()

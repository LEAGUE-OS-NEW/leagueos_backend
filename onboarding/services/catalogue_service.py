"""Catalogue service for the Fan Onboarding module.

Provides active-only catalogue queries for countries, sports,
competitions, and clubs used by the preference catalogues.
"""

from __future__ import annotations

from django.db.models import QuerySet

from profiles.models import Club, Country
from sports.models import Competition, Sport


class CatalogueService:
    """Service for retrieving preference catalogues."""

    @staticmethod
    def get_countries() -> QuerySet[Country]:
        """Return all active countries ordered by name."""
        return Country.objects.filter(is_active=True).order_by("name")

    @staticmethod
    def get_sports() -> QuerySet[Sport]:
        """Return all active sports ordered by name."""
        return Sport.objects.filter(is_active=True).order_by("name")

    @staticmethod
    def get_competitions(sport_id=None) -> QuerySet[Competition]:
        """Return active competitions, optionally filtered by sport."""
        queryset = Competition.objects.filter(is_active=True).select_related("sport")
        if sport_id is not None:
            queryset = queryset.filter(sport_id=sport_id)
        return queryset.order_by("sport__name", "name")

    @staticmethod
    def get_clubs(competition_id=None) -> QuerySet[Club]:
        """Return active clubs, optionally filtered by competition."""
        queryset = Club.objects.filter(is_active=True)
        if competition_id is not None:
            queryset = queryset.filter(competition_id=competition_id)
        return queryset.order_by("name")

"""Validators for the Fan Onboarding & Personalization module.

Provides reusable validation helpers for onboarding preference
selections, ensuring entities exist, are active, and satisfy
cross-entity business rules.
"""

from __future__ import annotations

from uuid import UUID

from rest_framework import serializers

from profiles.models import Club, Country
from sports.models import Competition, Sport


def validate_country_exists_and_active(country_id: UUID) -> Country:
    """Validate a country exists and is active.

    Raises:
        serializers.ValidationError: If the country does not exist or is inactive.
    """
    try:
        return Country.objects.get(pk=country_id, is_active=True)
    except Country.DoesNotExist:
        raise serializers.ValidationError("Country does not exist or is inactive.") from None


def validate_sport_exists_and_active(sport_id: UUID) -> Sport:
    """Validate a sport exists and is active.

    Raises:
        serializers.ValidationError: If the sport does not exist or is inactive.
    """
    try:
        return Sport.objects.get(pk=sport_id, is_active=True)
    except Sport.DoesNotExist:
        raise serializers.ValidationError("Sport does not exist or is inactive.") from None


def validate_competition_exists_and_active(competition_id: UUID) -> Competition:
    """Validate a competition exists and is active.

    Raises:
        serializers.ValidationError: If the competition does not exist or is inactive.
    """
    try:
        return Competition.objects.get(pk=competition_id, is_active=True)
    except Competition.DoesNotExist:
        raise serializers.ValidationError("Competition does not exist or is inactive.") from None


def validate_club_exists_and_active(club_id: UUID) -> Club:
    """Validate a club exists and is active.

    Raises:
        serializers.ValidationError: If the club does not exist or is inactive.
    """
    try:
        return Club.objects.get(pk=club_id, is_active=True)
    except Club.DoesNotExist:
        raise serializers.ValidationError("Club does not exist or is inactive.") from None


def validate_competition_belongs_to_sport(competition: Competition, sport_ids: set[UUID]) -> None:
    """Validate a competition belongs to one of the given sports.

    Raises:
        serializers.ValidationError: If the competition's sport is not in sport_ids.
    """
    if competition.sport_id not in sport_ids:
        raise serializers.ValidationError(
            f"Competition '{competition.name}' does not belong to any "
            "of your selected favourite sports."
        )


def validate_club_belongs_to_competition(club: Club, competition_ids: set[UUID]) -> None:
    """Validate a club belongs to one of the given competitions (when linked).

    Clubs without a linked competition are always allowed.

    Raises:
        serializers.ValidationError: If the club's competition is not in competition_ids.
    """
    if club.competition_id and club.competition_id not in competition_ids:
        raise serializers.ValidationError(
            f"Club '{club.name}' does not belong to any of your " "selected favourite competitions."
        )


def validate_competition_country(competition: Competition, country: Country | None) -> None:
    """Validate a competition's country matches the user's preferred country.

    International competitions (blank or 'XX' country_code) are always allowed.
    If the user has no preferred country, any competition is allowed.

    Raises:
        serializers.ValidationError: If the competition's country does not match.
    """
    if country is None:
        return
    competition_country = (competition.country_code or "").upper()
    if competition_country and competition_country not in ("XX", country.iso_code.upper()):
        raise serializers.ValidationError(
            f"Competition '{competition.name}' is not available in your "
            f"preferred country ({country.name})."
        )

"""Serializers for the Fan Onboarding & Personalization module."""

from __future__ import annotations

from uuid import UUID

from rest_framework import serializers

from onboarding.models import UserOnboarding
from onboarding.services.preference_service import PreferenceService
from profiles.models import Club, Country
from sports.models import Competition, Sport

# =============================================================================
# Catalogue Serializers
# =============================================================================


class CountryCatalogueSerializer(serializers.ModelSerializer):
    """Serializer for the country preference catalogue."""

    class Meta:
        model = Country
        fields = ["id", "name", "iso_code"]
        read_only_fields = fields


class SportCatalogueSerializer(serializers.ModelSerializer):
    """Serializer for the sport preference catalogue."""

    class Meta:
        model = Sport
        fields = ["id", "name", "code", "slug"]
        read_only_fields = fields


class CompetitionCatalogueSerializer(serializers.ModelSerializer):
    """Serializer for the competition preference catalogue."""

    sport = SportCatalogueSerializer(read_only=True)

    class Meta:
        model = Competition
        fields = ["id", "name", "slug", "country_code", "is_verified", "sport"]
        read_only_fields = fields


class ClubCatalogueSerializer(serializers.ModelSerializer):
    """Serializer for the club preference catalogue."""

    class Meta:
        model = Club
        fields = ["id", "name", "slug", "founded"]
        read_only_fields = fields


# =============================================================================
# Onboarding Selection Serializers
# =============================================================================


class CountrySelectionSerializer(serializers.Serializer):
    """Serializer for selecting the preferred country during onboarding."""

    country_id = serializers.UUIDField()

    def validate_country_id(self, value: UUID) -> UUID:
        """Validate the country exists and is active."""
        try:
            country = Country.objects.get(pk=value, is_active=True)
        except Country.DoesNotExist:
            raise serializers.ValidationError("Country does not exist or is inactive.") from None
        self.context["country"] = country
        return value


class SportSelectionSerializer(serializers.Serializer):
    """Serializer for selecting favourite sports during onboarding."""

    sport_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=True,
    )

    def validate_sport_ids(self, value: list[UUID]) -> list[UUID]:
        """Validate sports exist, are active, and are unique."""
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Duplicate sport selections are not allowed.")
        sports = Sport.objects.filter(pk__in=value, is_active=True)
        if sports.count() != len(value):
            raise serializers.ValidationError("One or more sports do not exist or are inactive.")
        self.context["sports"] = list(sports)
        return value


class CompetitionSelectionSerializer(serializers.Serializer):
    """Serializer for selecting favourite competitions during onboarding.

    Validates that each competition is active and belongs to one of
    the user's selected favourite sports.
    """

    competition_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=True,
    )

    def validate_competition_ids(self, value: list[UUID]) -> list[UUID]:
        """Validate competitions exist, are active, unique, and belong to user's sports."""
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Duplicate competition selections are not allowed.")
        competitions = Competition.objects.filter(pk__in=value, is_active=True)
        if competitions.count() != len(value):
            raise serializers.ValidationError(
                "One or more competitions do not exist or are inactive."
            )
        competitions = list(competitions)

        # Ensure each competition belongs to one of the user's selected sports
        user_sport_ids = set(PreferenceService.get_user_sport_ids(self.context["request"].user))
        for competition in competitions:
            if competition.sport_id not in user_sport_ids:
                raise serializers.ValidationError(
                    f"Competition '{competition.name}' does not belong to any "
                    "of your selected favourite sports."
                )
        self.context["competitions"] = competitions
        return value


class ClubSelectionSerializer(serializers.Serializer):
    """Serializer for selecting favourite clubs during onboarding.

    Validates that each club is active and belongs to one of the user's
    selected competitions (when the club is linked to a competition).
    """

    club_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=True,
    )

    def validate_club_ids(self, value: list[UUID]) -> list[UUID]:
        """Validate clubs exist, are active, unique, and belong to user's competitions."""
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Duplicate club selections are not allowed.")
        clubs = Club.objects.filter(pk__in=value, is_active=True)
        if clubs.count() != len(value):
            raise serializers.ValidationError("One or more clubs do not exist or are inactive.")
        clubs = list(clubs)

        # Ensure each club's competition (when set) is in user's selected competitions
        user_competition_ids = set(
            PreferenceService.get_user_competition_ids(self.context["request"].user)
        )
        for club in clubs:
            if club.competition_id and club.competition_id not in user_competition_ids:
                raise serializers.ValidationError(
                    f"Club '{club.name}' does not belong to any of your "
                    "selected favourite competitions."
                )
        self.context["clubs"] = clubs
        return value


class SkipStepSerializer(serializers.Serializer):
    """Serializer for skipping an onboarding step."""

    step = serializers.ChoiceField(
        choices=[
            UserOnboarding.Step.COUNTRY,
            UserOnboarding.Step.SPORTS,
            UserOnboarding.Step.COMPETITIONS,
            UserOnboarding.Step.CLUBS,
        ]
    )


# =============================================================================
# Onboarding Status & Dashboard Serializers
# =============================================================================


class OnboardingSerializer(serializers.ModelSerializer):
    """Serializer for the full onboarding status response."""

    completed_steps = serializers.SerializerMethodField()
    completion_percentage = serializers.SerializerMethodField()
    preferred_country = serializers.SerializerMethodField()
    favourite_sports = serializers.SerializerMethodField()
    favourite_competitions = serializers.SerializerMethodField()
    favourite_clubs = serializers.SerializerMethodField()

    class Meta:
        model = UserOnboarding
        fields = [
            "id",
            "current_step",
            "completed",
            "completed_at",
            "skipped_steps",
            "completed_steps",
            "completion_percentage",
            "preferred_country",
            "favourite_sports",
            "favourite_competitions",
            "favourite_clubs",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_completed_steps(self, obj: UserOnboarding) -> list[str]:
        return obj.completed_steps

    def get_completion_percentage(self, obj: UserOnboarding) -> int:
        return obj.completion_percentage

    def get_preferred_country(self, obj: UserOnboarding):
        country = self.context.get("preferred_country")
        return CountryCatalogueSerializer(country).data if country else None

    def get_favourite_sports(self, obj: UserOnboarding):
        sports = self.context.get("favourite_sports", [])
        return SportCatalogueSerializer(sports, many=True).data

    def get_favourite_competitions(self, obj: UserOnboarding):
        competitions = self.context.get("favourite_competitions", [])
        return CompetitionCatalogueSerializer(competitions, many=True).data

    def get_favourite_clubs(self, obj: UserOnboarding):
        clubs = self.context.get("favourite_clubs", [])
        return ClubCatalogueSerializer(clubs, many=True).data


class DashboardConfigurationSerializer(serializers.Serializer):
    """Serializer for the personalized dashboard configuration."""

    preferred_country = CountryCatalogueSerializer(read_only=True)
    favourite_sports = SportCatalogueSerializer(many=True, read_only=True)
    favourite_competitions = CompetitionCatalogueSerializer(many=True, read_only=True)
    favourite_clubs = ClubCatalogueSerializer(many=True, read_only=True)
    onboarding_completed = serializers.BooleanField(read_only=True)

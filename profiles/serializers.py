"""Serializers for the profiles app.

Provides serializers for Profile, lookup tables (Country, Language,
Timezone, Gender), Club, and avatar management operations.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from django.contrib.auth import get_user_model
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from profiles.models import Club, Country, Gender, Language, Profile, Timezone
from profiles.services.profile_service import ProfileService
from profiles.validators import sanitize_text
from sports.models import Competition, Sport

User = get_user_model()


# =============================================================================
# Lookup Serializers
# =============================================================================


class CountrySerializer(serializers.ModelSerializer):
    """Serializer for the Country lookup table."""

    class Meta:
        model = Country
        fields = ["id", "name", "iso_code", "is_active"]
        read_only_fields = ["id", "name", "iso_code", "is_active"]


class LanguageSerializer(serializers.ModelSerializer):
    """Serializer for the Language lookup table."""

    class Meta:
        model = Language
        fields = ["id", "name", "code", "is_active"]
        read_only_fields = ["id", "name", "code", "is_active"]


class TimezoneSerializer(serializers.ModelSerializer):
    """Serializer for the Timezone lookup table."""

    class Meta:
        model = Timezone
        fields = ["id", "timezone_name", "utc_offset", "is_active"]
        read_only_fields = ["id", "timezone_name", "utc_offset", "is_active"]


class GenderSerializer(serializers.ModelSerializer):
    """Serializer for the Gender lookup table."""

    class Meta:
        model = Gender
        fields = ["id", "name", "code", "is_active"]
        read_only_fields = ["id", "name", "code", "is_active"]


class ClubSerializer(serializers.ModelSerializer):
    """Serializer for the Club model."""

    logo = serializers.SerializerMethodField()

    class Meta:
        model = Club
        fields = ["id", "name", "slug", "founded", "logo", "is_active"]
        read_only_fields = fields

    def get_logo(self, obj):
        if not obj.logo:
            return None
        from profiles.services.storage_service import StorageService

        return StorageService.get_public_url(obj.logo.name)


class ClubCreateSerializer(serializers.ModelSerializer):
    """Writable serializer for creating a Club (Super Admin / admin.clubs.manage only).

    slug is auto-derived from name (with a numeric suffix on collision)
    when omitted.
    """

    slug = serializers.SlugField(required=False)
    sport = serializers.PrimaryKeyRelatedField(queryset=Sport.objects.filter(is_active=True))
    competition = serializers.PrimaryKeyRelatedField(
        queryset=Competition.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Club
        fields = ["id", "name", "slug", "sport", "competition", "founded", "is_active"]
        read_only_fields = ["id", "is_active"]

    def validate_name(self, value: str) -> str:
        value = sanitize_text(value).strip()
        if not value:
            raise serializers.ValidationError("Club name is required.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        competition = attrs.get("competition")
        sport = attrs.get("sport")
        if competition and sport and competition.sport_id != sport.id:
            raise serializers.ValidationError(
                {"competition": "Competition must belong to the selected sport."}
            )
        return attrs

    def create(self, validated_data: dict[str, Any]) -> Club:
        if not validated_data.get("slug"):
            base_slug = slugify(validated_data["name"])
            slug = base_slug
            suffix = 1
            while Club.objects.filter(slug=slug).exists():
                suffix += 1
                slug = f"{base_slug}-{suffix}"
            validated_data["slug"] = slug
        return super().create(validated_data)


# =============================================================================
# Profile Serializers
# =============================================================================


class _UserSerializer(serializers.ModelSerializer):
    """Minimal user serializer for nested profile representation."""

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name"]


class ProfileSerializer(serializers.ModelSerializer):
    """Read-only serializer for displaying a user's full profile.

    Includes nested user fields (first_name, last_name, email),
    lookup references (country, language, timezone, gender),
    and avatar information.
    """

    user = _UserSerializer(read_only=True)
    gender = GenderSerializer(read_only=True)
    country = CountrySerializer(read_only=True)
    preferred_language = LanguageSerializer(read_only=True)
    timezone = TimezoneSerializer(read_only=True)
    favourite_club = ClubSerializer(read_only=True)
    favourite_sports = serializers.SerializerMethodField()
    favourite_competitions = serializers.SerializerMethodField()
    first_name = serializers.SerializerMethodField()
    last_name = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = [
            "id",
            "user",
            "first_name",
            "last_name",
            "email",
            "display_name",
            "date_of_birth",
            "gender",
            "country",
            "city",
            "preferred_language",
            "timezone",
            "biography",
            "favourite_club",
            "favourite_sports",
            "favourite_competitions",
            "avatar",
            "avatar_url",
            "avatar_updated_at",
            "communication_preferences",
            "notification_preferences",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_first_name(self, obj: Profile) -> str | None:
        return obj.user.first_name

    def get_last_name(self, obj: Profile) -> str | None:
        return obj.user.last_name

    def get_email(self, obj: Profile) -> str | None:
        return obj.user.email

    def get_avatar_url(self, obj: Profile) -> str | None:
        return obj.get_avatar_url()

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_favourite_sports(self, obj: Profile):
        from onboarding.services.preference_service import PreferenceService

        return PreferenceService.get_user_sports(obj.user)

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_favourite_competitions(self, obj: Profile):
        from onboarding.services.preference_service import PreferenceService

        return PreferenceService.get_user_competitions(obj.user)


class ProfileUpdateSerializer(serializers.Serializer):
    """Serializer for updating a user's profile.

    Allows updates for: first_name, last_name, display_name,
    date_of_birth, gender, country, city, biography, favourite_club,
    preferred_language, timezone, communication_preferences,
    notification_preferences.

    Does NOT allow updates for: email, roles, account status,
    verification status.
    """

    first_name = serializers.CharField(max_length=150, required=False)
    last_name = serializers.CharField(max_length=150, required=False)
    display_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.PrimaryKeyRelatedField(
        queryset=Gender.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    country = serializers.PrimaryKeyRelatedField(
        queryset=Country.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    biography = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    favourite_club = serializers.PrimaryKeyRelatedField(
        queryset=Club.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    favourite_sports = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
    )
    favourite_competitions = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
    )
    preferred_language = serializers.PrimaryKeyRelatedField(
        queryset=Language.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    timezone = serializers.PrimaryKeyRelatedField(
        queryset=Timezone.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    communication_preferences = serializers.JSONField(required=False)
    notification_preferences = serializers.JSONField(required=False)

    def validate_first_name(self, value: str) -> str:
        """Sanitize first name: strip spaces, prevent XSS, normalize Unicode."""
        return sanitize_text(value)

    def validate_last_name(self, value: str) -> str:
        """Sanitize last name: strip spaces, prevent XSS, normalize Unicode."""
        return sanitize_text(value)

    def validate_display_name(self, value: str) -> str:
        """Sanitize display name."""
        return sanitize_text(value)

    def validate_city(self, value: str) -> str:
        """Sanitize city name."""
        return sanitize_text(value)

    def validate_biography(self, value: str) -> str:
        """Sanitize biography text."""
        return sanitize_text(value)

    def validate_date_of_birth(self, value: date | None) -> date | None:
        """Validate date of birth is not in the future and meets minimum age."""
        if value is not None:
            ProfileService.validate_date_of_birth(value)
        return value

    def validate_favourite_sports(self, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Duplicate sport selections are not allowed.")
        sports = Sport.objects.filter(pk__in=value, is_active=True)
        if sports.count() != len(value):
            raise serializers.ValidationError("One or more sports do not exist or are inactive.")
        return value

    def validate_favourite_competitions(self, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Duplicate competition selections are not allowed.")
        competitions = Competition.objects.filter(pk__in=value, is_active=True)
        if competitions.count() != len(value):
            raise serializers.ValidationError(
                "One or more competitions do not exist or are inactive."
            )
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Run cross-field validation."""
        return attrs


class AvatarUploadSerializer(serializers.Serializer):
    """Serializer for avatar upload requests."""

    avatar = serializers.ImageField(
        max_length=None,
        use_url=False,
        required=True,
    )

    class Meta:
        fields = ["avatar"]


class AvatarSerializer(serializers.ModelSerializer):
    """Serializer for returning avatar metadata and URL."""

    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = ["id", "avatar", "avatar_url", "avatar_updated_at"]
        read_only_fields = fields

    def get_avatar_url(self, obj: Profile) -> str | None:
        return obj.get_avatar_url()

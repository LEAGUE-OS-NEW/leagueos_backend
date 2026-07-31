import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Country(models.Model):
    """Lookup table for countries."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    iso_code = models.CharField(max_length=2, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Countries"

    def __str__(self) -> str:
        return self.name


class Language(models.Model):
    """Lookup table for languages."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Timezone(models.Model):
    """Lookup table for timezones."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timezone_name = models.CharField(max_length=100, unique=True)
    utc_offset = models.CharField(max_length=10)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["timezone_name"]

    def __str__(self) -> str:
        return self.timezone_name


class Gender(models.Model):
    """Lookup table for genders."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50, unique=True)
    code = models.CharField(max_length=10, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Club(models.Model):
    """Model representing a sports club.

    Used as the favourite club selection for user profiles.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=200, unique=True)
    founded = models.PositiveIntegerField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


def user_avatar_upload_to(instance: "Profile", filename: str) -> str:
    """Generate upload path for user avatar images.

    Uses UUID-based directory structure to prevent filename collisions
    and protect against path traversal attacks.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    return f"avatars/{instance.user.id}/{instance.user.id}.{ext}"


class Profile(models.Model):
    """User profile model storing extended user information.

    Each user has exactly one profile. Communication and notification
    preferences are stored as JSON dictionaries for flexibility.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    display_name = models.CharField(max_length=150, blank=True)
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.ForeignKey(
        "profiles.Gender",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="profiles",
    )
    country = models.ForeignKey(
        "profiles.Country",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="profiles",
    )
    city = models.CharField(max_length=100, blank=True)
    preferred_language = models.ForeignKey(
        "profiles.Language",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="profiles",
    )
    timezone = models.ForeignKey(
        "profiles.Timezone",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="profiles",
    )
    biography = models.TextField(blank=True)
    favourite_club = models.ForeignKey(
        "profiles.Club",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="favourite_of_profiles",
    )
    avatar = models.ImageField(
        upload_to=user_avatar_upload_to,
        blank=True,
        null=True,
    )
    avatar_updated_at = models.DateTimeField(blank=True, null=True)

    # Communication preferences: e.g. {"email": true, "sms": false}
    communication_preferences = models.JSONField(default=dict, blank=True)
    # Notification preferences: e.g. {"match_updates": true, "club_news": false}
    notification_preferences = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["favourite_club"]),
        ]

    def __str__(self) -> str:
        return f"Profile for {self.user}"

    def get_avatar_url(self) -> str | None:
        """Return the avatar URL if available, otherwise the default avatar URL."""
        if self.avatar:
            return self.avatar.url
        return getattr(settings, "DEFAULT_AVATAR_URL", None)

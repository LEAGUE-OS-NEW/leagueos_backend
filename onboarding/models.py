"""Models for the Fan Onboarding & Personalization module."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class UserOnboarding(models.Model):
    """Tracks a user's onboarding progress through the guided flow.

    Steps: COUNTRY → SPORTS → COMPETITIONS → CLUBS → COMPLETED.
    Users may skip any step and resume later.
    """

    class Step(models.TextChoices):
        COUNTRY = "COUNTRY", "Select Country"
        SPORTS = "SPORTS", "Select Favourite Sports"
        COMPETITIONS = "COMPETITIONS", "Select Favourite Competitions"
        CLUBS = "CLUBS", "Select Favourite Clubs"
        COMPLETED = "COMPLETED", "Completed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="onboarding",
    )
    current_step = models.CharField(
        max_length=20,
        choices=Step.choices,
        default=Step.COUNTRY,
    )
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    skipped_steps = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["completed"]),
        ]

    def __str__(self) -> str:
        return f"Onboarding for {self.user} ({self.current_step})"

    @property
    def completion_percentage(self) -> int:
        """Return the onboarding completion percentage (0-100)."""
        if self.completed:
            return 100
        step_order = [
            self.Step.COUNTRY,
            self.Step.SPORTS,
            self.Step.COMPETITIONS,
            self.Step.CLUBS,
        ]
        if self.current_step == self.Step.COMPLETED:
            return 100
        try:
            current_index = step_order.index(self.current_step)
        except ValueError:
            return 0
        return int((current_index / len(step_order)) * 100)

    @property
    def completed_steps(self) -> list[str]:
        """Return the list of completed step names."""
        if self.completed:
            return [step for step in self.Step.values if step != self.Step.COMPLETED]
        step_order = [
            self.Step.COUNTRY,
            self.Step.SPORTS,
            self.Step.COMPETITIONS,
            self.Step.CLUBS,
        ]
        try:
            current_index = step_order.index(self.current_step)
        except ValueError:
            return []
        return step_order[:current_index]


class UserSportPreference(models.Model):
    """Relational table linking a user to their favourite sports."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sport_preferences",
    )
    sport = models.ForeignKey(
        "sports.Sport",
        on_delete=models.PROTECT,
        related_name="user_preferences",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sport__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "sport"],
                name="unique_user_sport_preference",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "sport"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} → {self.sport}"


class UserCompetitionPreference(models.Model):
    """Relational table linking a user to their favourite competitions."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="competition_preferences",
    )
    competition = models.ForeignKey(
        "sports.Competition",
        on_delete=models.PROTECT,
        related_name="user_preferences",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["competition__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "competition"],
                name="unique_user_competition_preference",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "competition"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} → {self.competition}"


class UserClubPreference(models.Model):
    """Relational table linking a user to their favourite clubs."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="club_preferences",
    )
    club = models.ForeignKey(
        "profiles.Club",
        on_delete=models.PROTECT,
        related_name="user_preferences",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["club__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "club"],
                name="unique_user_club_preference",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "club"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} → {self.club}"


class OnboardingAnalyticsEvent(models.Model):
    """Event log for onboarding analytics.

    Designed to power future analytics dashboards: most selected sports,
    competitions, clubs, completion rates, skipped steps, etc.
    """

    class EventType(models.TextChoices):
        STARTED = "STARTED", "Started"
        STEP_SELECTED = "STEP_SELECTED", "Step Selected"
        STEP_SKIPPED = "STEP_SKIPPED", "Step Skipped"
        COMPLETED = "COMPLETED", "Completed"
        RESUMED = "RESUMED", "Resumed"
        PREFERENCES_UPDATED = "PREFERENCES_UPDATED", "Preferences Updated"
        DASHBOARD_GENERATED = "DASHBOARD_GENERATED", "Dashboard Generated"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="onboarding_analytics_events",
    )
    event_type = models.CharField(
        max_length=30,
        choices=EventType.choices,
        db_index=True,
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "event_type"]),
            models.Index(fields=["event_type", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} - {self.user} - {self.created_at.isoformat()}"

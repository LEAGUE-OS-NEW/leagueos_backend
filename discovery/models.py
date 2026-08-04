"""Discovery, Search, and Match Centre models.

Reuses canonical sporting entities from the ``sports`` and ``profiles``
apps.  Only adds models that do not already exist anywhere in the
codebase.  All business data is database-driven — nothing is hardcoded.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from profiles.models import Club, Country
from sports.models import Competition, Participant, Sport, SportingEvent


class TimeStampedUUIDModel(models.Model):
    """Abstract base with a UUID primary key and timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# =============================================================================
# Venue & Season
# =============================================================================


class Venue(TimeStampedUUIDModel):
    """Canonical venue entity."""

    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=280, unique=True, blank=True)
    country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        related_name="venues",
        null=True,
        blank=True,
    )
    country_code = models.CharField(max_length=2, blank=True)
    city = models.CharField(max_length=180, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    source_name = models.CharField(max_length=120, blank=True)
    source_reference = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    is_verified = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active", "is_verified"]),
            models.Index(fields=["country_code", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.country_code = self.country_code.strip().upper()
        self.source_name = self.source_name.strip()
        self.source_reference = self.source_reference.strip()
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Season(TimeStampedUUIDModel):
    """Canonical season entity."""

    sport = models.ForeignKey(
        Sport,
        on_delete=models.PROTECT,
        related_name="seasons",
    )
    competition = models.ForeignKey(
        Competition,
        on_delete=models.PROTECT,
        related_name="seasons",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, blank=True)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    is_verified = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-starts_on", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["sport", "competition", "slug"],
                name="unique_season_identity",
            )
        ]
        indexes = [
            models.Index(fields=["sport", "is_active"]),
            models.Index(fields=["competition", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.sport.name})"

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}
        if self.competition_id and self.competition.sport_id != self.sport_id:
            errors["competition"] = "Competition sport must match the season sport."
        if self.ends_on and self.starts_on and self.ends_on < self.starts_on:
            errors["ends_on"] = "Season end date must be after its start date."
        if errors:
            raise ValidationError(errors)


# =============================================================================
# Club & Player Profiles
# =============================================================================


class ClubProfile(TimeStampedUUIDModel):
    """Extended public profile for a canonical ``profiles.Club``."""

    club = models.OneToOneField(
        Club,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    logo = models.ImageField(upload_to="clubs/logos/", blank=True, null=True)
    country = models.ForeignKey(
        Country,
        on_delete=models.SET_NULL,
        related_name="club_profiles",
        null=True,
        blank=True,
    )
    stadium = models.CharField(max_length=255, blank=True)
    coach = models.CharField(max_length=180, blank=True)
    league = models.ForeignKey(
        Competition,
        on_delete=models.SET_NULL,
        related_name="club_profiles",
        null=True,
        blank=True,
    )
    founded = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    social_links = models.JSONField(default=dict, blank=True)
    current_season = models.ForeignKey(
        Season,
        on_delete=models.SET_NULL,
        related_name="club_profiles",
        null=True,
        blank=True,
    )
    is_published = models.BooleanField(default=True, db_index=True)
    is_verified = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["club__name"]
        indexes = [
            models.Index(fields=["is_published", "is_verified"]),
            models.Index(fields=["club", "is_published"]),
        ]

    def __str__(self) -> str:
        return f"Profile for {self.club.name}"


class PlayerProfile(TimeStampedUUIDModel):
    """Extended public profile for a canonical athlete ``Participant``."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INJURED = "INJURED", "Injured"
        SUSPENDED = "SUSPENDED", "Suspended"
        RETIRED = "RETIRED", "Retired"
        TRANSFERRED = "TRANSFERRED", "Transferred"

    participant = models.OneToOneField(
        Participant,
        on_delete=models.CASCADE,
        related_name="player_profile",
    )
    club = models.ForeignKey(
        Club,
        on_delete=models.SET_NULL,
        related_name="player_profiles",
        null=True,
        blank=True,
    )
    position = models.CharField(max_length=100, blank=True)
    shirt_number = models.PositiveSmallIntegerField(null=True, blank=True)
    nationality = models.ForeignKey(
        Country,
        on_delete=models.SET_NULL,
        related_name="player_profiles",
        null=True,
        blank=True,
    )
    biography = models.TextField(blank=True)
    career_history = models.JSONField(default=list, blank=True)
    statistics = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    is_published = models.BooleanField(default=True, db_index=True)
    is_verified = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["participant__name"]
        indexes = [
            models.Index(fields=["is_published", "is_verified"]),
            models.Index(fields=["club", "is_published"]),
            models.Index(fields=["status", "is_published"]),
        ]

    def __str__(self) -> str:
        return f"Profile for {self.participant.name}"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.participant_id and self.participant.kind != Participant.Kind.ATHLETE:
            raise ValidationError(
                {"participant": "A player profile requires an ATHLETE participant."}
            )


# =============================================================================
# News
# =============================================================================


class NewsCategory(TimeStampedUUIDModel):
    """Database-driven news category."""

    code = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    display_order = models.IntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["display_order", "name"]
        indexes = [
            models.Index(fields=["is_active", "display_order"]),
        ]

    def __str__(self) -> str:
        return self.name


class News(TimeStampedUUIDModel):
    """News article referencing canonical sporting entities."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING_APPROVAL = "PENDING_APPROVAL", "Pending approval"
        APPROVED = "APPROVED", "Approved"
        PUBLISHED = "PUBLISHED", "Published"
        REJECTED = "REJECTED", "Rejected"
        ARCHIVED = "ARCHIVED", "Archived"

    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=320, unique=True, blank=True)
    summary = models.TextField(blank=True)
    body = models.TextField()
    category = models.ForeignKey(
        NewsCategory,
        on_delete=models.PROTECT,
        related_name="news_articles",
    )
    sport = models.ForeignKey(
        Sport,
        on_delete=models.PROTECT,
        related_name="news_articles",
        null=True,
        blank=True,
    )
    competition = models.ForeignKey(
        Competition,
        on_delete=models.PROTECT,
        related_name="news_articles",
        null=True,
        blank=True,
    )
    club = models.ForeignKey(
        Club,
        on_delete=models.PROTECT,
        related_name="news_articles",
        null=True,
        blank=True,
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name="news_articles",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    is_featured = models.BooleanField(default=False, db_index=True)
    is_verified = models.BooleanField(default=False, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_news",
        null=True,
        blank=True,
    )
    source_name = models.CharField(max_length=120, blank=True)
    source_reference = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]
        indexes = [
            models.Index(fields=["status", "is_verified", "published_at"]),
            models.Index(fields=["is_featured", "status", "published_at"]),
            models.Index(fields=["category", "status", "published_at"]),
            models.Index(fields=["club", "status", "published_at"]),
            models.Index(fields=["competition", "status", "published_at"]),
        ]

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        self.title = self.title.strip()
        self.source_name = self.source_name.strip()
        self.source_reference = self.source_reference.strip()
        if not self.slug:
            self.slug = slugify(self.title)
        if self.status == self.Status.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}
        if self.sport_id and self.competition_id and self.competition.sport_id != self.sport_id:
            errors["competition"] = "Competition sport must match the article sport."
        if (
            self.sport_id
            and self.club_id
            and self.club.sport_id
            and self.club.sport_id != self.sport_id
        ):
            errors["club"] = "Club sport must match the article sport."
        if self.status == self.Status.PUBLISHED and self.published_at is None:
            self.published_at = timezone.now()
        if errors:
            raise ValidationError(errors)


# =============================================================================
# Match Centre (canonical fixture = SportingEvent)
# =============================================================================


class MatchCentre(TimeStampedUUIDModel):
    """Single canonical match centre record for a fixture."""

    class FeedStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"
        PARTIAL = "PARTIAL", "Partial"

    fixture = models.OneToOneField(
        SportingEvent,
        on_delete=models.CASCADE,
        related_name="match_centre",
    )
    result = models.CharField(max_length=255, blank=True)
    home_score = models.PositiveSmallIntegerField(null=True, blank=True)
    away_score = models.PositiveSmallIntegerField(null=True, blank=True)
    attendance = models.PositiveIntegerField(null=True, blank=True)
    venue = models.ForeignKey(
        Venue,
        on_delete=models.SET_NULL,
        related_name="match_centres",
        null=True,
        blank=True,
    )
    data_confidence = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Confidence 0.00 - 1.00",
    )
    feed_status = models.CharField(
        max_length=20,
        choices=FeedStatus.choices,
        default=FeedStatus.PENDING,
        db_index=True,
    )
    is_verified = models.BooleanField(default=False, db_index=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(data_confidence__gte=0) & models.Q(data_confidence__lte=1),
                name="match_centre_confidence_range",
            )
        ]
        indexes = [
            models.Index(fields=["fixture", "feed_status"]),
            models.Index(fields=["feed_status", "is_verified"]),
        ]

    def __str__(self) -> str:
        return f"Match centre for {self.fixture.name}"


class MatchLineup(TimeStampedUUIDModel):
    """A player in a fixture lineup."""

    match_centre = models.ForeignKey(
        MatchCentre,
        on_delete=models.CASCADE,
        related_name="lineups",
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name="match_lineups",
    )
    player = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name="player_lineups",
        null=True,
        blank=True,
    )
    side = models.CharField(max_length=10, choices=[("HOME", "Home"), ("AWAY", "Away")])
    position = models.CharField(max_length=100, blank=True)
    shirt_number = models.PositiveSmallIntegerField(null=True, blank=True)
    is_starter = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["match_centre", "side", "is_starter", "position"]
        indexes = [
            models.Index(fields=["match_centre", "side", "is_starter"]),
            models.Index(fields=["player", "match_centre"]),
        ]

    def __str__(self) -> str:
        return f"{self.match_centre_id} - {self.player_id or self.participant_id}"


class MatchPlayerStatistic(TimeStampedUUIDModel):
    """Per-player statistic for a fixture."""

    match_centre = models.ForeignKey(
        MatchCentre,
        on_delete=models.CASCADE,
        related_name="player_statistics",
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name="match_player_statistics",
    )
    stat_type = models.CharField(max_length=100, db_index=True)
    value = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["match_centre", "stat_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["match_centre", "participant", "stat_type"],
                name="unique_player_stat_per_match",
            )
        ]
        indexes = [
            models.Index(fields=["match_centre", "stat_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.stat_type}: {self.value}"


class MatchTeamStatistic(TimeStampedUUIDModel):
    """Per-team aggregate statistic for a fixture."""

    match_centre = models.ForeignKey(
        MatchCentre,
        on_delete=models.CASCADE,
        related_name="team_statistics",
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name="match_team_statistics",
    )
    stat_type = models.CharField(max_length=100, db_index=True)
    value = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        ordering = ["match_centre", "stat_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["match_centre", "participant", "stat_type"],
                name="unique_team_stat_per_match",
            )
        ]
        indexes = [
            models.Index(fields=["match_centre", "stat_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.stat_type}: {self.value}"


class MatchTimelineEvent(TimeStampedUUIDModel):
    """Timeline event for a fixture."""

    class EventType(models.TextChoices):
        GOAL = "GOAL", "Goal"
        ASSIST = "ASSIST", "Assist"
        YELLOW_CARD = "YELLOW_CARD", "Yellow card"
        RED_CARD = "RED_CARD", "Red card"
        SUBSTITUTION = "SUBSTITUTION", "Substitution"
        PENALTY = "PENALTY", "Penalty"
        OWN_GOAL = "OWN_GOAL", "Own goal"
        MATCH_START = "MATCH_START", "Match start"
        MATCH_END = "MATCH_END", "Match end"
        HALF_TIME = "HALF_TIME", "Half time"
        OTHER = "OTHER", "Other"

    match_centre = models.ForeignKey(
        MatchCentre,
        on_delete=models.CASCADE,
        related_name="timeline_events",
    )
    event_type = models.CharField(
        max_length=30,
        choices=EventType.choices,
        db_index=True,
    )
    minute = models.PositiveSmallIntegerField(db_index=True)
    participant = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name="match_timeline_events",
        null=True,
        blank=True,
    )
    player = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name="player_timeline_events",
        null=True,
        blank=True,
    )
    description = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["match_centre", "minute"]
        indexes = [
            models.Index(fields=["match_centre", "minute"]),
            models.Index(fields=["match_centre", "event_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.minute}' {self.event_type}"


class MatchOfficial(TimeStampedUUIDModel):
    """Official for a fixture."""

    match_centre = models.ForeignKey(
        MatchCentre,
        on_delete=models.CASCADE,
        related_name="officials",
    )
    role = models.CharField(max_length=100, db_index=True)
    name = models.CharField(max_length=180)

    class Meta:
        ordering = ["match_centre", "role"]
        constraints = [
            models.UniqueConstraint(
                fields=["match_centre", "role", "name"],
                name="unique_official_per_match",
            )
        ]

    def __str__(self) -> str:
        return f"{self.role}: {self.name}"


class MatchBroadcast(TimeStampedUUIDModel):
    """Broadcast information for a fixture."""

    match_centre = models.ForeignKey(
        MatchCentre,
        on_delete=models.CASCADE,
        related_name="broadcasts",
    )
    provider = models.CharField(max_length=180)
    url = models.URLField(blank=True)
    country_code = models.CharField(max_length=2, blank=True)

    class Meta:
        ordering = ["match_centre", "provider"]
        constraints = [
            models.UniqueConstraint(
                fields=["match_centre", "provider", "country_code"],
                name="unique_broadcast_per_match",
            )
        ]

    def __str__(self) -> str:
        return f"{self.provider} ({self.country_code})"


# =============================================================================
# Sports Data Feeds
# =============================================================================


class SportsFeedProvider(TimeStampedUUIDModel):
    """Configurable approved sports data feed provider."""

    code = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    base_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active", "code"]),
        ]

    def __str__(self) -> str:
        return self.name


class SportsFeedIngestion(TimeStampedUUIDModel):
    """Tracks a single feed ingestion with confidence and verification."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    provider = models.ForeignKey(
        SportsFeedProvider,
        on_delete=models.PROTECT,
        related_name="ingestions",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    feed_timestamp = models.DateTimeField(null=True, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_verified = models.BooleanField(default=False, db_index=True)
    records_received = models.PositiveIntegerField(default=0)
    records_processed = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["provider", "-started_at"]),
            models.Index(fields=["status", "-started_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider.code} - {self.status}"


# =============================================================================
# Search & Analytics
# =============================================================================


class SearchAnalytics(TimeStampedUUIDModel):
    """Structured search analytics for reporting."""

    query = models.CharField(max_length=300, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="search_analytics",
        null=True,
        blank=True,
    )
    duration_ms = models.PositiveIntegerField(default=0)
    result_count = models.PositiveIntegerField(default=0)
    clicked_entity_type = models.CharField(max_length=50, blank=True)
    clicked_entity_id = models.UUIDField(null=True, blank=True)
    applied_filters = models.JSONField(default=dict, blank=True)
    is_empty = models.BooleanField(default=False, db_index=True)
    is_failed = models.BooleanField(default=False, db_index=True)
    error_message = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user", "-timestamp"]),
            models.Index(fields=["query", "-timestamp"]),
            models.Index(fields=["-timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.query} ({self.result_count})"


class SearchSuggestion(TimeStampedUUIDModel):
    """Database-driven search suggestion."""

    class SuggestionType(models.TextChoices):
        RECENT = "RECENT", "Recently searched"
        POPULAR = "POPULAR", "Popular search"
        TRENDING = "TRENDING", "Trending"

    suggestion_type = models.CharField(
        max_length=20,
        choices=SuggestionType.choices,
        db_index=True,
    )
    entity_type = models.CharField(max_length=50, db_index=True)
    entity_id = models.UUIDField(db_index=True)
    display_name = models.CharField(max_length=300)
    score = models.PositiveIntegerField(default=0, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="search_suggestions",
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["-score"]
        constraints = [
            models.UniqueConstraint(
                fields=["suggestion_type", "entity_type", "entity_id", "user"],
                name="unique_suggestion_identity",
            )
        ]
        indexes = [
            models.Index(fields=["suggestion_type", "is_active", "-score"]),
        ]

    def __str__(self) -> str:
        return f"{self.suggestion_type}: {self.display_name}"


# =============================================================================
# Audit Logging
# =============================================================================


class AuditLog(TimeStampedUUIDModel):
    """Generic audit log for discovery actions."""

    ACTION_CHOICES = [
        ("SEARCH_PERFORMED", "Search performed"),
        ("SEARCH_FILTER_APPLIED", "Search filter applied"),
        ("CLUB_VIEWED", "Club viewed"),
        ("PLAYER_VIEWED", "Player viewed"),
        ("FIXTURE_VIEWED", "Fixture viewed"),
        ("MATCH_CENTRE_VIEWED", "Match centre viewed"),
        ("NEWS_VIEWED", "News viewed"),
        ("CLUB_FOLLOWED", "Club followed"),
        ("CLUB_UNFOLLOWED", "Club unfollowed"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="discovery_audit_logs",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES, db_index=True)
    entity_type = models.CharField(max_length=50, blank=True, db_index=True)
    entity_id = models.UUIDField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user", "action", "-timestamp"]),
            models.Index(fields=["action", "-timestamp"]),
            models.Index(fields=["-timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} - {self.timestamp.isoformat()}"

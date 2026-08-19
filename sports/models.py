import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.text import slugify


class TimeStampedUUIDModel(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        abstract = True


class Sport(TimeStampedUUIDModel):
    name = models.CharField(
        max_length=100,
        unique=True,
    )
    code = models.CharField(
        max_length=30,
        unique=True,
    )
    slug = models.SlugField(
        max_length=120,
        unique=True,
        blank=True,
    )
    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.code = self.code.strip().upper()

        if not self.slug:
            self.slug = slugify(self.name)

        super().save(*args, **kwargs)


class Competition(TimeStampedUUIDModel):
    sport = models.ForeignKey(
        Sport,
        on_delete=models.PROTECT,
        related_name="competitions",
    )
    name = models.CharField(
        max_length=180,
    )
    slug = models.SlugField(
        max_length=200,
        blank=True,
    )
    country_code = models.CharField(
        max_length=2,
        default="UG",
    )
    source_name = models.CharField(
        max_length=120,
        blank=True,
    )
    source_reference = models.CharField(
        max_length=255,
        blank=True,
    )
    is_active = models.BooleanField(
        default=True,
    )
    is_verified = models.BooleanField(
        default=False,
    )

    class Meta:
        ordering = [
            "sport__name",
            "name",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "sport",
                    "country_code",
                    "slug",
                ],
                name="unique_competition_identity",
            ),
            models.UniqueConstraint(
                fields=[
                    "source_name",
                    "source_reference",
                ],
                condition=~Q(source_reference=""),
                name="unique_competition_source_reference",
            ),
        ]
        indexes = [
            models.Index(
                fields=[
                    "sport",
                    "is_active",
                ],
            ),
            models.Index(
                fields=[
                    "country_code",
                    "is_active",
                ],
            ),
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


class Participant(TimeStampedUUIDModel):
    class Kind(models.TextChoices):
        TEAM = "TEAM", "Team"
        ATHLETE = "ATHLETE", "Athlete"
        COUNTRY = "COUNTRY", "Country or national team"
        PAIR = "PAIR", "Pair"
        OTHER = "OTHER", "Other"

    sport = models.ForeignKey(
        Sport,
        on_delete=models.PROTECT,
        related_name="participants",
    )
    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        default=Kind.TEAM,
        db_index=True,
    )
    name = models.CharField(
        max_length=180,
    )
    short_name = models.CharField(
        max_length=80,
        blank=True,
    )
    slug = models.SlugField(
        max_length=200,
        blank=True,
    )
    country_code = models.CharField(
        max_length=2,
        blank=True,
    )
    source_name = models.CharField(
        max_length=120,
        blank=True,
    )
    source_reference = models.CharField(
        max_length=255,
        blank=True,
    )
    is_active = models.BooleanField(
        default=True,
    )
    is_verified = models.BooleanField(
        default=False,
        db_index=True,
    )

    class Meta:
        ordering = [
            "sport__name",
            "name",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "sport",
                    "kind",
                    "country_code",
                    "slug",
                ],
                name="unique_sport_participant_identity",
            ),
            models.UniqueConstraint(
                fields=[
                    "source_name",
                    "source_reference",
                ],
                condition=~Q(source_reference=""),
                name="unique_participant_source_reference",
            ),
        ]
        indexes = [
            models.Index(
                fields=[
                    "sport",
                    "kind",
                    "is_active",
                ],
            ),
            models.Index(
                fields=[
                    "country_code",
                    "is_active",
                ],
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.short_name = self.short_name.strip()
        self.country_code = self.country_code.strip().upper()
        self.source_name = self.source_name.strip()
        self.source_reference = self.source_reference.strip()

        if not self.slug:
            self.slug = slugify(self.name)

        super().save(*args, **kwargs)


class SportingEvent(TimeStampedUUIDModel):
    class EventType(models.TextChoices):
        MATCH = "MATCH", "Match"
        RACE = "RACE", "Race"
        TOURNAMENT = "TOURNAMENT", "Tournament"
        BOUT = "BOUT", "Bout"
        SERIES = "SERIES", "Series"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SCHEDULED = "SCHEDULED", "Scheduled"
        LIVE = "LIVE", "Live"
        COMPLETED = "COMPLETED", "Completed"
        POSTPONED = "POSTPONED", "Postponed"
        CANCELLED = "CANCELLED", "Cancelled"
        ABANDONED = "ABANDONED", "Abandoned"

    sport = models.ForeignKey(
        Sport,
        on_delete=models.PROTECT,
        related_name="events",
    )
    competition = models.ForeignKey(
        Competition,
        on_delete=models.PROTECT,
        related_name="events",
        null=True,
        blank=True,
    )
    event_type = models.CharField(
        max_length=20,
        choices=EventType.choices,
        default=EventType.MATCH,
        db_index=True,
    )
    name = models.CharField(
        max_length=255,
    )
    starts_at = models.DateTimeField(
        db_index=True,
    )
    ends_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    venue = models.CharField(
        max_length=255,
        blank=True,
    )
    match_type = models.CharField(
        max_length=40,
        blank=True,
    )
    show_in_markets = models.BooleanField(
        default=False,
        db_index=True,
    )
    is_live_score_featured = models.BooleanField(
        default=False,
        db_index=True,
    )
    country_code = models.CharField(
        max_length=2,
        blank=True,
    )
    source_name = models.CharField(
        max_length=120,
        blank=True,
    )
    source_reference = models.CharField(
        max_length=255,
        blank=True,
    )
    is_verified = models.BooleanField(
        default=False,
        db_index=True,
    )
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    participants = models.ManyToManyField(
        Participant,
        through="EventParticipant",
        related_name="events",
    )

    class Meta:
        ordering = ["starts_at", "name"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(is_verified=False) | Q(verified_at__isnull=False)),
                name="verified_sporting_event_has_timestamp",
            ),
            models.UniqueConstraint(
                fields=[
                    "source_name",
                    "source_reference",
                ],
                condition=~Q(source_reference=""),
                name="unique_sporting_event_source_reference",
            ),
        ]
        indexes = [
            models.Index(
                fields=[
                    "sport",
                    "starts_at",
                ],
            ),
            models.Index(
                fields=[
                    "competition",
                    "starts_at",
                ],
            ),
            models.Index(
                fields=[
                    "status",
                    "starts_at",
                ],
            ),
            models.Index(
                fields=[
                    "is_verified",
                    "starts_at",
                ],
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        errors = {}

        if self.competition_id and self.competition.sport_id != self.sport_id:
            errors["competition"] = "Competition sport must match the event sport."

        if self.ends_at is not None and self.ends_at <= self.starts_at:
            errors["ends_at"] = "Event end time must be after its start time."

        if self.is_verified and self.verified_at is None:
            errors["verified_at"] = "A verified event requires " "a verification timestamp."

        if self.source_reference and not self.source_name:
            errors["source_name"] = (
                "A source name is required when a " "source reference is provided."
            )

        if errors:
            raise ValidationError(errors)


class EventParticipant(TimeStampedUUIDModel):
    class Role(models.TextChoices):
        HOME = "HOME", "Home"
        AWAY = "AWAY", "Away"
        COMPETITOR = "COMPETITOR", "Competitor"
        SUBJECT = "SUBJECT", "Subject"
        OTHER = "OTHER", "Other"

    event = models.ForeignKey(
        SportingEvent,
        on_delete=models.CASCADE,
        related_name="event_participants",
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name="event_entries",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.COMPETITOR,
    )
    position = models.PositiveSmallIntegerField()

    class Meta:
        ordering = [
            "event",
            "position",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "event",
                    "participant",
                ],
                name="unique_participant_per_sporting_event",
            ),
            models.UniqueConstraint(
                fields=[
                    "event",
                    "position",
                ],
                name="unique_participant_position_per_event",
            ),
            models.UniqueConstraint(
                fields=[
                    "event",
                    "role",
                ],
                condition=Q(
                    role__in=[
                        "HOME",
                        "AWAY",
                    ]
                ),
                name="unique_home_away_role_per_event",
            ),
        ]
        indexes = [
            models.Index(
                fields=[
                    "event",
                    "role",
                ],
            ),
            models.Index(
                fields=[
                    "participant",
                    "event",
                ],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event.name}: " f"{self.participant.name}"

    def clean(self):
        errors = {}

        if (
            self.event_id
            and self.participant_id
            and self.event.sport_id != self.participant.sport_id
        ):
            errors["participant"] = "Participant sport must match the event sport."

        if (
            self.event_id
            and self.event.event_type != SportingEvent.EventType.MATCH
            and self.role
            in {
                self.Role.HOME,
                self.Role.AWAY,
            }
        ):
            errors["role"] = "Home and away roles are only valid " "for match events."

        if errors:
            raise ValidationError(errors)

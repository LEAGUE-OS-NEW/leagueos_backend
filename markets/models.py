import uuid
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.text import slugify

from sports.models import (
    Competition,
    Participant,
    Sport,
    SportingEvent,
)


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


class MarketScope(models.TextChoices):
    EVENT = "EVENT", "Sporting event"
    COMPETITION = "COMPETITION", "Competition"
    PARTICIPANT = "PARTICIPANT", "Participant"
    CUSTOM = "CUSTOM", "Custom proposition"


class MarketParticipantCompliance(TimeStampedUUIDModel):
    class KYCStatus(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", "Not started"
        PENDING = "PENDING", "Pending"
        VERIFIED = "VERIFIED", "Verified"
        REJECTED = "REJECTED", "Rejected"
        EXPIRED = "EXPIRED", "Expired"

    class RestrictionStatus(models.TextChoices):
        CLEAR = "CLEAR", "Clear"
        RESTRICTED = "RESTRICTED", "Restricted"
        SUSPENDED = "SUSPENDED", "Suspended"

    class JurisdictionOverride(models.TextChoices):
        NONE = "NONE", "None"
        ALLOW = "ALLOW", "Allow"
        BLOCK = "BLOCK", "Block"

    participant = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="market_compliance"
    )
    kyc_status = models.CharField(
        max_length=20, choices=KYCStatus.choices, default=KYCStatus.NOT_STARTED, db_index=True
    )
    restriction_status = models.CharField(
        max_length=20,
        choices=RestrictionStatus.choices,
        default=RestrictionStatus.CLEAR,
        db_index=True,
    )
    jurisdiction_override = models.CharField(
        max_length=10, choices=JurisdictionOverride.choices, default=JurisdictionOverride.NONE
    )
    jurisdiction_override_reason = models.TextField(blank=True)
    internal_review_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="market_compliance_reviews_performed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Market compliance for {self.participant_id}"


class MarketComplianceReview(TimeStampedUUIDModel):
    participant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="market_compliance_reviews"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="market_compliance_audits"
    )
    previous_kyc_status = models.CharField(max_length=20)
    new_kyc_status = models.CharField(max_length=20)
    previous_restriction_status = models.CharField(max_length=20)
    new_restriction_status = models.CharField(max_length=20)
    previous_jurisdiction_override = models.CharField(max_length=10)
    new_jurisdiction_override = models.CharField(max_length=10)
    reason = models.TextField(blank=True)
    notes_snapshot = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["participant", "-created_at"])]

    def __str__(self):
        return f"Compliance review for {self.participant_id} at {self.created_at}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Compliance review records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Compliance review records are immutable.")


class MarketResponsibleParticipation(TimeStampedUUIDModel):
    MONEY_FIELDS = (
        "max_order_notional",
        "daily_buy_notional_limit",
        "weekly_buy_notional_limit",
        "max_open_buy_commitment",
        "max_market_exposure",
        "max_total_exposure",
        "max_cumulative_realized_loss",
    )

    participant = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="market_responsible_participation",
    )
    max_order_notional = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    daily_buy_notional_limit = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    weekly_buy_notional_limit = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    max_open_buy_commitment = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    max_market_exposure = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    max_total_exposure = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    max_cumulative_realized_loss = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    cooling_off_until = models.DateTimeField(null=True, blank=True)
    self_exclusion_until = models.DateTimeField(null=True, blank=True)
    self_excluded_indefinitely = models.BooleanField(default=False)
    administrative_block_until = models.DateTimeField(null=True, blank=True)
    administrative_block_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="market_responsible_reviews_performed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Responsible participation for {self.participant_id}"


class ImmutableResponsibleParticipationEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Responsible-participation events are immutable.")

    def delete(self):
        raise ValidationError("Responsible-participation events are immutable.")


class MarketResponsibleParticipationEvent(TimeStampedUUIDModel):
    class EventType(models.TextChoices):
        LIMITS_SET = "LIMITS_SET", "Limits set"
        LIMITS_TIGHTENED = "LIMITS_TIGHTENED", "Limits tightened"
        ADMIN_LIMITS_UPDATED = "ADMIN_LIMITS_UPDATED", "Admin limits updated"
        ADMIN_CONTROLS_UPDATED = "ADMIN_CONTROLS_UPDATED", "Admin controls updated"
        COOLING_OFF_STARTED = "COOLING_OFF_STARTED", "Cooling off started"
        COOLING_OFF_EXTENDED = "COOLING_OFF_EXTENDED", "Cooling off extended"
        SELF_EXCLUSION_STARTED = "SELF_EXCLUSION_STARTED", "Self exclusion started"
        SELF_EXCLUSION_EXTENDED = "SELF_EXCLUSION_EXTENDED", "Self exclusion extended"
        ADMIN_BLOCK_STARTED = "ADMIN_BLOCK_STARTED", "Admin block started"
        ADMIN_BLOCK_EXTENDED = "ADMIN_BLOCK_EXTENDED", "Admin block extended"

    participant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="market_responsible_participation_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="market_responsible_participation_actions",
    )
    event_type = models.CharField(max_length=40, choices=EventType.choices)
    previous_state = models.JSONField(default=dict)
    new_state = models.JSONField(default=dict)
    reason = models.TextField(blank=True)
    objects = ImmutableResponsibleParticipationEventQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["participant", "-created_at", "-id"])]

    def __str__(self):
        return f"{self.event_type} for {self.participant_id}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Responsible-participation events are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Responsible-participation events are immutable.")


class MarketCategory(TimeStampedUUIDModel):
    name = models.CharField(
        max_length=120,
        unique=True,
    )
    slug = models.SlugField(
        max_length=140,
        unique=True,
        blank=True,
    )
    description = models.TextField(
        blank=True,
    )
    display_order = models.PositiveSmallIntegerField(
        default=0,
    )
    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = [
            "display_order",
            "name",
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip()

        if not self.slug:
            self.slug = slugify(self.name)

        super().save(*args, **kwargs)


class MarketTemplate(TimeStampedUUIDModel):
    category = models.ForeignKey(
        MarketCategory,
        on_delete=models.PROTECT,
        related_name="templates",
    )
    sport = models.ForeignKey(
        Sport,
        on_delete=models.PROTECT,
        related_name="market_templates",
        null=True,
        blank=True,
    )
    scope_type = models.CharField(
        max_length=20,
        choices=MarketScope.choices,
        db_index=True,
    )
    name = models.CharField(
        max_length=160,
    )
    code = models.CharField(
        max_length=80,
        unique=True,
    )
    slug = models.SlugField(
        max_length=180,
        blank=True,
    )
    question_template = models.CharField(
        max_length=500,
    )
    description = models.TextField(
        blank=True,
    )
    rules_template = models.TextField(
        blank=True,
    )
    default_yes_label = models.CharField(
        max_length=120,
        default="Yes",
    )
    default_no_label = models.CharField(
        max_length=120,
        default="No",
    )
    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = [
            "category__display_order",
            "name",
        ]
        indexes = [
            models.Index(
                fields=[
                    "scope_type",
                    "is_active",
                ],
            ),
            models.Index(
                fields=[
                    "sport",
                    "is_active",
                ],
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.code = self.code.strip().upper()
        self.question_template = self.question_template.strip()
        self.default_yes_label = self.default_yes_label.strip()
        self.default_no_label = self.default_no_label.strip()

        if not self.slug:
            self.slug = slugify(self.name)

        super().save(*args, **kwargs)


class MarketEventGroup(TimeStampedUUIDModel):
    class EventType(models.TextChoices):
        SPORTING_EVENT = "SPORTING_EVENT", "Sporting event"
        LEAGUE_EVENT = "LEAGUE_EVENT", "League event"
        GENERAL_EVENT = "GENERAL_EVENT", "General event"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        ARCHIVED = "ARCHIVED", "Archived"

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True)
    description = models.TextField(blank=True)
    event_type = models.CharField(max_length=30, choices=EventType.choices, db_index=True)
    sporting_event = models.ForeignKey(
        SportingEvent,
        on_delete=models.PROTECT,
        related_name="market_event_groups",
        null=True,
        blank=True,
    )
    category = models.ForeignKey(
        MarketCategory,
        on_delete=models.PROTECT,
        related_name="event_groups",
        null=True,
        blank=True,
    )
    scheduled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_market_event_groups",
        null=True,
        blank=True,
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="published_market_event_groups",
        null=True,
        blank=True,
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["scheduled_at", "title", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["sporting_event"],
                condition=Q(sporting_event__isnull=False),
                name="unique_market_group_per_sporting_event",
            )
        ]
        indexes = [
            models.Index(fields=["status", "scheduled_at"]),
            models.Index(fields=["event_type", "status"]),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.title = self.title.strip()
        self.description = self.description.strip()
        if not self.slug:
            self.slug = slugify(self.title)
        if self.sporting_event_id and self.scheduled_at is None:
            self.scheduled_at = self.sporting_event.starts_at
        super().save(*args, **kwargs)

    def clean(self):
        if self.event_type == self.EventType.SPORTING_EVENT and not self.sporting_event_id:
            raise ValidationError(
                {"sporting_event": "A sporting-event group requires a sporting event."}
            )
        if self.event_type != self.EventType.SPORTING_EVENT and self.sporting_event_id:
            raise ValidationError(
                {"sporting_event": "Only sporting-event groups may reference a sporting event."}
            )


class Market(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING_APPROVAL = (
            "PENDING_APPROVAL",
            "Pending approval",
        )
        APPROVED = "APPROVED", "Approved"
        OPEN = "OPEN", "Open"
        SUSPENDED = "SUSPENDED", "Suspended"
        CLOSED = "CLOSED", "Closed"
        RESOLVED = "RESOLVED", "Resolved"
        VOIDED = "VOIDED", "Voided"
        REJECTED = "REJECTED", "Rejected"

    sport = models.ForeignKey(
        Sport,
        on_delete=models.PROTECT,
        related_name="markets",
    )
    category = models.ForeignKey(
        MarketCategory,
        on_delete=models.PROTECT,
        related_name="markets",
    )
    template = models.ForeignKey(
        MarketTemplate,
        on_delete=models.PROTECT,
        related_name="markets",
        null=True,
        blank=True,
    )
    event_group = models.ForeignKey(
        MarketEventGroup,
        on_delete=models.SET_NULL,
        related_name="markets",
        null=True,
        blank=True,
    )
    scope_type = models.CharField(
        max_length=20,
        choices=MarketScope.choices,
        db_index=True,
    )
    sporting_event = models.ForeignKey(
        SportingEvent,
        on_delete=models.PROTECT,
        related_name="markets",
        null=True,
        blank=True,
    )
    competition = models.ForeignKey(
        Competition,
        on_delete=models.PROTECT,
        related_name="markets",
        null=True,
        blank=True,
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name="markets",
        null=True,
        blank=True,
    )
    custom_subject = models.CharField(
        max_length=255,
        blank=True,
    )
    question = models.CharField(
        max_length=500,
    )
    duplicate_fingerprint = models.CharField(  # noqa: DJ001 -- legacy rows stay unmodified
        max_length=64, null=True, blank=True, db_index=True, editable=False
    )
    description = models.TextField(
        blank=True,
    )
    rules = models.TextField(
        blank=True,
    )
    resolution_source = models.CharField(
        max_length=255,
        blank=True,
    )
    resolution_criteria = models.TextField(
        blank=True,
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    opens_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )
    closes_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    approval_notes = models.TextField(
        blank=True,
    )
    resolution_notes = models.TextField(
        blank=True,
    )
    resolution_evidence = models.TextField(
        blank=True,
    )
    is_featured = models.BooleanField(
        default=False,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_markets",
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="approved_markets",
        null=True,
        blank=True,
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="resolved_markets",
        null=True,
        blank=True,
    )
    winning_outcome = models.ForeignKey(
        "MarketOutcome",
        on_delete=models.PROTECT,
        related_name="winning_markets",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = [
            "-is_featured",
            "closes_at",
            "-created_at",
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (
                        Q(scope_type=MarketScope.EVENT)
                        & Q(sporting_event__isnull=False)
                        & Q(competition__isnull=True)
                        & Q(participant__isnull=True)
                        & Q(custom_subject="")
                    )
                    | (
                        Q(scope_type=(MarketScope.COMPETITION))
                        & Q(sporting_event__isnull=True)
                        & Q(competition__isnull=False)
                        & Q(participant__isnull=True)
                        & Q(custom_subject="")
                    )
                    | (
                        Q(scope_type=(MarketScope.PARTICIPANT))
                        & Q(participant__isnull=False)
                        & Q(custom_subject="")
                    )
                    | (
                        Q(scope_type=MarketScope.CUSTOM)
                        & Q(sporting_event__isnull=True)
                        & Q(competition__isnull=True)
                        & Q(participant__isnull=True)
                        & ~Q(custom_subject="")
                    )
                ),
                name="market_scope_target_is_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(opens_at__isnull=True)
                    | Q(closes_at__isnull=True)
                    | Q(closes_at__gt=models.F("opens_at"))
                ),
                name="market_closes_after_opening",
            ),
        ]
        indexes = [
            models.Index(
                fields=[
                    "status",
                    "closes_at",
                ],
            ),
            models.Index(
                fields=[
                    "sport",
                    "status",
                ],
            ),
            models.Index(
                fields=[
                    "category",
                    "status",
                ],
            ),
            models.Index(
                fields=[
                    "scope_type",
                    "status",
                ],
            ),
            models.Index(
                fields=[
                    "is_featured",
                    "status",
                ],
            ),
        ]

    def __str__(self) -> str:
        return self.question

    def save(self, *args, **kwargs):
        self.question = self.question.strip()
        self.custom_subject = self.custom_subject.strip()
        self.description = self.description.strip()
        self.rules = self.rules.strip()
        self.resolution_source = self.resolution_source.strip()
        self.resolution_criteria = self.resolution_criteria.strip()
        self.resolution_notes = self.resolution_notes.strip()
        self.resolution_evidence = self.resolution_evidence.strip()

        # New and updated canonical markets get an indexed duplicate key. Historical
        # rows remain safely nullable and are covered by the service's bounded fallback.
        from markets.services.proposal_service import build_market_duplicate_fingerprint

        self.duplicate_fingerprint = build_market_duplicate_fingerprint(self)

        # A restricted save that changes duplicate identity must persist the
        # recalculated key as part of the same database write.
        update_fields = kwargs.get("update_fields")
        duplicate_context_fields = {
            "question",
            "category",
            "category_id",
            "sporting_event",
            "sporting_event_id",
            "event_group",
            "event_group_id",
            "scope_type",
        }
        if update_fields and duplicate_context_fields.intersection(update_fields):
            kwargs["update_fields"] = set(update_fields) | {"duplicate_fingerprint"}

        super().save(*args, **kwargs)

    def clean(self):
        errors = {}

        if (
            self.opens_at is not None
            and self.closes_at is not None
            and self.closes_at <= self.opens_at
        ):
            errors["closes_at"] = "Market close time must be after " "its opening time."

        if self.scope_type == MarketScope.CUSTOM and not self.custom_subject.strip():
            errors["custom_subject"] = "A custom market requires a subject."

        if self.sporting_event_id and self.sporting_event.sport_id != self.sport_id:
            errors["sporting_event"] = "Sporting event sport must match " "the market sport."

        if self.event_group_id:
            group_event_id = self.event_group.sporting_event_id
            if group_event_id and group_event_id != self.sporting_event_id:
                errors["event_group"] = "Market and event group sporting events must match."
            if (
                self.sporting_event_id
                and self.event_group.event_type != MarketEventGroup.EventType.SPORTING_EVENT
            ):
                errors["event_group"] = "A sporting market requires a sporting-event group."

        if self.competition_id and self.competition.sport_id != self.sport_id:
            errors["competition"] = "Competition sport must match " "the market sport."

        if self.participant_id and self.participant.sport_id != self.sport_id:
            errors["participant"] = "Participant sport must match " "the market sport."

        if (
            self.sporting_event_id
            and self.competition_id
            and self.sporting_event.competition_id != self.competition_id
        ):
            errors["competition"] = "Competition must match the " "sporting event competition."

        if self.template_id:
            if self.template.category_id != self.category_id:
                errors["template"] = "Template category must match " "the market category."
            elif self.template.scope_type != self.scope_type:
                errors["template"] = "Template scope must match " "the market scope."
            elif self.template.sport_id is not None and self.template.sport_id != self.sport_id:
                errors["template"] = "Template sport must match " "the market sport."

        public_statuses = {
            self.Status.PENDING_APPROVAL,
            self.Status.APPROVED,
            self.Status.OPEN,
            self.Status.SUSPENDED,
            self.Status.CLOSED,
            self.Status.RESOLVED,
            self.Status.VOIDED,
        }

        if self.status in public_statuses:
            if (
                self.scope_type == MarketScope.EVENT
                and self.sporting_event_id
                and not self.sporting_event.is_verified
            ):
                errors["sporting_event"] = (
                    "The sporting event must be " "verified before publication."
                )

            if (
                self.scope_type == MarketScope.COMPETITION
                and self.competition_id
                and not self.competition.is_verified
            ):
                errors["competition"] = "The competition must be " "verified before publication."

            if (
                self.scope_type == MarketScope.PARTICIPANT
                and self.participant_id
                and not self.participant.is_verified
            ):
                errors["participant"] = "The participant must be " "verified before publication."

            if self.sporting_event_id and not self.sporting_event.is_verified:
                errors["sporting_event"] = "The contextual sporting event " "must be verified."

            if self.competition_id and not self.competition.is_verified:
                errors["competition"] = "The contextual competition " "must be verified."

        if self.winning_outcome_id:
            if self.winning_outcome.market_id != self.pk:
                errors["winning_outcome"] = "The winning outcome must belong " "to this market."

        terminal_statuses = {
            self.Status.RESOLVED,
            self.Status.VOIDED,
        }

        if self.status == self.Status.RESOLVED:
            if not self.winning_outcome_id:
                errors["winning_outcome"] = "A resolved market requires " "a winning outcome."
        elif self.status == self.Status.VOIDED:
            if self.winning_outcome_id:
                errors["winning_outcome"] = "A voided market cannot have " "a winning outcome."
        elif self.winning_outcome_id:
            errors["winning_outcome"] = "Only resolved markets can have " "a winning outcome."

        if self.status in terminal_statuses:
            if not self.resolved_by_id:
                errors["resolved_by"] = "A terminal market requires " "a resolving administrator."

            if self.resolved_at is None:
                errors["resolved_at"] = "A terminal market requires " "a resolution timestamp."

            if not self.resolution_notes.strip():
                errors["resolution_notes"] = "Resolution notes are required."

            if not self.resolution_evidence.strip():
                errors["resolution_evidence"] = "Resolution evidence is required."

        if errors:
            raise ValidationError(errors)

    @property
    def has_complete_outcomes(self) -> bool:
        outcome_values = set(
            self.outcomes.values_list(
                "side",
                "position",
            )
        )

        return outcome_values == {
            (
                MarketOutcome.Side.YES,
                1,
            ),
            (
                MarketOutcome.Side.NO,
                2,
            ),
        }


class MarketProposal(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        UNDER_REVIEW = "UNDER_REVIEW", "Under review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        DUPLICATE = "DUPLICATE", "Duplicate"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"

    class DuplicateStatus(models.TextChoices):
        CLEAR = "CLEAR", "Clear"
        POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE", "Possible duplicate"
        CONFIRMED_DUPLICATE = "CONFIRMED_DUPLICATE", "Confirmed duplicate"

    proposer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="market_proposals"
    )
    question = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    category = models.ForeignKey(MarketCategory, on_delete=models.PROTECT, related_name="proposals")
    scope_type = models.CharField(
        max_length=20, choices=MarketScope.choices, default=MarketScope.EVENT
    )
    sporting_event = models.ForeignKey(
        SportingEvent,
        on_delete=models.PROTECT,
        related_name="market_proposals",
        null=True,
        blank=True,
    )
    proposed_event_group = models.ForeignKey(
        MarketEventGroup,
        on_delete=models.PROTECT,
        related_name="proposals",
        null=True,
        blank=True,
    )
    proposed_event_title = models.CharField(max_length=255, blank=True)
    proposed_closes_at = models.DateTimeField(null=True, blank=True)
    proposed_resolution_source = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SUBMITTED, db_index=True
    )
    duplicate_status = models.CharField(
        max_length=30,
        choices=DuplicateStatus.choices,
        default=DuplicateStatus.CLEAR,
        db_index=True,
    )
    duplicate_fingerprint = models.CharField(max_length=64, db_index=True, editable=False)
    duplicate_of_market = models.ForeignKey(
        Market,
        on_delete=models.PROTECT,
        related_name="duplicate_proposals",
        null=True,
        blank=True,
    )
    duplicate_of_proposal = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="duplicates",
        null=True,
        blank=True,
    )
    approved_market = models.OneToOneField(
        Market,
        on_delete=models.PROTECT,
        related_name="source_proposal",
        null=True,
        blank=True,
    )
    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_market_proposals",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-submitted_at", "-id"]
        indexes = [models.Index(fields=["status", "-submitted_at"])]

    def __str__(self):
        return self.question

    def save(self, *args, **kwargs):
        from markets.services.proposal_service import build_duplicate_fingerprint

        self.question = self.question.strip()
        self.description = self.description.strip()
        self.proposed_event_title = self.proposed_event_title.strip()
        self.proposed_resolution_source = self.proposed_resolution_source.strip()
        self.duplicate_fingerprint = build_duplicate_fingerprint(
            question=self.question,
            category_id=self.category_id,
            sporting_event_id=self.sporting_event_id,
            event_group_id=self.proposed_event_group_id,
        )
        super().save(*args, **kwargs)

    def clean(self):
        from markets.services.proposal_service import normalize_market_question

        errors = {}
        if not normalize_market_question(self.question):
            errors["question"] = ValidationError(
                "Question must contain meaningful characters.",
                code="market_proposal_question_empty",
            )
        if self.scope_type != MarketScope.EVENT:
            errors["scope_type"] = ValidationError(
                "Only sporting-event proposals are currently supported.",
                code="market_proposal_scope_unsupported",
            )
        if not self.sporting_event_id and not self.proposed_event_group_id:
            errors["sporting_event"] = ValidationError(
                "A sporting event is required.",
                code="market_proposal_sporting_event_required",
            )
        if self.proposed_event_group_id:
            group_event_id = self.proposed_event_group.sporting_event_id
            if not group_event_id:
                errors["proposed_event_group"] = ValidationError(
                    "The selected group is not a sporting-event group.",
                    code="market_proposal_event_group_invalid",
                )
            elif self.sporting_event_id and group_event_id != self.sporting_event_id:
                errors["proposed_event_group"] = ValidationError(
                    "The group and sporting event must match.",
                    code="market_proposal_context_mismatch",
                )
        if self.proposed_closes_at is None:
            errors["proposed_closes_at"] = ValidationError(
                "A proposed close time is required.",
                code="market_proposal_closes_at_required",
            )
        if errors:
            raise ValidationError(errors)


class ImmutableMarketProposalReviewQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Market proposal reviews are immutable.")

    def delete(self):
        raise ValidationError("Market proposal reviews are immutable.")


class MarketProposalReview(TimeStampedUUIDModel):
    class Action(models.TextChoices):
        START_REVIEW = "START_REVIEW", "Start review"
        APPROVE = "APPROVE", "Approve"
        REJECT = "REJECT", "Reject"
        MARK_DUPLICATE = "MARK_DUPLICATE", "Mark duplicate"

    proposal = models.ForeignKey(MarketProposal, on_delete=models.PROTECT, related_name="reviews")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="market_proposal_reviews"
    )
    action = models.CharField(max_length=30, choices=Action.choices)
    previous_status = models.CharField(max_length=20, choices=MarketProposal.Status.choices)
    new_status = models.CharField(max_length=20, choices=MarketProposal.Status.choices)
    reason = models.TextField(blank=True)
    duplicate_market = models.ForeignKey(
        Market, on_delete=models.PROTECT, null=True, blank=True, related_name="proposal_reviews"
    )
    duplicate_proposal = models.ForeignKey(
        MarketProposal,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="duplicate_review_references",
    )
    approved_market = models.ForeignKey(
        Market, on_delete=models.PROTECT, null=True, blank=True, related_name="approval_reviews"
    )
    objects = ImmutableMarketProposalReviewQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["proposal", "-created_at", "-id"])]

    def __str__(self):
        return f"{self.action}: {self.proposal_id}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Market proposal reviews are immutable.")
        self.reason = self.reason.strip()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Market proposal reviews are immutable.")


class MarketOutcome(TimeStampedUUIDModel):
    class Side(models.TextChoices):
        YES = "YES", "Yes"
        NO = "NO", "No"

    market = models.ForeignKey(
        Market,
        on_delete=models.CASCADE,
        related_name="outcomes",
    )
    side = models.CharField(
        max_length=10,
        choices=Side.choices,
    )
    position = models.PositiveSmallIntegerField()
    label = models.CharField(
        max_length=120,
    )
    description = models.TextField(
        blank=True,
    )

    class Meta:
        ordering = [
            "market",
            "position",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "market",
                    "side",
                ],
                name="unique_market_outcome_side",
            ),
            models.UniqueConstraint(
                fields=[
                    "market",
                    "position",
                ],
                name="unique_market_outcome_position",
            ),
            models.CheckConstraint(
                condition=Q(
                    position__in=[
                        1,
                        2,
                    ]
                ),
                name="market_outcome_position_is_binary",
            ),
            models.CheckConstraint(
                condition=((Q(side="YES") & Q(position=1)) | (Q(side="NO") & Q(position=2))),
                name="market_outcome_side_matches_position",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.market.question}: " f"{self.label}"

    def save(self, *args, **kwargs):
        self.label = self.label.strip()
        self.description = self.description.strip()

        super().save(*args, **kwargs)

        errors = {}

        expected_position = {
            self.Side.YES: 1,
            self.Side.NO: 2,
        }.get(self.side)

        if expected_position is not None and self.position != expected_position:
            errors["position"] = f"{self.side} outcomes must use " f"position {expected_position}."

        if not self.label.strip():
            errors["label"] = "Outcome label cannot be blank."

        if errors:
            raise ValidationError(errors)


class MarketWatchlistEntry(TimeStampedUUIDModel):
    participant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="market_watchlist_entries",
    )
    market = models.ForeignKey(
        Market,
        on_delete=models.CASCADE,
        related_name="watchlist_entries",
    )
    followed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-followed_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "market"], name="unique_market_watchlist_entry"
            )
        ]
        indexes = [
            models.Index(fields=["participant", "-followed_at"]),
            models.Index(fields=["market", "followed_at"]),
        ]

    def __str__(self):
        return f"{self.participant_id}: {self.market_id}"


class MarketRecentView(TimeStampedUUIDModel):
    participant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="market_recent_views",
    )
    market = models.ForeignKey(
        Market,
        on_delete=models.CASCADE,
        related_name="recent_views",
    )
    first_viewed_at = models.DateTimeField()
    last_viewed_at = models.DateTimeField()
    view_count = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])

    class Meta:
        ordering = ["-last_viewed_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "market"], name="unique_market_recent_view"
            ),
            models.CheckConstraint(
                condition=Q(view_count__gte=1), name="market_recent_view_count_positive"
            ),
            models.CheckConstraint(
                condition=Q(first_viewed_at__lte=models.F("last_viewed_at")),
                name="market_recent_view_timestamps_ordered",
            ),
        ]
        indexes = [
            models.Index(fields=["participant", "-last_viewed_at"]),
            models.Index(fields=["market", "last_viewed_at"]),
        ]

    def __str__(self):
        return f"{self.participant_id}: {self.market_id} ({self.view_count})"


class MarketOrder(TimeStampedUUIDModel):
    class Side(models.TextChoices):
        BUY = "BUY", "Buy"
        SELL = "SELL", "Sell"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        OPEN = "OPEN", "Open"
        PARTIALLY_FILLED = (
            "PARTIALLY_FILLED",
            "Partially filled",
        )
        FILLED = "FILLED", "Filled"
        CANCELLED = "CANCELLED", "Cancelled"
        REJECTED = "REJECTED", "Rejected"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="market_orders",
    )
    market = models.ForeignKey(
        Market,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    outcome = models.ForeignKey(
        MarketOutcome,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    side = models.CharField(
        max_length=10,
        choices=Side.choices,
        default=Side.BUY,
        db_index=True,
    )
    quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
    )
    limit_price = models.DecimalField(
        max_digits=6,
        decimal_places=5,
    )
    filled_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
    )
    average_fill_price = models.DecimalField(
        max_digits=6,
        decimal_places=5,
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    class Meta:
        ordering = [
            "-created_at",
            "-id",
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="market_order_quantity_positive",
            ),
            models.CheckConstraint(
                condition=(Q(limit_price__gt=0) & Q(limit_price__lt=1)),
                name="market_order_limit_price_valid",
            ),
            models.CheckConstraint(
                condition=Q(filled_quantity__gte=0),
                name=("market_order_filled_quantity_" "non_negative"),
            ),
            models.CheckConstraint(
                condition=Q(filled_quantity__lte=models.F("quantity")),
                name=("market_order_filled_quantity_" "within_order"),
            ),
            models.CheckConstraint(
                condition=(
                    Q(average_fill_price__isnull=True)
                    | (Q(average_fill_price__gt=0) & Q(average_fill_price__lt=1))
                ),
                name=("market_order_average_fill_" "price_valid"),
            ),
        ]
        indexes = [
            models.Index(
                fields=[
                    "user",
                    "status",
                    "created_at",
                ],
            ),
            models.Index(
                fields=[
                    "market",
                    "status",
                    "created_at",
                ],
            ),
            models.Index(
                fields=[
                    "outcome",
                    "side",
                    "status",
                    "limit_price",
                ],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}: {self.side} " f"{self.quantity} @ {self.limit_price}"

    def clean(self):
        errors = {}

        if self.outcome_id and self.market_id and self.outcome.market_id != self.market_id:
            errors["outcome"] = "The selected outcome must belong " "to this market."

        if self.quantity is None or self.quantity <= 0:
            errors["quantity"] = "Order quantity must be positive."

        if self.limit_price is None or self.limit_price <= 0 or self.limit_price >= 1:
            errors["limit_price"] = "Limit price must be greater than " "0 and less than 1."

        if self.filled_quantity is not None and self.filled_quantity < 0:
            errors["filled_quantity"] = "Filled quantity cannot be negative."
        elif (
            self.quantity is not None
            and self.filled_quantity is not None
            and self.filled_quantity > self.quantity
        ):
            errors["filled_quantity"] = "Filled quantity cannot exceed " "the order quantity."

        if self.average_fill_price is not None:
            if self.average_fill_price <= 0 or self.average_fill_price >= 1:
                errors["average_fill_price"] = (
                    "Average fill price must be " "greater than 0 and less than 1."
                )

        if errors:
            raise ValidationError(errors)


class MarketPosition(TimeStampedUUIDModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="market_positions",
    )
    market = models.ForeignKey(
        Market,
        on_delete=models.PROTECT,
        related_name="positions",
    )
    outcome = models.ForeignKey(
        MarketOutcome,
        on_delete=models.PROTECT,
        related_name="positions",
    )
    quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0"),
    )
    reserved_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    average_entry_price = models.DecimalField(
        max_digits=6,
        decimal_places=5,
        default=Decimal("0"),
    )
    total_cost = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=Decimal("0"),
    )
    realized_pnl = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=Decimal("0"),
    )

    class Meta:
        ordering = [
            "-updated_at",
            "-id",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "user",
                    "market",
                    "outcome",
                ],
                name=("unique_user_market_outcome_" "position"),
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=0),
                name=("market_position_quantity_" "non_negative"),
            ),
            models.CheckConstraint(
                condition=Q(reserved_quantity__gte=0),
                name=("market_position_reserved_quantity_" "non_negative"),
            ),
            models.CheckConstraint(
                condition=Q(reserved_quantity__lte=models.F("quantity")),
                name=("market_position_reserved_quantity_" "within_position"),
            ),
            models.CheckConstraint(
                condition=Q(total_cost__gte=0),
                name=("market_position_total_cost_" "non_negative"),
            ),
            models.CheckConstraint(
                condition=(Q(average_entry_price__gte=0) & Q(average_entry_price__lt=1)),
                name=("market_position_average_entry_" "price_valid"),
            ),
        ]
        indexes = [
            models.Index(
                fields=[
                    "user",
                    "market",
                ],
            ),
            models.Index(
                fields=[
                    "market",
                    "outcome",
                ],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}: " f"{self.outcome_id} " f"({self.quantity})"

    def clean(self):
        errors = {}

        if self.outcome_id and self.market_id and self.outcome.market_id != self.market_id:
            errors["outcome"] = "The selected outcome must belong " "to this market."

        if self.quantity is None or self.quantity < 0:
            errors["quantity"] = "Position quantity cannot be " "negative."

        if self.reserved_quantity is None or self.reserved_quantity < 0:
            errors["reserved_quantity"] = "Reserved quantity cannot be negative."
        elif self.quantity is not None and self.reserved_quantity > self.quantity:
            errors["reserved_quantity"] = "Reserved quantity cannot exceed the position quantity."
            errors["quantity"] = "Position quantity cannot be below reserved quantity."

        if (
            self.average_entry_price is None
            or self.average_entry_price < 0
            or self.average_entry_price >= 1
        ):
            errors["average_entry_price"] = (
                "Average entry price must be at " "least 0 and less than 1."
            )

        if self.total_cost is None or self.total_cost < 0:
            errors["total_cost"] = "Position total cost cannot be " "negative."

        if errors:
            raise ValidationError(errors)


class MarketSettlement(TimeStampedUUIDModel):
    market = models.OneToOneField(
        Market,
        on_delete=models.PROTECT,
        related_name="settlement",
    )
    winning_outcome = models.ForeignKey(
        MarketOutcome,
        on_delete=models.PROTECT,
        related_name="market_settlements",
    )
    payout_per_unit = models.DecimalField(
        max_digits=20,
        decimal_places=4,
    )
    settlement_currency = models.CharField(
        max_length=3,
    )
    total_position_count = models.PositiveIntegerField(default=0)
    winning_position_count = models.PositiveIntegerField(default=0)
    losing_position_count = models.PositiveIntegerField(default=0)
    total_winning_quantity = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_payout_amount = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="executed_market_settlements",
    )
    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-executed_at", "-id"]
        indexes = [
            models.Index(fields=["executed_at"]),
            models.Index(fields=["winning_outcome", "executed_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.market_id}: {self.total_payout_amount} {self.settlement_currency}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Market settlements are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Market settlements cannot be deleted.")


class MarketPositionSettlement(TimeStampedUUIDModel):
    market_settlement = models.ForeignKey(
        MarketSettlement,
        on_delete=models.PROTECT,
        related_name="position_settlements",
    )
    market_position = models.OneToOneField(
        MarketPosition,
        on_delete=models.PROTECT,
        related_name="settlement_record",
    )
    participant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="market_position_settlements",
    )
    outcome = models.ForeignKey(
        MarketOutcome,
        on_delete=models.PROTECT,
        related_name="position_settlements",
    )
    was_winner = models.BooleanField(db_index=True)
    settled_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    payout_per_unit = models.DecimalField(max_digits=20, decimal_places=4)
    payout_amount = models.DecimalField(max_digits=20, decimal_places=4)
    cost_basis = models.DecimalField(max_digits=20, decimal_places=4)
    realized_pnl_delta = models.DecimalField(max_digits=20, decimal_places=4)
    wallet_ledger_entry = models.OneToOneField(
        "wallets.LedgerEntry",
        on_delete=models.PROTECT,
        related_name="market_position_settlement",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["market_settlement", "was_winner"]),
            models.Index(fields=["participant", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.market_position_id}: {self.payout_amount}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Position settlements are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Position settlements cannot be deleted.")


class ImmutableVoidRefundModel(TimeStampedUUIDModel):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Void refund audit records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Void refund audit records cannot be deleted.")


class MarketVoidRefund(ImmutableVoidRefundModel):
    market = models.OneToOneField(
        Market,
        on_delete=models.PROTECT,
        related_name="void_refund",
    )
    refund_currency = models.CharField(max_length=3)
    total_cancelled_order_count = models.PositiveIntegerField(default=0)
    cancelled_buy_order_count = models.PositiveIntegerField(default=0)
    cancelled_sell_order_count = models.PositiveIntegerField(default=0)
    total_released_buy_reservation_amount = models.DecimalField(
        max_digits=20, decimal_places=4, default=Decimal("0.0000")
    )
    total_released_sell_reservation_quantity = models.DecimalField(
        max_digits=20, decimal_places=4, default=Decimal("0.0000")
    )
    refunded_position_count = models.PositiveIntegerField(default=0)
    total_refunded_position_quantity = models.DecimalField(
        max_digits=20, decimal_places=4, default=Decimal("0.0000")
    )
    total_position_refund_amount = models.DecimalField(
        max_digits=20, decimal_places=4, default=Decimal("0.0000")
    )
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="executed_market_void_refunds",
    )
    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-executed_at", "-id"]
        indexes = [models.Index(fields=["executed_at"])]

    def __str__(self):
        return f"{self.market_id}: {self.total_position_refund_amount} {self.refund_currency}"


class MarketVoidOrderCancellation(ImmutableVoidRefundModel):
    market_void_refund = models.ForeignKey(
        MarketVoidRefund,
        on_delete=models.PROTECT,
        related_name="order_cancellations",
    )
    market_order = models.OneToOneField(
        MarketOrder,
        on_delete=models.PROTECT,
        related_name="void_cancellation_record",
    )
    order_side = models.CharField(max_length=10, choices=MarketOrder.Side.choices)
    remaining_quantity_cancelled = models.DecimalField(max_digits=18, decimal_places=4)
    released_wallet_reservation_amount = models.DecimalField(
        max_digits=20, decimal_places=4, default=Decimal("0.0000")
    )
    released_position_reservation_quantity = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0.0000")
    )
    wallet_release_ledger_entry = models.OneToOneField(
        "wallets.LedgerEntry",
        on_delete=models.PROTECT,
        related_name="market_void_order_cancellation",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["market_void_refund", "order_side"])]

    def __str__(self):
        return f"{self.market_order_id}: {self.remaining_quantity_cancelled}"


class MarketPositionVoidRefund(ImmutableVoidRefundModel):
    market_void_refund = models.ForeignKey(
        MarketVoidRefund,
        on_delete=models.PROTECT,
        related_name="position_refunds",
    )
    market_position = models.OneToOneField(
        MarketPosition,
        on_delete=models.PROTECT,
        related_name="void_refund_record",
    )
    participant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="market_position_void_refunds",
    )
    outcome = models.ForeignKey(
        MarketOutcome,
        on_delete=models.PROTECT,
        related_name="position_void_refunds",
    )
    refunded_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    cost_basis = models.DecimalField(max_digits=20, decimal_places=4)
    refund_amount = models.DecimalField(max_digits=20, decimal_places=4)
    realized_pnl_delta = models.DecimalField(
        max_digits=20, decimal_places=4, default=Decimal("0.0000")
    )
    wallet_credit_ledger_entry = models.OneToOneField(
        "wallets.LedgerEntry",
        on_delete=models.PROTECT,
        related_name="market_position_void_refund",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["market_void_refund", "outcome"]),
            models.Index(fields=["participant", "created_at"]),
        ]

    def __str__(self):
        return f"{self.market_position_id}: {self.refund_amount}"


class ImmutableCloseCleanupModel(TimeStampedUUIDModel):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Market close cleanup audit records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Market close cleanup audit records cannot be deleted.")


class MarketCloseCleanup(ImmutableCloseCleanupModel):
    market = models.OneToOneField(Market, on_delete=models.PROTECT, related_name="close_cleanup")
    total_cancelled_order_count = models.PositiveIntegerField(default=0)
    cancelled_buy_order_count = models.PositiveIntegerField(default=0)
    cancelled_sell_order_count = models.PositiveIntegerField(default=0)
    total_released_buy_reservation_amount = models.DecimalField(
        max_digits=20, decimal_places=4, default=Decimal("0.0000")
    )
    total_released_sell_reservation_quantity = models.DecimalField(
        max_digits=20, decimal_places=4, default=Decimal("0.0000")
    )
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="executed_market_close_cleanups",
    )
    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-executed_at", "-id"]
        indexes = [models.Index(fields=["executed_at"])]

    def __str__(self):
        return f"{self.market_id}: {self.total_cancelled_order_count} orders"


class MarketCloseOrderCancellation(ImmutableCloseCleanupModel):
    market_close_cleanup = models.ForeignKey(
        MarketCloseCleanup,
        on_delete=models.PROTECT,
        related_name="order_cancellations",
    )
    market_order = models.OneToOneField(
        MarketOrder,
        on_delete=models.PROTECT,
        related_name="close_cancellation_record",
    )
    order_side = models.CharField(max_length=10, choices=MarketOrder.Side.choices)
    remaining_quantity_cancelled = models.DecimalField(max_digits=18, decimal_places=4)
    released_wallet_reservation_amount = models.DecimalField(
        max_digits=20, decimal_places=4, default=Decimal("0.0000")
    )
    released_position_reservation_quantity = models.DecimalField(
        max_digits=18, decimal_places=4, default=Decimal("0.0000")
    )
    wallet_release_ledger_entry = models.OneToOneField(
        "wallets.LedgerEntry",
        on_delete=models.PROTECT,
        related_name="market_close_order_cancellation",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["market_close_cleanup", "order_side"])]

    def __str__(self):
        return f"{self.market_order_id}: {self.remaining_quantity_cancelled}"


class MarketStatusTransition(TimeStampedUUIDModel):
    class Action(models.TextChoices):
        SUBMIT = "SUBMIT", "Submit for approval"
        APPROVE = "APPROVE", "Approve"
        REJECT = "REJECT", "Reject"
        OPEN = "OPEN", "Open"
        SUSPEND = "SUSPEND", "Suspend"
        REOPEN = "REOPEN", "Reopen"
        CLOSE = "CLOSE", "Close"
        RESOLVE = "RESOLVE", "Resolve"
        VOID = "VOID", "Void"

    market = models.ForeignKey(
        Market,
        on_delete=models.CASCADE,
        related_name="status_transitions",
    )
    action = models.CharField(
        max_length=20,
        choices=Action.choices,
        db_index=True,
    )
    from_status = models.CharField(
        max_length=30,
        choices=Market.Status.choices,
    )
    to_status = models.CharField(
        max_length=30,
        choices=Market.Status.choices,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="market_status_transitions",
        null=True,
        blank=True,
    )
    actor_email = models.EmailField()
    notes = models.TextField()
    metadata = models.JSONField(
        default=dict,
        blank=True,
    )

    class Meta:
        ordering = [
            "created_at",
            "id",
        ]
        indexes = [
            models.Index(
                fields=[
                    "market",
                    "created_at",
                ],
            ),
            models.Index(
                fields=[
                    "action",
                    "created_at",
                ],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.market.question}: " f"{self.from_status} → {self.to_status}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Market status history is immutable.")

        self.notes = self.notes.strip()

        if self.actor_id and not self.actor_email:
            self.actor_email = self.actor.email

        self.full_clean()

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Market status history cannot be deleted.")

    def clean(self):
        errors = {}

        if self.from_status == self.to_status:
            errors["to_status"] = "A status transition must change " "the market status."

        if not self.actor_email.strip():
            errors["actor_email"] = "An actor email snapshot is required."

        if not self.notes.strip():
            errors["notes"] = "Transition notes are required."

        if errors:
            raise ValidationError(errors)


class MarketFill(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False,
    )
    execution_reference = models.UUIDField(
        unique=True,
        editable=False,
    )
    market = models.ForeignKey(
        Market,
        on_delete=models.PROTECT,
        related_name="fills",
    )
    outcome = models.ForeignKey(
        MarketOutcome,
        on_delete=models.PROTECT,
        related_name="fills",
    )
    buy_order = models.ForeignKey(
        MarketOrder,
        on_delete=models.PROTECT,
        related_name="buy_fills",
    )
    sell_order = models.ForeignKey(
        MarketOrder,
        on_delete=models.PROTECT,
        related_name="sell_fills",
    )
    maker_order = models.ForeignKey(
        MarketOrder,
        on_delete=models.PROTECT,
        related_name="maker_fills",
    )
    taker_order = models.ForeignKey(
        MarketOrder,
        on_delete=models.PROTECT,
        related_name="taker_fills",
    )
    quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
    )
    price = models.DecimalField(
        max_digits=6,
        decimal_places=5,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = [
            "-created_at",
            "-id",
        ]
        indexes = [
            models.Index(
                fields=[
                    "market",
                    "created_at",
                ],
            ),
            models.Index(
                fields=[
                    "outcome",
                    "created_at",
                ],
            ),
            models.Index(
                fields=[
                    "buy_order",
                    "created_at",
                ],
            ),
            models.Index(
                fields=[
                    "sell_order",
                    "created_at",
                ],
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    quantity__gt=0,
                ),
                name=("market_fill_quantity_positive"),
            ),
            models.CheckConstraint(
                condition=models.Q(
                    price__gt=0,
                ),
                name=("market_fill_price_positive"),
            ),
            models.CheckConstraint(
                condition=models.Q(
                    price__lt=1,
                ),
                name=("market_fill_price_below_one"),
            ),
        ]

    def __str__(self):
        return f"{self.execution_reference}: " f"{self.quantity} @ {self.price}"

    def save(self, *args, **kwargs):
        if (
            self.pk
            and type(self)
            .objects.filter(
                pk=self.pk,
            )
            .exists()
        ):
            raise DjangoValidationError("Market fills are immutable and " "cannot be updated.")

        return super().save(
            *args,
            **kwargs,
        )

    def delete(self, *args, **kwargs):
        raise DjangoValidationError("Market fills are immutable and " "cannot be deleted.")

    def clean(self):
        super().clean()

        errors = {}

        buy_order = self.buy_order if self.buy_order_id else None
        sell_order = self.sell_order if self.sell_order_id else None
        maker_order = self.maker_order if self.maker_order_id else None
        taker_order = self.taker_order if self.taker_order_id else None
        outcome = self.outcome if self.outcome_id else None

        if buy_order and buy_order.side != MarketOrder.Side.BUY:
            errors["buy_order"] = "The buy order must have BUY side."

        if sell_order and sell_order.side != MarketOrder.Side.SELL:
            errors["sell_order"] = "The sell order must have " "SELL side."

        fill_orders = [
            order
            for order in [
                buy_order,
                sell_order,
                maker_order,
                taker_order,
            ]
            if order is not None
        ]

        if any(order.market_id != self.market_id for order in fill_orders):
            errors["market"] = "The fill market must match " "every fill order."

        if any(order.outcome_id != self.outcome_id for order in fill_orders):
            errors["outcome"] = "The fill outcome must match " "every fill order."

        if outcome and outcome.market_id != self.market_id:
            errors["outcome"] = "The fill outcome must belong " "to the fill market."

        fill_order_ids = {
            self.buy_order_id,
            self.sell_order_id,
        }

        if self.maker_order_id and self.maker_order_id not in fill_order_ids:
            errors["maker_order"] = "The maker must be one of the " "fill orders."

        if self.taker_order_id and self.taker_order_id not in fill_order_ids:
            errors["taker_order"] = "The taker must be one of the " "fill orders."

        if (
            self.maker_order_id
            and self.taker_order_id
            and self.maker_order_id == self.taker_order_id
        ):
            errors["taker_order"] = "Maker and taker must be " "different fill orders."

        if buy_order and sell_order and buy_order.user_id == sell_order.user_id:
            errors["sell_order"] = "Self-trading is not allowed."

        if self.quantity is not None and self.quantity <= Decimal("0.0000"):
            errors["quantity"] = "Fill quantity must be positive."

        if self.price is not None and (
            self.price <= Decimal("0.00000") or self.price >= Decimal("1.00000")
        ):
            errors["price"] = "Fill price must be greater " "than zero and less than one."

        if errors:
            raise DjangoValidationError(errors)

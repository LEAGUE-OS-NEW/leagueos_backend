import uuid
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
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
    class Source(models.TextChoices):
        ADMIN = "ADMIN", "Administrator"
        PROVIDER = "PROVIDER", "Provider"
        SYSTEM = "SYSTEM", "System"

    participant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="market_compliance_reviews"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="market_compliance_audits",
    )
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.ADMIN)
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


class ImmutableAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Audit records are immutable.")

    def delete(self):
        raise ValidationError("Audit records are immutable.")


class MarketRiskProfile(TimeStampedUUIDModel):
    class Band(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    participant = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="market_risk_profile"
    )
    current_score = models.PositiveSmallIntegerField(default=0)
    risk_band = models.CharField(
        max_length=10, choices=Band.choices, default=Band.LOW, db_index=True
    )
    restriction_recommendation = models.CharField(max_length=32, default="NONE", db_index=True)
    reason_codes = models.JSONField(default=list)
    last_assessed_at = models.DateTimeField(null=True, blank=True)
    assessment_source = models.CharField(max_length=16, default="SYSTEM")
    manual_override_state = models.CharField(max_length=16, default="NONE")
    manual_override_reason = models.TextField(blank=True)
    override_actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="market_risk_overrides",
    )
    override_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.risk_band} risk for {self.participant_id}"


class MarketRiskAssessment(TimeStampedUUIDModel):
    participant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="market_risk_assessments"
    )
    score = models.PositiveSmallIntegerField()
    band = models.CharField(max_length=10, choices=MarketRiskProfile.Band.choices)
    reason_codes = models.JSONField(default=list)
    input_summary = models.JSONField(default=dict)
    recommended_action = models.CharField(max_length=32)
    assessment_source = models.CharField(max_length=16, default="SYSTEM")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="market_risk_assessment_actions",
    )
    input_digest = models.CharField(max_length=64)
    objects = ImmutableAuditQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "input_digest"], name="risk_participant_input_uniq"
            )
        ]
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.band} assessment for {self.participant_id}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Risk assessments are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Risk assessments are immutable.")


class ComplianceDecisionProposal(TimeStampedUUIDModel):
    class DecisionType(models.TextChoices):
        CLEAR_CRITICAL_RISK_BLOCK = "CLEAR_CRITICAL_RISK_BLOCK", "Clear critical risk block"
        REMOVE_SUSPENDED_RESTRICTION = "REMOVE_SUSPENDED_RESTRICTION", "Remove suspension"
        JURISDICTION_BLOCK_TO_ALLOW = "JURISDICTION_BLOCK_TO_ALLOW", "Allow jurisdiction"
        APPLY_RISK_OVERRIDE = "APPLY_RISK_OVERRIDE", "Apply risk override"
        CLEAR_RISK_OVERRIDE = "CLEAR_RISK_OVERRIDE", "Clear risk override"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    participant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="compliance_decisions"
    )
    decision_type = models.CharField(max_length=40, choices=DecisionType.choices)
    requested_change = models.JSONField(default=dict)
    reason = models.TextField()
    before_snapshot = models.JSONField(default=dict)
    proposed_after_snapshot = models.JSONField(default=dict)
    proposer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="proposed_compliance_decisions",
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="decided_compliance_decisions",
    )
    decision_reason = models.TextField(blank=True)
    proposed_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)
    objects = ImmutableAuditQuerySet.as_manager()

    class Meta:
        ordering = ["-proposed_at", "-id"]
        indexes = [models.Index(fields=["status", "-proposed_at"])]

    def __str__(self):
        return f"{self.decision_type} proposal for {self.participant_id}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            previous = type(self).objects.get(pk=self.pk)
            allowed = (
                getattr(self, "_allow_finalize", False)
                and previous.status == self.Status.PENDING
                and self.status in {self.Status.APPROVED, self.Status.REJECTED}
            )
            if not allowed:
                raise ValidationError("Compliance decision proposals are immutable.")
        if not self.reason.strip():
            raise ValidationError("A proposal reason is required.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Compliance decision proposals are immutable.")


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
    face_value_ugx = models.PositiveIntegerField(default=5000)
    class MarketCloseReason(models.TextChoices):
        MAXIMUM_AMOUNT_REACHED = "MAXIMUM_AMOUNT_REACHED", "Maximum amount reached"
        SCHEDULED_CLOSE = "SCHEDULED_CLOSE", "Scheduled close"
        ADMIN_CLOSED = "ADMIN_CLOSED", "Admin closed"

    settlement_unit = models.PositiveIntegerField(
        default=5000,
        validators=[MinValueValidator(1)],
        help_text="UGX payout per winning share unit.",
    )
    max_market_amount = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Maximum UGX trading volume for this market.",
    )
    current_market_amount = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=Decimal("0.0000"),
        validators=[MinValueValidator(0)],
        help_text="Current executed BUY volume counting toward market capacity.",
    )
    close_reason = models.CharField(
        max_length=30,
        choices=MarketCloseReason.choices,
        null=True,
        blank=True,
        db_index=True,
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
    settles_by = models.DateTimeField(
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
            models.Index(
                fields=[
                    "status",
                    "current_market_amount",
                ],
                name="market_capacity_idx",
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

        if (
            self.closes_at is not None
            and self.settles_by is not None
            and self.settles_by < self.closes_at
        ):
            errors["settles_by"] = "Settlement target must be at or after the market close time."

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
    opening_price = models.DecimalField(max_digits=6, decimal_places=5, null=True, blank=True)

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
            models.CheckConstraint(
                condition=(
                    Q(opening_price__isnull=True)
                    | (Q(opening_price__gt=0) & Q(opening_price__lt=1))
                ),
                name="market_outcome_opening_price_between_zero_and_one",
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


class ImmutableProvisionalResultQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Provisional result records are immutable.")

    def delete(self):
        raise ValidationError("Provisional result records are immutable.")


class MarketProvisionalResult(TimeStampedUUIDModel):
    market = models.OneToOneField(
        Market,
        on_delete=models.PROTECT,
        related_name="provisional_result",
    )
    winning_outcome = models.ForeignKey(
        MarketOutcome,
        on_delete=models.PROTECT,
        related_name="provisional_results",
    )
    notes = models.TextField()
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="published_market_provisional_results",
    )
    publisher_email = models.EmailField()
    published_at = models.DateTimeField(db_index=True)
    dispute_deadline = models.DateTimeField(db_index=True)

    objects = ImmutableProvisionalResultQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at", "-id"]
        indexes = [
            models.Index(
                fields=["dispute_deadline"],
                name="mkt_prov_deadline_idx",
            ),
            models.Index(
                fields=["published_by", "-published_at"],
                name="mkt_prov_publisher_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(dispute_deadline__gt=models.F("published_at")),
                name="market_provisional_deadline_after_publish",
            )
        ]

    def __str__(self):
        return f"Provisional result for {self.market_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Provisional result records are immutable.")

        self.notes = self.notes.strip()

        if self.published_by_id and not self.publisher_email:
            self.publisher_email = self.published_by.email

        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Provisional result records cannot be deleted.")

    def clean(self):
        errors = {}

        if self.winning_outcome_id:
            if self.market_id and self.winning_outcome.market_id != self.market_id:
                errors["winning_outcome"] = (
                    "The provisional winning outcome must belong to the market."
                )

        if not self.notes.strip():
            errors["notes"] = "Provisional result notes are required."

        if self.published_at is None:
            errors["published_at"] = "A publication timestamp is required."

        if self.dispute_deadline is None:
            errors["dispute_deadline"] = "A dispute deadline is required."
        elif self.published_at is not None and self.dispute_deadline <= self.published_at:
            errors["dispute_deadline"] = "The dispute deadline must be after publication."

        if not self.publisher_email:
            errors["publisher_email"] = "The publisher email snapshot is required."

        if errors:
            raise ValidationError(errors)


class MarketResultDevelopmentAcceleration(TimeStampedUUIDModel):
    """Immutable marker ending a synthetic local market's dispute window for testing."""

    provisional_result = models.OneToOneField(
        MarketProvisionalResult,
        on_delete=models.PROTECT,
        related_name="development_acceleration",
    )
    accelerated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="result_development_accelerations",
    )
    accelerated_at = models.DateTimeField(default=timezone.now)
    reason = models.CharField(max_length=255, default="Development testing only")

    def __str__(self):
        return f"Development result acceleration for {self.provisional_result_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Development acceleration records are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Development acceleration records cannot be deleted.")


class MarketProvisionalEvidence(TimeStampedUUIDModel):
    class EvidenceType(models.TextChoices):
        OFFICIAL_RESULT = "OFFICIAL_RESULT", "Official result"
        DOCUMENT_REFERENCE = "DOCUMENT_REFERENCE", "Document reference"
        OFFICIAL_SOURCE = "OFFICIAL_SOURCE", "Official source"
        MEDIA_REFERENCE = "MEDIA_REFERENCE", "Media reference"

    provisional_result = models.ForeignKey(
        MarketProvisionalResult,
        on_delete=models.PROTECT,
        related_name="evidence_items",
    )
    evidence_type = models.CharField(
        max_length=30,
        choices=EvidenceType.choices,
        db_index=True,
    )
    label = models.CharField(max_length=255)
    reference = models.TextField()
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="recorded_market_provisional_evidence",
    )
    recorder_email = models.EmailField()
    recorded_at = models.DateTimeField(db_index=True)

    objects = ImmutableProvisionalResultQuerySet.as_manager()

    class Meta:
        ordering = ["recorded_at", "id"]
        indexes = [
            models.Index(
                fields=["provisional_result", "recorded_at"],
                name="mkt_prov_evidence_idx",
            )
        ]

    def __str__(self):
        return f"{self.evidence_type}: {self.label}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Provisional evidence records are immutable.")

        self.label = self.label.strip()
        self.reference = self.reference.strip()

        if self.recorded_by_id and not self.recorder_email:
            self.recorder_email = self.recorded_by.email

        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Provisional evidence records cannot be deleted.")

    def clean(self):
        errors = {}

        if not self.label.strip():
            errors["label"] = "An evidence label is required."

        if not self.reference.strip():
            errors["reference"] = "An evidence reference is required."

        if self.recorded_at is None:
            errors["recorded_at"] = "An evidence timestamp is required."

        if not self.recorder_email:
            errors["recorder_email"] = "The recorder email snapshot is required."

        if errors:
            raise ValidationError(errors)


class ImmutableResultDisputeQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Market result dispute records are immutable.")

    def delete(self):
        raise ValidationError("Market result dispute records are immutable.")


class MarketResultDispute(TimeStampedUUIDModel):
    class Category(models.TextChoices):
        INCORRECT_OUTCOME = (
            "INCORRECT_OUTCOME",
            "Incorrect outcome",
        )
        INCOMPLETE_EVIDENCE = (
            "INCOMPLETE_EVIDENCE",
            "Incomplete evidence",
        )
        SOURCE_CONFLICT = (
            "SOURCE_CONFLICT",
            "Conflicting official sources",
        )
        RULES_APPLICATION = (
            "RULES_APPLICATION",
            "Incorrect rules application",
        )
        OTHER = "OTHER", "Other"

    provisional_result = models.ForeignKey(
        MarketProvisionalResult,
        on_delete=models.PROTECT,
        related_name="disputes",
    )
    participant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="market_result_disputes",
    )
    participant_email = models.EmailField()
    category = models.CharField(
        max_length=30,
        choices=Category.choices,
        db_index=True,
    )
    explanation = models.TextField()
    submitted_at = models.DateTimeField(
        db_index=True,
    )

    objects = ImmutableResultDisputeQuerySet.as_manager()

    class Meta:
        ordering = [
            "-submitted_at",
            "-id",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "provisional_result",
                    "participant",
                ],
                name="uniq_mkt_result_dispute",
            )
        ]
        indexes = [
            models.Index(
                fields=[
                    "provisional_result",
                    "submitted_at",
                ],
                name="mkt_dispute_result_idx",
            ),
            models.Index(
                fields=[
                    "participant",
                    "-submitted_at",
                ],
                name="mkt_dispute_part_idx",
            ),
        ]

    def __str__(self):
        return f"Result dispute by {self.participant_id} " f"for {self.provisional_result_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Market result dispute records are immutable.")

        self.explanation = self.explanation.strip()

        if self.participant_id and not self.participant_email:
            self.participant_email = self.participant.email

        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Market result dispute records cannot be deleted.")

    def clean(self):
        errors = {}

        if not self.explanation.strip():
            errors["explanation"] = "A dispute explanation is required."

        if not self.participant_email:
            errors["participant_email"] = "The participant email snapshot is required."

        if self.submitted_at is None:
            errors["submitted_at"] = "A dispute submission timestamp is required."

        if errors:
            raise ValidationError(errors)


class MarketResultDisputeEvidence(TimeStampedUUIDModel):
    dispute = models.ForeignKey(
        MarketResultDispute,
        on_delete=models.PROTECT,
        related_name="evidence_items",
    )
    label = models.CharField(
        max_length=255,
    )
    reference = models.TextField()
    recorded_at = models.DateTimeField(
        db_index=True,
    )

    objects = ImmutableResultDisputeQuerySet.as_manager()

    class Meta:
        ordering = [
            "recorded_at",
            "id",
        ]
        indexes = [
            models.Index(
                fields=[
                    "dispute",
                    "recorded_at",
                ],
                name="mkt_dispute_evid_idx",
            )
        ]

    def __str__(self):
        return f"Dispute evidence: {self.label}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Market result dispute evidence is immutable.")

        self.label = self.label.strip()
        self.reference = self.reference.strip()

        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Market result dispute evidence cannot be deleted.")

    def clean(self):
        errors = {}

        if not self.label.strip():
            errors["label"] = "A dispute evidence label is required."

        if not self.reference.strip():
            errors["reference"] = "A dispute evidence reference is required."

        if self.recorded_at is None:
            errors["recorded_at"] = "An evidence timestamp is required."

        if errors:
            raise ValidationError(errors)


class MarketResultDisputeDecision(TimeStampedUUIDModel):
    class DecisionType(models.TextChoices):
        CONFIRM = "CONFIRM", "Confirm provisional result"
        CORRECT = "CORRECT", "Correct provisional result"
        VOID = "VOID", "Void market"
        EXTEND_REVIEW = "EXTEND_REVIEW", "Extend review"

    provisional_result = models.ForeignKey(
        MarketProvisionalResult,
        on_delete=models.PROTECT,
        related_name="decisions",
    )
    sequence = models.PositiveIntegerField()
    decision_type = models.CharField(
        max_length=20,
        choices=DecisionType.choices,
        db_index=True,
    )
    winning_outcome = models.ForeignKey(
        MarketOutcome,
        on_delete=models.PROTECT,
        related_name="result_dispute_decisions",
        null=True,
        blank=True,
    )
    review_extended_until = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )
    covered_dispute_count = models.PositiveIntegerField()
    notes = models.TextField()
    evidence = models.TextField()
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="market_result_dispute_decisions",
    )
    decision_maker_email = models.EmailField()
    decided_at = models.DateTimeField(
        db_index=True,
    )

    objects = ImmutableResultDisputeQuerySet.as_manager()

    class Meta:
        ordering = [
            "sequence",
            "id",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "provisional_result",
                    "sequence",
                ],
                name="uniq_mkt_dispute_dec_seq",
            ),
            models.UniqueConstraint(
                fields=[
                    "provisional_result",
                ],
                condition=Q(
                    decision_type__in=[
                        "CONFIRM",
                        "CORRECT",
                        "VOID",
                    ]
                ),
                name="uniq_mkt_dispute_final",
            ),
            models.CheckConstraint(
                condition=Q(sequence__gte=1),
                name="mkt_dispute_dec_seq_gte1",
            ),
            models.CheckConstraint(
                condition=Q(covered_dispute_count__gte=1),
                name="mkt_dispute_count_gte1",
            ),
        ]
        indexes = [
            models.Index(
                fields=[
                    "provisional_result",
                    "sequence",
                ],
                name="mkt_dispute_dec_seq_idx",
            ),
            models.Index(
                fields=[
                    "decided_by",
                    "-decided_at",
                ],
                name="mkt_dispute_decider_idx",
            ),
        ]

    def __str__(self):
        return f"Decision {self.sequence} for " f"{self.provisional_result_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Market result dispute decisions are immutable.")

        self.notes = self.notes.strip()
        self.evidence = self.evidence.strip()

        if self.decided_by_id and not self.decision_maker_email:
            self.decision_maker_email = self.decided_by.email

        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Market result dispute decisions cannot be deleted.")

    def clean(self):
        errors = {}

        if not self.notes.strip():
            errors["notes"] = "Decision notes are required."

        if not self.evidence.strip():
            errors["evidence"] = "Decision evidence is required."

        if not self.decision_maker_email:
            errors["decision_maker_email"] = "The decision-maker email snapshot is required."

        if self.decided_at is None:
            errors["decided_at"] = "A decision timestamp is required."

        if self.sequence is not None and self.sequence < 1:
            errors["sequence"] = "The decision sequence must be at least one."

        if self.covered_dispute_count is not None and self.covered_dispute_count < 1:
            errors["covered_dispute_count"] = "A decision must cover at least one dispute."

        provisional_result = None

        if self.provisional_result_id:
            provisional_result = self.provisional_result

        if self.winning_outcome_id and provisional_result:
            if self.winning_outcome.market_id != provisional_result.market_id:
                errors["winning_outcome"] = "The decision outcome must belong to the market."

        if self.decision_type == self.DecisionType.CONFIRM:
            if not self.winning_outcome_id:
                errors["winning_outcome"] = (
                    "A confirmed decision requires the " "provisional winning outcome."
                )
            elif (
                provisional_result
                and self.winning_outcome_id != provisional_result.winning_outcome_id
            ):
                errors["winning_outcome"] = (
                    "A confirmed decision must use the " "provisional winning outcome."
                )

            if self.review_extended_until is not None:
                errors["review_extended_until"] = "A final decision cannot extend review."

        elif self.decision_type == self.DecisionType.CORRECT:
            if not self.winning_outcome_id:
                errors["winning_outcome"] = "A corrected decision requires a winning outcome."
            elif (
                provisional_result
                and self.winning_outcome_id == provisional_result.winning_outcome_id
            ):
                errors["winning_outcome"] = (
                    "A corrected decision must differ from the " "provisional winning outcome."
                )

            if self.review_extended_until is not None:
                errors["review_extended_until"] = "A final decision cannot extend review."

        elif self.decision_type == self.DecisionType.VOID:
            if self.winning_outcome_id:
                errors["winning_outcome"] = "A void decision cannot have a winning outcome."

            if self.review_extended_until is not None:
                errors["review_extended_until"] = "A void decision cannot extend review."

        elif self.decision_type == self.DecisionType.EXTEND_REVIEW:
            if self.winning_outcome_id:
                errors["winning_outcome"] = "A review extension cannot have a winning outcome."

            if self.review_extended_until is None:
                errors["review_extended_until"] = "A review extension requires an end time."
            elif self.decided_at is not None and self.review_extended_until <= self.decided_at:
                errors["review_extended_until"] = (
                    "The extended review end time must be " "after the decision time."
                )

        if errors:
            raise ValidationError(errors)

    @property
    def is_final(self):
        return self.decision_type in {
            self.DecisionType.CONFIRM,
            self.DecisionType.CORRECT,
            self.DecisionType.VOID,
        }


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
        EXPIRED = "EXPIRED", "Expired"
        REJECTED = "REJECTED", "Rejected"

    class TimeInForce(models.TextChoices):
        GTC = "GTC", "Good till cancelled"
        GTD = "GTD", "Good till date"
        IOC = "IOC", "Immediate or cancel"
        FOK = "FOK", "Fill or kill"

    class OrderType(models.TextChoices):
        MARKET = "MARKET", "Market"
        LIMIT = "LIMIT", "Limit"

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
    order_type = models.CharField(
        max_length=10,
        choices=OrderType.choices,
        default=OrderType.LIMIT,
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
    amount = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="For MARKET BUY orders: UGX amount to spend.",
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
    time_in_force = models.CharField(
        max_length=3,
        choices=TimeInForce.choices,
        default=TimeInForce.GTC,
        db_index=True,
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )
    expired_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )
    fee_schedule = models.ForeignKey(
        "MarketFeeSchedule",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="orders",
    )
    maximum_fee_bps = models.PositiveIntegerField(default=0)

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
            models.CheckConstraint(
                condition=(
                    Q(
                        time_in_force="GTD",
                        expires_at__isnull=False,
                    )
                    | Q(
                        time_in_force__in=["GTC", "IOC", "FOK"],
                        expires_at__isnull=True,
                    )
                ),
                name="market_order_tif_expiry_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="EXPIRED",
                        expired_at__isnull=False,
                    )
                    | (~Q(status="EXPIRED") & Q(expired_at__isnull=True))
                ),
                name="market_order_expired_at_consistent",
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
            models.Index(
                fields=[
                    "time_in_force",
                    "status",
                    "expires_at",
                ],
                name="mkt_order_expiry_due_idx",
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

        if self.time_in_force == self.TimeInForce.GTD:
            if self.expires_at is None:
                errors["expires_at"] = "GTD orders require an expiry time."
            else:
                if self._state.adding and self.expires_at <= timezone.now():
                    errors["expires_at"] = "The order expiry time must be in the future."

                if (
                    self.market_id
                    and self.market.closes_at is not None
                    and self.expires_at > self.market.closes_at
                ):
                    errors["expires_at"] = (
                        "The order expiry time cannot be after " "the market close time."
                    )
        elif self.expires_at is not None:
            errors["expires_at"] = "Only GTD orders may define an expiry time."

        if self.status == self.Status.EXPIRED:
            if self.expired_at is None:
                errors["expired_at"] = "Expired orders require an expiry timestamp."
        elif self.expired_at is not None:
            errors["expired_at"] = "Only expired orders may have an expiry timestamp."

        if errors:
            raise ValidationError(errors)


class ImmutableOrderExpiryAuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Market order expiry audit records are immutable.")

    def delete(self):
        raise ValidationError("Market order expiry audit records are immutable.")


class MarketOrderExpiryAudit(TimeStampedUUIDModel):
    class Source(models.TextChoices):
        SYSTEM = "SYSTEM", "System"
        ADMIN = "ADMIN", "Administrator"

    market_order = models.OneToOneField(
        MarketOrder,
        on_delete=models.PROTECT,
        related_name="expiry_audit",
    )
    source = models.CharField(
        max_length=10,
        choices=Source.choices,
        db_index=True,
    )
    previous_status = models.CharField(
        max_length=30,
        choices=MarketOrder.Status.choices,
    )
    expired_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
    )
    released_wallet_reservation_amount = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    released_position_reservation_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    wallet_release_ledger_entry = models.OneToOneField(
        "wallets.LedgerEntry",
        on_delete=models.PROTECT,
        related_name="market_order_expiry_audit",
        null=True,
        blank=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="market_order_expiry_actions",
        null=True,
        blank=True,
    )
    reason = models.TextField()
    expired_at = models.DateTimeField(
        db_index=True,
    )

    objects = ImmutableOrderExpiryAuditQuerySet.as_manager()

    class Meta:
        ordering = [
            "-expired_at",
            "-id",
        ]
        indexes = [
            models.Index(
                fields=[
                    "source",
                    "-expired_at",
                ],
                name="mkt_order_exp_source_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(expired_quantity__gt=0),
                name="mkt_order_exp_qty_positive",
            ),
            models.CheckConstraint(
                condition=Q(released_wallet_reservation_amount__gte=0),
                name="mkt_order_exp_cash_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(released_position_reservation_quantity__gte=0),
                name="mkt_order_exp_shares_nonneg",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.market_order_id}: " f"{self.expired_quantity}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Market order expiry audit records are immutable.")

        self.reason = (self.reason or "").strip()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Market order expiry audit records cannot be deleted.")

    def clean(self):
        errors = {}

        if not self.reason:
            errors["reason"] = "An expiry reason is required."

        if self.expired_quantity is None or self.expired_quantity <= Decimal("0.0000"):
            errors["expired_quantity"] = "Expired quantity must be positive."

        if (
            self.released_wallet_reservation_amount is None
            or self.released_wallet_reservation_amount < Decimal("0.0000")
        ):
            errors["released_wallet_reservation_amount"] = (
                "Released wallet reservation amount " "cannot be negative."
            )

        if (
            self.released_position_reservation_quantity is None
            or self.released_position_reservation_quantity < Decimal("0.0000")
        ):
            errors["released_position_reservation_quantity"] = (
                "Released position reservation quantity " "cannot be negative."
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

    @property
    def available_shares(self):
        return (self.quantity - self.reserved_quantity).quantize(Decimal("0.0001"))

    @property
    def locked_shares(self):
        return self.reserved_quantity

    @property
    def current_value(self):
        if self.quantity <= 0:
            return Decimal("0.0000")
        return (self.quantity * self.average_entry_price).quantize(Decimal("0.0001"))

    @property
    def unrealized_profit(self):
        if self.quantity <= 0:
            return Decimal("0.0000")
        return (self.current_value - self.total_cost).quantize(Decimal("0.0001"))


class MarketLiquidityProvider(TimeStampedUUIDModel):
    class ProviderType(models.TextChoices):
        PLATFORM_TREASURY = "PLATFORM_TREASURY", "Platform treasury"
        EXTERNAL_MARKET_MAKER = "EXTERNAL_MARKET_MAKER", "External market maker"

    code = models.CharField(max_length=80, unique=True)
    provider_type = models.CharField(max_length=40, choices=ProviderType.choices)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="liquidity_provider"
    )
    is_active = models.BooleanField(default=True)
    display_name = models.CharField(max_length=160)

    def __str__(self):
        return f"{self.code}: {self.display_name}"


class MarketLiquidityConfiguration(TimeStampedUUIDModel):  # noqa: DJ012
    class Source(models.TextChoices):
        PLATFORM_TREASURY = "PLATFORM_TREASURY", "Platform treasury"
        EXTERNAL_MARKET_MAKER = "EXTERNAL_MARKET_MAKER", "External market maker"

    class Status(models.TextChoices):
        UNCONFIGURED = "UNCONFIGURED", "Unconfigured"
        CONFIGURED = "CONFIGURED", "Configured"
        ACTIVE = "ACTIVE", "Active"
        EXHAUSTED = "EXHAUSTED", "Exhausted"
        CLOSED = "CLOSED", "Closed"

    market = models.OneToOneField(
        Market, on_delete=models.PROTECT, related_name="liquidity_configuration"
    )
    source = models.CharField(
        max_length=40, choices=Source.choices, default=Source.PLATFORM_TREASURY
    )
    initial_liquidity_ugx = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    opening_spread_bps = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNCONFIGURED)
    configured_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="configured_market_liquidity",
    )
    configured_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    provider = models.ForeignKey(
        MarketLiquidityProvider,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="market_configurations",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(initial_liquidity_ugx__gte=0), name="market_liquidity_non_negative"
            ),
            models.CheckConstraint(
                condition=Q(opening_spread_bps__lte=5000), name="market_liquidity_spread_bounded"
            ),
        ]

    def clean(self):
        if self.market_id and self.market.status not in {
            Market.Status.DRAFT,
            Market.Status.REJECTED,
        }:
            previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
            mutable = ("source", "initial_liquidity_ugx", "opening_spread_bps", "provider_id")
            if previous is None or any(getattr(previous, f) != getattr(self, f) for f in mutable):
                raise ValidationError(
                    {"market": "Opening liquidity is frozen after draft/rejected."}
                )
        if self.initial_liquidity_ugx < 0:
            raise ValidationError({"initial_liquidity_ugx": "Liquidity cannot be negative."})
        if self.opening_spread_bps > 5000:
            raise ValidationError({"opening_spread_bps": "Spread cannot exceed 5000 bps."})

    def __str__(self):  # noqa: DJ012
        return f"{self.market_id}: {self.status}"


class MarketCollateralPool(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        SETTLED = "SETTLED", "Settled"
        RELEASED = "RELEASED", "Released"

    market = models.OneToOneField(Market, on_delete=models.PROTECT, related_name="collateral_pool")
    currency = models.CharField(max_length=3, default="UGX")
    locked_collateral = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    settled_collateral = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    released_collateral = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(locked_collateral__gte=0)
                & Q(settled_collateral__gte=0)
                & Q(released_collateral__gte=0),
                name="market_collateral_balances_non_negative",
            )
        ]

    def __str__(self):
        return f"{self.market_id}: {self.locked_collateral} {self.currency} locked"


class MarketCompleteSetIssuance(TimeStampedUUIDModel):  # noqa: DJ012
    class IssuanceType(models.TextChoices):
        PLATFORM_OPENING = "PLATFORM_OPENING", "Platform opening"
        COMPLEMENTARY_BUYS = "COMPLEMENTARY_BUYS", "Complementary buys"

    market = models.ForeignKey(
        Market, on_delete=models.PROTECT, related_name="complete_set_issuances"
    )
    issuance_type = models.CharField(max_length=30, choices=IssuanceType.choices)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    collateral_amount = models.DecimalField(max_digits=20, decimal_places=4)
    yes_execution_price = models.DecimalField(max_digits=6, decimal_places=5)
    no_execution_price = models.DecimalField(max_digits=6, decimal_places=5)
    yes_order = models.ForeignKey(
        MarketOrder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="yes_complete_set_issuances",
    )
    no_order = models.ForeignKey(
        MarketOrder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="no_complete_set_issuances",
    )
    provider = models.ForeignKey(
        MarketLiquidityProvider,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="issuances",
    )
    idempotency_reference = models.UUIDField(unique=True)
    issued_at = models.DateTimeField(default=timezone.now)

    def clean(self):
        if self.quantity <= 0 or self.collateral_amount != self.quantity:
            raise ValidationError(
                {"collateral_amount": "Collateral must exactly equal issuance quantity."}
            )
        if self.yes_execution_price + self.no_execution_price != Decimal("1.00000"):
            raise ValidationError({"prices": "YES and NO prices must sum exactly to 1.00000."})

    def save(self, *args, **kwargs):  # noqa: DJ012
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Complete-set issuances are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Complete-set issuances are immutable.")

    def __str__(self):  # noqa: DJ012
        return f"{self.market_id}: {self.issuance_type} {self.quantity}"


class MarketCollateralEntry(TimeStampedUUIDModel):  # noqa: DJ012
    class EntryType(models.TextChoices):
        TREASURY_LOCK = "TREASURY_LOCK", "Treasury lock"
        COMPLEMENTARY_BUY_LOCK = "COMPLEMENTARY_BUY_LOCK", "Complementary buy lock"
        SETTLEMENT_PAYOUT = "SETTLEMENT_PAYOUT", "Settlement payout"
        VOID_RELEASE = "VOID_RELEASE", "Void release"
        TREASURY_RELEASE = "TREASURY_RELEASE", "Treasury release"

    pool = models.ForeignKey(MarketCollateralPool, on_delete=models.PROTECT, related_name="entries")
    market = models.ForeignKey(Market, on_delete=models.PROTECT, related_name="collateral_entries")
    entry_type = models.CharField(max_length=40, choices=EntryType.choices)
    amount = models.DecimalField(max_digits=20, decimal_places=4)
    idempotency_reference = models.UUIDField(unique=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="market_collateral_entries",
    )
    provider = models.ForeignKey(
        MarketLiquidityProvider,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="collateral_entries",
    )
    order = models.ForeignKey(
        MarketOrder,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="collateral_entries",
    )
    issuance = models.ForeignKey(
        MarketCompleteSetIssuance,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="collateral_entries",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="market_collateral_entry_amount_positive"
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Collateral entries are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Collateral entries are immutable.")

    def __str__(self):  # noqa: DJ012
        return f"{self.market_id}: {self.entry_type} {self.amount}"


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
    payout_fee_amount = models.DecimalField(max_digits=20, decimal_places=4, default=Decimal("0"))
    net_payout_amount = models.DecimalField(max_digits=20, decimal_places=4, default=Decimal("0"))
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
    refund_fee_amount = models.DecimalField(max_digits=20, decimal_places=4, default=Decimal("0"))
    net_refund_amount = models.DecimalField(max_digits=20, decimal_places=4, default=Decimal("0"))
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


class ImmutableFinancialQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise DjangoValidationError("Financial audit records are immutable.")

    def delete(self):
        raise DjangoValidationError("Financial audit records are immutable.")


class MarketFeeScheduleQuerySet(models.QuerySet):
    FINANCIAL_FIELDS = {
        "status",
        "maker_fee_bps",
        "taker_fee_bps",
        "settlement_fee_bps",
        "refund_fee_bps",
        "effective_at",
        "market",
        "market_id",
        "version",
        "activated_by",
        "activated_by_id",
        "activated_at",
        "retired_by",
        "retired_by_id",
        "retired_at",
    }

    def update(self, **kwargs):
        if self.exclude(status=MarketFeeSchedule.Status.DRAFT).exists():
            raise DjangoValidationError("Activated fee schedules are immutable.")
        if self.FINANCIAL_FIELDS.intersection(kwargs):
            raise DjangoValidationError("Fee schedule lifecycle changes require the service.")
        return super().update(**kwargs)

    def delete(self):
        if self.exclude(status=MarketFeeSchedule.Status.DRAFT).exists():
            raise DjangoValidationError("Activated fee schedules cannot be deleted.")
        return super().delete()


class MarketFeeSchedule(TimeStampedUUIDModel):  # noqa: DJ008
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        RETIRED = "RETIRED", "Retired"

    MAX_RATE_BPS = 1000
    market = models.ForeignKey(
        Market, on_delete=models.PROTECT, related_name="fee_schedules", null=True, blank=True
    )
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    maker_fee_bps = models.PositiveIntegerField(default=0)
    taker_fee_bps = models.PositiveIntegerField(default=0)
    settlement_fee_bps = models.PositiveIntegerField(default=0)
    refund_fee_bps = models.PositiveIntegerField(default=0)
    effective_at = models.DateTimeField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_fee_schedules"
    )
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="activated_fee_schedules",
        null=True,
        blank=True,
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    retired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="retired_fee_schedules",
        null=True,
        blank=True,
    )
    retired_at = models.DateTimeField(null=True, blank=True)
    objects = MarketFeeScheduleQuerySet.as_manager()

    class Meta:
        ordering = ["-version", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["market", "version"],
                name="mkt_fee_scope_version_uniq",
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                condition=Q(maker_fee_bps__lte=1000),
                name="mkt_fee_maker_bps_max",
            ),
            models.CheckConstraint(
                condition=Q(taker_fee_bps__lte=1000),
                name="mkt_fee_taker_bps_max",
            ),
            models.CheckConstraint(
                condition=Q(settlement_fee_bps__lte=1000),
                name="mkt_fee_settle_bps_max",
            ),
            models.CheckConstraint(
                condition=Q(refund_fee_bps__lte=1000),
                name="mkt_fee_refund_bps_max",
            ),
        ]

    def save(self, *args, **kwargs):
        if (
            self.pk
            and type(self).objects.filter(pk=self.pk).exclude(status=self.Status.DRAFT).exists()
        ):
            raise DjangoValidationError("Activated fee schedules are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT:
            raise DjangoValidationError("Activated fee schedules cannot be deleted.")
        return super().delete(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        for field in (
            "maker_fee_bps",
            "taker_fee_bps",
            "settlement_fee_bps",
            "refund_fee_bps",
        ):
            value = getattr(self, field)
            if value is not None and value > self.MAX_RATE_BPS:
                errors[field] = f"Fee rate cannot exceed {self.MAX_RATE_BPS} basis points."
        if self.status == self.Status.ACTIVE and (
            self.activated_by_id is None or self.activated_at is None
        ):
            errors["status"] = "Active schedules require activation metadata."
        if errors:
            raise DjangoValidationError(errors)


class MarketFeeLedgerEntry(TimeStampedUUIDModel):  # noqa: DJ008
    class FeeType(models.TextChoices):
        MAKER = "MAKER", "Maker"
        TAKER = "TAKER", "Taker"
        SETTLEMENT = "SETTLEMENT", "Settlement"
        REFUND = "REFUND", "Refund"

    idempotency_reference = models.UUIDField(unique=True)
    schedule = models.ForeignKey(
        MarketFeeSchedule,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        null=True,
        blank=True,
    )
    schedule_version = models.PositiveIntegerField(default=0)
    market = models.ForeignKey(Market, on_delete=models.PROTECT, related_name="fee_entries")
    participant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="market_fee_entries"
    )
    fill = models.ForeignKey(
        MarketFill, on_delete=models.PROTECT, related_name="fee_entries", null=True, blank=True
    )
    order = models.ForeignKey(
        MarketOrder, on_delete=models.PROTECT, related_name="fee_entries", null=True, blank=True
    )
    fee_type = models.CharField(max_length=12, choices=FeeType.choices)
    rate_bps = models.PositiveIntegerField()
    gross_amount = models.DecimalField(max_digits=20, decimal_places=4)
    fee_amount = models.DecimalField(max_digits=20, decimal_places=4)
    net_amount = models.DecimalField(max_digits=20, decimal_places=4)
    currency = models.CharField(max_length=3, default="UGX")
    objects = ImmutableFinancialQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(rate_bps__lte=1000), name="mkt_fee_entry_rate_max"),
            models.CheckConstraint(condition=Q(gross_amount__gte=0), name="mkt_fee_gross_nonneg"),
            models.CheckConstraint(condition=Q(fee_amount__gte=0), name="mkt_fee_amount_nonneg"),
            models.CheckConstraint(condition=Q(net_amount__gte=0), name="mkt_fee_net_nonneg"),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise DjangoValidationError("Fee ledger entries are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise DjangoValidationError("Fee ledger entries cannot be deleted.")


class MarketReconciliationRun(TimeStampedUUIDModel):  # noqa: DJ008
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    reference = models.UUIDField(unique=True)
    run_date = models.DateField()
    market = models.ForeignKey(
        Market, on_delete=models.PROTECT, related_name="reconciliation_runs", null=True, blank=True
    )
    wallet = models.ForeignKey(
        "wallets.Wallet",
        on_delete=models.PROTECT,
        related_name="market_reconciliation_runs",
        null=True,
        blank=True,
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    started_at = models.DateTimeField(null=True)
    completed_at = models.DateTimeField(null=True)
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="market_reconciliation_runs",
        null=True,
        blank=True,
    )
    order_count = models.PositiveIntegerField(default=0)
    fill_count = models.PositiveIntegerField(default=0)
    mismatch_count = models.PositiveIntegerField(default=0)
    total_fee_amount = models.DecimalField(max_digits=20, decimal_places=4, default=Decimal("0"))

    objects = ImmutableFinancialQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        service_transition = kwargs.pop("_service_transition", False)
        if (
            self.pk
            and type(self)
            ._base_manager.filter(
                pk=self.pk,
                status__in=[self.Status.COMPLETED, self.Status.FAILED],
            )
            .exists()
        ):
            raise DjangoValidationError("Final reconciliation runs are immutable.")
        if not self._state.adding and not service_transition:
            raise DjangoValidationError("Reconciliation runs may only be finalized by the service.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise DjangoValidationError("Reconciliation runs cannot be deleted.")


class MarketReconciliationMismatch(TimeStampedUUIDModel):  # noqa: DJ008
    class Severity(models.TextChoices):
        INFO = "INFO", "Info"
        WARNING = "WARNING", "Warning"
        ERROR = "ERROR", "Error"
        CRITICAL = "CRITICAL", "Critical"

    class ResolutionStatus(models.TextChoices):
        OPEN = "OPEN", "Open"
        RESOLVED = "RESOLVED", "Resolved"

    run = models.ForeignKey(
        MarketReconciliationRun, on_delete=models.PROTECT, related_name="mismatches"
    )
    code = models.CharField(max_length=64, db_index=True)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    market_id_snapshot = models.UUIDField(null=True)
    participant_id_snapshot = models.UUIDField(null=True)
    wallet_id_snapshot = models.UUIDField(null=True)
    order_id_snapshot = models.UUIDField(null=True)
    fill_id_snapshot = models.UUIDField(null=True)
    expected_value = models.DecimalField(max_digits=24, decimal_places=4, null=True)
    actual_value = models.DecimalField(max_digits=24, decimal_places=4, null=True)
    unit = models.CharField(max_length=12, blank=True)
    explanation = models.TextField()
    detected_at = models.DateTimeField(default=timezone.now)
    resolution_status = models.CharField(
        max_length=10, choices=ResolutionStatus.choices, default=ResolutionStatus.OPEN
    )
    objects = ImmutableFinancialQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise DjangoValidationError("Reconciliation mismatches are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise DjangoValidationError("Reconciliation mismatches cannot be deleted.")


class MarketFinancialAdjustment(TimeStampedUUIDModel):  # noqa: DJ008
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    reason = models.TextField()
    evidence_reference = models.CharField(max_length=255)
    currency = models.CharField(max_length=3, default="UGX")
    market = models.ForeignKey(
        Market,
        on_delete=models.PROTECT,
        related_name="financial_adjustments",
        null=True,
        blank=True,
    )
    mismatch = models.ForeignKey(
        MarketReconciliationMismatch,
        on_delete=models.PROTECT,
        related_name="adjustments",
        null=True,
        blank=True,
    )
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="proposed_adjustments"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    executed_at = models.DateTimeField(null=True)

    objects = ImmutableFinancialQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]

    def save(self, *args, **kwargs):
        service_transition = kwargs.pop("_service_transition", False)
        if (
            self.pk
            and type(self)
            ._base_manager.filter(pk=self.pk)
            .exclude(status=self.Status.PENDING)
            .exists()
        ):
            raise DjangoValidationError("Final financial adjustments are immutable.")
        if not self._state.adding and not service_transition:
            raise DjangoValidationError("Adjustment decisions require the approval service.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise DjangoValidationError("Financial adjustments cannot be deleted.")


class MarketFinancialAdjustmentLine(TimeStampedUUIDModel):  # noqa: DJ008
    class Direction(models.TextChoices):
        DEBIT = "DEBIT", "Debit"
        CREDIT = "CREDIT", "Credit"

    adjustment = models.ForeignKey(
        MarketFinancialAdjustment, on_delete=models.PROTECT, related_name="lines"
    )
    wallet = models.ForeignKey(
        "wallets.Wallet", on_delete=models.PROTECT, related_name="market_adjustment_lines"
    )
    direction = models.CharField(max_length=6, choices=Direction.choices)
    amount = models.DecimalField(max_digits=20, decimal_places=4)
    idempotency_reference = models.UUIDField(unique=True)
    wallet_ledger_entry = models.OneToOneField(
        "wallets.LedgerEntry",
        on_delete=models.PROTECT,
        related_name="market_adjustment_line",
        null=True,
        blank=True,
    )

    objects = ImmutableFinancialQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="mkt_adjust_line_positive")
        ]

    def save(self, *args, **kwargs):
        service_link = kwargs.pop("_service_link", False)
        if not self._state.adding and not service_link:
            raise DjangoValidationError("Financial adjustment lines are immutable.")
        if service_link and set(kwargs.get("update_fields") or ()) - {
            "wallet_ledger_entry",
            "updated_at",
        }:
            raise DjangoValidationError("Only the executed ledger link may be updated.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise DjangoValidationError("Financial adjustment lines cannot be deleted.")


class MarketFinancialAdjustmentApproval(TimeStampedUUIDModel):  # noqa: DJ008
    class Decision(models.TextChoices):
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    adjustment = models.OneToOneField(
        MarketFinancialAdjustment, on_delete=models.PROTECT, related_name="approval"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="adjustment_decisions"
    )
    decision = models.CharField(max_length=10, choices=Decision.choices)
    notes = models.TextField(blank=True)
    decided_at = models.DateTimeField(default=timezone.now)
    objects = ImmutableFinancialQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise DjangoValidationError("Adjustment approvals are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise DjangoValidationError("Adjustment approvals cannot be deleted.")

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
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

    def clean(self):
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

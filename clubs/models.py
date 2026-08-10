"""Club Management & Administration models.

Extends the canonical ``profiles.Club`` with workspace-scoped administration
features.  All business configuration is database-driven — nothing is hardcoded.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class TimeStampedUUIDModel(models.Model):
    """Abstract base with UUID primary key and UTC timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True


# =============================================================================
# Workspace & Staff
# =============================================================================


class ClubWorkspace(TimeStampedUUIDModel):
    """Workspace linking a user to a club with a role and permissions."""

    class WorkspaceRole(models.TextChoices):
        ADMIN = "ADMIN", "Club Admin"
        STAFF = "STAFF", "Club Staff"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="club_workspaces",
    )
    club = models.ForeignKey(
        "profiles.Club",
        on_delete=models.CASCADE,
        related_name="workspaces",
    )
    role = models.CharField(
        max_length=20,
        choices=WorkspaceRole.choices,
        db_index=True,
    )
    permissions = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invited_workspaces",
    )
    invited_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)
    disabled_reason = models.TextField(blank=True)

    class Meta:
        unique_together = ["user", "club"]
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["club", "is_active", "role"]),
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} -> {self.club} ({self.role})"


class WorkspaceMembership(TimeStampedUUIDModel):
    """Membership of a user in a club workspace.

    Encapsulates a user's role (and effective permissions) within a specific
    ``ClubWorkspace``. Distinct from the platform-level ``Role``/``UserRole``
    assignments; a club-scoped administrator is linked to clubs through this
    model.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    workspace = models.ForeignKey(
        ClubWorkspace,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=ClubWorkspace.WorkspaceRole.choices,
        db_index=True,
    )
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="added_workspace_memberships",
    )
    added_at = models.DateTimeField(auto_now_add=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        unique_together = [("user", "workspace")]
        ordering = ["-added_at"]
        indexes = [
            models.Index(fields=["workspace", "is_active", "role"]),
            models.Index(fields=["user", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} -> {self.workspace} ({self.role})"


class StaffInvitation(TimeStampedUUIDModel):
    """Pending invitation for club staff."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        ACCEPTED = "ACCEPTED", "Accepted"
        EXPIRED = "EXPIRED", "Expired"
        CANCELLED = "CANCELLED", "Cancelled"

    club = models.ForeignKey(
        "profiles.Club",
        on_delete=models.CASCADE,
        related_name="staff_invitations",
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=20,
        choices=ClubWorkspace.WorkspaceRole.choices,
        db_index=True,
    )
    permissions = models.JSONField(default=list, blank=True)
    token = models.CharField(max_length=255, unique=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    expires_at = models.DateTimeField()
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_staff_invitations",
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_staff_invitations",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ["club", "email", "status"]
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["club", "status", "-created_at"]),
            models.Index(fields=["token", "status"]),
        ]

    def __str__(self) -> str:
        return f"Invitation to {self.email} for {self.club}"


# =============================================================================
# Club Profile (Extended)
# =============================================================================


class ClubProfileVersion(TimeStampedUUIDModel):
    """Versioned club profile for draft/preview/publish workflow."""

    class ProfileStatus(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING_APPROVAL = "PENDING_APPROVAL", "Pending approval"
        PUBLISHED = "PUBLISHED", "Published"
        ARCHIVED = "ARCHIVED", "Archived"

    club = models.ForeignKey(
        "profiles.Club",
        on_delete=models.CASCADE,
        related_name="profile_versions",
    )
    version = models.PositiveIntegerField(db_index=True)
    status = models.CharField(
        max_length=20,
        choices=ProfileStatus.choices,
        default=ProfileStatus.DRAFT,
        db_index=True,
    )
    display_name = models.CharField(max_length=200, blank=True)
    tagline = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    founded = models.PositiveIntegerField(null=True, blank=True)
    website = models.URLField(blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    country = models.ForeignKey(
        "profiles.Country",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="club_profile_versions",
    )
    logo = models.ImageField(upload_to="clubs/logos/", blank=True, null=True)
    cover_image = models.ImageField(upload_to="clubs/covers/", blank=True, null=True)
    stadium = models.CharField(max_length=255, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    coach = models.CharField(max_length=180, blank=True)
    league = models.ForeignKey(
        "sports.Competition",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="club_profile_versions",
    )
    social_links = models.JSONField(default=dict, blank=True)
    # {"twitter": "...", "facebook": "...", "instagram": "...", "youtube": "..."}
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_club_profiles",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_club_profiles",
    )

    class Meta:
        unique_together = ["club", "version"]
        ordering = ["-version"]
        indexes = [
            models.Index(fields=["club", "status", "-version"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.club.name} v{self.version} ({self.status})"

    def save(self, *args, **kwargs):
        if self.display_name:
            self.display_name = self.display_name.strip()
        if self.website:
            self.website = self.website.strip()
        super().save(*args, **kwargs)


class ClubMedia(TimeStampedUUIDModel):
    """Media asset for a club."""

    class MediaType(models.TextChoices):
        IMAGE = "IMAGE", "Image"
        VIDEO = "VIDEO", "Video"
        DOCUMENT = "DOCUMENT", "Document"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        ARCHIVED = "ARCHIVED", "Archived"

    club = models.ForeignKey(
        "profiles.Club",
        on_delete=models.CASCADE,
        related_name="media_assets",
    )
    media_type = models.CharField(
        max_length=20,
        choices=MediaType.choices,
        db_index=True,
    )
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    file = models.FileField(upload_to="clubs/media/", blank=True, null=True)
    url = models.URLField(max_length=1024, blank=True)
    thumbnail = models.ImageField(upload_to="clubs/thumbnails/", blank=True, null=True)
    file_size = models.BigIntegerField(null=True, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    is_featured = models.BooleanField(default=False, db_index=True)
    display_order = models.PositiveIntegerField(default=0, db_index=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_club_media",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_club_media",
    )

    class Meta:
        ordering = ["display_order", "-created_at"]
        indexes = [
            models.Index(fields=["club", "status", "display_order"]),
            models.Index(fields=["club", "media_type", "status"]),
            models.Index(fields=["is_featured", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.club.name} - {self.title or self.media_type}"


class ClubNews(TimeStampedUUIDModel):
    """News article for a club."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING_APPROVAL = "PENDING_APPROVAL", "Pending approval"
        PUBLISHED = "PUBLISHED", "Published"
        ARCHIVED = "ARCHIVED", "Archived"

    club = models.ForeignKey(
        "profiles.Club",
        on_delete=models.CASCADE,
        related_name="admin_news",
    )
    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=320, blank=True)
    summary = models.TextField(blank=True)
    body = models.TextField()
    category = models.ForeignKey(
        "discovery.NewsCategory",
        on_delete=models.PROTECT,
        related_name="club_news",
    )
    sport = models.ForeignKey(
        "sports.Sport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="club_news",
    )
    cover_image = models.ForeignKey(
        ClubMedia,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="news_cover",
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
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_club_news",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_club_news",
    )
    source_name = models.CharField(max_length=120, blank=True)
    source_reference = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]
        indexes = [
            models.Index(fields=["club", "status", "-published_at"]),
            models.Index(fields=["status", "is_verified", "-published_at"]),
            models.Index(fields=["is_featured", "status", "-published_at"]),
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


# =============================================================================
# Memberships
# =============================================================================


class MembershipPlan(TimeStampedUUIDModel):
    """Configurable membership plan for a club."""

    class BillingPeriod(models.TextChoices):
        MONTHLY = "MONTHLY", "Monthly"
        QUARTERLY = "QUARTERLY", "Quarterly"
        ANNUAL = "ANNUAL", "Annual"
        ONE_TIME = "ONE_TIME", "One time"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        PAUSED = "PAUSED", "Paused"
        ARCHIVED = "ARCHIVED", "Archived"

    club = models.ForeignKey(
        "profiles.Club",
        on_delete=models.CASCADE,
        related_name="membership_plans",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="UGX")
    billing_period = models.CharField(
        max_length=20,
        choices=BillingPeriod.choices,
        default=BillingPeriod.MONTHLY,
    )
    duration_days = models.PositiveIntegerField(default=30)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    is_featured = models.BooleanField(default=False, db_index=True)
    max_members = models.PositiveIntegerField(null=True, blank=True)
    benefits = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_membership_plans",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_membership_plans",
    )

    class Meta:
        unique_together = ["club", "slug"]
        ordering = ["-is_featured", "name"]
        indexes = [
            models.Index(fields=["club", "status", "-created_at"]),
            models.Index(fields=["status", "is_featured"]),
        ]

    def __str__(self) -> str:
        return f"{self.club.name} - {self.name}"

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        if not self.slug:
            self.slug = slugify(self.name)
        if self.price is not None and self.price < Decimal("0.00"):
            raise ValidationError({"price": "Price cannot be negative."})
        super().save(*args, **kwargs)


class Membership(TimeStampedUUIDModel):
    """User membership to a club plan."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        EXPIRED = "EXPIRED", "Expired"
        CANCELLED = "CANCELLED", "Cancelled"
        PENDING = "PENDING", "Pending"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    plan = models.ForeignKey(
        MembershipPlan,
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    starts_at = models.DateTimeField()
    expires_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ["user", "plan"]
        ordering = ["-starts_at"]
        indexes = [
            models.Index(fields=["user", "status", "-starts_at"]),
            models.Index(fields=["plan", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} - {self.plan}"


# =============================================================================
# Ticketing
# =============================================================================


class TicketProduct(TimeStampedUUIDModel):
    """Configurable ticket product for a club event."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        PAUSED = "PAUSED", "Paused"
        ARCHIVED = "ARCHIVED", "Archived"
        SOLD_OUT = "SOLD_OUT", "Sold out"

    club = models.ForeignKey(
        "profiles.Club",
        on_delete=models.CASCADE,
        related_name="ticket_products",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="UGX")
    event = models.ForeignKey(
        "sports.SportingEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ticket_products",
    )
    venue = models.CharField(max_length=255, blank=True)
    sales_start = models.DateTimeField(null=True, blank=True)
    sales_end = models.DateTimeField(null=True, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    sold = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    is_refundable = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_ticket_products",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_ticket_products",
    )

    class Meta:
        unique_together = ["club", "slug"]
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["club", "status", "-created_at"]),
            models.Index(fields=["status", "sales_start", "sales_end"]),
        ]

    def __str__(self) -> str:
        return f"{self.club.name} - {self.name}"

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        if not self.slug:
            self.slug = slugify(self.name)
        if self.price is not None and self.price < Decimal("0.00"):
            raise ValidationError({"price": "Price cannot be negative."})
        if self.capacity is not None and self.sold > self.capacity:
            raise ValidationError({"sold": "Sold cannot exceed capacity."})
        super().save(*args, **kwargs)


class TicketOrder(TimeStampedUUIDModel):
    """Order for tickets."""

    class OrderStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        FULFILLED = "FULFILLED", "Fulfilled"
        CANCELLED = "CANCELLED", "Cancelled"
        REFUNDED = "REFUNDED", "Refunded"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ticket_orders",
    )
    product = models.ForeignKey(
        TicketProduct,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="UGX")
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
        db_index=True,
    )
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status", "-created_at"]),
            models.Index(fields=["product", "status"]),
        ]

    def __str__(self) -> str:
        return f"Order {self.id} - {self.product}"


# =============================================================================
# Merchandise / Store
# =============================================================================


class ProductCategory(TimeStampedUUIDModel):
    """Configurable merchandise category."""

    club = models.ForeignKey(
        "profiles.Club",
        on_delete=models.CASCADE,
        related_name="product_categories",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    display_order = models.PositiveIntegerField(default=0, db_index=True)

    class Meta:
        unique_together = ["club", "slug"]
        ordering = ["display_order", "name"]
        indexes = [
            models.Index(fields=["club", "is_active", "display_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.club.name} - {self.name}"

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class MerchandiseProduct(TimeStampedUUIDModel):
    """Merchandise product for a club."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        PAUSED = "PAUSED", "Paused"
        ARCHIVED = "ARCHIVED", "Archived"
        OUT_OF_STOCK = "OUT_OF_STOCK", "Out of stock"

    club = models.ForeignKey(
        "profiles.Club",
        on_delete=models.CASCADE,
        related_name="merchandise_products",
    )
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="UGX")
    sku = models.CharField(max_length=100, blank=True, db_index=True)
    stock = models.PositiveIntegerField(default=0)
    reserved_stock = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=10)
    images = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    is_featured = models.BooleanField(default=False, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_merchandise",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_merchandise",
    )

    class Meta:
        unique_together = ["club", "slug"]
        ordering = ["-is_featured", "name"]
        indexes = [
            models.Index(fields=["club", "status", "-created_at"]),
            models.Index(fields=["status", "is_featured"]),
            models.Index(fields=["sku", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.club.name} - {self.name}"

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        if not self.slug:
            self.slug = slugify(self.name)
        if self.price is not None and self.price < Decimal("0.00"):
            raise ValidationError({"price": "Price cannot be negative."})
        if self.stock < 0 or self.reserved_stock < 0:
            raise ValidationError("Stock values cannot be negative.")
        if self.reserved_stock > self.stock:
            raise ValidationError("Reserved stock cannot exceed total stock.")
        super().save(*args, **kwargs)

    @property
    def available_stock(self) -> int:
        return max(0, self.stock - self.reserved_stock)

    @property
    def is_low_stock(self) -> bool:
        return self.available_stock <= self.low_stock_threshold


class StoreOrder(TimeStampedUUIDModel):
    """Merchandise order."""

    class OrderStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        PROCESSING = "PROCESSING", "Processing"
        FULFILLED = "FULFILLED", "Fulfilled"
        CANCELLED = "CANCELLED", "Cancelled"
        REFUNDED = "REFUNDED", "Refunded"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="store_orders",
    )
    club = models.ForeignKey(
        "profiles.Club",
        on_delete=models.CASCADE,
        related_name="store_orders",
    )
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
        db_index=True,
    )
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="UGX")
    shipping_address = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status", "-created_at"]),
            models.Index(fields=["club", "status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Store order {self.id} - {self.club.name}"


class StoreOrderItem(TimeStampedUUIDModel):
    """Line item in a merchandise order."""

    order = models.ForeignKey(
        StoreOrder,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        MerchandiseProduct,
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    total_price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["order", "product"]),
        ]

    def __str__(self) -> str:
        return f"{self.product.name} x {self.quantity}"

    def save(self, *args, **kwargs):
        self.total_price = self.unit_price * self.quantity
        super().save(*args, **kwargs)


# =============================================================================
# Inventory
# =============================================================================


class InventoryAdjustment(TimeStampedUUIDModel):
    """Auditable inventory adjustment."""

    class AdjustmentType(models.TextChoices):
        RESTOCK = "RESTOCK", "Restock"
        SALE = "SALE", "Sale"
        RETURN = "RETURN", "Return"
        DAMAGED = "DAMAGED", "Damaged"
        CORRECTION = "CORRECTION", "Correction"

    product = models.ForeignKey(
        MerchandiseProduct,
        on_delete=models.CASCADE,
        related_name="inventory_adjustments",
    )
    adjustment_type = models.CharField(
        max_length=20,
        choices=AdjustmentType.choices,
        db_index=True,
    )
    quantity_change = models.IntegerField()
    previous_stock = models.PositiveIntegerField()
    new_stock = models.PositiveIntegerField()
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_adjustments",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["product", "-created_at"]),
            models.Index(fields=["adjustment_type", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.product.name}: {self.adjustment_type} ({self.quantity_change})"

    def save(self, *args, **kwargs):
        if self.quantity_change == 0:
            raise ValidationError("Quantity change cannot be zero.")
        if self.new_stock < 0:
            raise ValidationError("New stock cannot be negative.")
        super().save(*args, **kwargs)


# =============================================================================
# Analytics
# =============================================================================


class ClubAnalytics(TimeStampedUUIDModel):
    """Aggregated daily analytics for a club."""

    class MetricType(models.TextChoices):
        FAN_GROWTH = "FAN_GROWTH", "Fan growth"
        MEMBERSHIP_SALES = "MEMBERSHIP_SALES", "Membership sales"
        TICKET_SALES = "TICKET_SALES", "Ticket sales"
        MERCHANDISE_SALES = "MERCHANDISE_SALES", "Merchandise sales"
        CONTENT_ENGAGEMENT = "CONTENT_ENGAGEMENT", "Content engagement"
        REVENUE = "REVENUE", "Revenue"
        INVENTORY_PERFORMANCE = "INVENTORY_PERFORMANCE", "Inventory performance"

    club = models.ForeignKey(
        "profiles.Club",
        on_delete=models.CASCADE,
        related_name="analytics",
    )
    metric_type = models.CharField(
        max_length=30,
        choices=MetricType.choices,
        db_index=True,
    )
    date = models.DateField(db_index=True)
    value = models.DecimalField(max_digits=16, decimal_places=2)
    currency = models.CharField(max_length=3, default="UGX")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ["club", "metric_type", "date"]
        ordering = ["-date", "metric_type"]
        indexes = [
            models.Index(fields=["club", "metric_type", "-date"]),
            models.Index(fields=["metric_type", "-date"]),
        ]

    def __str__(self) -> str:
        return f"{self.club.name} - {self.metric_type} ({self.date})"


# =============================================================================
# Audit
# =============================================================================


class ClubAuditLog(TimeStampedUUIDModel):
    """Audit log for club administration actions."""

    ACTION_CHOICES = [
        ("WORKSPACE_SWITCHED", "Workspace switched"),
        ("CLUB_PROFILE_UPDATED", "Club profile updated"),
        ("BRANDING_CHANGED", "Branding changed"),
        ("MEDIA_UPLOADED", "Media uploaded"),
        ("NEWS_PUBLISHED", "News published"),
        ("MEMBERSHIP_CREATED", "Membership created"),
        ("TICKET_CREATED", "Ticket created"),
        ("PRODUCT_CREATED", "Product created"),
        ("INVENTORY_UPDATED", "Inventory updated"),
        ("STAFF_INVITED", "Staff invited"),
        ("STAFF_DISABLED", "Staff disabled"),
        ("ROLE_GRANTED", "Role granted"),
        ("ROLE_REVOKED", "Role revoked"),
        ("PERMISSION_CHANGED", "Permission changed"),
        ("ANALYTICS_VIEWED", "Analytics viewed"),
    ]

    club = models.ForeignKey(
        "profiles.Club",
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="club_audit_logs",
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES, db_index=True)
    entity_type = models.CharField(max_length=50, blank=True, db_index=True)
    entity_id = models.UUIDField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["club", "action", "-created_at"]),
            models.Index(fields=["user", "action", "-created_at"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.club.name} - {self.action} ({self.created_at.isoformat()})"

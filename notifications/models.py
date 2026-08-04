"""Notification and Communication Preferences models.

Provides enterprise-grade, fully configurable notification preferences
with no hardcoded business logic. All categories and channels are
database-driven.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class NotificationCategory(models.Model):
    """Configurable notification category.

    Categories are seeded via data migrations and can be extended
    without code changes. Examples: Fixtures, Live Match Updates,
    Security Alerts, etc.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    mandatory = models.BooleanField(default=False, db_index=True)
    default_enabled = models.BooleanField(default=True)
    priority = models.IntegerField(default=0, db_index=True)
    display_order = models.IntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "priority", "name"]
        indexes = [
            models.Index(fields=["is_active", "display_order"]),
            models.Index(fields=["mandatory", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class NotificationChannel(models.Model):
    """Configurable communication channel.

    Channels are seeded via data migrations. Initial channels:
    - Email
    - Push Notification
    - In-App Notification

    Architecture supports future channels without code changes.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    provider = models.CharField(max_length=100, blank=True)
    display_order = models.IntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name"]
        indexes = [
            models.Index(fields=["is_active", "display_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class NotificationChannelCapability(models.Model):
    """Channel capability definition.

    Defines what each channel supports. Enables extensible validation
    without modifying existing business logic.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        NotificationChannel,
        on_delete=models.CASCADE,
        related_name="capabilities",
    )
    capability = models.CharField(max_length=100, db_index=True)
    is_supported = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["channel", "capability"]
        ordering = ["channel__display_order", "capability"]
        indexes = [
            models.Index(fields=["channel", "capability"]),
        ]

    def __str__(self) -> str:
        return f"{self.channel.code} - {self.capability}"


class UserNotificationPreference(models.Model):
    """User-specific notification preference.

    Each record represents whether a user wants to receive a specific
    notification category through a specific channel.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    notification_category = models.ForeignKey(
        NotificationCategory,
        on_delete=models.CASCADE,
        related_name="user_preferences",
    )
    notification_channel = models.ForeignKey(
        NotificationChannel,
        on_delete=models.CASCADE,
        related_name="user_preferences",
    )
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["user", "notification_category", "notification_channel"]
        ordering = ["user__email", "notification_category__display_order"]
        indexes = [
            models.Index(fields=["user", "notification_category"]),
            models.Index(fields=["user", "enabled"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.user} - {self.notification_category.code} via {self.notification_channel.code}"
        )


class CommunicationConsent(models.Model):
    """Immutable consent record.

    Tracks user consent for communications. Never overwritten -
    new records are created for changes.
    """

    CONSENT_TYPES = [
        ("MARKETING", "Marketing communications"),
        ("NEWSLETTER", "Newsletter subscription"),
        ("SMS_NOTIFICATIONS", "SMS notifications"),
        ("PUSH_NOTIFICATIONS", "Push notifications"),
        ("EMAIL_NOTIFICATIONS", "Email notifications"),
        ("DATA_SHARING", "Data sharing with partners"),
        ("PROFILING", "User profiling"),
        ("COOKIES", "Cookie consent"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="communication_consents",
    )
    consent_type = models.CharField(max_length=50, choices=CONSENT_TYPES, db_index=True)
    granted = models.BooleanField()
    granted_at = models.DateTimeField(default=timezone.now)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(
        max_length=50,
        default="WEB",
        choices=[("WEB", "Web"), ("MOBILE", "Mobile"), ("API", "API"), ("ADMIN", "Admin")],
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-granted_at"]
        indexes = [
            models.Index(fields=["user", "consent_type", "-granted_at"]),
            models.Index(fields=["user", "granted"]),
        ]

    def __str__(self) -> str:
        status = "granted" if self.granted else "withdrawn"
        return f"{self.user} - {self.consent_type} ({status})"


class QuietHours(models.Model):
    """User quiet hours configuration.

    Optional notifications respect quiet hours. Mandatory notifications
    bypass quiet hours.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="quiet_hours",
    )
    enabled = models.BooleanField(default=False)
    start_time = models.TimeField()
    end_time = models.TimeField()
    timezone = models.CharField(max_length=100, default="UTC")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "enabled"]),
        ]

    def __str__(self) -> str:
        return f"Quiet hours for {self.user} ({self.start_time} - {self.end_time})"


class NotificationPreferenceAudit(models.Model):
    """Audit log for notification preference changes.

    Records all actions related to notification preferences for
    compliance and debugging.
    """

    ACTION_CHOICES = [
        ("NOTIFICATION_PREFERENCES_VIEWED", "Notification preferences viewed"),
        ("NOTIFICATION_PREFERENCES_UPDATED", "Notification preferences updated"),
        ("CHANNEL_ENABLED", "Channel enabled"),
        ("CHANNEL_DISABLED", "Channel disabled"),
        ("QUIET_HOURS_UPDATED", "Quiet hours updated"),
        ("QUIET_HOURS_DISABLED", "Quiet hours disabled"),
        ("CONSENT_GRANTED", "Consent granted"),
        ("CONSENT_WITHDRAWN", "Consent withdrawn"),
        ("RESET_TO_DEFAULTS", "Reset to defaults"),
        ("MANDATORY_NOTIFICATION_SENT", "Mandatory notification sent"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_audit_logs",
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES, db_index=True)
    category = models.ForeignKey(
        NotificationCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    channel = models.ForeignKey(
        NotificationChannel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user", "action", "-timestamp"]),
            models.Index(fields=["-timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} - {self.timestamp.isoformat()}"


class ImmutableDeliveryAttemptQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Delivery attempts are immutable.")

    def delete(self):
        raise ValidationError("Delivery attempts are immutable.")


class Notification(models.Model):
    class Severity(models.TextChoices):
        INFO = "INFO", "Information"
        WARNING = "WARNING", "Warning"
        CRITICAL = "CRITICAL", "Critical"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    category = models.ForeignKey(
        NotificationCategory, on_delete=models.PROTECT, related_name="notifications"
    )
    event_type = models.CharField(max_length=100, db_index=True)
    title = models.CharField(max_length=255)
    message = models.TextField()
    severity = models.CharField(
        max_length=12, choices=Severity.choices, default=Severity.INFO, db_index=True
    )
    data = models.JSONField(default=dict, blank=True)
    deep_link_path = models.CharField(max_length=500, blank=True)
    market_id = models.UUIDField(null=True, blank=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_notifications",
    )
    deduplication_key = models.CharField(max_length=255)
    mandatory = models.BooleanField(default=False)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "deduplication_key"], name="notification_recipient_dedupe_uniq"
            )
        ]
        indexes = [models.Index(fields=["recipient", "-occurred_at", "-id"])]

    def __str__(self):
        return f"{self.event_type} for {self.recipient_id}"


class ProtectedDeliveryQuerySet(models.QuerySet):
    TERMINAL = {"DELIVERED", "FAILED", "CANCELLED"}

    def update(self, **kwargs):
        if kwargs.get("status") in self.TERMINAL or self.filter(status__in=self.TERMINAL).exists():
            raise ValidationError("Terminal delivery transitions require the delivery service.")
        return super().update(**kwargs)

    def delete(self):
        if self.filter(status__in=self.TERMINAL).exists():
            raise ValidationError("Terminal notification deliveries are immutable.")
        return super().delete()


class NotificationDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        DEFERRED = "DEFERRED", "Deferred"
        PROCESSING = "PROCESSING", "Processing"
        DELIVERED = "DELIVERED", "Delivered"
        FAILED = "FAILED", "Failed"
        CANCELLED = "CANCELLED", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="deliveries"
    )
    channel = models.ForeignKey(
        NotificationChannel, on_delete=models.PROTECT, related_name="deliveries"
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    provider_message_id = models.CharField(max_length=255, null=True, blank=True)  # noqa: DJ001
    last_error_code = models.CharField(max_length=100, blank=True)
    last_error_message = models.CharField(max_length=500, blank=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = ProtectedDeliveryQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["notification", "channel"], name="notification_channel_delivery_uniq"
            )
        ]
        ordering = ["next_attempt_at", "created_at", "id"]

    def __str__(self):
        return f"{self.channel_id} delivery for {self.notification_id}"

    def save(self, *args, **kwargs):
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).values("status").first()
            terminal = {self.Status.DELIVERED, self.Status.FAILED, self.Status.CANCELLED}
            if previous and previous["status"] in terminal:
                raise ValidationError("Terminal notification deliveries are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        terminal = {self.Status.DELIVERED, self.Status.FAILED, self.Status.CANCELLED}
        if self.status in terminal:
            raise ValidationError("Terminal notification deliveries are immutable.")
        return super().delete(*args, **kwargs)


class NotificationDeliveryAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    delivery = models.ForeignKey(
        NotificationDelivery, on_delete=models.PROTECT, related_name="attempts"
    )
    attempt_number = models.PositiveIntegerField()
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField()
    outcome = models.CharField(max_length=16)
    provider_reference = models.CharField(max_length=255, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    error_message = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableDeliveryAttemptQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["delivery", "attempt_number"], name="delivery_attempt_number_uniq"
            )
        ]
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Attempt {self.attempt_number} for {self.delivery_id}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Delivery attempts are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Delivery attempts are immutable.")

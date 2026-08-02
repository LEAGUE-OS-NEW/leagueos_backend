"""Admin configuration for notifications app."""

from django.contrib import admin

from notifications.models import (
    CommunicationConsent,
    NotificationCategory,
    NotificationChannel,
    NotificationChannelCapability,
    NotificationPreferenceAudit,
    QuietHours,
    UserNotificationPreference,
)


@admin.register(NotificationCategory)
class NotificationCategoryAdmin(admin.ModelAdmin):
    """Admin for NotificationCategory."""

    list_display = [
        "code",
        "name",
        "mandatory",
        "default_enabled",
        "priority",
        "display_order",
        "is_active",
    ]
    list_filter = ["mandatory", "is_active", "priority"]
    search_fields = ["code", "name", "description"]
    ordering = ["display_order", "priority", "name"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(NotificationChannel)
class NotificationChannelAdmin(admin.ModelAdmin):
    """Admin for NotificationChannel."""

    list_display = ["code", "name", "provider", "display_order", "is_active"]
    list_filter = ["is_active", "provider"]
    search_fields = ["code", "name", "description", "provider"]
    ordering = ["display_order", "name"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(NotificationChannelCapability)
class NotificationChannelCapabilityAdmin(admin.ModelAdmin):
    """Admin for NotificationChannelCapability."""

    list_display = ["channel", "capability", "is_supported"]
    list_filter = ["channel", "is_supported"]
    search_fields = ["channel__code", "capability"]
    ordering = ["channel__display_order", "capability"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(UserNotificationPreference)
class UserNotificationPreferenceAdmin(admin.ModelAdmin):
    """Admin for UserNotificationPreference."""

    list_display = ["user", "notification_category", "notification_channel", "enabled"]
    list_filter = ["enabled", "notification_category__mandatory"]
    search_fields = ["user__email", "notification_category__code", "notification_channel__code"]
    ordering = ["user__email", "notification_category__display_order"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(CommunicationConsent)
class CommunicationConsentAdmin(admin.ModelAdmin):
    """Admin for CommunicationConsent."""

    list_display = ["user", "consent_type", "granted", "granted_at", "source"]
    list_filter = ["granted", "consent_type", "source"]
    search_fields = ["user__email", "consent_type"]
    ordering = ["-granted_at"]
    readonly_fields = ["id", "created_at"]


@admin.register(QuietHours)
class QuietHoursAdmin(admin.ModelAdmin):
    """Admin for QuietHours."""

    list_display = ["user", "enabled", "start_time", "end_time", "timezone"]
    list_filter = ["enabled"]
    search_fields = ["user__email"]
    ordering = ["user__email"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(NotificationPreferenceAudit)
class NotificationPreferenceAuditAdmin(admin.ModelAdmin):
    """Admin for NotificationPreferenceAudit."""

    list_display = ["user", "action", "category", "channel", "timestamp"]
    list_filter = ["action", "timestamp"]
    search_fields = ["user__email", "action"]
    ordering = ["-timestamp"]
    readonly_fields = ["id", "timestamp"]
    date_hierarchy = "timestamp"

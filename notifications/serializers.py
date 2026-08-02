"""Serializers for notification and communication preferences.

Provides serializers for all notification-related models with
proper validation and no hardcoded business logic.
"""

from __future__ import annotations

from datetime import time
from typing import Any

from django.contrib.auth import get_user_model
from rest_framework import serializers

from notifications.models import (
    CommunicationConsent,
    NotificationCategory,
    NotificationChannel,
    NotificationChannelCapability,
    NotificationPreferenceAudit,
    QuietHours,
    UserNotificationPreference,
)

User = get_user_model()


# =============================================================================
# Lookup Serializers (Read-only for users)
# =============================================================================


class NotificationCategorySerializer(serializers.ModelSerializer):
    """Serializer for notification categories.

    Read-only for users - categories are managed by admins.
    """

    class Meta:
        model = NotificationCategory
        fields = [
            "id",
            "code",
            "name",
            "description",
            "mandatory",
            "default_enabled",
            "priority",
            "display_order",
        ]
        read_only_fields = fields


class NotificationChannelSerializer(serializers.ModelSerializer):
    """Serializer for notification channels.

    Read-only for users - channels are managed by admins.
    """

    class Meta:
        model = NotificationChannel
        fields = [
            "id",
            "code",
            "name",
            "description",
            "provider",
            "display_order",
        ]
        read_only_fields = fields


# =============================================================================
# Preference Serializers
# =============================================================================


class UserNotificationPreferenceSerializer(serializers.ModelSerializer):
    """Serializer for user notification preferences."""

    category = NotificationCategorySerializer(source="notification_category", read_only=True)
    channel = NotificationChannelSerializer(source="notification_channel", read_only=True)

    class Meta:
        model = UserNotificationPreference
        fields = [
            "id",
            "category",
            "channel",
            "enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class SinglePreferenceUpdateSerializer(serializers.Serializer):
    """Serializer for a single preference update."""

    category_id = serializers.UUIDField()
    channel_id = serializers.UUIDField()
    enabled = serializers.BooleanField()


class PreferenceBulkUpdateSerializer(serializers.Serializer):
    """Serializer for bulk updating notification preferences.

    Expects a list of preference updates:
    [
        {"category_id": "uuid", "channel_id": "uuid", "enabled": true},
        ...
    ]
    """

    preferences = serializers.ListField(
        child=SinglePreferenceUpdateSerializer(),
        allow_empty=False,
    )


# =============================================================================
# Quiet Hours Serializers
# =============================================================================


class QuietHoursSerializer(serializers.ModelSerializer):
    """Serializer for quiet hours configuration."""

    class Meta:
        model = QuietHours
        fields = [
            "id",
            "enabled",
            "start_time",
            "end_time",
            "timezone",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_start_time(self, value: time) -> time:
        """Validate start_time is a valid time."""
        return value

    def validate_end_time(self, value: time) -> time:
        """Validate end_time is a valid time."""
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Cross-field validation for quiet hours."""
        start = attrs.get("start_time")
        end = attrs.get("end_time")

        if start and end:
            # Allow quiet hours to wrap around midnight (e.g., 22:00 to 08:00)
            # But validate they're not the same time
            if start == end:
                raise serializers.ValidationError("start_time and end_time cannot be the same.")

            # Validate timezone
            timezone = attrs.get("timezone", "UTC")
            try:
                import pytz

                if timezone not in pytz.all_timezones:
                    raise serializers.ValidationError({"timezone": f"Invalid timezone: {timezone}"})
            except ImportError:
                # pytz not installed, skip validation
                pass

        return attrs


# =============================================================================
# Consent Serializers
# =============================================================================


class CommunicationConsentSerializer(serializers.ModelSerializer):
    """Serializer for communication consent records.

    Read-only - consents are created via dedicated endpoints.
    """

    class Meta:
        model = CommunicationConsent
        fields = [
            "id",
            "consent_type",
            "granted",
            "granted_at",
            "withdrawn_at",
            "source",
            "ip_address",
            "user_agent",
            "created_at",
        ]
        read_only_fields = fields


class ConsentGrantSerializer(serializers.Serializer):
    """Serializer for granting consent."""

    consent_type = serializers.ChoiceField(choices=CommunicationConsent.CONSENT_TYPES)
    granted = serializers.BooleanField()
    source = serializers.ChoiceField(
        choices=[("WEB", "Web"), ("MOBILE", "Mobile"), ("API", "API")],
        default="WEB",
    )


class ConsentHistorySerializer(serializers.ModelSerializer):
    """Serializer for consent history."""

    class Meta:
        model = CommunicationConsent
        fields = [
            "id",
            "consent_type",
            "granted",
            "granted_at",
            "withdrawn_at",
            "source",
            "ip_address",
            "user_agent",
            "created_at",
        ]
        read_only_fields = fields


# =============================================================================
# Capability Serializers
# =============================================================================


class ChannelCapabilitySerializer(serializers.ModelSerializer):
    """Serializer for channel capabilities."""

    channel_name = serializers.CharField(source="channel.name", read_only=True)
    channel_code = serializers.CharField(source="channel.code", read_only=True)

    class Meta:
        model = NotificationChannelCapability
        fields = [
            "id",
            "channel",
            "channel_name",
            "channel_code",
            "capability",
            "is_supported",
        ]
        read_only_fields = fields


# =============================================================================
# Audit Serializers
# =============================================================================


class NotificationPreferenceAuditSerializer(serializers.ModelSerializer):
    """Serializer for notification preference audit logs."""

    action_display = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = NotificationPreferenceAudit
        fields = [
            "id",
            "action",
            "action_display",
            "category",
            "channel",
            "ip_address",
            "user_agent",
            "metadata",
            "timestamp",
        ]
        read_only_fields = fields

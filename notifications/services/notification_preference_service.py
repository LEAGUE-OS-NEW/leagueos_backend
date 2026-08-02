"""Service layer for notification preference operations.

Handles all business logic for managing user notification preferences,
including bulk operations, validation, and audit logging.
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction

from notifications.models import (
    NotificationCategory,
    NotificationChannel,
    NotificationPreferenceAudit,
    UserNotificationPreference,
)

logger = logging.getLogger(__name__)
User = get_user_model()


class NotificationPreferenceService:
    """Service for notification preference operations."""

    @staticmethod
    @transaction.atomic
    def bulk_update_preferences(
        user: User,
        preferences_data: list[dict[str, Any]],
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> list[UserNotificationPreference]:
        """Bulk update user notification preferences.

        Args:
            user: The user whose preferences are being updated.
            preferences_data: List of preference updates with keys:
                - category_id: UUID of NotificationCategory
                - channel_id: UUID of NotificationChannel
                - enabled: Boolean
            ip_address: IP address of the request.
            user_agent: User agent string of the request.

        Returns:
            List of updated/created UserNotificationPreference instances.

        Raises:
            ValueError: If category or channel is invalid.
        """
        if not preferences_data:
            raise ValueError("preferences_data cannot be empty")

        updated_preferences = []

        for pref_data in preferences_data:
            category_id = pref_data["category_id"]
            channel_id = pref_data["channel_id"]
            enabled = pref_data["enabled"]

            # Validate category and channel exist and are active
            try:
                category = NotificationCategory.objects.get(id=category_id, is_active=True)
            except NotificationCategory.DoesNotExist as err:
                raise ValueError(f"Invalid or inactive category: {category_id}") from err

            try:
                channel = NotificationChannel.objects.get(id=channel_id, is_active=True)
            except NotificationChannel.DoesNotExist as err:
                raise ValueError(f"Invalid or inactive channel: {channel_id}") from err

            # Check if mandatory - cannot be disabled
            if category.mandatory and not enabled:
                logger.warning(
                    "Attempted to disable mandatory category %s for user %s",
                    category.code,
                    user,
                )
                # Force enabled to True for mandatory categories
                enabled = True

            # Get or create preference
            preference, created = UserNotificationPreference.objects.update_or_create(
                user=user,
                notification_category=category,
                notification_channel=channel,
                defaults={"enabled": enabled},
            )

            updated_preferences.append(preference)

            # Record audit log
            action = "CHANNEL_ENABLED" if enabled else "CHANNEL_DISABLED"
            NotificationPreferenceAudit.objects.create(
                user=user,
                action=action,
                category=category,
                channel=channel,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"created": created},
            )

        logger.info(
            "Updated %d preferences for user %s",
            len(updated_preferences),
            user,
        )

        return updated_preferences

    @staticmethod
    def get_user_preferences(user: User) -> list[UserNotificationPreference]:
        """Get all notification preferences for a user.

        Args:
            user: The user whose preferences to retrieve.

        Returns:
            List of UserNotificationPreference instances.
        """
        return list(
            UserNotificationPreference.objects.filter(user=user)
            .select_related("notification_category", "notification_channel")
            .order_by("notification_category__display_order", "notification_channel__display_order")
        )

    @staticmethod
    def reset_to_defaults(
        user: User,
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> int:
        """Reset user preferences to default values from categories.

        Args:
            user: The user whose preferences to reset.
            ip_address: IP address of the request.
            user_agent: User agent string of the request.

        Returns:
            Number of preferences reset.
        """
        # Delete existing preferences
        existing_count = UserNotificationPreference.objects.filter(user=user).count()
        UserNotificationPreference.objects.filter(user=user).delete()

        # Create preferences from active categories with default_enabled
        categories = NotificationCategory.objects.filter(
            is_active=True, default_enabled=True
        ).select_related(None)

        channels = NotificationChannel.objects.filter(is_active=True)
        channel_list = list(channels)

        preferences_to_create = []
        for category in categories:
            for channel in channel_list:
                preferences_to_create.append(
                    UserNotificationPreference(
                        user=user,
                        notification_category=category,
                        notification_channel=channel,
                        enabled=True,
                    )
                )

        UserNotificationPreference.objects.bulk_create(preferences_to_create)

        # Record audit log
        NotificationPreferenceAudit.objects.create(
            user=user,
            action="RESET_TO_DEFAULTS",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"reset_count": len(preferences_to_create)},
        )

        logger.info(
            "Reset %d preferences to defaults for user %s",
            len(preferences_to_create),
            user,
        )

        return existing_count

    @staticmethod
    def get_or_create_default_preferences(user: User) -> list[UserNotificationPreference]:
        """Get existing preferences or create defaults if none exist.

        Args:
            user: The user whose preferences to get/create.

        Returns:
            List of UserNotificationPreference instances.
        """
        existing = NotificationPreferenceService.get_user_preferences(user)
        if existing:
            return existing

        # Create defaults
        categories = NotificationCategory.objects.filter(is_active=True, default_enabled=True)
        channels = NotificationChannel.objects.filter(is_active=True)
        channel_list = list(channels)

        preferences = []
        for category in categories:
            for channel in channel_list:
                preferences.append(
                    UserNotificationPreference(
                        user=user,
                        notification_category=category,
                        notification_channel=channel,
                        enabled=True,
                    )
                )

        UserNotificationPreference.objects.bulk_create(preferences)

        return NotificationPreferenceService.get_user_preferences(user)

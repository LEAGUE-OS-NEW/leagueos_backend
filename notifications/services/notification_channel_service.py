"""Service layer for notification channel operations.

Handles channel validation and capability checking with extensible
design supporting future channels without code changes.
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_user_model

from notifications.models import NotificationChannel

logger = logging.getLogger(__name__)
User = get_user_model()


class NotificationChannelService:
    """Service for notification channel operations."""

    @staticmethod
    def validate_channel_availability(user: User, channel_code: str) -> dict[str, Any]:
        """Validate if a channel is available for a user.

        Checks channel-specific requirements:
        - Email: User must have verified email
        - Push: User must have at least one active push device
        - In-App: User account must be active

        Args:
            user: The user to validate.
            channel_code: The channel code to validate.

        Returns:
            Dict with 'available' (bool) and 'reason' (str) keys.

        Raises:
            NotificationChannel.DoesNotExist: If channel doesn't exist.
        """
        try:
            NotificationChannel.objects.get(code=channel_code, is_active=True)
        except NotificationChannel.DoesNotExist:
            logger.warning("Attempted to validate unknown channel: %s", channel_code)
            raise

        # Channel-specific validation
        if channel_code == "EMAIL":
            if not user.email:
                return {
                    "available": False,
                    "reason": "User has no email address configured",
                }
            if not user.is_verified:
                return {
                    "available": False,
                    "reason": "User email is not verified",
                }

        elif channel_code == "PUSH":
            # Check if user has at least one active push device
            # This assumes a push device model exists - adjust based on your implementation
            has_push_device = (
                hasattr(user, "push_devices") and user.push_devices.filter(is_active=True).exists()
            )
            if not has_push_device:
                return {
                    "available": False,
                    "reason": "No active push devices registered",
                }

        elif channel_code == "IN_APP":
            if not user.is_active:
                return {
                    "available": False,
                    "reason": "User account is not active",
                }

        # Default: channel is available
        return {"available": True, "reason": ""}

    @staticmethod
    def get_user_available_channels(user: User) -> list[dict[str, Any]]:
        """Get all channels available for a user.

        Args:
            user: The user to check.

        Returns:
            List of dicts with channel info and availability.
        """
        channels = NotificationChannel.objects.filter(is_active=True)
        result = []

        for channel in channels:
            try:
                availability = NotificationChannelService.validate_channel_availability(
                    user, channel.code
                )
                result.append(
                    {
                        "channel": {
                            "id": channel.id,
                            "code": channel.code,
                            "name": channel.name,
                            "description": channel.description,
                        },
                        "available": availability["available"],
                        "reason": availability["reason"],
                    }
                )
            except NotificationChannel.DoesNotExist:
                logger.error("Channel %s not found", channel.code)
                continue

        return result

    @staticmethod
    def get_all_channels() -> list[dict[str, Any]]:
        """Get all active notification channels.

        Returns:
            List of channel dicts.
        """
        channels = NotificationChannel.objects.filter(is_active=True).order_by(
            "display_order", "name"
        )
        return [
            {
                "id": channel.id,
                "code": channel.code,
                "name": channel.name,
                "description": channel.description,
                "provider": channel.provider,
                "display_order": channel.display_order,
            }
            for channel in channels
        ]

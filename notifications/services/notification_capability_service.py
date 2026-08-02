"""Service layer for notification channel capability operations.

Provides extensible capability validation without modifying existing
business logic when new channels are added.
"""

from __future__ import annotations

import logging
from typing import Any

from notifications.models import NotificationChannel, NotificationChannelCapability

logger = logging.getLogger(__name__)


class NotificationCapabilityService:
    """Service for notification channel capability operations."""

    @staticmethod
    def check_capability(channel_code: str, capability: str) -> bool:
        """Check if a channel supports a specific capability.

        Args:
            channel_code: The channel code to check.
            capability: The capability to verify.

        Returns:
            True if the capability is supported, False otherwise.
        """
        try:
            channel = NotificationChannel.objects.get(code=channel_code, is_active=True)
            capability_obj = NotificationChannelCapability.objects.get(
                channel=channel, capability=capability, is_supported=True
            )
            return capability_obj.is_supported
        except (NotificationChannel.DoesNotExist, NotificationChannelCapability.DoesNotExist):
            logger.warning(
                "Capability check failed: channel=%s, capability=%s",
                channel_code,
                capability,
            )
            return False

    @staticmethod
    def get_channel_capabilities(channel_code: str) -> list[dict[str, Any]]:
        """Get all capabilities for a channel.

        Args:
            channel_code: The channel code.

        Returns:
            List of capability dicts with 'capability' and 'is_supported' keys.
        """
        try:
            channel = NotificationChannel.objects.get(code=channel_code, is_active=True)
            capabilities = NotificationChannelCapability.objects.filter(channel=channel).order_by(
                "capability"
            )

            return [
                {
                    "capability": cap.capability,
                    "is_supported": cap.is_supported,
                }
                for cap in capabilities
            ]
        except NotificationChannel.DoesNotExist:
            logger.warning("Channel not found: %s", channel_code)
            return []

    @staticmethod
    def get_all_capabilities() -> dict[str, list[dict[str, Any]]]:
        """Get all capabilities grouped by channel.

        Returns:
            Dict mapping channel codes to lists of capabilities.
        """
        channels = NotificationChannel.objects.filter(is_active=True)
        result = {}

        for channel in channels:
            capabilities = NotificationChannelCapability.objects.filter(
                channel=channel, is_supported=True
            ).order_by("capability")

            result[channel.code] = [
                {
                    "capability": cap.capability,
                    "is_supported": cap.is_supported,
                }
                for cap in capabilities
            ]

        return result

    @staticmethod
    def validate_channel_supports(
        channel_code: str, required_capabilities: list[str]
    ) -> dict[str, Any]:
        """Validate that a channel supports all required capabilities.

        Args:
            channel_code: The channel code to validate.
            required_capabilities: List of required capabilities.

        Returns:
            Dict with 'valid' (bool) and 'missing_capabilities' (list) keys.
        """
        supported_caps = {
            cap["capability"]
            for cap in NotificationCapabilityService.get_channel_capabilities(channel_code)
            if cap["is_supported"]
        }

        missing = [cap for cap in required_capabilities if cap not in supported_caps]

        return {
            "valid": len(missing) == 0,
            "missing_capabilities": missing,
        }

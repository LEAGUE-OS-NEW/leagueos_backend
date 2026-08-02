"""Service layer for quiet hours operations.

Handles quiet hours management with timezone-aware validation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from notifications.models import NotificationPreferenceAudit, QuietHours

logger = logging.getLogger(__name__)
User = get_user_model()


class QuietHoursService:
    """Service for quiet hours operations."""

    @staticmethod
    @transaction.atomic
    def set_quiet_hours(
        user: User,
        start_time: str,
        end_time: str,
        timezone_name: str = "UTC",
        enabled: bool = True,
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> QuietHours:
        """Set or update quiet hours for a user.

        Args:
            user: The user whose quiet hours to set.
            start_time: Start time in HH:MM format.
            end_time: End time in HH:MM format.
            timezone_name: Timezone name (e.g., 'UTC', 'Africa/Kampala').
            enabled: Whether quiet hours are enabled.
            ip_address: IP address of the request.
            user_agent: User agent string of the request.

        Returns:
            The QuietHours instance.

        Raises:
            ValueError: If times or timezone are invalid.
        """

        # Parse times
        try:
            start = datetime.strptime(start_time, "%H:%M").time()
            end = datetime.strptime(end_time, "%H:%M").time()
        except ValueError as err:
            raise ValueError(f"Invalid time format: {err}") from err

        if start == end:
            raise ValueError("start_time and end_time cannot be the same")

        # Validate timezone
        try:
            import pytz

            if timezone_name not in pytz.all_timezones:
                raise ValueError(f"Invalid timezone: {timezone_name}")
        except ImportError:
            logger.warning("pytz not installed, skipping timezone validation")

        # Get or create quiet hours
        quiet_hours, created = QuietHours.objects.update_or_create(
            user=user,
            defaults={
                "enabled": enabled,
                "start_time": start,
                "end_time": end,
                "timezone": timezone_name,
            },
        )

        # Record audit log
        action = "QUIET_HOURS_UPDATED" if (created or enabled) else "QUIET_HOURS_DISABLED"
        NotificationPreferenceAudit.objects.create(
            user=user,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={
                "start_time": start_time,
                "end_time": end_time,
                "timezone": timezone_name,
                "enabled": enabled,
            },
        )

        logger.info(
            "Quiet hours %s for user %s: %s-%s (%s)",
            "set" if created else "updated",
            user,
            start_time,
            end_time,
            timezone_name,
        )

        return quiet_hours

    @staticmethod
    def disable_quiet_hours(
        user: User,
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> None:
        """Disable quiet hours for a user.

        Args:
            user: The user whose quiet hours to disable.
            ip_address: IP address of the request.
            user_agent: User agent string of the request.
        """
        try:
            quiet_hours = user.quiet_hours
            quiet_hours.enabled = False
            quiet_hours.save(update_fields=["enabled", "updated_at"])

            # Record audit log
            NotificationPreferenceAudit.objects.create(
                user=user,
                action="QUIET_HOURS_DISABLED",
                ip_address=ip_address,
                user_agent=user_agent,
            )

            logger.info("Quiet hours disabled for user %s", user)
        except QuietHours.DoesNotExist:
            logger.debug("No quiet hours configured for user %s", user)

    @staticmethod
    def get_quiet_hours(user: User) -> QuietHours | None:
        """Get quiet hours for a user.

        Args:
            user: The user whose quiet hours to get.

        Returns:
            QuietHours instance or None if not configured.
        """
        try:
            return user.quiet_hours
        except QuietHours.DoesNotExist:
            return None

    @staticmethod
    def is_in_quiet_hours(user: User, check_time: datetime | None = None) -> bool:
        """Check if user is currently in quiet hours.

        Args:
            user: The user to check.
            check_time: Time to check (defaults to now).

        Returns:
            True if in quiet hours, False otherwise.
        """
        quiet_hours = QuietHoursService.get_quiet_hours(user)
        if not quiet_hours or not quiet_hours.enabled:
            return False

        if check_time is None:
            check_time = timezone.now()

        # Convert check_time to user's timezone
        try:
            import pytz

            user_tz = pytz.timezone(quiet_hours.timezone)
            if check_time.tzinfo is None:
                check_time = timezone.make_aware(check_time, timezone.utc)
            check_time = check_time.astimezone(user_tz)
        except ImportError:
            # If pytz not available, use UTC
            user_tz = UTC

        current_time = check_time.time()

        start = quiet_hours.start_time
        end = quiet_hours.end_time

        # Handle overnight quiet hours (e.g., 22:00 to 08:00)
        if start <= end:
            return start <= current_time < end
        else:
            # Wraps around midnight
            return current_time >= start or current_time < end

    @staticmethod
    def delete_quiet_hours(
        user: User,
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> bool:
        """Delete quiet hours configuration for a user.

        Args:
            user: The user whose quiet hours to delete.
            ip_address: IP address of the request.
            user_agent: User agent string of the request.

        Returns:
            True if deleted, False if not found.
        """
        try:
            quiet_hours = user.quiet_hours
            quiet_hours.delete()

            # Record audit log
            NotificationPreferenceAudit.objects.create(
                user=user,
                action="QUIET_HOURS_DISABLED",
                ip_address=ip_address,
                user_agent=user_agent,
            )

            logger.info("Quiet hours deleted for user %s", user)
            return True
        except QuietHours.DoesNotExist:
            return False

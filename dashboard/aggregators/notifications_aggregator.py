"""Notifications aggregator for gathering notification summary data."""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from dashboard.aggregators.base_aggregator import BaseAggregator

User = get_user_model()
logger = logging.getLogger(__name__)


class NotificationsAggregator(BaseAggregator):
    """Aggregates notification summary for the dashboard."""

    module_code = "notifications"
    module_name = "Notifications"

    def aggregate(self, user: User) -> dict:
        """Aggregate notification data for the user.

        Args:
            user: The user to get notification data for

        Returns:
            Notification summary data
        """
        try:
            # Get unread notification count
            unread_count = user.notifications.filter(read=False).count() if hasattr(user, "notifications") else 0

            # Get recent notifications (last 5)
            recent_notifications = []
            if hasattr(user, "notifications"):
                recent_qs = user.notifications.select_related("category").filter(read=False)[:5]
                recent_notifications = [
                    {
                        "id": str(notif.id),
                        "category": notif.category.name if notif.category else "General",
                        "title": notif.title or "",
                        "message": notif.message or "",
                        "created_at": notif.created_at.isoformat(),
                        "read": notif.read,
                    }
                    for notif in recent_qs
                ]

            data = {
                "unread_count": unread_count,
                "recent_notifications": recent_notifications,
            }

            if unread_count == 0 and not recent_notifications:
                return self._empty_response(data)

            return self._success_response(data)

        except Exception as e:  # noqa: BLE001
            logger.error("Notifications aggregation failed for user %s: %s", user.id, str(e))
            return self._error_response("Notifications service temporarily unavailable.")
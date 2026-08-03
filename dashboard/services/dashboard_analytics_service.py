"""Dashboard analytics service for tracking user interactions.

Records dashboard views, widget clicks, navigation clicks, and module interactions.
"""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from accounts.models import AuditLog
from dashboard.models import DashboardAnalytics

User = get_user_model()
logger = logging.getLogger(__name__)


class DashboardAnalyticsService:
    """Service for recording dashboard analytics events.

    Tracks user interactions for analytics and personalization.
    """

    @staticmethod
    def record_event(
        user: User,
        module: str,
        interaction_type: str,
        widget: str = "",
        metadata: dict | None = None,
    ) -> None:
        """Record a dashboard analytics event.

        Args:
            user: The user who triggered the event
            module: Module code where interaction occurred
            interaction_type: Type of interaction (from DashboardAnalytics.InteractionType)
            widget: Optional widget code
            metadata: Optional metadata dictionary
        """
        try:
            DashboardAnalytics.objects.create(
                user=user,
                module=module,
                widget=widget,
                interaction_type=interaction_type,
                metadata=metadata or {},
            )

            # Also create audit log for compliance
            AuditLog.objects.create(
                user=user,
                action=f"DASHBOARD_{interaction_type}",
                metadata={
                    "module": module,
                    "widget": widget,
                    **metadata,
                },
            )

            logger.debug(
                "Analytics recorded: user=%s, module=%s, type=%s, widget=%s",
                user.id,
                module,
                interaction_type,
                widget,
            )
        except Exception:  # noqa: BLE001
            # Analytics should never break the dashboard
            logger.exception("Failed to record analytics event")

    @staticmethod
    def record_dashboard_viewed(user: User, metadata: dict | None = None) -> None:
        """Record dashboard view event.

        Args:
            user: The user who viewed the dashboard
            metadata: Optional metadata (e.g., session_id, load_time)
        """
        DashboardAnalyticsService.record_event(
            user=user,
            module="dashboard",
            interaction_type=DashboardAnalytics.InteractionType.VIEWED,
            metadata=metadata or {},
        )

    @staticmethod
    def record_widget_clicked(user: User, widget: str, module: str = "dashboard") -> None:
        """Record widget click event.

        Args:
            user: The user who clicked the widget
            widget: Widget code that was clicked
            module: Module code containing the widget
        """
        DashboardAnalyticsService.record_event(
            user=user,
            module=module,
            interaction_type=DashboardAnalytics.InteractionType.WIDGET_CLICKED,
            widget=widget,
        )

    @staticmethod
    def record_navigation_clicked(user: User, route: str, name: str) -> None:
        """Record navigation click event.

        Args:
            user: The user who clicked navigation
            route: Route that was navigated to
            name: Name of the navigation item
        """
        DashboardAnalyticsService.record_event(
            user=user,
            module="navigation",
            interaction_type=DashboardAnalytics.InteractionType.NAVIGATION_CLICKED,
            metadata={"route": route, "name": name},
        )

    @staticmethod
    def record_module_opened(user: User, module: str) -> None:
        """Record module opened event.

        Args:
            user: The user who opened the module
            module: Module code that was opened
        """
        DashboardAnalyticsService.record_event(
            user=user,
            module=module,
            interaction_type=DashboardAnalytics.InteractionType.MODULE_OPENED,
        )

    @staticmethod
    def get_user_analytics(user: User, limit: int = 100) -> list[DashboardAnalytics]:
        """Get recent analytics for a user.

        Args:
            user: The user to get analytics for
            limit: Maximum number of records to return

        Returns:
            List of DashboardAnalytics instances
        """
        return list(DashboardAnalytics.objects.filter(user=user).select_related("user")[:limit])

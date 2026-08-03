"""Main dashboard service.

Orchestrates dashboard generation with caching, analytics, and personalization.
"""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model

from dashboard.services.dashboard_aggregation_service import DashboardAggregationService
from dashboard.services.dashboard_analytics_service import DashboardAnalyticsService
from dashboard.services.dashboard_cache_service import DashboardCacheService
from dashboard.services.navigation_service import NavigationService

User = get_user_model()
logger = logging.getLogger(__name__)


class DashboardService:
    """Main service for dashboard generation.

    Orchestrates all dashboard components: aggregation, caching, navigation,
    and analytics. Provides a single entry point for dashboard data.
    """

    @classmethod
    def get_dashboard(cls, user: User, use_cache: bool = True) -> dict:
        """Get complete dashboard data for the user.

        Args:
            user: The user to get dashboard for
            use_cache: Whether to use cached data if available

        Returns:
            Complete dashboard response dictionary
        """
        # Try cache first
        if use_cache:
            cached_dashboard = DashboardCacheService.get_dashboard(user)
            if cached_dashboard is not None:
                # Record analytics for cache hit
                DashboardAnalyticsService.record_dashboard_viewed(user, {"cached": True})
                return cached_dashboard

        # Build dashboard from scratch
        try:
            # Get aggregated module data
            aggregated_data = DashboardAggregationService.get_aggregated_data(user)

            # Get navigation
            navigation = NavigationService.get_navigation(user)

            # Get user preferences
            user_prefs = cls._get_user_preferences(user)

            # Get enabled widgets
            widgets = cls._get_enabled_widgets(user)

            # Get personalized recommendations
            recommendations = cls._get_recommendations(user)

            # Build complete response
            dashboard_data = {
                "user_summary": cls._get_user_summary(user),
                "navigation": navigation,
                "widgets": widgets,
                "modules": aggregated_data["modules"],
                "module_metadata": aggregated_data["metadata"],
                "preferences": user_prefs,
                "recommendations": recommendations,
            }

            # Cache the dashboard
            if use_cache:
                # Calculate timeout based on module cache timeouts
                timeout = cls._calculate_cache_timeout(aggregated_data)
                DashboardCacheService.set_dashboard(user, dashboard_data, timeout=timeout)

            # Record analytics
            DashboardAnalyticsService.record_dashboard_viewed(user, {"cached": False})

            # Record audit log
            cls._record_audit_log(user, "DASHBOARD_VIEWED")

            return dashboard_data

        except Exception as e:  # noqa: BLE001
            logger.exception("Dashboard generation failed for user %s", user.id)
            return cls._get_minimal_dashboard(user, str(e))

    @staticmethod
    def _get_user_preferences(user: User) -> dict:
        """Get user dashboard preferences.

        Args:
            user: The user to get preferences for

        Returns:
            User preferences dictionary
        """
        try:
            prefs = getattr(user, "dashboard_preferences", None)
            if prefs:
                return {
                    "widget_order": prefs.widget_order or [],
                    "hidden_widgets": prefs.hidden_widgets or [],
                    "layout_config": prefs.layout_config or {},
                }
        except Exception:  # noqa: BLE001
            pass

        return {
            "widget_order": [],
            "hidden_widgets": [],
            "layout_config": {},
        }

    @staticmethod
    def _get_enabled_widgets(user: User) -> list[dict]:
        """Get enabled widgets for the user.

        Args:
            user: The user to get widgets for

        Returns:
            List of enabled widget dictionaries
        """
        try:
            from dashboard.models import DashboardWidget

            widgets = (
                DashboardWidget.objects.filter(
                    is_active=True,
                    module__is_active=True,
                    module__enabled=True,
                )
                .select_related("module")
                .order_by("module__display_order", "display_order")
            )

            # Filter by permissions
            enabled_widgets = []
            for widget in widgets:
                # Check permission if required
                if widget.permission_required and not user.has_perm(widget.permission_required):
                    continue

                enabled_widgets.append(
                    {
                        "id": str(widget.id),
                        "code": widget.code,
                        "title": widget.title,
                        "description": widget.description,
                        "module_code": widget.module.code,
                        "module_name": widget.module.name,
                        "display_order": widget.display_order,
                    }
                )

            return enabled_widgets

        except Exception as e:  # noqa: BLE001
            logger.error("Failed to get widgets: %s", str(e))
            return []

    @staticmethod
    def _get_recommendations(user: User) -> list[dict]:
        """Get personalized recommendations for the user.

        Args:
            user: The user to get recommendations for

        Returns:
            List of recommendation dictionaries
        """
        try:
            recommendations = []

            # Recommendation 1: Complete onboarding
            onboarding = getattr(user, "onboarding", None)
            if not onboarding or not onboarding.completed:
                recommendations.append(
                    {
                        "type": "onboarding",
                        "title": "Complete your profile",
                        "description": (
                            "Add your favourite clubs and preferences to "
                            "personalize your experience."
                        ),
                        "action": "complete_onboarding",
                        "priority": "high",
                    }
                )

            # Recommendation 2: Notification preferences
            if (
                not hasattr(user, "notification_preferences")
                or not user.notification_preferences.exists()
            ):
                recommendations.append(
                    {
                        "type": "notifications",
                        "title": "Configure notifications",
                        "description": "Set up your notification preferences to stay updated.",
                        "action": "configure_notifications",
                        "priority": "medium",
                    }
                )

            # Recommendation 3: Upcoming fixtures based on favourites
            if hasattr(user, "club_preferences") and user.club_preferences.exists():
                recommendations.append(
                    {
                        "type": "fixtures",
                        "title": "Check upcoming matches",
                        "description": "Your favourite teams have upcoming matches.",
                        "action": "view_fixtures",
                        "priority": "medium",
                    }
                )

            return recommendations

        except Exception as e:  # noqa: BLE001
            logger.error("Failed to get recommendations: %s", str(e))
            return []

    @staticmethod
    def _get_user_summary(user: User) -> dict:
        """Get user summary for the dashboard.

        Args:
            user: The user to get summary for

        Returns:
            User summary dictionary
        """
        try:
            profile = getattr(user, "profile", None)
            onboarding = getattr(user, "onboarding", None)

            return {
                "id": str(user.id),
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "display_name": profile.display_name if profile else "",
                "avatar_url": profile.get_avatar_url() if profile else None,
                "is_verified": user.is_verified,
                "onboarding_completed": bool(onboarding and onboarding.completed)
                if onboarding
                else False,
            }

        except Exception as e:  # noqa: BLE001
            logger.error("Failed to get user summary: %s", str(e))
            return {
                "id": str(user.id),
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "is_verified": user.is_verified,
            }

    @staticmethod
    def _calculate_cache_timeout(aggregated_data: dict) -> int:
        """Calculate cache timeout based on module data.

        Args:
            aggregated_data: Aggregated module data

        Returns:
            Cache timeout in seconds
        """
        # Use shortest timeout from successful modules
        timeouts = []
        for module_data in aggregated_data.get("modules", {}).values():
            if module_data.get("status") == "success":
                timeout = module_data.get("cache_timeout", 300)
                if timeout:
                    timeouts.append(timeout)

        if timeouts:
            return min(timeouts)

        return 300  # Default 5 minutes

    @staticmethod
    def _record_audit_log(user: User, action: str) -> None:
        """Record audit log for dashboard action.

        Args:
            user: The user who performed the action
            action: Action string from AuditLog.ACTION_CHOICES
        """
        try:
            from accounts.models import AuditLog

            AuditLog.objects.create(
                user=user,
                action=action,
            )
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _get_minimal_dashboard(user: User, error: str) -> dict:
        """Get minimal dashboard when full generation fails.

        Args:
            user: The user to get dashboard for
            error: Error message

        Returns:
            Minimal dashboard response
        """
        return {
            "user_summary": DashboardService._get_user_summary(user),
            "navigation": [],
            "widgets": [],
            "modules": {},
            "module_metadata": {
                "total_modules": 0,
                "successful_modules": 0,
                "failed_modules": [],
                "has_failures": True,
                "error": error,
            },
            "preferences": {
                "widget_order": [],
                "hidden_widgets": [],
                "layout_config": {},
            },
            "recommendations": [],
        }

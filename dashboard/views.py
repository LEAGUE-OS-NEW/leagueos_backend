"""Views for the dashboard module."""

from __future__ import annotations

import logging

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from dashboard.models import DashboardAnalytics
from dashboard.serializers import (
    DashboardAnalyticsCreateSerializer,
    DashboardModuleSerializer,
    DashboardWidgetSerializer,
)
from dashboard.services.dashboard_analytics_service import DashboardAnalyticsService
from dashboard.services.dashboard_service import DashboardService
from dashboard.services.navigation_service import NavigationService

logger = logging.getLogger(__name__)


# =============================================================================
# Main Dashboard View
# =============================================================================


class DashboardView(APIView):
    """Main dashboard endpoint.

    Returns aggregated dashboard data for authenticated users.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):  # noqa: C901
        """Get dashboard data for the current user.

        Returns:
            Complete dashboard response with user summary, navigation,
            widgets, module data, and recommendations.
        """
        try:
            user = request.user

            # Get dashboard data
            dashboard_data = DashboardService.get_dashboard(user, use_cache=True)

            # Record analytics asynchronously
            DashboardAnalyticsService.record_dashboard_viewed(user)

            return Response(dashboard_data)

        except Exception as e:  # noqa: BLE001
            logger.exception("Dashboard view failed")
            return Response(
                {"error": "Failed to load dashboard. Please try again."},
                status=500,
            )


# =============================================================================
# Navigation View
# =============================================================================


class NavigationView(APIView):
    """Dynamic navigation endpoint.

    Returns navigation menu structure based on user permissions.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get navigation menu for the current user.

        Returns:
            Hierarchical navigation structure
        """
        try:
            user = request.user
            navigation = NavigationService.get_navigation(user)

            # Record analytics
            DashboardAnalyticsService.record_event(
                user=user,
                module="navigation",
                interaction_type=DashboardAnalytics.InteractionType.VIEWED,
            )

            return Response({"navigation": navigation})

        except Exception as e:  # noqa: BLE001
            logger.exception("Navigation view failed")
            return Response(
                {"error": "Failed to load navigation. Please try again."},
                status=500,
            )


# =============================================================================
# Widgets View
# =============================================================================


class WidgetsView(APIView):
    """Dashboard widgets endpoint.

    Returns enabled widgets for the current user.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get enabled widgets for the current user.

        Returns:
            List of enabled widgets
        """
        try:
            user = request.user
            widgets = DashboardService._get_enabled_widgets(user)

            return Response({"widgets": widgets})

        except Exception as e:  # noqa: BLE001
            logger.exception("Widgets view failed")
            return Response(
                {"error": "Failed to load widgets. Please try again."},
                status=500,
            )


# =============================================================================
# Modules View
# =============================================================================


class ModulesView(APIView):
    """Dashboard modules endpoint.

    Returns available dashboard modules.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get available dashboard modules.

        Returns:
            List of active dashboard modules
        """
        try:
            from dashboard.models import DashboardModule

            modules = DashboardModule.objects.filter(
                is_active=True,
                enabled=True,
            ).order_by("display_order")

            serializer = DashboardModuleSerializer(modules, many=True)
            return Response({"modules": serializer.data})

        except Exception as e:  # noqa: BLE001
            logger.exception("Modules view failed")
            return Response(
                {"error": "Failed to load modules. Please try again."},
                status=500,
            )


# =============================================================================
# Analytics View
# =============================================================================


class AnalyticsView(APIView):
    """Dashboard analytics endpoint.

    Records user interactions with dashboard components.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """Record analytics event.

        Request body:
            - module: Module code (required)
            - widget: Widget code (optional)
            - interaction_type: Type of interaction (required)
            - metadata: Additional metadata (optional)

        Returns:
            Success response
        """
        try:
            user = request.user

            # Validate input
            serializer = DashboardAnalyticsCreateSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=400)

            # Record analytics
            DashboardAnalyticsService.record_event(
                user=user,
                module=serializer.validated_data["module"],
                widget=serializer.validated_data.get("widget", ""),
                interaction_type=serializer.validated_data["interaction_type"],
                metadata=serializer.validated_data.get("metadata", {}),
            )

            return Response({"status": "recorded"})

        except Exception as e:  # noqa: BLE001
            logger.exception("Analytics recording failed")
            # Analytics should never fail the request
            return Response({"status": "error", "message": str(e)})
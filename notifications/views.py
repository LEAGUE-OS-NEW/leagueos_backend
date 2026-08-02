"""Views for notification and communication preferences.

Provides RESTful API endpoints for managing notification preferences,
quiet hours, consents, and capabilities.
"""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from notifications.models import (
    NotificationCategory,
    NotificationChannel,
    NotificationPreferenceAudit,
)
from notifications.serializers import (
    ChannelCapabilitySerializer,
    CommunicationConsentSerializer,
    ConsentGrantSerializer,
    NotificationCategorySerializer,
    NotificationChannelSerializer,
    NotificationPreferenceAuditSerializer,
    PreferenceBulkUpdateSerializer,
    QuietHoursSerializer,
    UserNotificationPreferenceSerializer,
)
from notifications.services import (
    ConsentService,
    NotificationCapabilityService,
    NotificationChannelService,
    NotificationPreferenceService,
    QuietHoursService,
)

# =============================================================================
# Notification Preferences
# =============================================================================


class NotificationPreferenceView(APIView):
    """View for managing user notification preferences."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserNotificationPreferenceSerializer

    def get(self, request):
        """Get user notification preferences."""
        user = request.user

        # Get or create default preferences
        preferences = NotificationPreferenceService.get_or_create_default_preferences(user)

        # Record audit log
        NotificationPreferenceAudit.objects.create(
            user=user,
            action="NOTIFICATION_PREFERENCES_VIEWED",
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        serializer = UserNotificationPreferenceSerializer(preferences, many=True)
        return Response(serializer.data)

    def patch(self, request):
        """Bulk update user notification preferences."""
        user = request.user

        # Validate input
        serializer = PreferenceBulkUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            preferences_data = serializer.validated_data["preferences"]
            updated = NotificationPreferenceService.bulk_update_preferences(
                user=user,
                preferences_data=preferences_data,
                ip_address=request.META.get("REMOTE_ADDR"),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )

            response_serializer = UserNotificationPreferenceSerializer(updated, many=True)
            return Response(response_serializer.data)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error("Error updating preferences: %s", str(e))
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ResetPreferencesView(APIView):
    """View for resetting notification preferences to defaults."""

    permission_classes = [IsAuthenticated]
    serializer_class = UserNotificationPreferenceSerializer

    def post(self, request):
        """Reset user preferences to defaults."""
        user = request.user

        count = NotificationPreferenceService.reset_to_defaults(
            user=user,
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        # Return updated preferences
        preferences = NotificationPreferenceService.get_or_create_default_preferences(user)
        serializer = UserNotificationPreferenceSerializer(preferences, many=True)

        return Response(
            {
                "message": f"Reset {count} preferences to defaults",
                "preferences": serializer.data,
            }
        )


# =============================================================================
# Categories and Channels
# =============================================================================


class NotificationCategoryListView(APIView):
    """View for listing notification categories."""

    permission_classes = [IsAuthenticated]
    serializer_class = NotificationCategorySerializer

    def get(self, request):
        """Get all active notification categories."""
        categories = NotificationCategory.objects.filter(is_active=True).order_by(
            "display_order", "priority", "name"
        )
        serializer = NotificationCategorySerializer(categories, many=True)
        return Response(serializer.data)


class NotificationChannelListView(APIView):
    """View for listing notification channels."""

    permission_classes = [IsAuthenticated]
    serializer_class = NotificationChannelSerializer

    def get(self, request):
        """Get all active notification channels."""
        channels = NotificationChannel.objects.filter(is_active=True).order_by(
            "display_order", "name"
        )
        serializer = NotificationChannelSerializer(channels, many=True)
        return Response(serializer.data)


# =============================================================================
# Quiet Hours
# =============================================================================


class QuietHoursView(APIView):
    """View for managing user quiet hours."""

    permission_classes = [IsAuthenticated]
    serializer_class = QuietHoursSerializer

    def post(self, request):
        """Set or update quiet hours."""
        user = request.user
        data = request.data

        # Validate required fields
        required_fields = ["start_time", "end_time"]
        for field in required_fields:
            if field not in data:
                return Response(
                    {"error": f"Missing required field: {field}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            quiet_hours = QuietHoursService.set_quiet_hours(
                user=user,
                start_time=data["start_time"],
                end_time=data["end_time"],
                timezone_name=data.get("timezone", "UTC"),
                enabled=data.get("enabled", True),
                ip_address=request.META.get("REMOTE_ADDR"),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )

            serializer = QuietHoursSerializer(quiet_hours)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error("Error setting quiet hours: %s", str(e))
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def delete(self, request):
        """Delete quiet hours configuration."""
        user = request.user

        deleted = QuietHoursService.delete_quiet_hours(
            user=user,
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        if deleted:
            return Response(status=status.HTTP_204_NO_CONTENT)
        else:
            return Response(
                {"error": "No quiet hours configuration found"},
                status=status.HTTP_404_NOT_FOUND,
            )


# =============================================================================
# Consent
# =============================================================================


class ConsentView(APIView):
    """View for managing communication consents."""

    permission_classes = [IsAuthenticated]
    serializer_class = CommunicationConsentSerializer

    def get(self, request):
        """Get current consent status."""
        user = request.user
        consents = ConsentService.get_current_consents(user)

        # Also get full history
        history = ConsentService.get_consent_history(user, limit=50)
        history_serializer = CommunicationConsentSerializer(history, many=True)

        return Response(
            {
                "current": consents,
                "history": history_serializer.data,
            }
        )

    def post(self, request):
        """Grant or withdraw consent."""
        user = request.user

        # Validate input
        serializer = ConsentGrantSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            consent = ConsentService.record_consent(
                user=user,
                consent_type=serializer.validated_data["consent_type"],
                granted=serializer.validated_data["granted"],
                source=serializer.validated_data.get("source", "WEB"),
                ip_address=request.META.get("REMOTE_ADDR"),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )

            response_serializer = CommunicationConsentSerializer(consent)
            action = "granted" if consent.granted else "withdrawn"
            return Response(
                {
                    "message": f"Consent {action} successfully",
                    "consent": response_serializer.data,
                },
                status=status.HTTP_201_CREATED,
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error("Error recording consent: %s", str(e))
            return Response(
                {"error": "Internal server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# =============================================================================
# Channel Capabilities
# =============================================================================


class ChannelCapabilityView(APIView):
    """View for checking channel capabilities."""

    permission_classes = [IsAuthenticated]
    serializer_class = ChannelCapabilitySerializer

    def get(self, request):
        """Get channel capabilities for current user."""
        user = request.user

        # Get available channels
        available_channels = NotificationChannelService.get_user_available_channels(user)

        # Get all capabilities
        all_capabilities = NotificationCapabilityService.get_all_capabilities()

        return Response(
            {
                "available_channels": available_channels,
                "capabilities": all_capabilities,
            }
        )


# =============================================================================
# Audit Logs
# =============================================================================


class NotificationAuditLogView(APIView):
    """View for retrieving notification audit logs."""

    permission_classes = [IsAuthenticated]
    serializer_class = NotificationPreferenceAuditSerializer

    def get(self, request):
        """Get user's notification audit logs."""
        user = request.user
        limit = int(request.query_params.get("limit", 50))
        limit = min(limit, 100)  # Cap at 100

        logs = NotificationPreferenceAudit.objects.filter(user=user).order_by("-timestamp")[:limit]

        serializer = NotificationPreferenceAuditSerializer(logs, many=True)
        return Response(serializer.data)


logger = logging.getLogger(__name__)

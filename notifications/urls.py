"""URL configuration for notifications app.

Provides RESTful endpoints for notification preferences management.
"""

from django.urls import path

from notifications.views import (
    ChannelCapabilityView,
    ConsentView,
    NotificationAuditLogView,
    NotificationCategoryListView,
    NotificationChannelListView,
    NotificationPreferenceView,
    QuietHoursView,
    ResetPreferencesView,
)

app_name = "notifications"

urlpatterns = [
    # Notification Preferences
    path(
        "notification-preferences/",
        NotificationPreferenceView.as_view(),
        name="notification-preferences",
    ),
    path(
        "notification-preferences/reset/",
        ResetPreferencesView.as_view(),
        name="notification-preferences-reset",
    ),
    # Categories and Channels
    path(
        "notification-categories/",
        NotificationCategoryListView.as_view(),
        name="notification-categories",
    ),
    path(
        "notification-channels/",
        NotificationChannelListView.as_view(),
        name="notification-channels",
    ),
    # Quiet Hours
    path(
        "notification-preferences/quiet-hours/",
        QuietHoursView.as_view(),
        name="quiet-hours",
    ),
    # Consent
    path(
        "notification-preferences/consents/",
        ConsentView.as_view(),
        name="consents",
    ),
    # Channel Capabilities
    path(
        "notification-preferences/capabilities/",
        ChannelCapabilityView.as_view(),
        name="capabilities",
    ),
    # Audit Logs
    path(
        "notification-preferences/audit-log/",
        NotificationAuditLogView.as_view(),
        name="audit-log",
    ),
]

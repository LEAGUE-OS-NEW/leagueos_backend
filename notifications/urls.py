"""URL configuration for notifications app.

Provides RESTful endpoints for notification preferences management.
"""

from django.urls import path

from notifications.admin_alert_views import (
    AdminAlertArchiveView,
    AdminAlertDetailView,
    AdminAlertListView,
    AdminAlertReadView,
    AdminAlertUnreadView,
)
from notifications.inbox_views import (
    ArchiveView,
    InboxDetailView,
    InboxListView,
    MarkAllReadView,
    MarkMultipleReadView,
    MarkReadView,
    UnreadCountView,
)
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
    path("admin/alerts/", AdminAlertListView.as_view(), name="admin-alert-list"),
    path("admin/alerts/unread-count/", AdminAlertUnreadView.as_view(), name="admin-alert-unread"),
    path(
        "admin/alerts/<uuid:alert_id>/", AdminAlertDetailView.as_view(), name="admin-alert-detail"
    ),
    path(
        "admin/alerts/<uuid:alert_id>/read/", AdminAlertReadView.as_view(), name="admin-alert-read"
    ),
    path(
        "admin/alerts/<uuid:alert_id>/archive/",
        AdminAlertArchiveView.as_view(),
        name="admin-alert-archive",
    ),
    path("notifications/", InboxListView.as_view(), name="inbox-list"),
    path("notifications/unread-count/", UnreadCountView.as_view(), name="inbox-unread-count"),
    path(
        "notifications/mark-read/", MarkMultipleReadView.as_view(), name="inbox-mark-multiple-read"
    ),
    path("notifications/mark-all-read/", MarkAllReadView.as_view(), name="inbox-mark-all-read"),
    path("notifications/<uuid:notification_id>/", InboxDetailView.as_view(), name="inbox-detail"),
    path(
        "notifications/<uuid:notification_id>/read/", MarkReadView.as_view(), name="inbox-mark-read"
    ),
    path(
        "notifications/<uuid:notification_id>/archive/", ArchiveView.as_view(), name="inbox-archive"
    ),
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

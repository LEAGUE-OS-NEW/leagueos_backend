"""Tests for notification views."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status

User = get_user_model()


@pytest.mark.django_db
class TestNotificationPreferenceView:
    """Tests for NotificationPreferenceView."""

    def test_get_preferences(self, api_client, user):
        """Test getting notification preferences."""
        api_client.force_authenticate(user=user)
        response = api_client.get("/api/v1/notification-preferences/")

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)

    def test_patch_preferences(self, api_client, user, notification_category, notification_channel):
        """Test updating notification preferences."""
        api_client.force_authenticate(user=user)

        data = {
            "preferences": [
                {
                    "category_id": str(notification_category.id),
                    "channel_id": str(notification_channel.id),
                    "enabled": False,
                }
            ]
        }

        response = api_client.patch("/api/v1/notification-preferences/", data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)
        assert len(response.data) == 1
        assert response.data[0]["enabled"] is False

    def test_patch_preferences_invalid_category(self, api_client, user, notification_channel):
        """Test updating preferences with invalid category."""
        api_client.force_authenticate(user=user)

        data = {
            "preferences": [
                {
                    "category_id": "00000000-0000-0000-0000-000000000000",
                    "channel_id": str(notification_channel.id),
                    "enabled": False,
                }
            ]
        }

        response = api_client.patch("/api/v1/notification-preferences/", data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestResetPreferencesView:
    """Tests for ResetPreferencesView."""

    def test_reset_preferences(self, api_client, user, notification_category, notification_channel):
        """Test resetting preferences to defaults."""
        api_client.force_authenticate(user=user)

        # First update a preference
        data = {
            "preferences": [
                {
                    "category_id": str(notification_category.id),
                    "channel_id": str(notification_channel.id),
                    "enabled": False,
                }
            ]
        }
        api_client.patch("/api/v1/notification-preferences/", data, format="json")

        # Now reset
        response = api_client.post("/api/v1/notification-preferences/reset/")

        assert response.status_code == status.HTTP_200_OK
        assert "message" in response.data
        assert "preferences" in response.data


@pytest.mark.django_db
class TestNotificationCategoryListView:
    """Tests for NotificationCategoryListView."""

    def test_get_categories(self, api_client, user):
        """Test getting all notification categories."""
        api_client.force_authenticate(user=user)
        response = api_client.get("/api/v1/notification-categories/")

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)
        assert len(response.data) > 0

    def test_get_categories_unauthenticated(self, api_client):
        """Test getting categories without authentication."""
        response = api_client.get("/api/v1/notification-categories/")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestNotificationChannelListView:
    """Tests for NotificationChannelListView."""

    def test_get_channels(self, api_client, user):
        """Test getting all notification channels."""
        api_client.force_authenticate(user=user)
        response = api_client.get("/api/v1/notification-channels/")

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)
        assert len(response.data) > 0


@pytest.mark.django_db
class TestQuietHoursView:
    """Tests for QuietHoursView."""

    def test_set_quiet_hours(self, api_client, user):
        """Test setting quiet hours."""
        api_client.force_authenticate(user=user)

        data = {
            "start_time": "22:00",
            "end_time": "08:00",
            "timezone": "UTC",
            "enabled": True,
        }

        response = api_client.post(
            "/api/v1/notification-preferences/quiet-hours/", data, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["start_time"] == "22:00:00"
        assert response.data["end_time"] == "08:00:00"
        assert response.data["enabled"] is True

    def test_set_quiet_hours_invalid_times(self, api_client, user):
        """Test setting quiet hours with invalid times."""
        api_client.force_authenticate(user=user)

        data = {
            "start_time": "10:00",
            "end_time": "10:00",  # Same as start
        }

        response = api_client.post(
            "/api/v1/notification-preferences/quiet-hours/", data, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_delete_quiet_hours(self, api_client, user):
        """Test deleting quiet hours."""
        api_client.force_authenticate(user=user)

        # First set quiet hours
        data = {"start_time": "22:00", "end_time": "08:00"}
        api_client.post("/api/v1/notification-preferences/quiet-hours/", data, format="json")

        # Now delete
        response = api_client.delete("/api/v1/notification-preferences/quiet-hours/")

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_quiet_hours_not_found(self, api_client, user):
        """Test deleting non-existent quiet hours."""
        api_client.force_authenticate(user=user)

        response = api_client.delete("/api/v1/notification-preferences/quiet-hours/")

        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestConsentView:
    """Tests for ConsentView."""

    def test_get_consents(self, api_client, user):
        """Test getting consent status."""
        api_client.force_authenticate(user=user)
        response = api_client.get("/api/v1/notification-preferences/consents/")

        assert response.status_code == status.HTTP_200_OK
        assert "current" in response.data
        assert "history" in response.data

    def test_grant_consent(self, api_client, user):
        """Test granting consent."""
        api_client.force_authenticate(user=user)

        data = {
            "consent_type": "MARKETING",
            "granted": True,
            "source": "WEB",
        }

        response = api_client.post(
            "/api/v1/notification-preferences/consents/", data, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["consent"]["granted"] is True

    def test_withdraw_consent(self, api_client, user):
        """Test withdrawing consent."""
        api_client.force_authenticate(user=user)

        # First grant
        grant_data = {"consent_type": "MARKETING", "granted": True}
        api_client.post("/api/v1/notification-preferences/consents/", grant_data, format="json")

        # Then withdraw
        withdraw_data = {"consent_type": "MARKETING", "granted": False}
        response = api_client.post(
            "/api/v1/notification-preferences/consents/", withdraw_data, format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["consent"]["granted"] is False

    def test_invalid_consent_type(self, api_client, user):
        """Test granting consent with invalid type."""
        api_client.force_authenticate(user=user)

        data = {
            "consent_type": "INVALID_TYPE",
            "granted": True,
        }

        response = api_client.post(
            "/api/v1/notification-preferences/consents/", data, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestChannelCapabilityView:
    """Tests for ChannelCapabilityView."""

    def test_get_capabilities(self, api_client, user):
        """Test getting channel capabilities."""
        api_client.force_authenticate(user=user)
        response = api_client.get("/api/v1/notification-preferences/capabilities/")

        assert response.status_code == status.HTTP_200_OK
        assert "available_channels" in response.data
        assert "capabilities" in response.data


@pytest.mark.django_db
class TestNotificationAuditLogView:
    """Tests for NotificationAuditLogView."""

    def test_get_audit_logs(self, api_client, user):
        """Test getting audit logs."""
        api_client.force_authenticate(user=user)
        response = api_client.get("/api/v1/notification-preferences/audit-log/")

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.data, list)

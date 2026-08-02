"""Tests for notification services."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from notifications.models import NotificationChannel, QuietHours
from notifications.services import (
    ConsentService,
    NotificationCapabilityService,
    NotificationChannelService,
    NotificationPreferenceService,
    QuietHoursService,
)
from notifications.tests.factories import (
    NotificationCategoryFactory,
    NotificationChannelCapabilityFactory,
    NotificationChannelFactory,
)

User = get_user_model()


@pytest.mark.django_db
class TestNotificationPreferenceService:
    """Tests for NotificationPreferenceService."""

    def test_get_or_create_default_preferences_creates_defaults(self, user):
        """Test that default preferences are created when none exist."""
        preferences = NotificationPreferenceService.get_or_create_default_preferences(user)

        assert len(preferences) > 0
        assert all(pref.user == user for pref in preferences)
        assert all(pref.enabled for pref in preferences)

    def test_get_or_create_default_preferences_returns_existing(self, user):
        """Test that existing preferences are returned if they exist."""
        # Create initial preferences
        prefs1 = NotificationPreferenceService.get_or_create_default_preferences(user)

        # Get again
        prefs2 = NotificationPreferenceService.get_or_create_default_preferences(user)

        assert prefs1 == prefs2

    def test_bulk_update_preferences(self, user, notification_category, notification_channel):
        """Test bulk updating notification preferences."""
        preferences_data = [
            {
                "category_id": notification_category.id,
                "channel_id": notification_channel.id,
                "enabled": False,
            }
        ]

        result = NotificationPreferenceService.bulk_update_preferences(user, preferences_data)

        assert len(result) == 1
        assert result[0].enabled is False
        assert result[0].user == user
        assert result[0].notification_category == notification_category
        assert result[0].notification_channel == notification_channel

    def test_bulk_update_mandatory_category_cannot_be_disabled(self, user, notification_channel):
        """Test that mandatory categories cannot be disabled."""
        mandatory_category = NotificationCategoryFactory(mandatory=True)

        preferences_data = [
            {
                "category_id": mandatory_category.id,
                "channel_id": notification_channel.id,
                "enabled": False,
            }
        ]

        result = NotificationPreferenceService.bulk_update_preferences(user, preferences_data)

        assert result[0].enabled is True  # Should be forced to True

    def test_reset_to_defaults(self, user, notification_category, notification_channel):
        """Test resetting preferences to defaults."""
        # Create a custom preference
        NotificationPreferenceService.bulk_update_preferences(
            user,
            [
                {
                    "category_id": notification_category.id,
                    "channel_id": notification_channel.id,
                    "enabled": False,
                }
            ],
        )

        # Reset to defaults
        count = NotificationPreferenceService.reset_to_defaults(user)

        assert count > 0

        # Verify preferences were reset
        preferences = NotificationPreferenceService.get_user_preferences(user)
        assert all(pref.enabled for pref in preferences)


@pytest.mark.django_db
class TestNotificationChannelService:
    """Tests for NotificationChannelService."""

    def test_validate_email_channel_availability_verified_user(self, user):
        """Test email channel availability for verified user."""
        result = NotificationChannelService.validate_channel_availability(user, "EMAIL")
        assert result["available"] is True

    def test_validate_email_channel_unverified_user(self, user):
        """Test email channel availability for unverified user."""
        user.is_verified = False
        user.save()

        result = NotificationChannelService.validate_channel_availability(user, "EMAIL")
        assert result["available"] is False
        assert "not verified" in result["reason"]

    def test_validate_push_channel_no_devices(self, user):
        """Test push channel availability with no devices."""
        result = NotificationChannelService.validate_channel_availability(user, "PUSH")
        # Should be unavailable if no push devices
        assert result["available"] is False

    def test_validate_in_app_channel_inactive_user(self, user):
        """Test in-app channel availability for inactive user."""
        user.is_active = False
        user.save()

        result = NotificationChannelService.validate_channel_availability(user, "IN_APP")
        assert result["available"] is False

    def test_validate_invalid_channel(self, user):
        """Test validating an invalid channel."""
        with pytest.raises(NotificationChannel.DoesNotExist):
            NotificationChannelService.validate_channel_availability(user, "INVALID")

    def test_get_user_available_channels(self, user):
        """Test getting all available channels for a user."""
        channels = NotificationChannelService.get_user_available_channels(user)
        assert len(channels) > 0
        assert all("channel" in ch and "available" in ch for ch in channels)

    def test_get_all_channels(self):
        """Test getting all active channels."""
        channels = NotificationChannelService.get_all_channels()
        assert len(channels) > 0
        assert all("code" in ch and "name" in ch for ch in channels)


@pytest.mark.django_db
class TestQuietHoursService:
    """Tests for QuietHoursService."""

    def test_set_quiet_hours(self, user):
        """Test setting quiet hours."""
        quiet_hours = QuietHoursService.set_quiet_hours(
            user,
            start_time="22:00",
            end_time="08:00",
            timezone_name="UTC",
            enabled=True,
        )

        assert quiet_hours.user == user
        assert quiet_hours.start_time.strftime("%H:%M") == "22:00"
        assert quiet_hours.end_time.strftime("%H:%M") == "08:00"
        assert quiet_hours.enabled is True

    def test_disable_quiet_hours(self, user):
        """Test disabling quiet hours."""
        QuietHoursService.set_quiet_hours(
            user,
            start_time="22:00",
            end_time="08:00",
        )

        QuietHoursService.disable_quiet_hours(user)

        quiet_hours = QuietHoursService.get_quiet_hours(user)
        assert quiet_hours.enabled is False

    def test_is_in_quiet_hours(self, user):
        """Test checking if currently in quiet hours."""
        # Set quiet hours for a future time
        QuietHoursService.set_quiet_hours(
            user,
            start_time="00:00",
            end_time="23:59",
            enabled=True,
        )

        # Should be in quiet hours
        assert QuietHoursService.is_in_quiet_hours(user) is True

    def test_not_in_quiet_hours_when_disabled(self, user):
        """Test not in quiet hours when disabled."""
        QuietHoursService.set_quiet_hours(
            user,
            start_time="00:00",
            end_time="23:59",
            enabled=False,
        )

        assert QuietHoursService.is_in_quiet_hours(user) is False

    def test_get_quiet_hours_none(self, user):
        """Test getting quiet hours when none configured."""
        assert QuietHoursService.get_quiet_hours(user) is None

    def test_delete_quiet_hours(self, user):
        """Test deleting quiet hours."""
        QuietHoursService.set_quiet_hours(user, "22:00", "08:00")
        assert QuietHoursService.delete_quiet_hours(user) is True
        # Query directly to avoid cached reverse relation
        assert not QuietHours.objects.filter(user=user).exists()

    def test_delete_quiet_hours_not_found(self, user):
        """Test deleting quiet hours when none exist."""
        assert QuietHoursService.delete_quiet_hours(user) is False

    def test_invalid_time_format(self, user):
        """Test setting quiet hours with invalid time format."""
        with pytest.raises(ValueError, match="Invalid time format"):
            QuietHoursService.set_quiet_hours(user, "invalid", "08:00")

    def test_same_start_end_time(self, user):
        """Test setting quiet hours with same start and end time."""
        with pytest.raises(ValueError, match="cannot be the same"):
            QuietHoursService.set_quiet_hours(user, "10:00", "10:00")


@pytest.mark.django_db
class TestConsentService:
    """Tests for ConsentService."""

    def test_record_consent_grant(self, user):
        """Test recording consent grant."""
        consent = ConsentService.record_consent(
            user,
            consent_type="MARKETING",
            granted=True,
            source="WEB",
        )

        assert consent.user == user
        assert consent.consent_type == "MARKETING"
        assert consent.granted is True
        assert consent.source == "WEB"

    def test_record_consent_withdraw(self, user):
        """Test recording consent withdrawal."""
        # First grant
        ConsentService.record_consent(user, "MARKETING", granted=True)

        # Then withdraw
        consent = ConsentService.record_consent(user, "MARKETING", granted=False)

        assert consent.granted is False

    def test_get_current_consents(self, user):
        """Test getting current consent status."""
        ConsentService.record_consent(user, "MARKETING", granted=True)
        ConsentService.record_consent(user, "NEWSLETTER", granted=False)

        consents = ConsentService.get_current_consents(user)

        assert consents["MARKETING"] is True
        assert consents["NEWSLETTER"] is False

    def test_consent_history_immutable(self, user):
        """Test that consent history is immutable."""
        # Grant consent
        consent1 = ConsentService.record_consent(user, "MARKETING", granted=True)

        # Withdraw consent
        consent2 = ConsentService.record_consent(user, "MARKETING", granted=False)

        # Should be two separate records
        assert consent1.id != consent2.id
        assert consent1.granted is True
        assert consent2.granted is False

    def test_invalid_consent_type(self, user):
        """Test recording consent with invalid type."""
        with pytest.raises(ValueError, match="Invalid consent_type"):
            ConsentService.record_consent(user, "INVALID", granted=True)

    def test_invalid_source(self, user):
        """Test recording consent with invalid source."""
        with pytest.raises(ValueError, match="Invalid source"):
            ConsentService.record_consent(user, "MARKETING", granted=True, source="INVALID")

    def test_get_consent_status_no_consent(self, user):
        """Test getting consent status when no consent exists."""
        status = ConsentService.get_consent_status(user, "MARKETING")
        assert status["granted"] is False
        assert status["granted_at"] is None

    def test_get_consent_status_with_consent(self, user):
        """Test getting consent status with existing consent."""
        ConsentService.record_consent(user, "MARKETING", granted=True)
        status = ConsentService.get_consent_status(user, "MARKETING")
        assert status["granted"] is True
        assert status["consent_type"] == "MARKETING"


@pytest.mark.django_db
class TestNotificationCapabilityService:
    """Tests for NotificationCapabilityService."""

    def test_check_capability(self, notification_channel):
        """Test checking if channel supports capability."""
        NotificationChannelCapabilityFactory(
            channel=notification_channel,
            capability="send",
            is_supported=True,
        )

        assert (
            NotificationCapabilityService.check_capability(notification_channel.code, "send")
            is True
        )
        assert (
            NotificationCapabilityService.check_capability(notification_channel.code, "nonexistent")
            is False
        )

    def test_check_capability_unsupported(self, notification_channel):
        """Test checking capability that is not supported."""
        NotificationChannelCapabilityFactory(
            channel=notification_channel,
            capability="send",
            is_supported=False,
        )

        assert (
            NotificationCapabilityService.check_capability(notification_channel.code, "send")
            is False
        )

    def test_get_channel_capabilities(self, notification_channel):
        """Test getting all capabilities for a channel."""
        NotificationChannelCapabilityFactory(channel=notification_channel, capability="send")
        NotificationChannelCapabilityFactory(
            channel=notification_channel, capability="rich_content"
        )

        capabilities = NotificationCapabilityService.get_channel_capabilities(
            notification_channel.code
        )

        assert len(capabilities) == 2
        assert any(cap["capability"] == "send" for cap in capabilities)

    def test_get_all_capabilities(self):
        """Test getting all capabilities."""
        channel = NotificationChannelFactory(code="TEST_CAP_CHANNEL")
        NotificationChannelCapabilityFactory(channel=channel, capability="send")

        capabilities = NotificationCapabilityService.get_all_capabilities()

        assert len(capabilities) > 0
        assert "TEST_CAP_CHANNEL" in capabilities
        assert any(cap["capability"] == "send" for cap in capabilities["TEST_CAP_CHANNEL"])

    def test_get_channel_capabilities_invalid_channel(self):
        """Test getting capabilities for invalid channel."""
        capabilities = NotificationCapabilityService.get_channel_capabilities("NONEXISTENT")
        assert capabilities == []

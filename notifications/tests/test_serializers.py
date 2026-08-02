"""Tests for notification serializers."""

from __future__ import annotations

import pytest

from notifications.serializers import (
    PreferenceBulkUpdateSerializer,
    QuietHoursSerializer,
    SinglePreferenceUpdateSerializer,
)


@pytest.mark.django_db
class TestPreferenceBulkUpdateSerializer:
    """Tests for PreferenceBulkUpdateSerializer."""

    def test_valid_preferences(self, notification_category, notification_channel):
        """Test valid preference updates."""
        data = {
            "preferences": [
                {
                    "category_id": str(notification_category.id),
                    "channel_id": str(notification_channel.id),
                    "enabled": True,
                }
            ]
        }
        serializer = PreferenceBulkUpdateSerializer(data=data)
        assert serializer.is_valid() is True

    def test_empty_preferences(self):
        """Test empty preferences list."""
        serializer = PreferenceBulkUpdateSerializer(data={"preferences": []})
        assert serializer.is_valid() is False
        assert "preferences" in serializer.errors

    def test_missing_category_id(self, notification_channel):
        """Test missing category_id."""
        data = {
            "preferences": [
                {
                    "channel_id": str(notification_channel.id),
                    "enabled": True,
                }
            ]
        }
        serializer = PreferenceBulkUpdateSerializer(data=data)
        assert serializer.is_valid() is False

    def test_missing_channel_id(self, notification_category):
        """Test missing channel_id."""
        data = {
            "preferences": [
                {
                    "category_id": str(notification_category.id),
                    "enabled": True,
                }
            ]
        }
        serializer = PreferenceBulkUpdateSerializer(data=data)
        assert serializer.is_valid() is False

    def test_invalid_uuid_format(self):
        """Test invalid UUID format."""
        data = {
            "preferences": [
                {
                    "category_id": "not-a-uuid",
                    "channel_id": "also-not-a-uuid",
                    "enabled": True,
                }
            ]
        }
        serializer = PreferenceBulkUpdateSerializer(data=data)
        assert serializer.is_valid() is False


@pytest.mark.django_db
class TestSinglePreferenceUpdateSerializer:
    """Tests for SinglePreferenceUpdateSerializer."""

    def test_valid_data(self):
        """Test valid single preference update."""
        import uuid

        data = {
            "category_id": str(uuid.uuid4()),
            "channel_id": str(uuid.uuid4()),
            "enabled": True,
        }
        serializer = SinglePreferenceUpdateSerializer(data=data)
        assert serializer.is_valid() is True

    def test_missing_enabled(self):
        """Test missing enabled field."""
        import uuid

        data = {
            "category_id": str(uuid.uuid4()),
            "channel_id": str(uuid.uuid4()),
        }
        serializer = SinglePreferenceUpdateSerializer(data=data)
        assert serializer.is_valid() is False
        assert "enabled" in serializer.errors


@pytest.mark.django_db
class TestQuietHoursSerializer:
    """Tests for QuietHoursSerializer."""

    def test_valid_data(self, user):
        """Test valid quiet hours data."""
        data = {
            "enabled": True,
            "start_time": "22:00:00",
            "end_time": "08:00:00",
            "timezone": "UTC",
        }
        serializer = QuietHoursSerializer(data=data)
        assert serializer.is_valid() is True

    def test_same_start_and_end_time(self, user):
        """Test that start_time and end_time cannot be the same."""
        data = {
            "enabled": True,
            "start_time": "10:00:00",
            "end_time": "10:00:00",
            "timezone": "UTC",
        }
        serializer = QuietHoursSerializer(data=data)
        assert serializer.is_valid() is False
        assert "non_field_errors" in serializer.errors

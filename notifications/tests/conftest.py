"""Pytest configuration and fixtures for notifications app tests."""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from notifications.tests.factories import (
    CommunicationConsentFactory,
    NotificationCategoryFactory,
    NotificationChannelCapabilityFactory,
    NotificationChannelFactory,
    NotificationPreferenceAuditFactory,
    QuietHoursFactory,
    UserNotificationPreferenceFactory,
)

User = get_user_model()


@pytest.fixture(autouse=True)
def seed_notification_data(db):
    """Seed notification data before each test."""
    call_command("seed_notification_data")


@pytest.fixture
def user(db):
    """Create and return a test user."""
    return User.objects.create_user(
        email="testuser@example.com",
        username="testuser",
        first_name="Test",
        last_name="User",
        password="testpass123",
        is_verified=True,
        is_active=True,
    )


@pytest.fixture
def notification_category(db):
    """Create and return a test notification category."""
    # Ensure category is active and has defaults
    return NotificationCategoryFactory(
        code="TEST_CATEGORY",
        name="Test Category",
        default_enabled=True,
        is_active=True,
    )


@pytest.fixture
def notification_channel(db):
    """Create and return a test notification channel."""
    # Ensure channel is active
    return NotificationChannelFactory(
        code="TEST_CHANNEL",
        name="Test Channel",
        is_active=True,
    )


@pytest.fixture
def notification_preference(user, notification_category, notification_channel):
    """Create and return a test notification preference."""
    return UserNotificationPreferenceFactory(
        user=user,
        notification_category=notification_category,
        notification_channel=notification_channel,
    )


@pytest.fixture
def quiet_hours(user):
    """Create and return test quiet hours."""
    return QuietHoursFactory(user=user)


@pytest.fixture
def communication_consent(user):
    """Create and return test communication consent."""
    return CommunicationConsentFactory(user=user)


@pytest.fixture
def capability(user, notification_channel):
    """Create and return a test capability."""
    return NotificationChannelCapabilityFactory(channel=notification_channel)


@pytest.fixture
def audit_log(user):
    """Create and return a test audit log."""
    return NotificationPreferenceAuditFactory(user=user)


@pytest.fixture
def api_client():
    """Create and return an API test client."""
    return APIClient()

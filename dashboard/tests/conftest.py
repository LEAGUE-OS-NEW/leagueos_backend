"""Pytest configuration and fixtures for dashboard tests."""

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
        first_name="Test",
        last_name="User",
    )


@pytest.fixture
def authenticated_client(user):
    """Create an authenticated API client with JWT credentials."""
    from rest_framework.test import APIClient
    from rest_framework_simplejwt.tokens import RefreshToken

    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


@pytest.fixture
def dashboard_module(db):
    """Create a test dashboard module."""
    from dashboard.models import DashboardModule

    return DashboardModule.objects.create(
        code="test_module",
        name="Test Module",
        description="Test module description",
        display_order=1,
        icon="test-icon",
        route="/test",
        enabled=True,
        is_active=True,
    )


@pytest.fixture
def dashboard_widget(db, dashboard_module):
    """Create a test dashboard widget."""
    from dashboard.models import DashboardWidget

    return DashboardWidget.objects.create(
        module=dashboard_module,
        code="test_widget",
        title="Test Widget",
        description="Test widget description",
        display_order=1,
        is_active=True,
    )


@pytest.fixture
def navigation_menu(db):
    """Create a test navigation menu."""
    from dashboard.models import NavigationMenu

    return NavigationMenu.objects.create(
        name="Test Menu",
        route="/test",
        icon="test-icon",
        display_order=1,
        is_active=True,
    )

"""Tests for dashboard views."""

from django.urls import reverse
from rest_framework import status

from dashboard.models import DashboardAnalytics, DashboardModule, DashboardWidget, NavigationMenu


def test_dashboard_view_requires_authentication(client):
    """Test that dashboard view requires authentication."""
    url = reverse("dashboard:dashboard")
    response = client.get(url)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_dashboard_view_returns_data(authenticated_client, user, dashboard_module, dashboard_widget):
    """Test that dashboard view returns data for authenticated user."""
    url = reverse("dashboard:dashboard")
    response = authenticated_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert "user_summary" in response.data
    assert "navigation" in response.data
    assert "widgets" in response.data
    assert "modules" in response.data
    assert "preferences" in response.data
    assert "recommendations" in response.data


def test_navigation_view_requires_authentication(client):
    """Test that navigation view requires authentication."""
    url = reverse("dashboard:navigation")
    response = client.get(url)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_navigation_view_returns_navigation(authenticated_client, user, navigation_menu):
    """Test that navigation view returns navigation menu."""
    url = reverse("dashboard:navigation")
    response = authenticated_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert "navigation" in response.data
    assert isinstance(response.data["navigation"], list)


def test_widgets_view_requires_authentication(client):
    """Test that widgets view requires authentication."""
    url = reverse("dashboard:widgets")
    response = client.get(url)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_widgets_view_returns_widgets(authenticated_client, user, dashboard_widget):
    """Test that widgets view returns enabled widgets."""
    url = reverse("dashboard:widgets")
    response = authenticated_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert "widgets" in response.data
    assert isinstance(response.data["widgets"], list)


def test_modules_view_requires_authentication(client):
    """Test that modules view requires authentication."""
    url = reverse("dashboard:modules")
    response = client.get(url)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_modules_view_returns_modules(authenticated_client, user, dashboard_module):
    """Test that modules view returns active modules."""
    url = reverse("dashboard:modules")
    response = authenticated_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert "modules" in response.data
    assert isinstance(response.data["modules"], list)
    assert len(response.data["modules"]) > 0


def test_analytics_view_requires_authentication(client):
    """Test that analytics view requires authentication."""
    url = reverse("dashboard:analytics")
    response = client.post(url, {})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_analytics_view_records_event(authenticated_client, user):
    """Test that analytics view records analytics event."""
    url = reverse("dashboard:analytics")

    data = {
        "module": "test",
        "widget": "test_widget",
        "interaction_type": "WIDGET_CLICKED",
        "metadata": {"key": "value"},
    }

    response = authenticated_client.post(url, data)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["status"] == "recorded"

    # Verify analytics was recorded
    analytics = DashboardAnalytics.objects.filter(
        user=user,
        module="test",
        widget="test_widget",
    )
    assert analytics.exists()


def test_analytics_view_validates_input(authenticated_client, user):
    """Test that analytics view validates input."""
    url = reverse("dashboard:analytics")

    # Missing required fields
    data = {"module": ""}
    response = authenticated_client.post(url, data)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
"""Tests for dashboard services."""

from django.contrib.auth import get_user_model

from dashboard.models import DashboardAnalytics, NavigationMenu
from dashboard.services.dashboard_analytics_service import DashboardAnalyticsService
from dashboard.services.dashboard_cache_service import DashboardCacheService
from dashboard.services.dashboard_service import DashboardService
from dashboard.services.navigation_service import NavigationService


def test_dashboard_cache_service_generate_key():
    """Test cache key generation."""
    key = DashboardCacheService._generate_cache_key("user-id-123", "dashboard")
    assert key == "dashboard:dashboard:user-id-123"

    key_with_suffix = DashboardCacheService._generate_cache_key("user-id-123", "navigation", "test")
    assert key_with_suffix == "dashboard:navigation:user-id-123:test"


def test_dashboard_cache_service_set_and_get(user, cache):
    """Test setting and getting cached dashboard."""
    test_data = {"test": "data"}
    DashboardCacheService.set_dashboard(user, test_data, timeout=60)
    cached_data = DashboardCacheService.get_dashboard(user)

    assert cached_data == test_data


def test_dashboard_cache_service_invalidate(user, cache):
    """Test cache invalidation."""
    test_data = {"test": "data"}
    DashboardCacheService.set_dashboard(user, test_data, timeout=60)
    assert DashboardCacheService.get_dashboard(user) is not None

    DashboardCacheService.invalidate_dashboard(user)
    assert DashboardCacheService.get_dashboard(user) is None


def test_dashboard_cache_service_invalidate_all(user, cache):
    """Test invalidating all dashboard cache."""
    DashboardCacheService.set_dashboard(user, {"data": "dashboard"}, timeout=60)
    DashboardCacheService.set_navigation(user, {"data": "navigation"}, timeout=60)
    DashboardCacheService.set_widgets(user, [{"data": "widgets"}], timeout=60)

    DashboardCacheService.invalidate_all(user)

    assert DashboardCacheService.get_dashboard(user) is None
    assert DashboardCacheService.get_navigation(user) is None
    assert DashboardCacheService.get_widgets(user) is None


def test_navigation_service_returns_navigation(user, navigation_menu):
    """Test that navigation service returns navigation menu."""
    navigation = NavigationService.get_navigation(user)

    assert isinstance(navigation, list)
    assert len(navigation) > 0
    assert navigation[0]["name"] == "Test Menu"


def test_navigation_service_filters_by_permission(user, navigation_menu):
    """Test that navigation service filters by permissions."""
    # Create menu item with permission requirement
    NavigationMenu.objects.create(
        name="Protected Menu",
        route="/protected",
        icon="protected-icon",
        display_order=2,
        permission_required="auth.add_user",
        is_active=True,
    )

    # User doesn't have permission, should only see public menu
    navigation = NavigationService.get_navigation(user)
    assert len(navigation) == 1  # Only the test menu (navigation_menu fixture)

    # Make user a superuser (has all permissions)
    user.is_superuser = True
    user.save()
    user = get_user_model().objects.get(pk=user.pk)

    # Now user should see both menus
    navigation = NavigationService.get_navigation(user)
    assert len(navigation) == 2


def test_dashboard_analytics_service_records_event(user):
    """Test that analytics service records events."""
    DashboardAnalyticsService.record_event(
        user=user,
        module="test_module",
        interaction_type="WIDGET_CLICKED",
        widget="test_widget",
        metadata={"key": "value"},
    )

    analytics = DashboardAnalytics.objects.filter(user=user, module="test_module")
    assert analytics.exists()
    assert analytics.first().widget == "test_widget"


def test_dashboard_analytics_service_records_dashboard_viewed(user):
    """Test that dashboard viewed event is recorded."""
    DashboardAnalyticsService.record_dashboard_viewed(user)

    analytics = DashboardAnalytics.objects.filter(
        user=user,
        module="dashboard",
        interaction_type="VIEWED",
    )
    assert analytics.exists()


def test_dashboard_service_get_dashboard(user, dashboard_widget):
    """Test that dashboard service returns dashboard data."""
    dashboard_data = DashboardService.get_dashboard(user, use_cache=False)

    assert "user_summary" in dashboard_data
    assert "navigation" in dashboard_data
    assert "widgets" in dashboard_data
    assert "modules" in dashboard_data
    assert "preferences" in dashboard_data
    assert "recommendations" in dashboard_data


def test_dashboard_service_returns_user_summary(user):
    """Test that dashboard includes user summary."""
    dashboard_data = DashboardService.get_dashboard(user, use_cache=False)

    user_summary = dashboard_data["user_summary"]
    assert user_summary["email"] == user.email
    assert user_summary["id"] == str(user.id)

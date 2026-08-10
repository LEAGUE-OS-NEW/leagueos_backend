"""Pytest fixtures for markets tests."""

import pytest

from authentication.tests.factories import (
    PermissionFactory,
    RoleFactory,
    RolePermissionFactory,
    UserFactory,
    UserRoleFactory,
)
from sports.models import Sport, Competition, SportingEvent
from markets.models import MarketCategory, MarketScope


@pytest.fixture
def user_factory():
    """Provide the UserFactory for tests."""
    return UserFactory


@pytest.fixture
def role_factory():
    """Provide the RoleFactory for tests."""
    return RoleFactory


@pytest.fixture
def permission_factory():
    """Provide the PermissionFactory for tests."""
    return PermissionFactory


@pytest.fixture
def role_permission_factory():
    """Provide the RolePermissionFactory for tests."""
    return RolePermissionFactory


@pytest.fixture
def user_role_factory():
    """Provide the UserRoleFactory for tests."""
    return UserRoleFactory


@pytest.fixture
def sport(db):
    """Create a basic sport for tests."""
    return Sport.objects.create(
        name="Football",
        code="FOOTBALL",
    )


@pytest.fixture
def competition(db, sport):
    """Create a basic competition for tests."""
    return Competition.objects.create(
        sport=sport,
        name="Test League",
        country_code="UG",
        is_verified=True,
    )


@pytest.fixture
def sporting_event(db, sport, competition):
    """Create a basic sporting event for tests."""
    from datetime import timedelta
    from django.utils import timezone

    return SportingEvent.objects.create(
        sport=sport,
        competition=competition,
        event_type=SportingEvent.EventType.MATCH,
        name="Test Match",
        starts_at=timezone.now() + timedelta(days=1),
        status=SportingEvent.Status.SCHEDULED,
        is_verified=True,
        verified_at=timezone.now(),
    )


@pytest.fixture
def market_category(db):
    """Create a basic market category for tests."""
    return MarketCategory.objects.create(
        name="Test Category",
        description="Test category description",
    )


@pytest.fixture
def market_scope_enum():
    """Provide the MarketScope enum for tests."""
    return MarketScope

"""Pytest fixtures for authentication tests."""

import pytest

from accounts.models import User
from authentication.tests.factories import (
    LoginHistoryFactory,
    PermissionFactory,
    RoleFactory,
    RolePermissionFactory,
    UserFactory,
    UserRoleFactory,
    UserSessionFactory,
)


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
def user_session_factory():
    """Provide the UserSessionFactory for tests."""
    return UserSessionFactory


@pytest.fixture
def login_history_factory():
    """Provide the LoginHistoryFactory for tests."""
    return LoginHistoryFactory


@pytest.fixture
def club_workspace_factory():
    """Provide the ClubWorkspaceFactory for tests."""
    from clubs.tests.factories import ClubWorkspaceFactory

    return ClubWorkspaceFactory


@pytest.fixture
def user(db):
    """Create a basic user for tests."""
    return User.objects.create_user(
        email="testuser@example.com",
        username="testuser",
        password="testpass123",
        first_name="Test",
        last_name="User",
        is_verified=True,
        is_active=True,
    )

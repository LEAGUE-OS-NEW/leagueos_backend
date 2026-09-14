"""Tests for AuthContextService.user_context's club identity."""

from __future__ import annotations

import pytest

from authentication.services.auth_context_service import AuthContextService
from clubs.models import ClubWorkspace
from clubs.tests.factories import ClubWorkspaceFactory

pytestmark = pytest.mark.django_db


def test_user_context_includes_active_club_for_club_workspace_user():
    workspace = ClubWorkspaceFactory(is_active=True)

    context = AuthContextService.user_context(workspace.user)

    assert context["club"] == {"id": str(workspace.club.id), "name": workspace.club.name}


def test_user_context_scopes_club_admin_entitlement_to_active_workspace(
    role_factory,
    permission_factory,
    role_permission_factory,
    user_role_factory,
):
    workspace = ClubWorkspaceFactory(
        is_active=True,
        role=ClubWorkspace.WorkspaceRole.ADMIN,
        permissions=["club.store.manage"],
    )
    role = role_factory(name="Club Admin", display_name="Club Admin")
    permission = permission_factory(
        name="club.profile.view",
        code="club.profile.view",
        resource="club.profile",
        action="view",
    )
    role_permission_factory(role=role, permission=permission)
    user_role_factory(user=workspace.user, role=role)

    context = AuthContextService.user_context(workspace.user)
    entitlement = context["dashboard_access"]["entitlements"][0]

    assert entitlement["dashboard"] == "CLUB_ADMIN"
    assert entitlement["scope_type"] == "CLUB"
    assert entitlement["scope_id"] == str(workspace.club.id)
    assert entitlement["workspace_role"] == "CLUB_ADMIN"
    assert entitlement["permissions"] == ["club.profile.view", "club.store.manage"]


def test_user_context_club_is_none_without_a_workspace(user):
    context = AuthContextService.user_context(user)

    assert context["club"] is None


def test_user_context_ignores_an_inactive_workspace():
    workspace = ClubWorkspaceFactory(is_active=False)

    context = AuthContextService.user_context(workspace.user)

    assert context["club"] is None

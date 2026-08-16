"""Tests for AuthContextService.user_context's club identity."""

from __future__ import annotations

import pytest

from authentication.services.auth_context_service import AuthContextService
from clubs.tests.factories import ClubWorkspaceFactory

pytestmark = pytest.mark.django_db


def test_user_context_includes_active_club_for_club_workspace_user():
    workspace = ClubWorkspaceFactory(is_active=True)

    context = AuthContextService.user_context(workspace.user)

    assert context["club"] == {"id": str(workspace.club.id), "name": workspace.club.name}


def test_user_context_club_is_none_without_a_workspace(user):
    context = AuthContextService.user_context(user)

    assert context["club"] is None


def test_user_context_ignores_an_inactive_workspace():
    workspace = ClubWorkspaceFactory(is_active=False)

    context = AuthContextService.user_context(workspace.user)

    assert context["club"] is None

"""Tests for admin-authored Participant creation (ParticipantListView POST)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from accounts.models import User
from discovery.tests.factories import SportFactory
from sports.models import Participant

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def manager_user():
    from authentication.models import Permission, Role, RolePermission, UserRole

    user = User.objects.create_user(
        username="clubmanager",
        email="clubmanager@example.com",
        password="testpass123",
    )
    role = Role.objects.create(name="Club Manager Role")
    permission = Permission.objects.create(
        name="admin.clubs.manage",
        code="admin.clubs.manage",
        resource="admin",
        action="clubs.manage",
    )
    RolePermission.objects.create(role=role, permission=permission)
    UserRole.objects.create(user=user, role=role, is_active=True)
    return user


@pytest.fixture
def plain_user():
    return User.objects.create_user(
        username="planeuser",
        email="plainuser@example.com",
        password="testpass123",
    )


class TestParticipantCreate:
    def test_manager_can_create_participant(self, api_client, manager_user):
        sport = SportFactory()
        api_client.force_authenticate(user=manager_user)

        resp = api_client.post(
            "/api/v1/participants/",
            {"sport": str(sport.id), "name": "Vipers SC", "short_name": "Vipers"},
            format="json",
        )

        assert resp.status_code == 201
        participant = Participant.objects.get(name="Vipers SC")
        assert participant.is_verified is True
        assert participant.kind == Participant.Kind.TEAM
        assert participant.slug

    def test_plain_user_forbidden(self, api_client, plain_user):
        sport = SportFactory()
        api_client.force_authenticate(user=plain_user)

        resp = api_client.post(
            "/api/v1/participants/",
            {"sport": str(sport.id), "name": "Vipers SC"},
            format="json",
        )
        assert resp.status_code == 403
        assert not Participant.objects.filter(name="Vipers SC").exists()

    def test_created_participant_visible_in_public_list(self, api_client, manager_user):
        sport = SportFactory()
        api_client.force_authenticate(user=manager_user)
        api_client.post(
            "/api/v1/participants/",
            {"sport": str(sport.id), "name": "Vipers SC"},
            format="json",
        )

        resp = APIClient().get("/api/v1/participants/")
        names = {item["name"] for item in resp.data["results"]}
        assert "Vipers SC" in names

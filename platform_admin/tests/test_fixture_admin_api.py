"""Tests for the fixture admin API (create, status, score, complete)."""

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from authentication.models import Role
from authentication.services.role_service import RoleService
from discovery.tests.factories import ParticipantFactory, SportFactory
from sports.models import SportingEvent

from .factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def plain_user(db):
    return UserFactory(is_active=True, is_verified=True)


@pytest.fixture
def super_admin_user(db):
    return UserFactory(is_active=True, is_verified=True, is_superuser=True)


@pytest.fixture
def seeded_roles(db):
    call_command("seed_roles", verbosity=0)


@pytest.fixture
def sports_data_admin_user(db, seeded_roles):
    user = UserFactory(is_active=True, is_verified=True)
    role = Role.objects.get(name="Sports Data & Statistics Admin")
    RoleService.assign_role(user, role)
    return user


def authenticate(client, user):
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


class TestFixtureListCreate:
    def test_plain_user_forbidden(self, api_client, plain_user):
        authenticate(api_client, plain_user)
        resp = api_client.get("/api/v1/admin/fixtures/")
        assert resp.status_code == 403

    def test_sports_data_admin_can_create_fixture(self, api_client, sports_data_admin_user):
        sport = SportFactory()
        home = ParticipantFactory(sport=sport, name="Vipers SC")
        away = ParticipantFactory(sport=sport, name="KCCA FC")
        authenticate(api_client, sports_data_admin_user)

        resp = api_client.post(
            "/api/v1/admin/fixtures/",
            {
                "sport": str(sport.id),
                "home_participant": str(home.id),
                "away_participant": str(away.id),
                "starts_at": (timezone.now() + timezone.timedelta(days=1)).isoformat(),
                "venue": "St. Mary's Stadium",
            },
            format="json",
        )

        assert resp.status_code == 201
        assert resp.data["status"] == SportingEvent.Status.SCHEDULED
        assert len(resp.data["participants"]) == 2

    def test_create_rejects_same_home_and_away(self, api_client, sports_data_admin_user):
        sport = SportFactory()
        team = ParticipantFactory(sport=sport)
        authenticate(api_client, sports_data_admin_user)

        resp = api_client.post(
            "/api/v1/admin/fixtures/",
            {
                "sport": str(sport.id),
                "home_participant": str(team.id),
                "away_participant": str(team.id),
                "starts_at": timezone.now().isoformat(),
            },
            format="json",
        )
        assert resp.status_code == 400

    def test_list_includes_unverified_and_draft(self, api_client, sports_data_admin_user):
        sport = SportFactory()
        home = ParticipantFactory(sport=sport)
        away = ParticipantFactory(sport=sport)
        authenticate(api_client, sports_data_admin_user)

        api_client.post(
            "/api/v1/admin/fixtures/",
            {
                "sport": str(sport.id),
                "home_participant": str(home.id),
                "away_participant": str(away.id),
                "starts_at": timezone.now().isoformat(),
            },
            format="json",
        )

        resp = api_client.get("/api/v1/admin/fixtures/")
        assert resp.status_code == 200
        assert len(resp.data) == 1


class TestFixtureStatusScoreComplete:
    def _create_fixture(self, api_client, sports_data_admin_user):
        sport = SportFactory()
        home = ParticipantFactory(sport=sport)
        away = ParticipantFactory(sport=sport)
        authenticate(api_client, sports_data_admin_user)
        resp = api_client.post(
            "/api/v1/admin/fixtures/",
            {
                "sport": str(sport.id),
                "home_participant": str(home.id),
                "away_participant": str(away.id),
                "starts_at": timezone.now().isoformat(),
            },
            format="json",
        )
        return resp.data["id"]

    def test_set_status_to_live(self, api_client, sports_data_admin_user):
        fixture_id = self._create_fixture(api_client, sports_data_admin_user)

        resp = api_client.patch(
            f"/api/v1/admin/fixtures/{fixture_id}/status/", {"status": "LIVE"}, format="json"
        )
        assert resp.status_code == 200
        assert resp.data["status"] == "LIVE"

    def test_update_score(self, api_client, sports_data_admin_user):
        fixture_id = self._create_fixture(api_client, sports_data_admin_user)

        resp = api_client.post(
            f"/api/v1/admin/fixtures/{fixture_id}/score/",
            {"home_score": 1, "away_score": 0, "clock_display": "60'"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["home_score"] == 1
        assert resp.data["away_score"] == 0
        assert resp.data["clock_display"] == "60'"

    def test_complete_fixture(self, api_client, sports_data_admin_user):
        fixture_id = self._create_fixture(api_client, sports_data_admin_user)

        resp = api_client.post(f"/api/v1/admin/fixtures/{fixture_id}/complete/", {}, format="json")
        assert resp.status_code == 200
        assert resp.data["status"] == "COMPLETED"

    def test_score_update_requires_manage_permission(
        self, api_client, plain_user, sports_data_admin_user
    ):
        fixture_id = self._create_fixture(api_client, sports_data_admin_user)

        authenticate(api_client, plain_user)
        resp = api_client.post(
            f"/api/v1/admin/fixtures/{fixture_id}/score/",
            {"home_score": 1, "away_score": 0},
            format="json",
        )
        assert resp.status_code == 403

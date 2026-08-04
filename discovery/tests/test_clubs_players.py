"""Tests for discovery club and player endpoints."""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from discovery.models import AuditLog
from discovery.tests.factories import (
    ClubFactory,
    ClubProfileFactory,
    PlayerParticipantFactory,
    PlayerProfileFactory,
    SportFactory,
)
from sports.models import Participant

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client():
    return APIClient()


class TestClubEndpoints:
    def test_club_list_returns_active_clubs(self, client):
        ClubFactory(name="KCCA FC", slug="kcca-fc")
        ClubFactory(name="Vipers SC", slug="vipers-sc")
        resp = client.get("/api/v1/clubs/")
        assert resp.status_code == 200
        names = {item["name"] for item in resp.data["results"]}
        assert "KCCA FC" in names
        assert "Vipers SC" in names

    def test_club_list_filters_by_sport(self, client):
        football = SportFactory(name="Football", code="FOOTBALL")
        rugby = SportFactory(name="Rugby", code="RUGBY")
        ClubFactory(name="Football Club", slug="football-club", sport=football)
        ClubFactory(name="Rugby Club", slug="rugby-club", sport=rugby)
        resp = client.get("/api/v1/clubs/", {"sport": str(football.id)})
        assert resp.status_code == 200
        names = {item["name"] for item in resp.data["results"]}
        assert "Football Club" in names
        assert "Rugby Club" not in names

    def test_club_detail_returns_profile(self, client):
        club = ClubFactory(name="KCCA FC", slug="kcca-fc")
        ClubProfileFactory(club=club, stadium="St Mary's Stadium", coach="Coach A")
        resp = client.get(f"/api/v1/clubs/{club.id}/")
        assert resp.status_code == 200
        assert resp.data["id"] == str(club.id)
        assert resp.data["profile"]["stadium"] == "St Mary's Stadium"

    def test_club_detail_404(self, client):
        import uuid

        resp = client.get(f"/api/v1/clubs/{uuid.uuid4()}/")
        assert resp.status_code == 404

    def test_club_detail_records_audit(self, client):
        club = ClubFactory(name="KCCA FC", slug="kcca-fc")
        client.get(f"/api/v1/clubs/{club.id}/")
        assert AuditLog.objects.filter(action="CLUB_VIEWED", entity_id=club.id).exists()

    def test_unpublished_club_profile_hidden(self, client):
        club = ClubFactory(name="Hidden Club", slug="hidden-club")
        ClubProfileFactory(club=club, is_published=False, is_verified=True)
        resp = client.get(f"/api/v1/clubs/{club.id}/")
        assert resp.status_code == 200
        assert resp.data["profile"] is None


class TestPlayerEndpoints:
    def test_player_list_returns_athletes(self, client):
        PlayerParticipantFactory(name="John Doe", short_name="JD")
        resp = client.get("/api/v1/players/")
        assert resp.status_code == 200
        names = {item["name"] for item in resp.data["results"]}
        assert "John Doe" in names

    def test_player_list_excludes_teams(self, client):
        PlayerParticipantFactory(name="Athlete One")
        from discovery.tests.factories import ParticipantFactory

        ParticipantFactory(kind=Participant.Kind.TEAM, name="Team One")
        resp = client.get("/api/v1/players/")
        assert resp.status_code == 200
        names = {item["name"] for item in resp.data["results"]}
        assert "Athlete One" in names
        assert "Team One" not in names

    def test_player_detail_returns_profile(self, client):
        player = PlayerParticipantFactory(name="John Doe")
        PlayerProfileFactory(participant=player, position="Forward", shirt_number=9)
        resp = client.get(f"/api/v1/players/{player.id}/")
        assert resp.status_code == 200
        assert resp.data["profile"]["position"] == "Forward"
        assert resp.data["profile"]["shirt_number"] == 9

    def test_player_detail_404(self, client):
        import uuid

        resp = client.get(f"/api/v1/players/{uuid.uuid4()}/")
        assert resp.status_code == 404

    def test_player_detail_records_audit(self, client):
        player = PlayerParticipantFactory(name="John Doe")
        client.get(f"/api/v1/players/{player.id}/")
        assert AuditLog.objects.filter(action="PLAYER_VIEWED", entity_id=player.id).exists()

    def test_unpublished_player_profile_hidden(self, client):
        player = PlayerParticipantFactory(name="Hidden Player")
        PlayerProfileFactory(participant=player, is_published=False, is_verified=True)
        resp = client.get(f"/api/v1/players/{player.id}/")
        assert resp.status_code == 200
        assert resp.data["profile"] is None

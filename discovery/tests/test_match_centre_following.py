"""Tests for discovery match centre and club following endpoints."""

import uuid

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from discovery.models import AuditLog
from discovery.tests.factories import (
    ClubFactory,
    MatchBroadcastFactory,
    MatchCentreFactory,
    MatchLineupFactory,
    MatchOfficialFactory,
    MatchPlayerStatisticFactory,
    MatchTeamStatisticFactory,
    MatchTimelineEventFactory,
    SportingEventFactory,
    UserClubPreferenceFactory,
    UserFactory,
    VenueFactory,
)
from onboarding.models import UserClubPreference

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def auth_client():
    client = APIClient()
    user = UserFactory()
    client.force_authenticate(user=user)
    client.user = user
    return client


class TestMatchCentre:
    def test_returns_aggregated_match_centre(self, client):
        fixture = SportingEventFactory(name="Big Match", is_verified=True)
        mc = MatchCentreFactory(fixture=fixture, result="2-1", home_score=2, away_score=1)
        venue = VenueFactory(name="National Stadium")
        mc.venue = venue
        mc.save()

        MatchLineupFactory(match_centre=mc, side="HOME", is_starter=True)
        MatchPlayerStatisticFactory(match_centre=mc, stat_type="GOALS", value=2)
        MatchTeamStatisticFactory(match_centre=mc, stat_type="POSSESSION", value=60)
        MatchTimelineEventFactory(match_centre=mc, minute=23)
        MatchOfficialFactory(match_centre=mc, role="REFEREE")
        MatchBroadcastFactory(match_centre=mc, provider="TV Network")

        resp = client.get(f"/api/v1/match-centre/{fixture.id}/")
        assert resp.status_code == 200
        assert resp.data["fixture"]["id"] == str(fixture.id)
        assert resp.data["result"] == "2-1"
        assert resp.data["home_score"] == 2
        assert resp.data["away_score"] == 1
        assert resp.data["venue"]["name"] == "National Stadium"
        assert len(resp.data["lineups"]) >= 1
        assert len(resp.data["player_statistics"]) >= 1
        assert len(resp.data["team_statistics"]) >= 1
        assert len(resp.data["timeline"]) >= 1
        assert len(resp.data["officials"]) >= 1
        assert len(resp.data["broadcasts"]) >= 1

    def test_returns_404_for_missing_fixture(self, client):
        resp = client.get(f"/api/v1/match-centre/{uuid.uuid4()}/")
        assert resp.status_code == 404

    def test_records_match_centre_view_audit(self, client):
        fixture = SportingEventFactory(name="Audited Match", is_verified=True)
        MatchCentreFactory(fixture=fixture)
        client.get(f"/api/v1/match-centre/{fixture.id}/")
        assert AuditLog.objects.filter(action="MATCH_CENTRE_VIEWED", entity_id=fixture.id).exists()

    def test_canonical_fixture_reuse(self, client):
        """The match centre must reference the same canonical SportingEvent."""
        fixture = SportingEventFactory(name="Canonical Match", is_verified=True)
        mc = MatchCentreFactory(fixture=fixture)
        assert mc.fixture_id == fixture.id
        assert mc.fixture.name == "Canonical Match"


class TestClubFollowing:
    def test_follow_requires_auth(self, client):
        club = ClubFactory(name="Auth Club", slug="auth-club")
        resp = client.post(f"/api/v1/clubs/{club.id}/follow/")
        assert resp.status_code == 401

    def test_follow_club(self, auth_client):
        club = ClubFactory(name="Follow Club", slug="follow-club")
        resp = auth_client.post(f"/api/v1/clubs/{club.id}/follow/")
        assert resp.status_code == 201
        assert UserClubPreference.objects.filter(user=auth_client.user, club=club).exists()

    def test_duplicate_follow_prevented(self, auth_client):
        club = ClubFactory(name="Dup Club", slug="dup-club")
        auth_client.post(f"/api/v1/clubs/{club.id}/follow/")
        auth_client.post(f"/api/v1/clubs/{club.id}/follow/")
        assert UserClubPreference.objects.filter(user=auth_client.user, club=club).count() == 1

    def test_unfollow_club(self, auth_client):
        club = ClubFactory(name="Unfollow Club", slug="unfollow-club")
        auth_client.post(f"/api/v1/clubs/{club.id}/follow/")
        resp = auth_client.delete(f"/api/v1/clubs/{club.id}/follow/")
        assert resp.status_code == 204
        assert not UserClubPreference.objects.filter(user=auth_client.user, club=club).exists()

    def test_following_list(self, auth_client):
        club = ClubFactory(name="Listed Club", slug="listed-club")
        UserClubPreferenceFactory(user=auth_client.user, club=club)
        resp = auth_client.get("/api/v1/profile/following/")
        assert resp.status_code == 200
        names = {item["club_name"] for item in resp.data["results"]}
        assert "Listed Club" in names

    def test_follow_records_audit(self, auth_client):
        club = ClubFactory(name="Audit Club", slug="audit-club")
        auth_client.post(f"/api/v1/clubs/{club.id}/follow/")
        assert AuditLog.objects.filter(action="CLUB_FOLLOWED", entity_id=club.id).exists()

    def test_unfollow_records_audit(self, auth_client):
        club = ClubFactory(name="Audit Unfollow", slug="audit-unfollow")
        auth_client.post(f"/api/v1/clubs/{club.id}/follow/")
        auth_client.delete(f"/api/v1/clubs/{club.id}/follow/")
        assert AuditLog.objects.filter(action="CLUB_UNFOLLOWED", entity_id=club.id).exists()

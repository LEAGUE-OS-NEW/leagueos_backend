"""Tests for FixtureAdminService — create/status/score/complete."""

from __future__ import annotations

import pytest
from django.utils import timezone

from discovery.models import MatchCentre
from discovery.services.fixture_admin_service import fixture_admin_service
from discovery.tests.factories import ParticipantFactory, SportFactory, UserFactory
from sports.models import EventParticipant, SportingEvent

pytestmark = pytest.mark.django_db


class TestCreateFixture:
    def test_creates_scheduled_verified_fixture_with_two_participants(self):
        sport = SportFactory()
        home = ParticipantFactory(sport=sport, name="Vipers SC")
        away = ParticipantFactory(sport=sport, name="KCCA FC")
        actor = UserFactory()

        fixture = fixture_admin_service.create_fixture(
            sport=sport,
            competition=None,
            home_participant=home,
            away_participant=away,
            starts_at=timezone.now() + timezone.timedelta(days=1),
            venue="St. Mary's Stadium",
            actor=actor,
        )

        assert fixture.status == SportingEvent.Status.SCHEDULED
        assert fixture.is_verified is True
        assert fixture.verified_at is not None

        participants = EventParticipant.objects.filter(event=fixture)
        assert participants.count() == 2
        assert participants.get(role=EventParticipant.Role.HOME).participant_id == home.id
        assert participants.get(role=EventParticipant.Role.AWAY).participant_id == away.id

    def test_appears_on_public_fixtures_immediately(self):
        sport = SportFactory()
        home = ParticipantFactory(sport=sport, name="Vipers SC")
        away = ParticipantFactory(sport=sport, name="KCCA FC")
        actor = UserFactory()

        fixture_admin_service.create_fixture(
            sport=sport,
            competition=None,
            home_participant=home,
            away_participant=away,
            starts_at=timezone.now() + timezone.timedelta(days=1),
            venue="",
            actor=actor,
        )

        from rest_framework.test import APIClient

        resp = APIClient().get("/api/v1/fixtures/")
        names = {item["name"] for item in resp.data["results"]}
        assert "Vipers SC vs KCCA FC" in names


class TestListAdminFixtures:
    def test_includes_all_statuses(self):
        sport = SportFactory()
        home = ParticipantFactory(sport=sport)
        away = ParticipantFactory(sport=sport)
        actor = UserFactory()

        fixture = fixture_admin_service.create_fixture(
            sport=sport,
            competition=None,
            home_participant=home,
            away_participant=away,
            starts_at=timezone.now(),
            venue="",
            actor=actor,
        )
        fixture_admin_service.set_status(fixture=fixture, status=SportingEvent.Status.POSTPONED)

        fixtures = fixture_admin_service.list_admin_fixtures()
        assert fixture.id in {f.id for f in fixtures}


class TestSetStatus:
    def test_updates_status(self):
        sport = SportFactory()
        home = ParticipantFactory(sport=sport)
        away = ParticipantFactory(sport=sport)
        actor = UserFactory()

        fixture = fixture_admin_service.create_fixture(
            sport=sport,
            competition=None,
            home_participant=home,
            away_participant=away,
            starts_at=timezone.now(),
            venue="",
            actor=actor,
        )

        updated = fixture_admin_service.set_status(
            fixture=fixture, status=SportingEvent.Status.LIVE
        )
        assert updated.status == SportingEvent.Status.LIVE


class TestUpdateScore:
    def test_creates_match_centre_and_sets_score(self):
        sport = SportFactory()
        home = ParticipantFactory(sport=sport)
        away = ParticipantFactory(sport=sport)
        actor = UserFactory()

        fixture = fixture_admin_service.create_fixture(
            sport=sport,
            competition=None,
            home_participant=home,
            away_participant=away,
            starts_at=timezone.now(),
            venue="",
            actor=actor,
        )
        fixture_admin_service.set_status(fixture=fixture, status=SportingEvent.Status.LIVE)

        fixture_admin_service.update_score(
            fixture=fixture, home_score=1, away_score=0, clock_display="35'"
        )

        match_centre = MatchCentre.objects.get(fixture=fixture)
        assert match_centre.home_score == 1
        assert match_centre.away_score == 0
        assert match_centre.clock_display == "35'"
        assert match_centre.is_verified is True

    def test_score_visible_on_public_fixture_detail(self):
        sport = SportFactory()
        home = ParticipantFactory(sport=sport)
        away = ParticipantFactory(sport=sport)
        actor = UserFactory()

        fixture = fixture_admin_service.create_fixture(
            sport=sport,
            competition=None,
            home_participant=home,
            away_participant=away,
            starts_at=timezone.now(),
            venue="",
            actor=actor,
        )
        fixture_admin_service.update_score(
            fixture=fixture, home_score=2, away_score=1, clock_display="HT"
        )

        from rest_framework.test import APIClient

        resp = APIClient().get(f"/api/v1/fixtures/{fixture.id}/")
        assert resp.status_code == 200
        assert resp.data["home_score"] == 2
        assert resp.data["away_score"] == 1
        assert resp.data["clock_display"] == "HT"


class TestCompleteFixture:
    def test_marks_completed_with_final_score(self):
        sport = SportFactory()
        home = ParticipantFactory(sport=sport)
        away = ParticipantFactory(sport=sport)
        actor = UserFactory()

        fixture = fixture_admin_service.create_fixture(
            sport=sport,
            competition=None,
            home_participant=home,
            away_participant=away,
            starts_at=timezone.now(),
            venue="",
            actor=actor,
        )
        fixture_admin_service.update_score(
            fixture=fixture, home_score=3, away_score=2, clock_display="90'"
        )

        completed = fixture_admin_service.complete_fixture(fixture=fixture)

        assert completed.status == SportingEvent.Status.COMPLETED
        assert completed.ends_at is not None
        match_centre = MatchCentre.objects.get(fixture=fixture)
        assert match_centre.feed_status == MatchCentre.FeedStatus.COMPLETED

    def test_completed_fixture_appears_in_results(self):
        sport = SportFactory()
        home = ParticipantFactory(sport=sport, name="Vipers SC")
        away = ParticipantFactory(sport=sport, name="KCCA FC")
        actor = UserFactory()

        fixture = fixture_admin_service.create_fixture(
            sport=sport,
            competition=None,
            home_participant=home,
            away_participant=away,
            starts_at=timezone.now(),
            venue="",
            actor=actor,
        )
        fixture_admin_service.complete_fixture(fixture=fixture)

        from rest_framework.test import APIClient

        resp = APIClient().get("/api/v1/results/")
        names = {item["name"] for item in resp.data["results"]}
        assert "Vipers SC vs KCCA FC" in names

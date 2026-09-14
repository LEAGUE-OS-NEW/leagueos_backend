"""
Tests for the Sports Data Admin statistics entry workflow.

Covers the design requirements:
  1.  GET  /admin/fixtures/<id>/player-statistics/ returns correct player + stat structure
  2.  POST valid bulk save creates MatchPlayerStatistic records
  3.  POST invalid stat_type returns 400 with row-level errors
  4.  POST invalid participant (non-existent) returns 400
  5.  POST negative value rejected
  6.  POST atomic rollback — validation failure on any row writes nothing
  7.  POST idempotent save (re-submit same values)
  8.  POST update existing statistic (value changes)
  9.  POST LIVE save with trigger_scoring=False does NOT schedule scoring
  10. POST COMPLETED save with trigger_scoring=True schedules scoring
  11. manage_statistics permission required — 403 without it
  12. Unauthenticated request returns 401
  13. FINALIZED gameweek: statistics saved, scoring task skips the gameweek
  14. Integration: Sports Data Admin stats → FantasyPlayerGameweekPoints
  15. Coexistence: Club Admin CSV and Sports Data Admin both use MatchPlayerStatistic (last writer wins)
  16. Fixture status guard: SCHEDULED fixture returns 400 (only LIVE / COMPLETED allowed)
  17. Service: validate_rows reports correct errors per-index
  18. Service: participant sport mismatch rejected

All tests mirror patterns from:
  - clubs/tests/test_match_data_upload.py  (on_commit patch, provider seeding)
  - fantasy/tests/test_match_statistics_review_flow.py  (domain helper pattern)
  - fantasy/tests/test_automatic_scoring_bridge.py  (.run() for task tests)
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from discovery.models import (
    MatchCentre,
    MatchPlayerStatistic,
    SportsFeedIngestion,
    SportsFeedProvider,
)
from discovery.services.statistics_entry_service import (
    SPORTS_DATA_ADMIN_PROVIDER_CODE,
    StatisticsEntryService,
    statistics_entry_service,
)
from fantasy.models import (
    FantasyCompetition,
    FantasyGameweek,
    FantasyPlayer,
    FantasyPlayerGameweekPoints,
    FantasyScoringRule,
    FantasyTeam,
    FantasyTeamGameweekScore,
    FantasyTeamPlayer,
)
from profiles.models import Club
from sports.models import Competition, EventParticipant, Participant, Sport, SportingEvent
from discovery.models import Season

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

BASE_URL = "/api/v1/admin/fixtures/{}/player-statistics/"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _ensure_provider() -> SportsFeedProvider:
    """Ensure the SPORTS_DATA_ADMIN provider row exists (mirrors migration)."""
    provider, _ = SportsFeedProvider.objects.get_or_create(
        code=SPORTS_DATA_ADMIN_PROVIDER_CODE,
        defaults={"name": "Sports Data & Statistics Admin", "is_active": True},
    )
    return provider


def _make_domain(*, fixture_status: str = "COMPLETED", gw_status: str = "SCORING"):
    """
    Build a minimal isolated domain for statistics entry tests.
    Returns a dict with all objects needed across tests.
    Uses 'football' sport so statistic_catalogue() returns the full catalogue.
    """
    uid = _uid()
    sport, _ = Sport.objects.get_or_create(
        name="football",
        defaults={"slug": f"football-{uid}", "code": f"FB{uid[:4].upper()}", "is_active": True},
    )
    competition = Competition.objects.create(
        sport=sport, name=f"League_{uid}", country_code="UG"
    )
    season = Season.objects.create(sport=sport, competition=competition, name=f"S_{uid}")
    fantasy_comp = FantasyCompetition.objects.create(
        competition=competition,
        season=season,
        name=f"Fantasy_{uid}",
        registration_state="OPEN",
        squad_size=2,
        starting_lineup_size=1,
        bench_size=1,
        initial_budget=Decimal("20"),
        max_players_per_team=2,
        captain_multiplier=Decimal("2"),
        position_rules={"GK": 1, "FWD": 1},
        formation_rules={"GK": {"min": 0, "max": 1}, "FWD": {"min": 0, "max": 1}},
    )
    FantasyScoringRule.objects.create(
        fantasy_competition=fantasy_comp,
        statistic_type="GOALS",
        points=Decimal("3"),
        enabled=True,
        conditions={},
    )

    club = Club.objects.create(name=f"Club_{uid}", slug=f"club-{uid}")

    # Athlete linked to fixture via EventParticipant
    athlete = Participant.objects.create(
        sport=sport, kind=Participant.Kind.ATHLETE, name=f"Athlete_{uid}"
    )
    # Second athlete (only in FantasyPlayer pool, not via EventParticipant)
    pool_only = Participant.objects.create(
        sport=sport, kind=Participant.Kind.ATHLETE, name=f"PoolOnly_{uid}"
    )

    now = timezone.now()
    fixture = SportingEvent.objects.create(
        sport=sport,
        competition=competition,
        name=f"Match_{uid}",
        starts_at=now - timedelta(hours=2),
        status=fixture_status,
        is_verified=True,
        verified_at=now,
    )
    EventParticipant.objects.create(
        event=fixture, participant=athlete, role=EventParticipant.Role.COMPETITOR, position=1
    )

    gameweek = FantasyGameweek.objects.create(
        fantasy_competition=fantasy_comp,
        number=1,
        name=f"GW1_{uid}",
        starts_at=now - timedelta(days=1),
        deadline_at=now + timedelta(hours=1),
        ends_at=now + timedelta(days=2),
        status=gw_status,
    )
    gameweek.fixtures.add(fixture)

    # Add both athletes to the Fantasy player pool
    athlete_fp = FantasyPlayer.objects.create(
        fantasy_competition=fantasy_comp,
        player=athlete,
        position="FWD",
        price=Decimal("8"),
    )
    pool_only_fp = FantasyPlayer.objects.create(
        fantasy_competition=fantasy_comp,
        player=pool_only,
        position="GK",
        price=Decimal("5"),
    )

    _ensure_provider()

    return {
        "sport": sport,
        "competition": competition,
        "fantasy_comp": fantasy_comp,
        "club": club,
        "athlete": athlete,
        "athlete_fp": athlete_fp,
        "pool_only": pool_only,
        "pool_only_fp": pool_only_fp,
        "fixture": fixture,
        "gameweek": gameweek,
        "season": season,
    }


def _make_admin_user():
    from django.contrib.auth import get_user_model
    User = get_user_model()
    uid = _uid()
    return User.objects.create_user(
        username=f"admin_{uid}",
        email=f"admin_{uid}@test.com",
        password="pass",
        is_superuser=True,
        is_staff=True,
    )


def _make_regular_user():
    from django.contrib.auth import get_user_model
    User = get_user_model()
    uid = _uid()
    return User.objects.create_user(
        username=f"fan_{uid}",
        email=f"fan_{uid}@test.com",
        password="pass",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — GET returns correct player + stat structure
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestGetFixtureStatistics:
    def test_get_returns_fixture_metadata(self, db):
        domain = _make_domain()
        admin = _make_admin_user()
        client = APIClient()
        client.force_authenticate(user=admin)

        url = BASE_URL.format(domain["fixture"].id)
        resp = client.get(url)
        assert resp.status_code == 200, resp.data
        data = resp.data
        assert data["fixture_id"] == str(domain["fixture"].id)
        assert data["fixture_name"] == domain["fixture"].name
        assert "stat_types" in data
        assert "stat_labels" in data
        assert isinstance(data["stat_types"], list)
        assert len(data["stat_types"]) > 0

    def test_get_returns_players_in_pool_and_event_participants(self, db):
        domain = _make_domain()
        admin = _make_admin_user()
        client = APIClient()
        client.force_authenticate(user=admin)

        url = BASE_URL.format(domain["fixture"].id)
        resp = client.get(url)
        assert resp.status_code == 200

        player_ids = {p["participant_id"] for p in resp.data["players"]}
        # Both athlete (via EventParticipant) and pool_only (via FantasyPlayer pool)
        assert str(domain["athlete"].id) in player_ids
        assert str(domain["pool_only"].id) in player_ids

    def test_get_marks_fantasy_pool_players_correctly(self, db):
        domain = _make_domain()
        admin = _make_admin_user()
        client = APIClient()
        client.force_authenticate(user=admin)

        url = BASE_URL.format(domain["fixture"].id)
        resp = client.get(url)
        assert resp.status_code == 200

        by_id = {p["participant_id"]: p for p in resp.data["players"]}
        # Both are in the Fantasy pool (via FantasyPlayer + gameweek fixture)
        assert by_id[str(domain["athlete"].id)]["in_fantasy_pool"] is True
        assert by_id[str(domain["pool_only"].id)]["in_fantasy_pool"] is True

    def test_get_includes_existing_stats(self, db):
        domain = _make_domain()
        fixture = domain["fixture"]
        athlete = domain["athlete"]

        # Pre-create a stat
        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=athlete, stat_type="GOALS", value=Decimal("2")
        )

        admin = _make_admin_user()
        client = APIClient()
        client.force_authenticate(user=admin)

        url = BASE_URL.format(fixture.id)
        resp = client.get(url)
        assert resp.status_code == 200

        player_row = next(
            p for p in resp.data["players"] if p["participant_id"] == str(athlete.id)
        )
        stat = next((s for s in player_row["stats"] if s["stat_type"] == "GOALS"), None)
        assert stat is not None
        assert Decimal(stat["value"]) == Decimal("2")

    def test_get_returns_football_stat_types(self, db):
        domain = _make_domain()
        admin = _make_admin_user()
        client = APIClient()
        client.force_authenticate(user=admin)

        url = BASE_URL.format(domain["fixture"].id)
        resp = client.get(url)
        assert resp.status_code == 200
        # Football catalogue includes GOALS, ASSISTS, MINUTES_PLAYED, etc.
        assert "GOALS" in resp.data["stat_types"]
        assert "ASSISTS" in resp.data["stat_types"]
        assert "MINUTES_PLAYED" in resp.data["stat_types"]

    def test_get_requires_manage_statistics_permission(self, db):
        domain = _make_domain()
        regular = _make_regular_user()
        client = APIClient()
        client.force_authenticate(user=regular)

        url = BASE_URL.format(domain["fixture"].id)
        resp = client.get(url)
        assert resp.status_code == 403

    def test_get_unauthenticated_returns_401(self, db):
        domain = _make_domain()
        url = BASE_URL.format(domain["fixture"].id)
        resp = APIClient().get(url)
        assert resp.status_code in (401, 403)

    def test_get_nonexistent_fixture_returns_404(self, db):
        admin = _make_admin_user()
        client = APIClient()
        client.force_authenticate(user=admin)
        url = BASE_URL.format(uuid.uuid4())
        resp = client.get(url)
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — Valid bulk POST creates MatchPlayerStatistic records
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestPostSaveStatistics:
    def test_valid_save_creates_statistics(self, db):
        domain = _make_domain()
        fixture = domain["fixture"]
        athlete = domain["athlete"]
        admin = _make_admin_user()
        client = APIClient()
        client.force_authenticate(user=admin)

        url = BASE_URL.format(fixture.id)
        payload = {
            "statistics": [
                {"participant": str(athlete.id), "stat_type": "GOALS", "value": 2},
                {"participant": str(athlete.id), "stat_type": "MINUTES_PLAYED", "value": 90},
            ],
            "trigger_scoring": False,
        }
        resp = client.post(url, payload, format="json")
        assert resp.status_code == 202, resp.data
        assert resp.data["records_created"] == 2
        assert resp.data["records_updated"] == 0

        assert MatchPlayerStatistic.objects.filter(
            match_centre__fixture=fixture,
            participant=athlete,
            stat_type="GOALS",
            value=Decimal("2"),
        ).exists()
        assert MatchPlayerStatistic.objects.filter(
            match_centre__fixture=fixture,
            participant=athlete,
            stat_type="MINUTES_PLAYED",
            value=Decimal("90"),
        ).exists()

    def test_valid_save_creates_match_centre_automatically(self, db):
        domain = _make_domain()
        fixture = domain["fixture"]
        athlete = domain["athlete"]

        assert not MatchCentre.objects.filter(fixture=fixture).exists()

        admin = _make_admin_user()
        client = APIClient()
        client.force_authenticate(user=admin)

        url = BASE_URL.format(fixture.id)
        payload = {
            "statistics": [
                {"participant": str(athlete.id), "stat_type": "GOALS", "value": 1},
            ],
            "trigger_scoring": False,
        }
        resp = client.post(url, payload, format="json")
        assert resp.status_code == 202
        assert MatchCentre.objects.filter(fixture=fixture).exists()

    def test_valid_save_creates_ingestion_record(self, db):
        domain = _make_domain()
        fixture = domain["fixture"]
        athlete = domain["athlete"]
        admin = _make_admin_user()
        client = APIClient()
        client.force_authenticate(user=admin)

        url = BASE_URL.format(fixture.id)
        payload = {
            "statistics": [
                {"participant": str(athlete.id), "stat_type": "GOALS", "value": 1},
            ],
            "trigger_scoring": False,
        }
        resp = client.post(url, payload, format="json")
        assert resp.status_code == 202
        ingestion_id = resp.data["ingestion_id"]
        assert ingestion_id is not None

        ingestion = SportsFeedIngestion.objects.get(id=ingestion_id)
        assert ingestion.status == SportsFeedIngestion.Status.COMPLETED
        assert ingestion.provider.code == SPORTS_DATA_ADMIN_PROVIDER_CODE


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — Invalid stat_type → 400 with row errors
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_invalid_stat_type_returns_400():
    domain = _make_domain()
    fixture = domain["fixture"]
    athlete = domain["athlete"]
    admin = _make_admin_user()
    client = APIClient()
    client.force_authenticate(user=admin)

    url = BASE_URL.format(fixture.id)
    payload = {
        "statistics": [
            {"participant": str(athlete.id), "stat_type": "INVENTED_STAT", "value": 1},
        ],
        "trigger_scoring": False,
    }
    resp = client.post(url, payload, format="json")
    assert resp.status_code == 400, resp.data
    assert "errors" in resp.data
    assert any("INVENTED_STAT" in str(e.get("error", "")) for e in resp.data["errors"])
    # Nothing written
    assert not MatchPlayerStatistic.objects.filter(match_centre__fixture=fixture).exists()


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — Invalid participant (non-existent UUID) → 400
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_nonexistent_participant_returns_400():
    domain = _make_domain()
    fixture = domain["fixture"]
    admin = _make_admin_user()
    client = APIClient()
    client.force_authenticate(user=admin)

    url = BASE_URL.format(fixture.id)
    payload = {
        "statistics": [
            {"participant": str(uuid.uuid4()), "stat_type": "GOALS", "value": 1},
        ],
        "trigger_scoring": False,
    }
    resp = client.post(url, payload, format="json")
    assert resp.status_code == 400
    assert "errors" in resp.data
    assert not MatchPlayerStatistic.objects.filter(match_centre__fixture=fixture).exists()


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — Negative value → 400
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_negative_value_returns_400():
    domain = _make_domain()
    fixture = domain["fixture"]
    athlete = domain["athlete"]
    admin = _make_admin_user()
    client = APIClient()
    client.force_authenticate(user=admin)

    url = BASE_URL.format(fixture.id)
    payload = {
        "statistics": [
            {"participant": str(athlete.id), "stat_type": "GOALS", "value": -1},
        ],
        "trigger_scoring": False,
    }
    resp = client.post(url, payload, format="json")
    assert resp.status_code == 400
    assert not MatchPlayerStatistic.objects.filter(match_centre__fixture=fixture).exists()


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — Atomic rollback: one bad row in a batch writes nothing
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_atomic_rollback_on_any_validation_failure():
    domain = _make_domain()
    fixture = domain["fixture"]
    athlete = domain["athlete"]
    admin = _make_admin_user()
    client = APIClient()
    client.force_authenticate(user=admin)

    url = BASE_URL.format(fixture.id)
    payload = {
        "statistics": [
            # Row 0 — valid
            {"participant": str(athlete.id), "stat_type": "GOALS", "value": 2},
            # Row 1 — invalid stat type
            {"participant": str(athlete.id), "stat_type": "NOT_REAL", "value": 1},
        ],
        "trigger_scoring": False,
    }
    resp = client.post(url, payload, format="json")
    assert resp.status_code == 400
    # No rows at all must have been written
    assert MatchPlayerStatistic.objects.filter(match_centre__fixture=fixture).count() == 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 7 — Idempotent save: re-submit same values, nothing changes
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_idempotent_save():
    domain = _make_domain()
    fixture = domain["fixture"]
    athlete = domain["athlete"]
    admin = _make_admin_user()
    client = APIClient()
    client.force_authenticate(user=admin)

    url = BASE_URL.format(fixture.id)
    payload = {
        "statistics": [
            {"participant": str(athlete.id), "stat_type": "GOALS", "value": 2},
        ],
        "trigger_scoring": False,
    }
    resp1 = client.post(url, payload, format="json")
    assert resp1.status_code == 202
    assert resp1.data["records_created"] == 1

    resp2 = client.post(url, payload, format="json")
    assert resp2.status_code == 202
    assert resp2.data["records_created"] == 0
    assert resp2.data["records_updated"] == 0
    assert resp2.data["records_unchanged"] == 1

    # Still exactly 1 stat row
    assert (
        MatchPlayerStatistic.objects.filter(
            match_centre__fixture=fixture,
            participant=athlete,
            stat_type="GOALS",
        ).count()
        == 1
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 8 — Update existing statistic (value change)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_update_existing_statistic():
    domain = _make_domain()
    fixture = domain["fixture"]
    athlete = domain["athlete"]
    admin = _make_admin_user()
    client = APIClient()
    client.force_authenticate(user=admin)

    url = BASE_URL.format(fixture.id)

    # First save: GOALS = 1
    resp1 = client.post(
        url,
        {"statistics": [{"participant": str(athlete.id), "stat_type": "GOALS", "value": 1}],
         "trigger_scoring": False},
        format="json",
    )
    assert resp1.status_code == 202
    assert resp1.data["records_created"] == 1

    # Second save: GOALS = 2 (correction)
    resp2 = client.post(
        url,
        {"statistics": [{"participant": str(athlete.id), "stat_type": "GOALS", "value": 2}],
         "trigger_scoring": False},
        format="json",
    )
    assert resp2.status_code == 202
    assert resp2.data["records_updated"] == 1
    assert resp2.data["records_created"] == 0

    stat = MatchPlayerStatistic.objects.get(
        match_centre__fixture=fixture,
        participant=athlete,
        stat_type="GOALS",
    )
    assert stat.value == Decimal("2")


# ─────────────────────────────────────────────────────────────────────────────
# Test 9 — LIVE save with trigger_scoring=False does NOT dispatch scoring
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_live_save_without_scoring_does_not_dispatch_task():
    domain = _make_domain(fixture_status="LIVE", gw_status="SCORING")
    fixture = domain["fixture"]
    athlete = domain["athlete"]
    admin = _make_admin_user()
    client = APIClient()
    client.force_authenticate(user=admin)

    dispatched: list = []

    def fake_on_commit(func):
        func()  # fire synchronously like a real commit

    url = BASE_URL.format(fixture.id)
    payload = {
        "statistics": [
            {"participant": str(athlete.id), "stat_type": "GOALS", "value": 1},
        ],
        "trigger_scoring": False,
    }
    with patch("django.db.transaction.on_commit", side_effect=fake_on_commit):
        with patch("fantasy.tasks.score_affected_gameweeks") as mock_task:
            mock_task.delay = lambda ids: dispatched.append(ids)
            resp = client.post(url, payload, format="json")

    assert resp.status_code == 202
    assert resp.data["scoring_scheduled"] is False
    assert dispatched == [], "score_affected_gameweeks.delay() should NOT have been called"
    # But the statistics ARE saved
    assert MatchPlayerStatistic.objects.filter(
        match_centre__fixture=fixture, participant=athlete, stat_type="GOALS"
    ).exists()


# ─────────────────────────────────────────────────────────────────────────────
# Test 10 — COMPLETED save with trigger_scoring=True schedules scoring
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_completed_save_with_trigger_scoring_dispatches_task():
    domain = _make_domain(fixture_status="COMPLETED", gw_status="SCORING")
    fixture = domain["fixture"]
    athlete = domain["athlete"]
    admin = _make_admin_user()
    client = APIClient()
    client.force_authenticate(user=admin)

    dispatched: list = []

    def fake_on_commit(func):
        func()  # fire synchronously

    url = BASE_URL.format(fixture.id)
    payload = {
        "statistics": [
            {"participant": str(athlete.id), "stat_type": "GOALS", "value": 2},
        ],
        "trigger_scoring": True,
    }
    with patch("django.db.transaction.on_commit", side_effect=fake_on_commit):
        with patch("fantasy.tasks.score_affected_gameweeks") as mock_task:
            mock_task.delay = lambda ids: dispatched.append(ids)
            resp = client.post(url, payload, format="json")

    assert resp.status_code == 202
    assert resp.data["scoring_scheduled"] is True
    assert dispatched, "score_affected_gameweeks.delay() must have been called"
    assert str(fixture.id) in dispatched[0]


# ─────────────────────────────────────────────────────────────────────────────
# Test 11 — manage_statistics permission required; 403 without it
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestPermissions:
    def test_post_requires_manage_statistics(self, db):
        domain = _make_domain()
        fixture = domain["fixture"]
        athlete = domain["athlete"]
        regular = _make_regular_user()
        client = APIClient()
        client.force_authenticate(user=regular)

        url = BASE_URL.format(fixture.id)
        payload = {
            "statistics": [
                {"participant": str(athlete.id), "stat_type": "GOALS", "value": 1},
            ],
            "trigger_scoring": False,
        }
        resp = client.post(url, payload, format="json")
        assert resp.status_code == 403
        # Nothing written
        assert not MatchPlayerStatistic.objects.filter(match_centre__fixture=fixture).exists()

    def test_superuser_can_post(self, db):
        domain = _make_domain()
        fixture = domain["fixture"]
        athlete = domain["athlete"]
        admin = _make_admin_user()
        client = APIClient()
        client.force_authenticate(user=admin)

        url = BASE_URL.format(fixture.id)
        payload = {
            "statistics": [
                {"participant": str(athlete.id), "stat_type": "GOALS", "value": 1},
            ],
            "trigger_scoring": False,
        }
        resp = client.post(url, payload, format="json")
        assert resp.status_code == 202

    def test_superuser_can_get(self, db):
        domain = _make_domain()
        admin = _make_admin_user()
        client = APIClient()
        client.force_authenticate(user=admin)

        url = BASE_URL.format(domain["fixture"].id)
        resp = client.get(url)
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Test 12 — Unauthenticated → 401
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_unauthenticated_post_returns_401():
    domain = _make_domain()
    fixture = domain["fixture"]
    athlete = domain["athlete"]

    url = BASE_URL.format(fixture.id)
    payload = {
        "statistics": [
            {"participant": str(athlete.id), "stat_type": "GOALS", "value": 1},
        ],
        "trigger_scoring": False,
    }
    resp = APIClient().post(url, payload, format="json")
    assert resp.status_code in (401, 403)


# ─────────────────────────────────────────────────────────────────────────────
# Test 13 — FINALIZED gameweek: statistics saved, task skips gameweek
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_finalized_gameweek_stats_saved_scoring_skipped():
    """
    Statistics are always written (MatchPlayerStatistic is not gated on
    gameweek status). The scoring task itself skips FINALIZED gameweeks.
    This mirrors the existing Club Admin CSV behaviour.
    """
    from fantasy.tasks import score_affected_gameweeks

    domain = _make_domain(fixture_status="COMPLETED", gw_status="FINALIZED")
    fixture = domain["fixture"]
    athlete = domain["athlete"]

    # Save stats directly via service (bypasses HTTP layer for speed)
    result = statistics_entry_service.save_fixture_statistics(
        fixture=fixture,
        raw_rows=[{"participant": str(athlete.id), "stat_type": "GOALS", "value": 2}],
        actor=None,
        trigger_scoring=True,
    )
    assert result.success is True
    assert MatchPlayerStatistic.objects.filter(
        match_centre__fixture=fixture, participant=athlete, stat_type="GOALS"
    ).exists()

    # Now call the scoring task directly — it must skip the FINALIZED gameweek
    with patch("fantasy.services.score_gameweek") as mock_sg:
        task_result = score_affected_gameweeks.run([str(fixture.id)])

    mock_sg.assert_not_called()
    assert task_result["skipped_finalized"] == 1
    assert task_result["scored"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Test 14 — Integration: Sports Data Admin stats → FantasyPlayerGameweekPoints
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_stats_entry_produces_fantasy_player_gameweek_points():
    """
    Full integration: Sports Data Admin enters GOALS=2 for an athlete.
    With trigger_scoring=True and the on_commit patched to fire synchronously,
    score_affected_gameweeks runs, producing FantasyPlayerGameweekPoints with
    base_points = 2 goals × 3 pts = 6.
    """
    domain = _make_domain(fixture_status="COMPLETED", gw_status="SCORING")
    fixture = domain["fixture"]
    athlete = domain["athlete"]
    athlete_fp = domain["athlete_fp"]
    gameweek = domain["gameweek"]

    from fantasy.tasks import score_affected_gameweeks as _task

    def sync_delay(fixture_ids):
        _task.run(fixture_ids)

    def fake_on_commit(func):
        func()

    with patch("django.db.transaction.on_commit", side_effect=fake_on_commit):
        with patch.object(_task, "delay", side_effect=sync_delay):
            result = statistics_entry_service.save_fixture_statistics(
                fixture=fixture,
                raw_rows=[
                    {"participant": str(athlete.id), "stat_type": "GOALS", "value": 2},
                ],
                actor=None,
                trigger_scoring=True,
            )

    assert result.success is True

    pts = FantasyPlayerGameweekPoints.objects.filter(
        gameweek=gameweek, fantasy_player=athlete_fp
    ).first()
    assert pts is not None, "FantasyPlayerGameweekPoints not created"
    assert pts.base_points == Decimal("6"), (
        f"Expected 6 base points (2 goals × 3 pts), got {pts.base_points}"
    )
    assert pts.statistics_available is True


# ─────────────────────────────────────────────────────────────────────────────
# Test 15 — Coexistence: Club Admin CSV and Sports Data Admin last-writer-wins
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_club_admin_csv_and_sports_data_admin_coexist_last_writer_wins():
    """
    Sports Data Admin enters GOALS=2.
    Club Admin then re-uploads GOALS=3.
    The unique constraint ensures exactly one row; last value wins.

    The Club Admin CSV service validates club ownership via EventParticipant,
    so the athlete must be linked to the fixture via EventParticipant (already
    done in _make_domain) AND the athlete must have a PlayerProfile for the
    club so the club-ownership check passes.
    """
    from clubs.services.match_data_service import import_csv_for_club, CLUB_ADMIN_CSV_PROVIDER_CODE
    from discovery.models import PlayerProfile
    import io

    domain = _make_domain(fixture_status="COMPLETED")
    fixture = domain["fixture"]
    athlete = domain["athlete"]
    club = domain["club"]

    # Give the athlete a PlayerProfile linked to the club so Club Admin
    # ownership check passes (the CSV service resolves club_participant_ids
    # via Participant.player_profile.club).
    PlayerProfile.objects.get_or_create(
        participant=athlete,
        defaults={"club": club, "position": "FWD"},
    )

    # Ensure Club Admin CSV provider exists
    SportsFeedProvider.objects.get_or_create(
        code=CLUB_ADMIN_CSV_PROVIDER_CODE,
        defaults={"name": "Club Admin CSV Upload", "is_active": True},
    )

    # Step 1: Sports Data Admin enters GOALS=2
    result = statistics_entry_service.save_fixture_statistics(
        fixture=fixture,
        raw_rows=[{"participant": str(athlete.id), "stat_type": "GOALS", "value": 2}],
        actor=None,
        trigger_scoring=False,
    )
    assert result.success is True
    stat = MatchPlayerStatistic.objects.get(
        match_centre__fixture=fixture, participant=athlete, stat_type="GOALS"
    )
    assert stat.value == Decimal("2")

    # Step 2: Club Admin uploads CSV with GOALS=3
    lines = ["fixture_id,player_id,stat_type,value", f"{fixture.id},{athlete.id},GOALS,3"]
    csv_buf = io.BytesIO("\n".join(lines).encode())
    csv_buf.name = "stats.csv"
    csv_result = import_csv_for_club(csv_buf, club)
    assert csv_result.success is True, csv_result.message

    # Last writer (Club Admin CSV) wins
    stat.refresh_from_db()
    assert stat.value == Decimal("3")
    # Still exactly one row (no duplicate)
    assert MatchPlayerStatistic.objects.filter(
        match_centre__fixture=fixture, participant=athlete, stat_type="GOALS"
    ).count() == 1


# ─────────────────────────────────────────────────────────────────────────────
# Test 16 — SCHEDULED fixture returns 400
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_scheduled_fixture_returns_400():
    domain = _make_domain(fixture_status="SCHEDULED")
    fixture = domain["fixture"]
    athlete = domain["athlete"]
    admin = _make_admin_user()
    client = APIClient()
    client.force_authenticate(user=admin)

    url = BASE_URL.format(fixture.id)
    payload = {
        "statistics": [
            {"participant": str(athlete.id), "stat_type": "GOALS", "value": 1},
        ],
        "trigger_scoring": False,
    }
    resp = client.post(url, payload, format="json")
    assert resp.status_code == 400
    assert "SCHEDULED" in str(resp.data) or "LIVE" in str(resp.data) or "COMPLETED" in str(resp.data)
    assert not MatchPlayerStatistic.objects.filter(match_centre__fixture=fixture).exists()


# ─────────────────────────────────────────────────────────────────────────────
# Test 17 — Service: validate_rows errors per-index
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_validate_rows_reports_correct_index():
    domain = _make_domain()
    fixture = domain["fixture"]
    athlete = domain["athlete"]

    raw_rows = [
        {"participant": str(athlete.id), "stat_type": "GOALS", "value": 1},   # index 0 — valid
        {"participant": str(uuid.uuid4()), "stat_type": "GOALS", "value": 1},  # index 1 — bad
        {"participant": str(athlete.id), "stat_type": "INVENTED", "value": 1}, # index 2 — bad
    ]
    valid, errors = StatisticsEntryService.validate_rows(fixture, raw_rows)
    assert len(valid) == 1
    assert len(errors) == 2
    error_indices = {e.index for e in errors}
    assert 1 in error_indices
    assert 2 in error_indices
    assert 0 not in error_indices


# ─────────────────────────────────────────────────────────────────────────────
# Test 18 — Participant sport mismatch rejected
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_participant_sport_mismatch_rejected():
    domain = _make_domain()
    fixture = domain["fixture"]

    # Create an athlete from a different sport
    other_uid = _uid()
    other_sport = Sport.objects.create(
        name=f"OtherSport_{other_uid}",
        slug=f"other-sport-{other_uid}",
        code=f"OS{other_uid[:4].upper()}",
    )
    wrong_sport_athlete = Participant.objects.create(
        sport=other_sport, kind=Participant.Kind.ATHLETE, name=f"WrongSport_{other_uid}"
    )

    raw_rows = [{"participant": str(wrong_sport_athlete.id), "stat_type": "GOALS", "value": 1}]
    valid, errors = StatisticsEntryService.validate_rows(fixture, raw_rows)
    assert len(valid) == 0
    assert len(errors) == 1
    assert "sport" in errors[0].error.lower()


# ─────────────────────────────────────────────────────────────────────────────
# Test 19 — POST with empty statistics list returns 400
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_empty_statistics_list_returns_400():
    domain = _make_domain()
    fixture = domain["fixture"]
    admin = _make_admin_user()
    client = APIClient()
    client.force_authenticate(user=admin)

    url = BASE_URL.format(fixture.id)
    payload = {"statistics": [], "trigger_scoring": False}
    resp = client.post(url, payload, format="json")
    assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# Test 20 — POST trigger_scoring defaults to True when not specified
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_trigger_scoring_defaults_to_true():
    domain = _make_domain(fixture_status="COMPLETED", gw_status="SCORING")
    fixture = domain["fixture"]
    athlete = domain["athlete"]
    admin = _make_admin_user()
    client = APIClient()
    client.force_authenticate(user=admin)

    dispatched: list = []

    def fake_on_commit(func):
        func()

    url = BASE_URL.format(fixture.id)
    # Omit trigger_scoring — should default to True
    payload = {
        "statistics": [
            {"participant": str(athlete.id), "stat_type": "GOALS", "value": 1},
        ],
    }
    with patch("django.db.transaction.on_commit", side_effect=fake_on_commit):
        with patch("fantasy.tasks.score_affected_gameweeks") as mock_task:
            mock_task.delay = lambda ids: dispatched.append(ids)
            resp = client.post(url, payload, format="json")

    assert resp.status_code == 202
    assert resp.data["scoring_scheduled"] is True
    assert dispatched, "Default trigger_scoring=True should dispatch scoring"

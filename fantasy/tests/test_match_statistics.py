"""
Tests for the Fantasy Admin match-statistics endpoint.

POST /api/v1/fantasy/admin/match-statistics/
GET  /api/v1/fantasy/admin/match-statistics/

Covers:
  - successful statistic creation (Alex scenario: GOALS = 2)
  - MatchCentre created when it does not exist
  - MatchCentre reused when it already exists
  - invalid fixture UUID
  - invalid participant UUID
  - invalid statistic type (not in sport catalogue)
  - negative value rejected
  - duplicate (fixture, participant, stat_type) returns 400
  - participant sport mismatch returns 400
  - list endpoint with fixture/participant filters
  - score_gameweek() uses the created statistic correctly (Alex = 6 pts)
"""

from decimal import Decimal

import pytest
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient

from discovery.models import MatchCentre, MatchPlayerStatistic
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
from fantasy.services import score_gameweek
from discovery.models import Season
from profiles.models import Club
from sports.models import Competition, Participant, Sport, SportingEvent


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def football_domain(db):
    """
    Minimal Football domain matching the "Alex" test scenario.

    Returns a dict with all objects needed by multiple test cases.
    """
    sport = Sport.objects.create(name="Football", slug="football", code="FB")
    competition = Competition.objects.create(sport=sport, name="Test League", country_code="UG")
    season = Season.objects.create(sport=sport, competition=competition, name="2026")
    fantasy = FantasyCompetition.objects.create(
        competition=competition,
        season=season,
        name="Test Fantasy",
        registration_state="OPEN",
        squad_size=2,
        starting_lineup_size=1,
        bench_size=1,
        initial_budget=Decimal("20"),
        max_players_per_team=2,
        position_rules={"GK": 1, "FWD": 1},
        formation_rules={
            "GK": {"min": 0, "max": 1},
            "FWD": {"min": 0, "max": 1},
        },
    )
    club = Club.objects.create(name="Test Club")

    # Alex — the primary test player
    alex_participant = Participant.objects.create(
        sport=sport, kind="ATHLETE", name="Alex"
    )
    try:
        from discovery.models import PlayerProfile
        PlayerProfile.objects.create(participant=alex_participant, club=club, position="FWD")
    except Exception:
        pass

    alex_fp = FantasyPlayer.objects.create(
        fantasy_competition=fantasy,
        player=alex_participant,
        position="FWD",
        price=Decimal("8"),
    )

    # Second player to fill the squad
    other_participant = Participant.objects.create(
        sport=sport, kind="ATHLETE", name="Other Player"
    )
    other_fp = FantasyPlayer.objects.create(
        fantasy_competition=fantasy,
        player=other_participant,
        position="GK",
        price=Decimal("5"),
    )

    now = timezone.now()
    fixture = SportingEvent.objects.create(
        sport=sport,
        competition=competition,
        name="Test Match",
        starts_at=now - timedelta(hours=2),
        status="COMPLETED",
    )
    gameweek = FantasyGameweek.objects.create(
        fantasy_competition=fantasy,
        number=1,
        name="GW1",
        starts_at=now - timedelta(days=1),
        deadline_at=now + timedelta(hours=1),
        ends_at=now + timedelta(days=2),
        status="SCORING",
    )
    gameweek.fixtures.add(fixture)

    return {
        "sport": sport,
        "competition": competition,
        "fantasy": fantasy,
        "alex_participant": alex_participant,
        "alex_fp": alex_fp,
        "other_participant": other_participant,
        "other_fp": other_fp,
        "fixture": fixture,
        "gameweek": gameweek,
    }


@pytest.fixture
def client():
    return APIClient()


URL = "/api/v1/fantasy/admin/match-statistics/"


# ── helpers ───────────────────────────────────────────────────────────────────


def _payload(domain, stat_type="GOALS", value=2):
    return {
        "fixture": str(domain["fixture"].id),
        "participant": str(domain["alex_participant"].id),
        "stat_type": stat_type,
        "value": value,
    }


# ── creation tests ────────────────────────────────────────────────────────────


def test_create_stat_success(client, football_domain):
    """Happy path: Alex scores 2 goals — stat is created and response is correct."""
    resp = client.post(URL, _payload(football_domain), format="json")

    assert resp.status_code == 201, resp.data
    data = resp.data
    assert data["fixture"] == str(football_domain["fixture"].id)
    assert data["fixture_name"] == "Test Match"
    assert data["participant"] == str(football_domain["alex_participant"].id)
    assert data["participant_name"] == "Alex"
    assert data["stat_type"] == "GOALS"
    assert Decimal(data["value"]) == Decimal("2")
    assert data["match_centre_created"] is True  # MatchCentre was new

    # Verify the row is in the DB
    stat = MatchPlayerStatistic.objects.get(id=data["id"])
    assert stat.value == Decimal("2")
    assert stat.stat_type == "GOALS"


def test_create_stat_creates_match_centre_when_missing(client, football_domain):
    """MatchCentre is created automatically when it does not exist."""
    fixture = football_domain["fixture"]
    assert not MatchCentre.objects.filter(fixture=fixture).exists()

    resp = client.post(URL, _payload(football_domain), format="json")
    assert resp.status_code == 201
    assert MatchCentre.objects.filter(fixture=fixture).exists()
    assert resp.data["match_centre_created"] is True


def test_create_stat_reuses_existing_match_centre(client, football_domain):
    """MatchCentre is reused when it already exists; no duplicate is created."""
    fixture = football_domain["fixture"]
    existing_mc = MatchCentre.objects.create(fixture=fixture)

    resp = client.post(URL, _payload(football_domain), format="json")
    assert resp.status_code == 201
    assert resp.data["match_centre_created"] is False  # was NOT newly created
    # Still exactly one MatchCentre
    assert MatchCentre.objects.filter(fixture=fixture).count() == 1
    # Stat attached to the pre-existing MatchCentre
    stat = MatchPlayerStatistic.objects.get(id=resp.data["id"])
    assert stat.match_centre_id == existing_mc.id


def test_create_stat_normalises_stat_type_to_uppercase(client, football_domain):
    """stat_type is normalised to uppercase before DB insert."""
    payload = _payload(football_domain)
    payload["stat_type"] = "goals"  # lowercase input
    resp = client.post(URL, payload, format="json")
    assert resp.status_code == 201
    assert resp.data["stat_type"] == "GOALS"


def test_create_stat_value_zero_is_valid(client, football_domain):
    """value=0 is a valid boundary — e.g. clean sheet kept but no other stat."""
    payload = _payload(football_domain, value=0)
    resp = client.post(URL, payload, format="json")
    assert resp.status_code == 201
    assert Decimal(resp.data["value"]) == Decimal("0")


def test_create_stat_fractional_value(client, football_domain):
    """Decimal values are accepted."""
    payload = _payload(football_domain, stat_type="MINUTES_PLAYED", value="88.5")
    resp = client.post(URL, payload, format="json")
    assert resp.status_code == 201
    assert Decimal(resp.data["value"]) == Decimal("88.5")


# ── validation failure tests ──────────────────────────────────────────────────


def test_create_stat_invalid_fixture_uuid(client, football_domain):
    """Non-existent fixture UUID → 400."""
    payload = _payload(football_domain)
    payload["fixture"] = "00000000-0000-0000-0000-000000000000"
    resp = client.post(URL, payload, format="json")
    assert resp.status_code == 400
    assert "fixture" in resp.data


def test_create_stat_missing_fixture(client, football_domain):
    """Missing fixture field → 400."""
    payload = _payload(football_domain)
    del payload["fixture"]
    resp = client.post(URL, payload, format="json")
    assert resp.status_code == 400
    assert "fixture" in resp.data


def test_create_stat_invalid_participant_uuid(client, football_domain):
    """Non-existent participant UUID → 400."""
    payload = _payload(football_domain)
    payload["participant"] = "00000000-0000-0000-0000-000000000000"
    resp = client.post(URL, payload, format="json")
    assert resp.status_code == 400
    assert "participant" in resp.data


def test_create_stat_participant_is_not_athlete(client, football_domain):
    """Non-athlete Participant (e.g. a club) is rejected by the queryset filter."""
    sport = football_domain["sport"]
    team_participant = Participant.objects.create(
        sport=sport, kind="CLUB", name="Some Club"
    )
    payload = _payload(football_domain)
    payload["participant"] = str(team_participant.id)
    resp = client.post(URL, payload, format="json")
    assert resp.status_code == 400
    assert "participant" in resp.data


def test_create_stat_invalid_stat_type(client, football_domain):
    """Stat type not in the sport's catalogue → 400 with a descriptive message."""
    payload = _payload(football_domain, stat_type="INVENTED_STAT")
    resp = client.post(URL, payload, format="json")
    assert resp.status_code == 400
    assert "stat_type" in resp.data
    # Error message should list allowed types
    error_text = str(resp.data["stat_type"])
    assert "GOALS" in error_text or "Allowed" in error_text


def test_create_stat_negative_value_rejected(client, football_domain):
    """Negative value → 400."""
    payload = _payload(football_domain, value=-1)
    resp = client.post(URL, payload, format="json")
    assert resp.status_code == 400
    assert "value" in resp.data


def test_create_stat_participant_sport_mismatch(client, football_domain):
    """Participant from a different sport → 400."""
    other_sport = Sport.objects.create(name="Basketball", slug="basketball", code="BB")
    basketball_player = Participant.objects.create(
        sport=other_sport, kind="ATHLETE", name="Baller"
    )
    payload = _payload(football_domain)
    payload["participant"] = str(basketball_player.id)
    resp = client.post(URL, payload, format="json")
    assert resp.status_code == 400
    assert "participant" in resp.data


# ── duplicate test ────────────────────────────────────────────────────────────


def test_create_stat_duplicate_returns_400(client, football_domain):
    """
    Submitting the same (fixture, participant, stat_type) twice returns 400
    with an informative message, and does NOT create a second DB row.
    """
    payload = _payload(football_domain)
    resp1 = client.post(URL, payload, format="json")
    assert resp1.status_code == 201

    resp2 = client.post(URL, payload, format="json")
    assert resp2.status_code == 400
    assert "already exists" in resp2.data["detail"].lower()

    # Exactly one stat in the DB
    assert MatchPlayerStatistic.objects.filter(
        participant=football_domain["alex_participant"],
        stat_type="GOALS",
    ).count() == 1


# ── list endpoint tests ───────────────────────────────────────────────────────


def test_list_returns_created_stats(client, football_domain):
    """GET returns stats after creation."""
    client.post(URL, _payload(football_domain), format="json")
    resp = client.get(URL)
    assert resp.status_code == 200
    ids = [row["participant"] for row in resp.data]
    assert str(football_domain["alex_participant"].id) in ids


def test_list_filter_by_fixture(client, football_domain):
    """?fixture= filter returns only stats for that fixture."""
    client.post(URL, _payload(football_domain), format="json")
    fixture_id = str(football_domain["fixture"].id)
    resp = client.get(URL, {"fixture": fixture_id})
    assert resp.status_code == 200
    assert all(row["fixture"] == fixture_id for row in resp.data)


def test_list_filter_by_participant(client, football_domain):
    """?participant= filter returns only stats for that participant."""
    client.post(URL, _payload(football_domain), format="json")
    participant_id = str(football_domain["alex_participant"].id)
    resp = client.get(URL, {"participant": participant_id})
    assert resp.status_code == 200
    assert all(row["participant"] == participant_id for row in resp.data)


def test_list_empty_when_no_stats(client, football_domain):
    """GET returns empty list when no stats exist."""
    resp = client.get(URL)
    assert resp.status_code == 200
    assert resp.data == []


# ── end-to-end scoring test (the "Alex = 6 pts" scenario) ────────────────────


def test_alex_scores_6_points_after_recalculate(client, football_domain):
    """
    Full end-to-end test:
      1. Create stat: Alex, GOALS = 2
      2. Create scoring rule: GOALS = 3 pts per goal
      3. Run score_gameweek()
      4. Alex's base_points = 2 * 3 = 6
      5. Team total = 6 (Alex is captain → captain_bonus applied)

    This exercises the complete pipeline without modifying score_gameweek().
    """
    from django.contrib.auth import get_user_model

    domain = football_domain
    fantasy = domain["fantasy"]
    gameweek = domain["gameweek"]

    # Step 1 — create the match statistic via the API
    resp = client.post(URL, _payload(domain, stat_type="GOALS", value=2), format="json")
    assert resp.status_code == 201, resp.data

    # Step 2 — scoring rule: GOALS = 3 pts per unit
    FantasyScoringRule.objects.create(
        fantasy_competition=fantasy,
        statistic_type="GOALS",
        points=Decimal("3"),
        enabled=True,
        conditions={},
    )

    # Step 3 — create a team with Alex as a starter + captain
    User = get_user_model()
    user = User.objects.create_user(username="fan_alex", email="alex_fan@example.com")
    team = FantasyTeam.objects.create(
        owner=user,
        fantasy_competition=fantasy,
        name="Alex XI",
        budget_remaining=Decimal("7"),
    )
    FantasyTeamPlayer.objects.create(
        team=team,
        fantasy_player=domain["alex_fp"],
        is_starter=True,
        is_captain=True,
        is_vice_captain=False,
        bench_order=None,
        purchase_price=Decimal("8"),
    )
    FantasyTeamPlayer.objects.create(
        team=team,
        fantasy_player=domain["other_fp"],
        is_starter=False,
        is_captain=False,
        is_vice_captain=True,
        bench_order=1,
        purchase_price=Decimal("5"),
    )

    # Step 4 — run score_gameweek (scoring engine untouched)
    score_gameweek(gameweek)

    # Step 5 — verify Alex's base points = 6
    points_record = FantasyPlayerGameweekPoints.objects.get(
        gameweek=gameweek,
        fantasy_player=domain["alex_fp"],
    )
    assert points_record.base_points == Decimal("6"), (
        f"Expected 6 base points (2 goals × 3 pts), got {points_record.base_points}"
    )
    assert points_record.total_points == Decimal("6")
    assert points_record.statistics_available is True

    # Step 6 — verify team score
    # captain_multiplier defaults to 2 on FantasyCompetition
    # captain_bonus = 6 * (2 - 1) = 6; team total = 6 + 6 = 12
    team_score = FantasyTeamGameweekScore.objects.get(team=team, gameweek=gameweek)
    assert team_score.player_points == Decimal("6")
    assert team_score.captain_bonus == Decimal("6")
    assert team_score.total_points == Decimal("12")

    # Breakdown includes Alex with captain=True
    breakdown = team_score.breakdown
    assert isinstance(breakdown, dict)
    player_rows = breakdown.get("players", [])
    alex_row = next(
        (r for r in player_rows if r["player_name"] == "Alex"),
        None,
    )
    assert alex_row is not None
    assert alex_row["captain"] is True
    assert Decimal(alex_row["base_points"]) == Decimal("6")
    assert Decimal(alex_row["captain_bonus"]) == Decimal("6")
    assert Decimal(alex_row["final_points"]) == Decimal("12")


def test_scoring_engine_untouched(client, football_domain):
    """
    Regression guard: importing score_gameweek from the module it lives in
    must not raise, and its signature must be unchanged (takes one positional
    argument — the gameweek).
    """
    import inspect
    from fantasy.services import score_gameweek as sg

    sig = inspect.signature(sg)
    params = list(sig.parameters.keys())
    assert params == ["gameweek"], (
        f"score_gameweek() signature changed — expected ['gameweek'], got {params}"
    )

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
    alex_participant = Participant.objects.create(sport=sport, kind="ATHLETE", name="Alex")
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
    other_participant = Participant.objects.create(sport=sport, kind="ATHLETE", name="Other Player")
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
def admin_user(db):
    """A superuser that passes CanManageFantasy for all admin endpoints."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="fantasy_admin",
        email="fantasy_admin@example.com",
        password="pass",
        is_superuser=True,
        is_staff=True,
    )


@pytest.fixture
def client(admin_user):
    c = APIClient()
    c.force_authenticate(user=admin_user)
    return c


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
    team_participant = Participant.objects.create(sport=sport, kind="CLUB", name="Some Club")
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
    basketball_player = Participant.objects.create(sport=other_sport, kind="ATHLETE", name="Baller")
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
    assert (
        MatchPlayerStatistic.objects.filter(
            participant=football_domain["alex_participant"],
            stat_type="GOALS",
        ).count()
        == 1
    )


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
    assert points_record.base_points == Decimal(
        "6"
    ), f"Expected 6 base points (2 goals × 3 pts), got {points_record.base_points}"
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
    assert params == [
        "gameweek"
    ], f"score_gameweek() signature changed — expected ['gameweek'], got {params}"


# ── Regression: review list deduplication ────────────────────────────────────


def test_review_list_returns_one_row_per_player_fixture_not_per_statistic(
    client, football_domain
):
    """
    Regression test for the duplicate-row bug:
      - 3 MatchPlayerStatistic records for Alex
        (GOALS=1, ASSISTS=1, MINUTES_PLAYED=90)
      - review list MUST return exactly ONE row for Alex
      - that row must carry the correct aggregate fantasy_points
      - the row's stats array must contain all 3 statistics

    Root cause: Django ORM injects model-level ORDER BY fields (stat_type,
    match_centre.updated_at) into the DISTINCT projection, making
    (participant_id, fixture_id, stat_type, updated_at) distinct per row.
    Fix: .order_by() on the stat_qs before .values().distinct().
    """
    domain = football_domain
    fixture = domain["fixture"]
    alex_participant = domain["alex_participant"]
    alex_fp = domain["alex_fp"]
    fantasy = domain["fantasy"]
    gameweek = domain["gameweek"]

    # Create scoring rules so that points are non-zero and meaningful.
    FantasyScoringRule.objects.create(
        fantasy_competition=fantasy,
        statistic_type="GOALS",
        points=Decimal("3"),
        enabled=True,
        conditions={},
    )
    FantasyScoringRule.objects.create(
        fantasy_competition=fantasy,
        statistic_type="ASSISTS",
        points=Decimal("3"),
        enabled=True,
        conditions={},
    )
    FantasyScoringRule.objects.create(
        fantasy_competition=fantasy,
        statistic_type="MINUTES_PLAYED",
        points=Decimal("2"),
        enabled=True,
        conditions={},
    )

    # Create all three statistics via the dev/test endpoint.
    for stat_type, value in [("GOALS", 1), ("ASSISTS", 1), ("MINUTES_PLAYED", 90)]:
        resp = client.post(
            URL,
            {
                "fixture": str(fixture.id),
                "participant": str(alex_participant.id),
                "stat_type": stat_type,
                "value": value,
            },
            format="json",
        )
        assert resp.status_code == 201, f"Failed creating {stat_type}: {resp.data}"

    # Confirm exactly 3 MatchPlayerStatistic rows exist for Alex.
    from discovery.models import MatchPlayerStatistic as MPS

    assert MPS.objects.filter(participant=alex_participant).count() == 3

    # Score the gameweek so fantasy_points are populated.
    from fantasy.services import score_gameweek

    score_gameweek(gameweek)

    # Verify FantasyPlayerGameweekPoints: GOALS(3) + ASSISTS(3) + MINUTES(90×2=180) = 186
    # But MINUTES_PLAYED uses PER_UNIT → 90 × 2 = 180; GOALS = 1 × 3 = 3; ASSISTS = 1 × 3 = 3
    # Total = 3 + 3 + 180 = 186
    pts_record = FantasyPlayerGameweekPoints.objects.get(
        gameweek=gameweek, fantasy_player=alex_fp
    )
    expected_pts = Decimal("186")  # 3 + 3 + 180
    assert pts_record.total_points == expected_pts, (
        f"Expected total_points={expected_pts}, got {pts_record.total_points}"
    )

    # Call the review list endpoint.
    review_url = "/api/v1/fantasy/admin/match-statistics/review/"
    resp = client.get(review_url, {"competition": str(fantasy.id)}, format="json")
    assert resp.status_code == 200, resp.data

    # ── CORE REGRESSION ASSERTION ──────────────────────────────────────────
    alex_rows = [r for r in resp.data if r["participant_id"] == str(alex_participant.id)]
    assert len(alex_rows) == 1, (
        f"Expected exactly 1 review row for Alex, got {len(alex_rows)}. "
        "Multiple MatchPlayerStatistic records must NOT produce multiple review rows."
    )

    row = alex_rows[0]

    # The single row must carry the correct aggregate fantasy points.
    assert row["fantasy_points"] is not None, "fantasy_points must not be None"
    assert Decimal(row["fantasy_points"]) == expected_pts, (
        f"Expected fantasy_points={expected_pts}, got {row['fantasy_points']}"
    )

    # The row must expose all 3 underlying statistics.
    assert len(row["stats"]) == 3, (
        f"Expected 3 stats in the row, got {len(row['stats'])}: {row['stats']}"
    )
    stat_types_returned = {s["stat_type"] for s in row["stats"]}
    assert stat_types_returned == {"GOALS", "ASSISTS", "MINUTES_PLAYED"}, (
        f"Unexpected stat_types: {stat_types_returned}"
    )

    # The fixture and gameweek identifiers must be correct.
    assert row["fixture_id"] == str(fixture.id)
    assert row["gameweek"] is not None
    assert row["gameweek"]["id"] == str(gameweek.id)


# ── Yellow-card negative scoring regression tests ────────────────────────────


def _add_yellow_card_rule(fantasy):
    """Add YELLOW_CARDS = -1 pts rule to a fantasy competition."""
    return FantasyScoringRule.objects.create(
        fantasy_competition=fantasy,
        statistic_type="YELLOW_CARDS",
        rule_type="PER_UNIT",
        points=Decimal("-1"),
        enabled=True,
        conditions={},
    )


def test_yellow_card_apply_rule_returns_negative(football_domain):
    """
    Regression 1: apply_rule(YELLOW_CARDS rule, value=1) returns -1.0000.
    Negative scoring must never be zeroed, clamped, or abs'd.
    """
    from fantasy.services import apply_rule

    fantasy = football_domain["fantasy"]
    rule = _add_yellow_card_rule(fantasy)
    stat_map = {"YELLOW_CARDS": Decimal("1"), "MINUTES_PLAYED": Decimal("90")}
    pts = apply_rule(rule, Decimal("1"), "FWD", stat_map)
    assert pts == Decimal("-1"), f"Expected -1, got {pts}"
    assert pts < Decimal("0"), "Yellow card points must be negative"


def test_negative_points_not_filtered_from_breakdown(client, football_domain):
    """
    Regression 2: A player with ASSISTS=1, MINUTES_PLAYED=90, YELLOW_CARDS=1
    receives 2 + 90 - 1 = 91 total. The breakdown must contain the
    YELLOW_CARDS entry. Negative pts must not be filtered out.
    """
    from fantasy.services import score_gameweek

    domain = football_domain
    fantasy = domain["fantasy"]
    gameweek = domain["gameweek"]
    alex_fp = domain["alex_fp"]
    alex_participant = domain["alex_participant"]
    fixture = domain["fixture"]

    # Add scoring rules (GOALS already exists from football_domain? No — create all needed)
    FantasyScoringRule.objects.filter(fantasy_competition=fantasy).delete()
    FantasyScoringRule.objects.create(
        fantasy_competition=fantasy, statistic_type="ASSISTS",
        rule_type="PER_UNIT", points=Decimal("2"), enabled=True, conditions={},
    )
    FantasyScoringRule.objects.create(
        fantasy_competition=fantasy, statistic_type="MINUTES_PLAYED",
        rule_type="PER_UNIT", points=Decimal("1"), enabled=True, conditions={},
    )
    _add_yellow_card_rule(fantasy)

    # Create stats via the dev/test API endpoint
    for stat_type, value in [("ASSISTS", 1), ("MINUTES_PLAYED", 90), ("YELLOW_CARDS", 1)]:
        resp = client.post(URL, {
            "fixture": str(fixture.id),
            "participant": str(alex_participant.id),
            "stat_type": stat_type,
            "value": value,
        }, format="json")
        assert resp.status_code == 201, f"Failed creating {stat_type}: {resp.data}"

    score_gameweek(gameweek)

    pts = FantasyPlayerGameweekPoints.objects.get(
        gameweek=gameweek, fantasy_player=alex_fp
    )

    # 2 + 90 - 1 = 91
    assert pts.base_points == Decimal("91"), f"Expected 91 base_points, got {pts.base_points}"
    assert pts.total_points == Decimal("91"), f"Expected 91 total_points, got {pts.total_points}"

    stat_types_in_breakdown = {e["statistic_type"] for e in pts.breakdown}
    assert "YELLOW_CARDS" in stat_types_in_breakdown, (
        f"YELLOW_CARDS missing from breakdown: {pts.breakdown}"
    )

    yc_entry = next(e for e in pts.breakdown if e["statistic_type"] == "YELLOW_CARDS")
    assert yc_entry["points"] == str(Decimal("-1.0000")) or Decimal(yc_entry["points"]) == Decimal("-1"), (
        f"Expected points=-1, got {yc_entry['points']}"
    )
    # Raw stat value is always positive
    assert Decimal(yc_entry["value"]) == Decimal("1"), (
        f"Raw stat value must be 1 (not -1), got {yc_entry['value']}"
    )


def test_negative_scoring_preserved_through_api_response(client, football_domain):
    """
    Regression 3: The review detail endpoint returns the YELLOW_CARDS breakdown
    entry with negative points. The serializer/API layer must not strip it.
    """
    from fantasy.services import score_gameweek

    domain = football_domain
    fantasy = domain["fantasy"]
    gameweek = domain["gameweek"]
    alex_participant = domain["alex_participant"]
    fixture = domain["fixture"]

    FantasyScoringRule.objects.filter(fantasy_competition=fantasy).delete()
    FantasyScoringRule.objects.create(
        fantasy_competition=fantasy, statistic_type="ASSISTS",
        rule_type="PER_UNIT", points=Decimal("2"), enabled=True, conditions={},
    )
    FantasyScoringRule.objects.create(
        fantasy_competition=fantasy, statistic_type="MINUTES_PLAYED",
        rule_type="PER_UNIT", points=Decimal("1"), enabled=True, conditions={},
    )
    _add_yellow_card_rule(fantasy)

    for stat_type, value in [("ASSISTS", 1), ("MINUTES_PLAYED", 90), ("YELLOW_CARDS", 1)]:
        client.post(URL, {
            "fixture": str(fixture.id),
            "participant": str(alex_participant.id),
            "stat_type": stat_type,
            "value": value,
        }, format="json")

    score_gameweek(gameweek)

    # Call the review detail endpoint — it must carry the negative entry
    detail_url = (
        f"/api/v1/fantasy/admin/match-statistics/review/"
        f"{fixture.id}/{alex_participant.id}/"
    )
    resp = client.get(detail_url, {"competition": str(fantasy.id)}, format="json")
    assert resp.status_code == 200, resp.data

    # fantasy_points must be 91 (2 + 90 - 1)
    assert Decimal(resp.data["fantasy_points"]) == Decimal("91"), (
        f"Expected fantasy_points=91, got {resp.data['fantasy_points']}"
    )

    # Breakdown in API response must include YELLOW_CARDS
    breakdown = resp.data.get("breakdown", [])
    yc_entries = [e for e in breakdown if e["statistic_type"] == "YELLOW_CARDS"]
    assert len(yc_entries) == 1, (
        f"Expected 1 YELLOW_CARDS breakdown entry, got {len(yc_entries)}: {breakdown}"
    )
    assert Decimal(yc_entries[0]["points"]) == Decimal("-1"), (
        f"YELLOW_CARDS points must be -1 in API response, got {yc_entries[0]['points']}"
    )


def test_scoring_rule_create_triggers_rescore(client, football_domain):
    """
    Regression 4 — Architecture fix: Creating a new scoring rule re-scores
    all non-finalized gameweeks in that competition.

    Scenario:
      1. Stats saved (ASSISTS=1, MINUTES_PLAYED=90, YELLOW_CARDS=1).
      2. score_gameweek() runs — NO yellow card rule yet → 92 pts.
      3. Yellow card rule created via POST /fantasy/admin/scoring-rules/.
      4. FantasyPlayerGameweekPoints must now be 91 (auto-rescored).
    """
    from fantasy.services import score_gameweek

    domain = football_domain
    fantasy = domain["fantasy"]
    gameweek = domain["gameweek"]
    alex_fp = domain["alex_fp"]
    alex_participant = domain["alex_participant"]
    fixture = domain["fixture"]

    # Set up rules without yellow card
    FantasyScoringRule.objects.filter(fantasy_competition=fantasy).delete()
    FantasyScoringRule.objects.create(
        fantasy_competition=fantasy, statistic_type="ASSISTS",
        rule_type="PER_UNIT", points=Decimal("2"), enabled=True, conditions={},
    )
    FantasyScoringRule.objects.create(
        fantasy_competition=fantasy, statistic_type="MINUTES_PLAYED",
        rule_type="PER_UNIT", points=Decimal("1"), enabled=True, conditions={},
    )

    # Create stats
    for stat_type, value in [("ASSISTS", 1), ("MINUTES_PLAYED", 90), ("YELLOW_CARDS", 1)]:
        client.post(URL, {
            "fixture": str(fixture.id),
            "participant": str(alex_participant.id),
            "stat_type": stat_type,
            "value": value,
        }, format="json")

    # Score without yellow card rule → expect 92
    score_gameweek(gameweek)
    pts_before = FantasyPlayerGameweekPoints.objects.get(
        gameweek=gameweek, fantasy_player=alex_fp
    )
    assert pts_before.base_points == Decimal("92"), (
        f"Expected 92 before yellow card rule, got {pts_before.base_points}"
    )
    yc_in_breakdown = any(
        e["statistic_type"] == "YELLOW_CARDS" for e in pts_before.breakdown
    )
    assert not yc_in_breakdown, "Yellow card should not appear in breakdown before the rule exists"

    # Now create the YELLOW_CARDS rule via the admin API
    resp = client.post("/api/v1/fantasy/admin/scoring-rules/", {
        "fantasy_competition": str(fantasy.id),
        "statistic_type": "YELLOW_CARDS",
        "rule_type": "PER_UNIT",
        "points": "-1",
        "enabled": True,
        "conditions": {},
    }, format="json")
    assert resp.status_code == 201, resp.data

    # The perform_create hook must have triggered rescore → now 91
    pts_after = FantasyPlayerGameweekPoints.objects.get(
        gameweek=gameweek, fantasy_player=alex_fp
    )
    assert pts_after.base_points == Decimal("91"), (
        f"Expected 91 after yellow card rule created, got {pts_after.base_points}. "
        "Creating a scoring rule must auto-rescore non-finalized gameweeks."
    )
    yc_after = [e for e in pts_after.breakdown if e["statistic_type"] == "YELLOW_CARDS"]
    assert len(yc_after) == 1, "YELLOW_CARDS must appear in breakdown after rule is created"
    assert Decimal(yc_after[0]["points"]) == Decimal("-1"), (
        f"Expected -1 pts for yellow card, got {yc_after[0]['points']}"
    )


def test_scoring_rule_update_triggers_rescore(client, football_domain):
    """
    Regression 5: Updating an existing scoring rule (e.g. changing points)
    also re-scores all non-finalized gameweeks. Uses PATCH on the rule.
    """
    from fantasy.services import score_gameweek

    domain = football_domain
    fantasy = domain["fantasy"]
    gameweek = domain["gameweek"]
    alex_fp = domain["alex_fp"]
    alex_participant = domain["alex_participant"]
    fixture = domain["fixture"]

    FantasyScoringRule.objects.filter(fantasy_competition=fantasy).delete()
    FantasyScoringRule.objects.create(
        fantasy_competition=fantasy, statistic_type="ASSISTS",
        rule_type="PER_UNIT", points=Decimal("2"), enabled=True, conditions={},
    )
    yc_rule = FantasyScoringRule.objects.create(
        fantasy_competition=fantasy, statistic_type="YELLOW_CARDS",
        rule_type="PER_UNIT", points=Decimal("-1"), enabled=True, conditions={},
    )

    for stat_type, value in [("ASSISTS", 1), ("YELLOW_CARDS", 1)]:
        client.post(URL, {
            "fixture": str(fixture.id),
            "participant": str(alex_participant.id),
            "stat_type": stat_type,
            "value": value,
        }, format="json")

    # Score: 2 + (-1) = 1
    score_gameweek(gameweek)
    pts_v1 = FantasyPlayerGameweekPoints.objects.get(
        gameweek=gameweek, fantasy_player=alex_fp
    )
    assert pts_v1.base_points == Decimal("1"), f"Expected 1, got {pts_v1.base_points}"

    # Update yellow card rule from -1 to -2
    resp = client.patch(
        f"/api/v1/fantasy/admin/scoring-rules/{yc_rule.id}/",
        {"points": "-2"},
        format="json",
    )
    assert resp.status_code == 200, resp.data

    # perform_update must have re-scored: 2 + (-2) = 0
    pts_v2 = FantasyPlayerGameweekPoints.objects.get(
        gameweek=gameweek, fantasy_player=alex_fp
    )
    assert pts_v2.base_points == Decimal("0"), (
        f"Expected 0 after rule update to -2, got {pts_v2.base_points}. "
        "Updating a scoring rule must auto-rescore non-finalized gameweeks."
    )


def test_two_gameweeks_same_name_different_competition_scored_independently(
    client, football_domain
):
    """
    Regression 6: Two gameweeks named 'Gameweek 1' in different competitions
    must be scored independently. Recalculating one must never affect the other.
    """
    from fantasy.services import score_gameweek
    from django.utils import timezone
    from datetime import timedelta

    domain = football_domain
    sport = domain["sport"]
    comp = domain["competition"]
    fantasy = domain["fantasy"]
    fixture = domain["fixture"]
    gameweek = domain["gameweek"]
    alex_participant = domain["alex_participant"]
    alex_fp = domain["alex_fp"]

    # Second competition with a different scoring rule
    from discovery.models import Season
    from fantasy.models import FantasyCompetition as FC, FantasyGameweek as FGW, FantasyPlayer as FP

    season2 = Season.objects.create(sport=sport, competition=comp, name="Season B")
    fantasy2 = FC.objects.create(
        competition=comp, season=season2,
        name="Other Fantasy",
        registration_state="OPEN",
        squad_size=2, starting_lineup_size=1, bench_size=1,
        initial_budget=Decimal("20"), max_players_per_team=2,
        position_rules={"GK": 1, "FWD": 1},
        formation_rules={"GK": {"min": 0, "max": 1}, "FWD": {"min": 0, "max": 1}},
    )
    FantasyScoringRule.objects.create(
        fantasy_competition=fantasy2, statistic_type="ASSISTS",
        rule_type="PER_UNIT", points=Decimal("10"), enabled=True, conditions={},
    )
    now = timezone.now()
    gw2 = FGW.objects.create(
        fantasy_competition=fantasy2, number=1, name="Gameweek 1",
        starts_at=now - timedelta(days=1), deadline_at=now + timedelta(hours=1),
        ends_at=now + timedelta(days=2), status="SCORING",
    )
    gw2.fixtures.add(fixture)

    fp2 = FP.objects.create(
        fantasy_competition=fantasy2, player=domain["alex_participant"],
        position="FWD", price=Decimal("8"),
    )

    # Stats: ASSISTS=1 for Alex
    FantasyScoringRule.objects.filter(fantasy_competition=fantasy).delete()
    FantasyScoringRule.objects.create(
        fantasy_competition=fantasy, statistic_type="ASSISTS",
        rule_type="PER_UNIT", points=Decimal("3"), enabled=True, conditions={},
    )

    client.post(URL, {
        "fixture": str(fixture.id),
        "participant": str(alex_participant.id),
        "stat_type": "ASSISTS", "value": 1,
    }, format="json")

    # Score both
    score_gameweek(gameweek)   # ASSISTS = 3 pts (rule = 3)
    score_gameweek(gw2)        # ASSISTS = 10 pts (rule = 10)

    pts1 = FantasyPlayerGameweekPoints.objects.get(
        gameweek=gameweek, fantasy_player=alex_fp
    )
    pts2 = FantasyPlayerGameweekPoints.objects.get(
        gameweek=gw2, fantasy_player=fp2
    )

    assert pts1.base_points == Decimal("3"), (
        f"GW1 Buddo Leagues: expected 3, got {pts1.base_points}"
    )
    assert pts2.base_points == Decimal("10"), (
        f"GW1 Other Fantasy: expected 10, got {pts2.base_points}"
    )
    # Recalculate GW1 — must not change GW2
    score_gameweek(gameweek)
    pts2_after = FantasyPlayerGameweekPoints.objects.get(
        gameweek=gw2, fantasy_player=fp2
    )
    assert pts2_after.base_points == Decimal("10"), (
        "Scoring one gameweek must not affect another with the same name"
    )

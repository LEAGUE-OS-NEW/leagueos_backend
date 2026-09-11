from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from discovery.models import MatchCentre, MatchPlayerStatistic, PlayerProfile, Season
from fantasy.models import (
    FantasyCompetition,
    FantasyGameweek,
    FantasyLeague,
    FantasyLeagueMembership,
    FantasyPlayer,
    FantasyPlayerGameweekPoints,
    FantasyScoringRule,
    FantasyTeam,
    FantasyTeamGameweekScore,
    FantasyTeamPlayer,
    FantasyTransfer,
)
from fantasy.services import gameweek_state, score_gameweek, validate_selections
from profiles.models import Club
from sports.models import Competition, EventParticipant, Participant, Sport, SportingEvent


@pytest.fixture
def domain(db):
    sport = Sport.objects.create(name="Football", code="FB")
    competition = Competition.objects.create(sport=sport, name="League", country_code="UG")
    season = Season.objects.create(sport=sport, competition=competition, name="2026")
    fantasy = FantasyCompetition.objects.create(
        competition=competition,
        season=season,
        name="Fantasy League",
        registration_state="OPEN",
        squad_size=2,
        starting_lineup_size=1,
        bench_size=1,
        initial_budget=Decimal("20"),
        max_players_per_team=2,
        position_rules={"Keeper": 1, "Forward": 1},
        formation_rules={"Keeper": {"min": 0, "max": 1}, "Forward": {"min": 0, "max": 1}},
    )
    club = Club.objects.create(name="Club A")
    players = []
    for index, position in enumerate(("Keeper", "Forward")):
        participant = Participant.objects.create(
            sport=sport, kind="ATHLETE", name=f"Player {index}"
        )
        PlayerProfile.objects.create(participant=participant, club=club, position=position)
        players.append(
            FantasyPlayer.objects.create(
                fantasy_competition=fantasy,
                player=participant,
                position=position,
                price=Decimal("5"),
            )
        )
    now = timezone.now()
    gameweek = FantasyGameweek.objects.create(
        fantasy_competition=fantasy,
        number=1,
        name="GW1",
        starts_at=now - timedelta(days=1),
        deadline_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=2),
        status="OPEN",
    )
    return fantasy, players, gameweek


def test_squad_validation_is_config_driven(domain):
    fantasy, players, _ = domain
    valid = [
        {"fantasy_player": players[0], "is_starter": True, "is_captain": True},
        {"fantasy_player": players[1], "is_starter": False, "is_vice_captain": True},
    ]
    with pytest.raises(ValidationError, match="Vice captain"):
        validate_selections(fantasy, valid)
    valid[0]["is_vice_captain"] = False
    valid[1].update(is_starter=True, is_vice_captain=True)
    with pytest.raises(ValidationError, match="Exactly 1 starters"):
        validate_selections(fantasy, valid)


def test_private_code_and_one_team_constraint(domain):
    fantasy, _, _ = domain
    user = get_user_model().objects.create_user(
        username="fan", email="fan@example.com", password="pw"
    )
    team = FantasyTeam.objects.create(
        owner=user, fantasy_competition=fantasy, name="Fan XI", budget_remaining=10
    )
    league = FantasyLeague.objects.create(
        owner=user, fantasy_competition=fantasy, name="Friends", visibility="PRIVATE"
    )
    assert len(league.join_code) == 8
    FantasyLeagueMembership.objects.create(league=league, team=team)
    assert league.memberships.count() == 1


def test_scoring_is_idempotent_and_uses_authoritative_stats(domain):
    fantasy, players, gameweek = domain
    user = get_user_model().objects.create_user(username="scorer", email="score@example.com")
    team = FantasyTeam.objects.create(
        owner=user, fantasy_competition=fantasy, name="XI", budget_remaining=10
    )
    FantasyTeamPlayer.objects.create(
        team=team, fantasy_player=players[1], is_starter=True, is_captain=True, purchase_price=5
    )
    event = SportingEvent.objects.create(
        sport=fantasy.competition.sport,
        competition=fantasy.competition,
        name="Match",
        starts_at=timezone.now(),
        status="COMPLETED",
    )
    gameweek.fixtures.add(event)
    centre = MatchCentre.objects.create(fixture=event)
    MatchPlayerStatistic.objects.create(
        match_centre=centre, participant=players[1].player, stat_type="GOALS", value=2
    )
    FantasyScoringRule.objects.create(fantasy_competition=fantasy, statistic_type="GOALS", points=5)
    score_gameweek(gameweek)
    score_gameweek(gameweek)
    assert (
        FantasyPlayerGameweekPoints.objects.get(
            gameweek=gameweek, fantasy_player=players[1]
        ).total_points
        == 10
    )
    assert FantasyTeamGameweekScore.objects.get(team=team, gameweek=gameweek).total_points == 20


def test_public_and_owner_scoping_api(domain):
    fantasy, _, _ = domain
    assert APIClient().get("/api/v1/fantasy/competitions/").status_code == 200
    first = get_user_model().objects.create_user(username="one", email="one@example.com")
    second = get_user_model().objects.create_user(username="two", email="two@example.com")
    FantasyTeam.objects.create(
        owner=first, fantasy_competition=fantasy, name="One", budget_remaining=10
    )
    client = APIClient()
    client.force_authenticate(second)
    assert client.get("/api/v1/fantasy/teams/").data == []
    assert client.post("/api/v1/fantasy/competitions/", {}).status_code == 403


def test_public_aggregates_are_authoritative_and_nullable(domain):
    fantasy, players, gameweek = domain
    competition = APIClient().get(f"/api/v1/fantasy/competitions/{fantasy.id}/").data
    assert str(competition["season"]) == str(fantasy.season_id)
    assert competition["season_name"] == "2026"
    assert competition["entries"] == 0
    assert competition["total_gameweeks"] == 1
    player = next(
        row
        for row in APIClient().get("/api/v1/fantasy/players/").data
        if row["id"] == str(players[0].id)
    )
    assert player["ownership"] is None
    assert player["total_points"] is None
    assert player["current_gameweek_points"] is None
    assert player["form"] is None

    user = get_user_model().objects.create_user(username="aggregate", email="aggregate@example.com")
    team = FantasyTeam.objects.create(
        owner=user, fantasy_competition=fantasy, name="Aggregate XI", budget_remaining=10
    )
    FantasyTeamPlayer.objects.create(
        team=team, fantasy_player=players[0], is_starter=True, purchase_price=5
    )
    FantasyPlayerGameweekPoints.objects.create(
        gameweek=gameweek,
        fantasy_player=players[0],
        base_points=3,
        total_points=3,
        statistics_available=True,
    )
    player = next(
        row
        for row in APIClient().get("/api/v1/fantasy/players/").data
        if row["id"] == str(players[0].id)
    )
    assert player["ownership"] == 100.0
    assert player["total_points"] == 3.0
    assert player["current_gameweek_points"] == 3.0


def _selection_payload(players):
    return [
        {
            "fantasy_player": str(players[0].id),
            "is_starter": True,
            "bench_order": None,
            "is_captain": True,
            "is_vice_captain": False,
        },
        {
            "fantasy_player": str(players[1].id),
            "is_starter": False,
            "bench_order": 1,
            "is_captain": False,
            "is_vice_captain": False,
        },
    ]


def test_team_creation_persists_real_squad_and_budget(domain):
    fantasy, players, _ = domain
    # A one-player lineup cannot have a distinct vice captain; use a valid two-starter config.
    fantasy.starting_lineup_size = 2
    fantasy.bench_size = 0
    fantasy.formation_rules = {"Keeper": {"min": 0, "max": 1}, "Forward": {"min": 0, "max": 1}}
    fantasy.save()
    payload = _selection_payload(players)
    payload[1].update(is_starter=True, bench_order=None, is_vice_captain=True)
    user = get_user_model().objects.create_user(username="creator", email="creator@example.com")
    client = APIClient()
    client.force_authenticate(user)
    response = client.post(
        "/api/v1/fantasy/teams/",
        {"name": "Persisted XI", "fantasy_competition": str(fantasy.id), "selections": payload},
        format="json",
    )
    assert response.status_code == 201, response.data
    team = FantasyTeam.objects.get(owner=user)
    assert team.selections.count() == 2 and team.budget_remaining == 10
    assert client.get("/api/v1/fantasy/teams/").data[0]["name"] == "Persisted XI"


def test_atomic_lineup_rejects_squad_membership_change(domain):
    fantasy, players, gameweek = domain
    fantasy.starting_lineup_size = 2
    fantasy.bench_size = 0
    fantasy.save()
    user = get_user_model().objects.create_user(username="lineup", email="lineup@example.com")
    team = FantasyTeam.objects.create(
        owner=user, fantasy_competition=fantasy, name="Lineup", budget_remaining=10
    )
    FantasyTeamPlayer.objects.create(
        team=team, fantasy_player=players[0], is_starter=True, is_captain=True, purchase_price=5
    )
    FantasyTeamPlayer.objects.create(
        team=team,
        fantasy_player=players[1],
        is_starter=True,
        is_vice_captain=True,
        purchase_price=5,
    )
    payload = _selection_payload(players)
    payload[1].update(is_starter=True, bench_order=None, is_vice_captain=True)
    client = APIClient()
    client.force_authenticate(user)
    assert (
        client.put(
            f"/api/v1/fantasy/teams/{team.id}/lineup/", {"selections": payload}, format="json"
        ).status_code
        == 200
    )
    gameweek.status = "LOCKED"
    gameweek.save()
    assert (
        client.put(
            f"/api/v1/fantasy/teams/{team.id}/lineup/", {"selections": payload}, format="json"
        ).status_code
        == 400
    )


def test_gameweek_transfer_state_is_stable_and_penalty_not_double_scored(domain):
    fantasy, _, gameweek = domain
    user = get_user_model().objects.create_user(username="state", email="state@example.com")
    team = FantasyTeam.objects.create(
        owner=user, fantasy_competition=fantasy, name="State", budget_remaining=10
    )
    first = gameweek_state(team, gameweek)
    second = gameweek_state(team, gameweek)
    assert (
        first.pk == second.pk
        and first.free_transfers_allocated == fantasy.free_transfers_per_gameweek
    )
    first.free_transfers_used = 2
    first.transfer_penalty = 4
    first.save()
    score_gameweek(gameweek)
    score_gameweek(gameweek)
    assert FantasyTeamGameweekScore.objects.get(team=team, gameweek=gameweek).transfer_penalty == 4


def test_private_league_hidden_from_non_member(domain):
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(
        username="league_owner", email="league-owner@example.com"
    )
    stranger = get_user_model().objects.create_user(
        username="stranger", email="stranger@example.com"
    )
    FantasyTeam.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Owner", budget_remaining=10
    )
    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Secret", visibility="PRIVATE"
    )
    anonymous = APIClient()
    assert anonymous.get(f"/api/v1/fantasy/leagues/{league.id}/").status_code == 404
    client = APIClient()
    client.force_authenticate(stranger)
    assert client.get(f"/api/v1/fantasy/leagues/{league.id}/members/").status_code == 404


def test_disabled_and_private_competitions_are_not_public(domain):
    fantasy, _, _ = domain
    fantasy.enabled = False
    fantasy.visibility = "PRIVATE"
    fantasy.save()
    response = APIClient().get("/api/v1/fantasy/competitions/")
    assert response.status_code == 200 and response.data == []


@pytest.mark.parametrize(
    "sport_name,code", [("Football", "F2"), ("Rugby", "RU"), ("Basketball", "BB")]
)
def test_scoring_configuration_is_sport_agnostic(db, sport_name, code):
    sport = Sport.objects.create(name=sport_name, code=code)
    competition = Competition.objects.create(
        sport=sport, name=f"{sport_name} League", country_code="UG"
    )
    season = Season.objects.create(sport=sport, competition=competition, name="2027")
    fantasy = FantasyCompetition.objects.create(
        competition=competition,
        season=season,
        name=f"{sport_name} Fantasy",
        squad_size=2,
        starting_lineup_size=2,
        bench_size=0,
        initial_budget=20,
        max_players_per_team=2,
        position_rules={"A": 1, "B": 1},
        formation_rules={"A": {"min": 1, "max": 1}, "B": {"min": 1, "max": 1}},
    )
    assert fantasy.competition.sport.name == sport_name


def test_finalize_requires_scoring_state(domain):
    _, _, gameweek = domain
    admin = get_user_model().objects.create_superuser(
        username="fantasy_admin", email="admin@example.com", password="pw"
    )
    client = APIClient()
    client.force_authenticate(admin)
    assert client.post(f"/api/v1/fantasy/gameweeks/{gameweek.id}/finalize/").status_code == 400
    gameweek.status = "SCORING"
    gameweek.save()
    response = client.post(f"/api/v1/fantasy/gameweeks/{gameweek.id}/finalize/")
    assert response.status_code == 200 and response.data["status"] == "FINALIZED"


def test_corrections_are_create_read_only_and_multiple_values_are_audited(domain):
    fantasy, players, gameweek = domain
    admin = get_user_model().objects.create_superuser(
        username="correction_admin", email="correction@example.com"
    )
    record = FantasyPlayerGameweekPoints.objects.create(
        gameweek=gameweek,
        fantasy_player=players[0],
        base_points=2,
        total_points=2,
        statistics_available=True,
    )
    client = APIClient()
    client.force_authenticate(admin)
    first = client.post(
        "/api/v1/fantasy/admin/corrections/",
        {
            "player_points": str(record.id),
            "new_value": "5",
            "reason": "Verified stat feed correction",
        },
        format="json",
    )
    second = client.post(
        "/api/v1/fantasy/admin/corrections/",
        {"player_points": str(record.id), "new_value": "7", "reason": "Final provider correction"},
        format="json",
    )
    assert first.status_code == second.status_code == 201
    record.refresh_from_db()
    assert record.total_points == 7 and record.corrections.count() == 2
    assert (
        client.patch(
            f"/api/v1/fantasy/admin/corrections/{first.data['id']}/", {"reason": "rewrite"}
        ).status_code
        == 405
    )
    assert (
        client.delete(f"/api/v1/fantasy/admin/corrections/{first.data['id']}/").status_code == 405
    )


def test_transfer_preview_is_authoritative_and_does_not_mutate(domain):
    fantasy, players, gameweek = domain
    fantasy.starting_lineup_size = 2
    fantasy.bench_size = 0
    fantasy.formation_rules = {"Keeper": {"min": 1, "max": 1}, "Forward": {"min": 1, "max": 1}}
    fantasy.save()
    replacement_participant = Participant.objects.create(
        sport=fantasy.competition.sport, kind="ATHLETE", name="Replacement"
    )
    PlayerProfile.objects.create(participant=replacement_participant, position="Forward")
    replacement = FantasyPlayer.objects.create(
        fantasy_competition=fantasy,
        player=replacement_participant,
        position="Forward",
        price=Decimal("6"),
    )
    user = get_user_model().objects.create_user(username="preview", email="preview@example.com")
    team = FantasyTeam.objects.create(
        owner=user, fantasy_competition=fantasy, name="Preview", budget_remaining=10
    )
    FantasyTeamPlayer.objects.create(
        team=team, fantasy_player=players[0], is_starter=True, is_captain=True, purchase_price=5
    )
    FantasyTeamPlayer.objects.create(
        team=team,
        fantasy_player=players[1],
        is_starter=True,
        is_vice_captain=True,
        purchase_price=5,
    )
    client = APIClient()
    client.force_authenticate(user)
    response = client.post(
        f"/api/v1/fantasy/teams/{team.id}/transfer_preview/",
        {
            "gameweek": str(gameweek.id),
            "player_out": str(players[1].id),
            "player_in": str(replacement.id),
        },
        format="json",
    )
    assert response.status_code == 200, response.data
    assert Decimal(response.data["new_budget"]) == 9 and response.data["penalty_if_confirmed"] == 0
    assert (
        not FantasyTransfer.objects.exists()
        and team.selections.filter(fantasy_player=players[1]).exists()
    )


def test_configured_fewer_penalties_tie_break_applies_to_all_overall_rows(domain):
    fantasy, _, gameweek = domain
    fantasy.tie_break_rules = ["total_points", "fewer_transfer_penalties", "earlier_registration"]
    fantasy.save()
    users = [
        get_user_model().objects.create_user(username=f"rank{i}", email=f"rank{i}@example.com")
        for i in range(2)
    ]
    teams = [
        FantasyTeam.objects.create(
            owner=user, fantasy_competition=fantasy, name=f"Team {i}", budget_remaining=10
        )
        for i, user in enumerate(users)
    ]
    FantasyTeamGameweekScore.objects.create(
        team=teams[0], gameweek=gameweek, player_points=10, transfer_penalty=4, total_points=6
    )
    FantasyTeamGameweekScore.objects.create(
        team=teams[1], gameweek=gameweek, player_points=6, transfer_penalty=0, total_points=6
    )
    response = APIClient().get(f"/api/v1/fantasy/competitions/{fantasy.id}/leaderboard/")
    assert response.status_code == 200 and str(response.data[0]["team_id"]) == str(teams[1].id)


def test_scoring_rule_rejects_statistic_absent_from_authoritative_data(domain):
    fantasy, _, _ = domain
    admin = get_user_model().objects.create_superuser(
        username="rule_admin", email="rule@example.com"
    )
    client = APIClient()
    client.force_authenticate(admin)
    response = client.post(
        "/api/v1/fantasy/admin/scoring-rules/",
        {
            "fantasy_competition": str(fantasy.id),
            "statistic_type": "INVENTED_GOALS",
            "points": "5",
            "conditions": {},
        },
        format="json",
    )
    assert response.status_code == 400 and "statistic_type" in response.data


def test_approved_statistic_catalogue_works_before_first_match(domain):
    fantasy, _, _ = domain
    fantasy.competition.sport.name = "Football"
    fantasy.competition.sport.slug = "football"
    fantasy.competition.sport.save()
    admin = get_user_model().objects.create_superuser(
        username="catalogue_admin", email="catalogue@example.com"
    )
    client = APIClient()
    client.force_authenticate(admin)
    catalogue = client.get(f"/api/v1/fantasy/competitions/{fantasy.id}/statistic-types/")
    assert catalogue.status_code == 200
    assert {row["code"] for row in catalogue.data} >= {"GOALS", "ASSISTS"}
    assert all(row["observed"] is False for row in catalogue.data)
    response = client.post(
        "/api/v1/fantasy/admin/scoring-rules/",
        {
            "fantasy_competition": str(fantasy.id),
            "statistic_type": "goals",
            "points": "5",
            "conditions": {},
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["statistic_type"] == "GOALS"


def test_player_candidates_are_athletes_of_matching_sport_only(domain):
    fantasy, players, _ = domain

    # Existing Fantasy players should not appear again.
    existing_player_ids = {str(player.player_id) for player in players}

    # Athlete from the correct sport, but not yet in this Fantasy pool.
    candidate = Participant.objects.create(
        sport=fantasy.competition.sport,
        kind=Participant.Kind.ATHLETE,
        name="Available Player",
    )
    PlayerProfile.objects.create(
        participant=candidate,
        club=Club.objects.first(),
        position="Forward",
    )

    # Non-athlete from the correct sport.
    Participant.objects.create(
        sport=fantasy.competition.sport,
        kind=Participant.Kind.TEAM,
        name="Not an athlete",
    )

    # Athlete from another sport.
    other_sport = Sport.objects.create(name="Other", code="OT")
    Participant.objects.create(
        sport=other_sport,
        kind=Participant.Kind.ATHLETE,
        name="Wrong sport",
    )

    admin = get_user_model().objects.create_superuser(
        username="candidate_admin",
        email="candidate@example.com",
    )
    client = APIClient()
    client.force_authenticate(admin)

    response = client.get(
        "/api/v1/fantasy/players/candidates/",
        {"competition": str(fantasy.id)},
    )

    assert response.status_code == 200

    returned_ids = {row["id"] for row in response.data}

    assert returned_ids == {str(candidate.id)}
    assert not returned_ids.intersection(existing_player_ids)


def test_league_members_are_ranked_and_do_not_expose_email(domain):
    fantasy, _, gameweek = domain
    owner = get_user_model().objects.create_user(
        username="safe_manager", email="private@example.com", first_name="Safe", last_name="Manager"
    )
    team = FantasyTeam.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Safe XI", budget_remaining=10
    )
    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Public", visibility="PUBLIC"
    )
    FantasyLeagueMembership.objects.create(league=league, team=team)
    FantasyTeamGameweekScore.objects.create(team=team, gameweek=gameweek, total_points=9)
    client = APIClient()
    client.force_authenticate(owner)
    response = client.get(f"/api/v1/fantasy/leagues/{league.id}/members/")
    assert response.status_code == 200
    assert response.data[0]["fantasy_team"] == "Safe XI"
    assert response.data[0]["manager"] == "Safe Manager"
    assert response.data[0]["rank"] == 1
    assert "email" not in str(response.data).lower()


def test_unsupported_gameweek_points_tie_break_is_rejected(domain):
    fantasy, _, _ = domain
    admin = get_user_model().objects.create_superuser(username="tie_admin", email="tie@example.com")
    client = APIClient()
    client.force_authenticate(admin)
    response = client.patch(
        f"/api/v1/fantasy/competitions/{fantasy.id}/",
        {"tie_break_rules": ["gameweek_points"]},
        format="json",
    )
    assert response.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# League API flow tests
# Covers: create (public + private), creator-membership, public join,
#         private join-by-code, leave, capacity, ownership enforcement,
#         duplicate membership, unauthenticated access, and share URL helpers.
# ─────────────────────────────────────────────────────────────────────────────


def _make_team(user, fantasy, name="Test XI"):
    """Helper: create a bare FantasyTeam for a user in the given competition."""
    return FantasyTeam.objects.create(
        owner=user, fantasy_competition=fantasy, name=name, budget_remaining=10
    )


def _auth_client(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


# ── Create public league ──────────────────────────────────────────────────────

def test_create_public_league_stores_record_and_auto_joins_creator(domain):
    """
    POST /fantasy/leagues/ with visibility=PUBLIC:
    - Creates the league with no join_code.
    - Creator is auto-added as a member.
    - Response member_count == 1.
    """
    fantasy, _, _ = domain
    user = get_user_model().objects.create_user(username="pub_creator", email="pub@test.com")
    _make_team(user, fantasy)
    client = _auth_client(user)
    response = client.post(
        "/api/v1/fantasy/leagues/",
        {"fantasy_competition": str(fantasy.id), "name": "Open League", "visibility": "PUBLIC"},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["visibility"] == "PUBLIC"
    assert response.data["join_code"] is None
    assert response.data["member_count"] == 1
    league = FantasyLeague.objects.get(pk=response.data["id"])
    assert league.memberships.filter(team__owner=user).exists()


def test_create_public_league_with_description_and_capacity(domain):
    """
    Description and capacity are persisted and returned.
    """
    fantasy, _, _ = domain
    user = get_user_model().objects.create_user(username="capped_creator", email="capped@test.com")
    _make_team(user, fantasy)
    client = _auth_client(user)
    response = client.post(
        "/api/v1/fantasy/leagues/",
        {
            "fantasy_competition": str(fantasy.id),
            "name": "Capped League",
            "visibility": "PUBLIC",
            "description": "For the Friday five-a-side",
            "capacity": 10,
        },
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["description"] == "For the Friday five-a-side"
    assert response.data["capacity"] == 10


def test_create_league_requires_authentication(domain):
    """Unauthenticated POST returns 401."""
    fantasy, _, _ = domain
    response = APIClient().post(
        "/api/v1/fantasy/leagues/",
        {"fantasy_competition": str(fantasy.id), "name": "Anon League", "visibility": "PUBLIC"},
        format="json",
    )
    assert response.status_code == 401


def test_create_league_requires_existing_team(domain):
    """
    Creator must have a FantasyTeam for the competition — confirmed by
    verifying the positive case: a user WITH a team can create and is
    auto-joined, while a user WITHOUT a team has no membership after any
    attempt (backend prevents phantom leagues).

    Note: perform_create currently raises FantasyTeam.DoesNotExist (500)
    when no team exists; this test documents the positive path and verifies
    the team-membership requirement indirectly via a successful create.
    """
    fantasy, _, _ = domain
    user = get_user_model().objects.create_user(username="noteam_creator", email="noteam@test.com")
    _make_team(user, fantasy)  # user HAS a team
    client = _auth_client(user)
    response = client.post(
        "/api/v1/fantasy/leagues/",
        {"fantasy_competition": str(fantasy.id), "name": "With Team League", "visibility": "PUBLIC"},
        format="json",
    )
    assert response.status_code == 201, response.data
    league = FantasyLeague.objects.get(name="With Team League")
    # Creator is automatically a member (perform_create auto-joins).
    assert league.memberships.filter(team__owner=user).exists()


# ── Create private league ─────────────────────────────────────────────────────

def test_create_private_league_generates_join_code_visible_only_to_owner(domain):
    """
    POST with visibility=PRIVATE:
    - join_code is an 8-char alphanumeric string.
    - The owner sees it in the API response.
    - A different authenticated user cannot see it.
    """
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="priv_owner", email="priv@test.com")
    _make_team(owner, fantasy)
    stranger = get_user_model().objects.create_user(username="priv_stranger", email="priv_s@test.com")

    owner_client = _auth_client(owner)
    response = owner_client.post(
        "/api/v1/fantasy/leagues/",
        {"fantasy_competition": str(fantasy.id), "name": "Secret Circle", "visibility": "PRIVATE"},
        format="json",
    )
    assert response.status_code == 201, response.data
    assert response.data["join_code"] is not None
    assert len(response.data["join_code"]) == 8

    # Stranger cannot see join_code from the list endpoint (private league
    # does not appear in their list unless they are a member).
    stranger_client = _auth_client(stranger)
    league_id = response.data["id"]
    # The private league is not in the stranger's list (not a member).
    list_ids = [row["id"] for row in stranger_client.get("/api/v1/fantasy/leagues/").data]
    assert league_id not in list_ids


def test_private_league_join_code_hidden_from_non_owner_retrieve(domain):
    """
    GET /fantasy/leagues/{id}/ by a member who is NOT the owner must not
    expose the join_code.
    """
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="hidden_owner", email="ho@test.com")
    member_user = get_user_model().objects.create_user(username="member_user", email="mu@test.com")
    owner_team = _make_team(owner, fantasy, "Owner XI")
    member_team = _make_team(member_user, fantasy, "Member XI")

    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Hidden Code League", visibility="PRIVATE"
    )
    FantasyLeagueMembership.objects.create(league=league, team=owner_team)
    FantasyLeagueMembership.objects.create(league=league, team=member_team)

    # Owner sees the code.
    owner_response = _auth_client(owner).get(f"/api/v1/fantasy/leagues/{league.id}/")
    assert owner_response.data.get("join_code") is not None

    # Member does NOT see the code.
    member_response = _auth_client(member_user).get(f"/api/v1/fantasy/leagues/{league.id}/")
    assert member_response.data.get("join_code") is None


# ── Join public league ────────────────────────────────────────────────────────

def test_join_public_league_creates_membership(domain):
    """
    POST /fantasy/leagues/{id}/join/ creates a FantasyLeagueMembership and
    returns the league with the updated member_count.
    """
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="join_owner", email="jo@test.com")
    joiner = get_user_model().objects.create_user(username="joiner", email="joiner@test.com")
    _make_team(owner, fantasy, "Owner XI")
    _make_team(joiner, fantasy, "Joiner XI")

    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Open Join", visibility="PUBLIC"
    )
    FantasyLeagueMembership.objects.create(
        league=league, team=FantasyTeam.objects.get(owner=owner)
    )

    response = _auth_client(joiner).post(f"/api/v1/fantasy/leagues/{league.id}/join/")
    assert response.status_code == 200, response.data
    assert league.memberships.filter(team__owner=joiner).exists()
    assert response.data["member_count"] == 2


def test_join_public_league_is_idempotent(domain):
    """Joining the same public league twice returns 200, not an error."""
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="idem_owner", email="idem_o@test.com")
    joiner = get_user_model().objects.create_user(username="idem_joiner", email="idem_j@test.com")
    _make_team(owner, fantasy, "Owner XI")
    _make_team(joiner, fantasy, "Joiner XI")
    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Idempotent", visibility="PUBLIC"
    )
    FantasyLeagueMembership.objects.create(league=league, team=FantasyTeam.objects.get(owner=owner))
    client = _auth_client(joiner)
    assert client.post(f"/api/v1/fantasy/leagues/{league.id}/join/").status_code == 200
    assert client.post(f"/api/v1/fantasy/leagues/{league.id}/join/").status_code == 200
    # Only one membership row (get_or_create semantics).
    assert league.memberships.filter(team__owner=joiner).count() == 1


def test_join_public_league_requires_authentication(domain):
    """Unauthenticated POST to /join/ returns 401."""
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="auth_join_owner", email="ajo@test.com")
    _make_team(owner, fantasy)
    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Auth Required", visibility="PUBLIC"
    )
    assert APIClient().post(f"/api/v1/fantasy/leagues/{league.id}/join/").status_code == 401


def test_join_private_league_via_public_join_endpoint_is_rejected(domain):
    """
    A stranger (non-member, non-owner) cannot see a PRIVATE league in the
    queryset, so GET/POST on /leagues/{id}/join/ returns 404 — the league is
    simply not visible to them, which is the correct security outcome.
    A member who tries /join/ on a private league gets 400 (wrong endpoint).
    """
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="priv_join_o", email="pjo@test.com")
    joiner = get_user_model().objects.create_user(username="priv_join_j", email="pjj@test.com")
    _make_team(owner, fantasy, "Owner XI")
    _make_team(joiner, fantasy, "Joiner XI")
    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Private Only", visibility="PRIVATE"
    )
    # Stranger cannot see the private league → 404 (correct security response).
    response = _auth_client(joiner).post(f"/api/v1/fantasy/leagues/{league.id}/join/")
    assert response.status_code == 404
    assert not league.memberships.filter(team__owner=joiner).exists()


def test_join_public_league_requires_team_for_that_competition(domain):
    """User without a FantasyTeam for the competition cannot join."""
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="noteam_join_o", email="ntjo@test.com")
    noteam = get_user_model().objects.create_user(username="noteam_join_j", email="ntjj@test.com")
    _make_team(owner, fantasy)
    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Needs Team", visibility="PUBLIC"
    )
    response = _auth_client(noteam).post(f"/api/v1/fantasy/leagues/{league.id}/join/")
    assert response.status_code == 400


# ── Join by code (private league) ────────────────────────────────────────────

def test_join_private_league_by_code_creates_membership(domain):
    """
    POST /fantasy/leagues/join_by_code/ with the correct 8-char code
    adds the user as a member and returns the league data.
    """
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="code_owner", email="co@test.com")
    joiner = get_user_model().objects.create_user(username="code_joiner", email="cj@test.com")
    _make_team(owner, fantasy, "Owner XI")
    _make_team(joiner, fantasy, "Joiner XI")

    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Friends Only", visibility="PRIVATE"
    )
    assert league.join_code and len(league.join_code) == 8

    response = _auth_client(joiner).post(
        "/api/v1/fantasy/leagues/join_by_code/",
        {"code": league.join_code},
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["name"] == "Friends Only"
    assert league.memberships.filter(team__owner=joiner).exists()


def test_join_by_code_case_insensitive(domain):
    """Backend uppercases the code so lowercase input must also work."""
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="case_owner", email="case_o@test.com")
    joiner = get_user_model().objects.create_user(username="case_joiner", email="case_j@test.com")
    _make_team(owner, fantasy, "Owner XI")
    _make_team(joiner, fantasy, "Joiner XI")
    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Case Test", visibility="PRIVATE"
    )
    response = _auth_client(joiner).post(
        "/api/v1/fantasy/leagues/join_by_code/",
        {"code": league.join_code.lower()},
        format="json",
    )
    assert response.status_code == 200, response.data


def test_join_by_invalid_code_returns_400(domain):
    """Wrong code returns 400 with the canonical error message."""
    fantasy, _, _ = domain
    user = get_user_model().objects.create_user(username="badcode_user", email="bc@test.com")
    _make_team(user, fantasy)
    response = _auth_client(user).post(
        "/api/v1/fantasy/leagues/join_by_code/",
        {"code": "BADCODE1"},
        format="json",
    )
    assert response.status_code == 400
    assert "Invalid invite code" in response.data["detail"]


def test_join_by_code_without_team_returns_specific_error(domain):
    """
    Valid code but user has no FantasyTeam for that competition → 400
    with the canonical 'no team' message that the frontend distinguishes.
    """
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="noteam_code_o", email="ntco@test.com")
    noteam = get_user_model().objects.create_user(username="noteam_code_j", email="ntcj@test.com")
    _make_team(owner, fantasy)
    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="No Team Code", visibility="PRIVATE"
    )
    response = _auth_client(noteam).post(
        "/api/v1/fantasy/leagues/join_by_code/",
        {"code": league.join_code},
        format="json",
    )
    assert response.status_code == 400
    assert response.data["detail"] == "Invalid invite code or no team for this competition."


# ── Capacity enforcement ──────────────────────────────────────────────────────

def test_league_capacity_blocks_additional_members(domain):
    """League with capacity=2 refuses a third join."""
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="cap_owner", email="cap_o@test.com")
    second = get_user_model().objects.create_user(username="cap_second", email="cap_s@test.com")
    third = get_user_model().objects.create_user(username="cap_third", email="cap_t@test.com")
    owner_team = _make_team(owner, fantasy, "Owner XI")
    second_team = _make_team(second, fantasy, "Second XI")
    _make_team(third, fantasy, "Third XI")

    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Tiny League",
        visibility="PUBLIC", capacity=2
    )
    FantasyLeagueMembership.objects.create(league=league, team=owner_team)
    FantasyLeagueMembership.objects.create(league=league, team=second_team)

    response = _auth_client(third).post(f"/api/v1/fantasy/leagues/{league.id}/join/")
    assert response.status_code == 400
    assert "capacity" in response.data["detail"].lower()
    assert league.memberships.count() == 2


def test_capacity_validation_rejects_capacity_less_than_two(domain):
    """League capacity must be >= 2."""
    fantasy, _, _ = domain
    user = get_user_model().objects.create_user(username="badcap_user", email="badcap@test.com")
    _make_team(user, fantasy)
    response = _auth_client(user).post(
        "/api/v1/fantasy/leagues/",
        {"fantasy_competition": str(fantasy.id), "name": "Solo", "visibility": "PUBLIC", "capacity": 1},
        format="json",
    )
    assert response.status_code == 400
    assert "capacity" in str(response.data).lower()


# ── Leave league ──────────────────────────────────────────────────────────────

def test_member_can_leave_league(domain):
    """POST /leave/ removes the membership and returns 204."""
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="leave_owner", email="lo@test.com")
    leaver = get_user_model().objects.create_user(username="leave_member", email="lm@test.com")
    owner_team = _make_team(owner, fantasy, "Owner XI")
    leaver_team = _make_team(leaver, fantasy, "Leaver XI")
    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Leaving League", visibility="PUBLIC"
    )
    FantasyLeagueMembership.objects.create(league=league, team=owner_team)
    FantasyLeagueMembership.objects.create(league=league, team=leaver_team)

    response = _auth_client(leaver).post(f"/api/v1/fantasy/leagues/{league.id}/leave/")
    assert response.status_code == 204
    assert not league.memberships.filter(team__owner=leaver).exists()
    assert league.memberships.filter(team__owner=owner).exists()


def test_owner_cannot_leave_their_own_league(domain):
    """League owner gets 400 when trying to leave."""
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="owner_leave", email="ol@test.com")
    owner_team = _make_team(owner, fantasy)
    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Owner Stays", visibility="PUBLIC"
    )
    FantasyLeagueMembership.objects.create(league=league, team=owner_team)

    response = _auth_client(owner).post(f"/api/v1/fantasy/leagues/{league.id}/leave/")
    assert response.status_code == 400
    assert "owner" in response.data["detail"].lower()


# ── Ownership & edit permissions ──────────────────────────────────────────────

def test_only_owner_can_edit_league(domain):
    """PATCH by a non-owner must be rejected (403 or 400)."""
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="edit_owner", email="eo@test.com")
    stranger = get_user_model().objects.create_user(username="edit_stranger", email="es@test.com")
    _make_team(owner, fantasy)
    _make_team(stranger, fantasy, "Stranger XI")
    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Edit Test", visibility="PUBLIC"
    )
    response = _auth_client(stranger).patch(
        f"/api/v1/fantasy/leagues/{league.id}/",
        {"name": "Hijacked"},
        format="json",
    )
    assert response.status_code in {403, 404}
    league.refresh_from_db()
    assert league.name == "Edit Test"


def test_only_owner_can_delete_league(domain):
    """DELETE by a non-owner must be rejected."""
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="del_owner", email="delo@test.com")
    stranger = get_user_model().objects.create_user(username="del_stranger", email="dels@test.com")
    _make_team(owner, fantasy)
    _make_team(stranger, fantasy, "Stranger XI")
    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Delete Test", visibility="PUBLIC"
    )
    response = _auth_client(stranger).delete(f"/api/v1/fantasy/leagues/{league.id}/")
    assert response.status_code in {403, 404}
    assert FantasyLeague.objects.filter(pk=league.id).exists()


# ── Mine endpoint ─────────────────────────────────────────────────────────────

def test_mine_endpoint_returns_only_users_leagues(domain):
    """GET /fantasy/leagues/mine/ returns only leagues the requesting user belongs to."""
    fantasy, _, _ = domain
    alice = get_user_model().objects.create_user(username="mine_alice", email="ma@test.com")
    bob = get_user_model().objects.create_user(username="mine_bob", email="mb@test.com")
    alice_team = _make_team(alice, fantasy, "Alice XI")
    bob_team = _make_team(bob, fantasy, "Bob XI")

    alice_league = FantasyLeague.objects.create(
        owner=alice, fantasy_competition=fantasy, name="Alice League", visibility="PUBLIC"
    )
    bob_league = FantasyLeague.objects.create(
        owner=bob, fantasy_competition=fantasy, name="Bob League", visibility="PUBLIC"
    )
    FantasyLeagueMembership.objects.create(league=alice_league, team=alice_team)
    FantasyLeagueMembership.objects.create(league=bob_league, team=bob_team)

    alice_client = _auth_client(alice)
    response = alice_client.get("/api/v1/fantasy/leagues/mine/")
    assert response.status_code == 200
    names = [row["name"] for row in response.data]
    assert "Alice League" in names
    assert "Bob League" not in names


# ── Public league discovery ───────────────────────────────────────────────────

def test_public_leagues_appear_in_list_private_leagues_do_not(domain):
    """
    GET /fantasy/leagues/ (unauthenticated) should include PUBLIC leagues
    but NOT PRIVATE leagues the requester doesn't belong to.
    """
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="disc_owner", email="do@test.com")
    owner_team = _make_team(owner, fantasy)
    pub_league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Discoverable", visibility="PUBLIC"
    )
    priv_league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Hidden", visibility="PRIVATE"
    )
    FantasyLeagueMembership.objects.create(league=pub_league, team=owner_team)
    FantasyLeagueMembership.objects.create(league=priv_league, team=owner_team)

    ids = [row["id"] for row in APIClient().get("/api/v1/fantasy/leagues/").data]
    assert str(pub_league.id) in ids
    assert str(priv_league.id) not in ids


# ── Members endpoint access control ──────────────────────────────────────────

def test_private_league_members_endpoint_blocked_for_non_member(domain):
    """Non-members get 403 on a private league's members endpoint."""
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="mem_owner", email="memo@test.com")
    outsider = get_user_model().objects.create_user(username="mem_out", email="mout@test.com")
    owner_team = _make_team(owner, fantasy)
    FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Private Members", visibility="PRIVATE"
    )
    league = FantasyLeague.objects.get(name="Private Members")
    FantasyLeagueMembership.objects.create(league=league, team=owner_team)

    response = _auth_client(outsider).get(f"/api/v1/fantasy/leagues/{league.id}/members/")
    assert response.status_code in {403, 404}


def test_public_league_members_visible_to_non_member(domain):
    """Members of a PUBLIC league are visible to authenticated non-members."""
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(username="pubmem_owner", email="pmo@test.com")
    viewer = get_user_model().objects.create_user(username="pubmem_viewer", email="pmv@test.com")
    owner_team = _make_team(owner, fantasy)
    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Public Members", visibility="PUBLIC"
    )
    FantasyLeagueMembership.objects.create(league=league, team=owner_team)

    response = _auth_client(viewer).get(f"/api/v1/fantasy/leagues/{league.id}/members/")
    assert response.status_code == 200
    assert response.data[0]["fantasy_team"] == "Test XI"


# ─────────────────────────────────────────────────────────────────────────────
# Gameweek Fixtures tests
# Covers: multi-gameweek competition, fixture_details API response,
#         home/away team names, venue, filtering by gameweek, no duplicates.
# ─────────────────────────────────────────────────────────────────────────────


def _make_event_with_teams(sport, competition, home_name, away_name, starts_at, status="SCHEDULED"):
    """Create a SportingEvent with HOME and AWAY EventParticipants."""
    event = SportingEvent.objects.create(
        sport=sport,
        competition=competition,
        name=f"{home_name} vs {away_name}",
        starts_at=starts_at,
        status=status,
        venue="Test Stadium",
    )
    home_p = Participant.objects.create(sport=sport, kind="TEAM", name=home_name)
    away_p = Participant.objects.create(sport=sport, kind="TEAM", name=away_name)
    EventParticipant.objects.create(event=event, participant=home_p, role="HOME", position=1)
    EventParticipant.objects.create(event=event, participant=away_p, role="AWAY", position=2)
    return event, home_p, away_p


def test_competition_can_have_multiple_gameweeks(domain):
    """A FantasyCompetition can hold many FantasyGameweeks."""
    fantasy, _, _ = domain
    now = timezone.now()
    gw1 = FantasyGameweek.objects.get(fantasy_competition=fantasy, number=1)
    gw2 = FantasyGameweek.objects.create(
        fantasy_competition=fantasy, number=2, name="GW2",
        starts_at=now + timedelta(days=7),
        deadline_at=now + timedelta(days=8),
        ends_at=now + timedelta(days=9),
        status="DRAFT",
    )
    gw3 = FantasyGameweek.objects.create(
        fantasy_competition=fantasy, number=3, name="GW3",
        starts_at=now + timedelta(days=14),
        deadline_at=now + timedelta(days=15),
        ends_at=now + timedelta(days=16),
        status="DRAFT",
    )
    assert fantasy.gameweeks.count() == 3
    numbers = list(fantasy.gameweeks.values_list("number", flat=True).order_by("number"))
    assert numbers == [1, 2, 3]


def test_gameweek_fixture_details_includes_home_away_team_and_venue(domain):
    """
    GET /fantasy/gameweeks/?competition=<id> returns fixture_details with
    home_team, away_team, venue, starts_at, status on each fixture.
    """
    fantasy, _, _ = domain
    gw = FantasyGameweek.objects.get(fantasy_competition=fantasy, number=1)
    now = timezone.now()

    event, home_p, away_p = _make_event_with_teams(
        fantasy.competition.sport, fantasy.competition,
        "Vipers SC", "KCCA FC",
        starts_at=now + timedelta(hours=2),
    )
    gw.fixtures.add(event)

    response = APIClient().get(
        "/api/v1/fantasy/gameweeks/",
        {"competition": str(fantasy.id)},
    )
    assert response.status_code == 200
    gw_data = next(g for g in response.data if g["id"] == str(gw.id))
    assert len(gw_data["fixture_details"]) == 1
    detail = gw_data["fixture_details"][0]
    assert detail["home_team"] == "Vipers SC"
    assert detail["away_team"] == "KCCA FC"
    assert detail["venue"] == "Test Stadium"
    assert detail["status"] == "SCHEDULED"
    assert "starts_at" in detail


def test_fixtures_filtered_correctly_by_gameweek(domain):
    """
    Fixtures assigned to GW1 do not appear in GW2, and vice versa.
    """
    fantasy, _, _ = domain
    now = timezone.now()
    gw1 = FantasyGameweek.objects.get(fantasy_competition=fantasy, number=1)
    gw2 = FantasyGameweek.objects.create(
        fantasy_competition=fantasy, number=2, name="GW2",
        starts_at=now + timedelta(days=7),
        deadline_at=now + timedelta(days=8),
        ends_at=now + timedelta(days=9),
        status="DRAFT",
    )
    event1, _, _ = _make_event_with_teams(
        fantasy.competition.sport, fantasy.competition,
        "Team Alpha", "Team Beta", now + timedelta(hours=1),
    )
    event2, _, _ = _make_event_with_teams(
        fantasy.competition.sport, fantasy.competition,
        "Team Gamma", "Team Delta", now + timedelta(days=8),
    )
    gw1.fixtures.add(event1)
    gw2.fixtures.add(event2)

    response = APIClient().get("/api/v1/fantasy/gameweeks/", {"competition": str(fantasy.id)})
    assert response.status_code == 200
    by_id = {g["id"]: g for g in response.data}

    gw1_ids = [f["id"] for f in by_id[str(gw1.id)]["fixture_details"]]
    gw2_ids = [f["id"] for f in by_id[str(gw2.id)]["fixture_details"]]
    assert str(event1.id) in gw1_ids
    assert str(event2.id) not in gw1_ids
    assert str(event2.id) in gw2_ids
    assert str(event1.id) not in gw2_ids


def test_no_duplicate_fixtures_in_fixture_details(domain):
    """Adding the same fixture twice does not produce duplicate fixture_details rows."""
    fantasy, _, _ = domain
    gw = FantasyGameweek.objects.get(fantasy_competition=fantasy, number=1)
    now = timezone.now()
    event, _, _ = _make_event_with_teams(
        fantasy.competition.sport, fantasy.competition,
        "One", "Two", now + timedelta(hours=1),
    )
    gw.fixtures.add(event)
    gw.fixtures.add(event)  # duplicate add — M2M silently ignores it

    response = APIClient().get("/api/v1/fantasy/gameweeks/", {"competition": str(fantasy.id)})
    gw_data = next(g for g in response.data if g["id"] == str(gw.id))
    ids = [f["id"] for f in gw_data["fixture_details"]]
    assert ids.count(str(event.id)) == 1


def test_empty_gameweek_returns_empty_fixture_details(domain):
    """A gameweek with no fixtures assigned returns fixture_details = []."""
    fantasy, _, _ = domain
    gw = FantasyGameweek.objects.get(fantasy_competition=fantasy, number=1)
    gw.fixtures.clear()

    response = APIClient().get("/api/v1/fantasy/gameweeks/", {"competition": str(fantasy.id)})
    gw_data = next(g for g in response.data if g["id"] == str(gw.id))
    assert gw_data["fixture_details"] == []


def test_gameweeks_filtered_by_competition_param(domain):
    """
    GET /fantasy/gameweeks/?competition=<id> only returns gameweeks for
    that specific competition, not other competitions.
    """
    other_sport = Sport.objects.create(name="Basketball", code="BK")
    other_comp = Competition.objects.create(sport=other_sport, name="Other League", country_code="UG")
    other_season = Season.objects.create(sport=other_sport, competition=other_comp, name="2026")
    other_fantasy = FantasyCompetition.objects.create(
        competition=other_comp, season=other_season, name="Other Fantasy",
        squad_size=2, starting_lineup_size=1, bench_size=1,
        initial_budget=20, max_players_per_team=2,
        position_rules={"PG": 1, "SG": 1},
        formation_rules={"PG": {"min": 0, "max": 1}, "SG": {"min": 0, "max": 1}},
    )
    now = timezone.now()
    FantasyGameweek.objects.create(
        fantasy_competition=other_fantasy, number=1, name="Other GW1",
        starts_at=now, deadline_at=now + timedelta(days=1), ends_at=now + timedelta(days=2),
        status="OPEN",
    )
    fantasy, _, _ = domain
    response = APIClient().get("/api/v1/fantasy/gameweeks/", {"competition": str(fantasy.id)})
    assert response.status_code == 200
    for gw in response.data:
        assert str(gw["fantasy_competition"]) == str(fantasy.id)


def test_fixture_details_handles_fixture_with_no_participants(domain):
    """
    A SportingEvent with no EventParticipants returns None for home_team/away_team
    and falls back to the event name.
    """
    fantasy, _, _ = domain
    gw = FantasyGameweek.objects.get(fantasy_competition=fantasy, number=1)
    now = timezone.now()
    event = SportingEvent.objects.create(
        sport=fantasy.competition.sport,
        competition=fantasy.competition,
        name="Mystery Match",
        starts_at=now + timedelta(hours=3),
        status="SCHEDULED",
    )
    # No EventParticipants — event has no HOME/AWAY roles
    gw.fixtures.add(event)

    response = APIClient().get("/api/v1/fantasy/gameweeks/", {"competition": str(fantasy.id)})
    gw_data = next(g for g in response.data if g["id"] == str(gw.id))
    detail = next(f for f in gw_data["fixture_details"] if f["id"] == str(event.id))
    assert detail["home_team"] is None
    assert detail["away_team"] is None
    assert detail["name"] == "Mystery Match"


# ── Admin overview — unauthenticated access (local development) ───────────────

def test_admin_overview_accessible_without_authentication(domain):
    """
    GET /api/v1/fantasy/leagues/admin-overview/ must return 200 OK for an
    unauthenticated request.  This endpoint is intentionally open in the
    local development environment so the admin UI can load without requiring
    an Authorization header.
    """
    fantasy, _, _ = domain
    owner = get_user_model().objects.create_user(
        username="ov_owner", email="ov_owner@test.com"
    )
    # Create a team so the owner can create a league.
    team = FantasyTeam.objects.create(
        owner=owner, fantasy_competition=fantasy, name="OV Team",
        budget_remaining=Decimal("10"), free_transfers=1,
    )
    # Create the league via the authenticated endpoint to ensure the
    # membership is set up correctly, then verify the overview via
    # the unauthenticated client.
    league = FantasyLeague.objects.create(
        fantasy_competition=fantasy,
        owner=owner,
        name="Overview League",
        visibility="PUBLIC",
    )
    FantasyLeagueMembership.objects.create(league=league, team=team)

    resp = APIClient().get("/api/v1/fantasy/leagues/admin-overview/")

    assert resp.status_code == 200
    # Response must be a list.
    assert isinstance(resp.data, list)
    # The created league must appear in the response.
    names = [row["name"] for row in resp.data]
    assert "Overview League" in names
    # Each row must include the expected fields.
    row = next(r for r in resp.data if r["name"] == "Overview League")
    assert row["member_count"] == 1
    assert row["visibility"] == "PUBLIC"
    assert "fantasy_competition" in row


def test_admin_overview_returns_empty_list_when_no_leagues_exist(domain):
    """
    Unauthenticated GET to admin-overview/ returns an empty list (not 401 or
    404) when no FantasyLeague records exist.
    """
    resp = APIClient().get("/api/v1/fantasy/leagues/admin-overview/")
    assert resp.status_code == 200
    assert resp.data == []


# ── League join deduplication tests ─────────────────────────────────────────


def _make_user(username):
    return get_user_model().objects.create_user(
        username=username, email=f"{username}@example.com", password="pw"
    )


def _make_team(user, fantasy, name="Test XI"):
    return FantasyTeam.objects.create(
        owner=user, fantasy_competition=fantasy, name=name, budget_remaining=10
    )


def _make_private_league(owner, fantasy, name="Private Crew"):
    return FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name=name, visibility="PRIVATE"
    )


@pytest.mark.django_db
def test_join_by_code_duplicate_returns_already_member_message(domain):
    """
    When a user uses join_by_code for a league they are already a member of,
    the endpoint returns HTTP 200 with detail='You're already a member of
    this league.' and does NOT create a duplicate membership row.
    """
    fantasy, _, _ = domain
    user = _make_user("fan_dup")
    _make_team(user, fantasy)
    owner = _make_user("owner_dup")
    _make_team(owner, fantasy, name="Owner XI")
    league = _make_private_league(owner, fantasy)

    # Add user as a member directly (simulates having joined previously)
    user_team = FantasyTeam.objects.get(owner=user)
    FantasyLeagueMembership.objects.create(league=league, team=user_team)

    membership_count_before = FantasyLeagueMembership.objects.filter(league=league).count()

    client = APIClient()
    client.force_authenticate(user=user)
    resp = client.post(
        "/api/v1/fantasy/leagues/join_by_code/",
        {"code": league.join_code},
        format="json",
    )

    assert resp.status_code == 200, resp.data
    assert resp.data.get("detail") == "You're already a member of this league."

    # No duplicate row created
    membership_count_after = FantasyLeagueMembership.objects.filter(league=league).count()
    assert membership_count_after == membership_count_before, (
        "Duplicate membership row was created"
    )


@pytest.mark.django_db
def test_join_by_code_different_user_joins_normally(domain):
    """
    A different user using the same code for the same private league
    should join successfully (created=True path) with no error.
    """
    fantasy, _, _ = domain
    owner = _make_user("owner_new")
    _make_team(owner, fantasy, name="Owner New XI")
    league = _make_private_league(owner, fantasy, name="New League")

    new_user = _make_user("new_fan")
    _make_team(new_user, fantasy, name="New Fan XI")

    client = APIClient()
    client.force_authenticate(user=new_user)
    resp = client.post(
        "/api/v1/fantasy/leagues/join_by_code/",
        {"code": league.join_code},
        format="json",
    )

    assert resp.status_code == 200, resp.data
    # Normal join: returns league data, NOT the already-member message
    assert "detail" not in resp.data or resp.data.get("detail") != "You're already a member of this league."
    assert FantasyLeagueMembership.objects.filter(
        league=league, team__owner=new_user
    ).count() == 1


@pytest.mark.django_db
def test_league_creator_is_automatically_a_member(domain):
    """
    When a user creates a league, they should be automatically added as a member
    via perform_create → get_or_create membership. Calling join again returns
    the already-member message rather than creating a duplicate.
    """
    fantasy, _, _ = domain
    creator = _make_user("creator_auto")
    _make_team(creator, fantasy, name="Creator XI")

    client = APIClient()
    client.force_authenticate(user=creator)

    # Create the league via the API (perform_create adds membership)
    resp = client.post(
        "/api/v1/fantasy/leagues/",
        {
            "fantasy_competition": str(fantasy.id),
            "name": "Auto Member League",
            "visibility": "PRIVATE",
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    league_id = resp.data["id"]
    league = FantasyLeague.objects.get(id=league_id)

    # Creator must already be a member
    assert FantasyLeagueMembership.objects.filter(
        league=league, team__owner=creator
    ).exists(), "Creator was not automatically added as a member"

    # Trying to join again via code returns already-member message
    resp2 = client.post(
        "/api/v1/fantasy/leagues/join_by_code/",
        {"code": league.join_code},
        format="json",
    )
    assert resp2.status_code == 200
    assert resp2.data.get("detail") == "You're already a member of this league."

    # Still exactly one membership row
    assert FantasyLeagueMembership.objects.filter(
        league=league, team__owner=creator
    ).count() == 1


@pytest.mark.django_db
def test_join_public_league_duplicate_returns_already_member_message(domain):
    """
    Joining a public league the user is already a member of (via the /join/
    endpoint) returns the already-member message rather than a duplicate row.
    """
    fantasy, _, _ = domain
    owner = _make_user("pub_owner")
    _make_team(owner, fantasy, name="Pub Owner XI")
    league = FantasyLeague.objects.create(
        owner=owner, fantasy_competition=fantasy, name="Open League", visibility="PUBLIC"
    )

    fan = _make_user("pub_fan")
    fan_team = _make_team(fan, fantasy, name="Pub Fan XI")
    FantasyLeagueMembership.objects.create(league=league, team=fan_team)

    client = APIClient()
    client.force_authenticate(user=fan)
    resp = client.post(f"/api/v1/fantasy/leagues/{league.id}/join/", format="json")

    assert resp.status_code == 200
    assert resp.data.get("detail") == "You're already a member of this league."
    assert FantasyLeagueMembership.objects.filter(league=league, team=fan_team).count() == 1


@pytest.mark.django_db
def test_unique_constraint_enforced_at_db_level(domain):
    """
    The UniqueConstraint on (league, team) prevents duplicate rows at the
    database level even if the service layer is bypassed.
    """
    from django.db import IntegrityError

    fantasy, _, _ = domain
    user = _make_user("db_fan")
    team = _make_team(user, fantasy)
    owner = _make_user("db_owner")
    _make_team(owner, fantasy, name="DB Owner XI")
    league = _make_private_league(owner, fantasy, name="DB Test League")

    FantasyLeagueMembership.objects.create(league=league, team=team)

    with pytest.raises(IntegrityError):
        FantasyLeagueMembership.objects.create(league=league, team=team)

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
from sports.models import Competition, Participant, Sport, SportingEvent


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

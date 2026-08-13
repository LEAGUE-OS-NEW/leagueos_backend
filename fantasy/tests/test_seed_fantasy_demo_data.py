from collections import Counter
from itertools import combinations

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from discovery.models import PlayerProfile, Season
from fantasy.models import FantasyCompetition, FantasyGameweek, FantasyPlayer, FantasyScoringRule
from fantasy.services import validate_selections
from profiles.models import Club
from sports.models import Competition, Participant, Sport, SportingEvent

SPORTS = (("Football", "football"), ("Rugby", "rugby"), ("Basketball", "basketball"))


@pytest.fixture
def canonical_demo_inputs(db):
    for name, code in SPORTS:
        sport = Sport.objects.create(name=name, code=code)
        competition = Competition.objects.create(sport=sport, name=f"{name} League")
        teams = [
            Participant.objects.create(
                sport=sport,
                kind=Participant.Kind.TEAM,
                name=f"{name} Team {index}",
                short_name=f"{name[0]}{index}",
            )
            for index in range(1, 7)
        ]
        SportingEvent.objects.create(
            sport=sport,
            competition=competition,
            name=f"{teams[0].name} v {teams[1].name}",
            starts_at=timezone.now(),
            status=SportingEvent.Status.SCHEDULED,
        )


def seed():
    call_command("seed_fantasy_demo_data", "--confirm")


def counts():
    return {
        "seasons": Season.objects.count(),
        "clubs": Club.objects.count(),
        "participants": Participant.objects.count(),
        "profiles": PlayerProfile.objects.count(),
        "competitions": FantasyCompetition.objects.count(),
        "players": FantasyPlayer.objects.count(),
        "gameweeks": FantasyGameweek.objects.count(),
        "rules": FantasyScoringRule.objects.count(),
    }


def selections_for(competition, *, expensive):
    by_position = {
        position: list(
            competition.player_pool.filter(position=position).select_related(
                "player__player_profile__club"
            )
        )
        for position in competition.position_rules
    }
    ordered_positions = list(competition.position_rules.items())
    candidates = []

    def choose(position_index, selected, club_counts):
        if position_index == len(ordered_positions):
            candidates.append(list(selected))
            return True
        position, required = ordered_positions[position_index]
        groups = combinations(by_position[position], int(required))
        groups = sorted(
            groups, key=lambda group: sum(player.price for player in group), reverse=expensive
        )
        for group in groups:
            additions = Counter(str(player.real_team.pk) for player in group)
            if any(
                club_counts[club_id] + amount > competition.max_players_per_team
                for club_id, amount in additions.items()
            ):
                continue
            if choose(position_index + 1, selected + list(group), club_counts + additions):
                return True
        return False

    assert choose(0, [], Counter())
    players = candidates[0]
    return [
        {
            "fantasy_player": player,
            "is_starter": index < competition.starting_lineup_size,
            "bench_order": (
                None
                if index < competition.starting_lineup_size
                else index - competition.starting_lineup_size + 1
            ),
            "is_captain": index == 0,
            "is_vice_captain": index == 1,
        }
        for index, player in enumerate(players)
    ]


@override_settings(DEBUG=False)
def test_seed_refuses_non_debug_even_with_confirmation(db):
    with pytest.raises(CommandError, match="DEBUG is False"):
        seed()


@override_settings(DEBUG=True)
def test_reseed_preserves_finalized_gameweek_and_row_counts(canonical_demo_inputs):
    seed()
    initial_counts = counts()
    gameweek = FantasyGameweek.objects.get(fantasy_competition__competition__sport__slug="football")
    gameweek.status = FantasyGameweek.Status.FINALIZED
    gameweek.save(update_fields=["status"])

    seed()

    gameweek.refresh_from_db()
    assert gameweek.status == FantasyGameweek.Status.FINALIZED
    assert counts() == initial_counts


@override_settings(DEBUG=True)
def test_slug_collision_does_not_mutate_unrelated_club(canonical_demo_inputs):
    team = Participant.objects.filter(sport__slug="football", kind=Participant.Kind.TEAM).first()
    unrelated = Club.objects.create(name="Unrelated Canonical Club", slug=team.slug)
    seed()
    unrelated.refresh_from_db()
    assert unrelated.name == "Unrelated Canonical Club"
    assert unrelated.sport_id is None
    assert Club.objects.filter(slug=f"fantasy-demo-football-{team.slug}").exists()


@override_settings(DEBUG=True)
@pytest.mark.parametrize("sport_slug", ["football", "rugby", "basketball"])
def test_demo_prices_support_legal_and_over_budget_squads(canonical_demo_inputs, sport_slug):
    seed()
    competition = FantasyCompetition.objects.get(competition__sport__slug=sport_slug)
    legal = selections_for(competition, expensive=False)
    over_budget = selections_for(competition, expensive=True)

    validate_selections(competition, legal)
    assert sum(item["fantasy_player"].price for item in legal) <= competition.initial_budget
    assert sum(item["fantasy_player"].price for item in over_budget) > competition.initial_budget
    with pytest.raises(ValidationError, match="exceeds the available budget"):
        validate_selections(competition, over_budget)

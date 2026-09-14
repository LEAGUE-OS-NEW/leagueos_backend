"""
Phase 1 scoring engine tests — Fantasy Football MVP.

Covers every approved rule type and edge case from:
  FANTASY_MVP_SCORING_REVIEW.md
  FANTASY_SCORING_FINAL_VALIDATION.md

These tests are written BEFORE implementation and are expected to fail
until the model, serializer, and services changes are applied.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from discovery.models import MatchCentre, MatchLineup, MatchPlayerStatistic, Season
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
from profiles.models import Club
from sports.models import Competition, Participant, Sport, SportingEvent

User = get_user_model()

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine_domain(db):
    """
    Full Football domain with GK + DEF + MID + FWD positions.
    Returns a dict with all objects needed across test classes.
    """
    sport = Sport.objects.create(name="Football", slug="football", code="FB")
    comp = Competition.objects.create(sport=sport, name="Engine League", country_code="UG")
    season = Season.objects.create(sport=sport, competition=comp, name="2026")
    fantasy = FantasyCompetition.objects.create(
        competition=comp,
        season=season,
        name="Engine Fantasy",
        registration_state="OPEN",
        squad_size=4,
        starting_lineup_size=4,
        bench_size=0,
        initial_budget=Decimal("100"),
        max_players_per_team=4,
        captain_multiplier=Decimal("2"),
        vice_captain_fallback=True,
        position_rules={"GK": 1, "DEF": 1, "MID": 1, "FWD": 1},
        formation_rules={
            "GK":  {"min": 0, "max": 1},
            "DEF": {"min": 0, "max": 1},
            "MID": {"min": 0, "max": 1},
            "FWD": {"min": 0, "max": 1},
        },
        transfer_penalty=4,
    )
    club = Club.objects.create(name="Engine Club")
    players = {}
    for pos in ("GK", "DEF", "MID", "FWD"):
        p = Participant.objects.create(sport=sport, kind="ATHLETE", name=f"Player_{pos}")
        fp = FantasyPlayer.objects.create(
            fantasy_competition=fantasy, player=p, position=pos, price=Decimal("10"),
        )
        players[pos] = fp

    now = timezone.now()
    fixture = SportingEvent.objects.create(
        sport=sport, competition=comp, name="Engine Match",
        starts_at=now - timedelta(hours=2), status="COMPLETED",
    )
    gameweek = FantasyGameweek.objects.create(
        fantasy_competition=fantasy, number=1, name="GW1",
        starts_at=now - timedelta(days=1),
        deadline_at=now + timedelta(hours=1),
        ends_at=now + timedelta(days=2),
        status="SCORING",
    )
    gameweek.fixtures.add(fixture)
    mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
    return {
        "sport": sport, "fantasy": fantasy, "players": players,
        "fixture": fixture, "gameweek": gameweek, "mc": mc,
    }


def _add_stat(mc, participant, stat_type, value):
    stat, _ = MatchPlayerStatistic.objects.update_or_create(
        match_centre=mc, participant=participant, stat_type=stat_type,
        defaults={"value": Decimal(str(value))},
    )
    return stat


def _rule(fantasy, stat_type, points, rule_type="PER_UNIT", conditions=None):
    return FantasyScoringRule.objects.create(
        fantasy_competition=fantasy,
        statistic_type=stat_type,
        points=Decimal(str(points)),
        rule_type=rule_type,
        conditions=conditions or {},
        enabled=True,
    )


def _make_team(fantasy, starters, captain_pos, vice_pos=None):
    """Create a team with all players from `starters` dict as starters."""
    user = User.objects.create_user(
        username=f"u_{id(starters)}", email=f"u_{id(starters)}@test.com"
    )
    team = FantasyTeam.objects.create(
        owner=user, fantasy_competition=fantasy, name="Test Team",
        budget_remaining=Decimal("0"),
    )
    for pos, fp in starters.items():
        FantasyTeamPlayer.objects.create(
            team=team, fantasy_player=fp, is_starter=True,
            is_captain=(pos == captain_pos),
            is_vice_captain=(pos == vice_pos) if vice_pos else False,
            bench_order=None, purchase_price=fp.price,
        )
    return team


# ---------------------------------------------------------------------------
# Part A — Rule type dispatch: apply_rule() via score_gameweek()
# ---------------------------------------------------------------------------

class TestRuleTypes:
    """Each rule type fires correctly and produces the expected points."""

    def test_per_unit_rule(self, engine_domain):
        """PER_UNIT: value × points. GOALS=2, rule=5 → 10."""
        d = engine_domain
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 2)
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("10")

    def test_flat_rule_fires_when_value_positive(self, engine_domain):
        """FLAT: fixed points when value > 0. PENALTIES_SAVED=1, rule=5 → 5."""
        d = engine_domain
        fp = d["players"]["GK"]
        _add_stat(d["mc"], fp.player, "PENALTIES_SAVED", 1)
        _rule(d["fantasy"], "PENALTIES_SAVED", 5, "FLAT")
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("5")

    def test_flat_rule_zero_value_gives_zero(self, engine_domain):
        """FLAT: value=0 → 0 points even though rule exists."""
        d = engine_domain
        fp = d["players"]["GK"]
        _add_stat(d["mc"], fp.player, "PENALTIES_SAVED", 0)
        _rule(d["fantasy"], "PENALTIES_SAVED", 5, "FLAT")
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("0")

    def test_per_n_rule(self, engine_domain):
        """PER_N: floor(value/n)×points. SAVES=6, n=3, pts=1 → 2."""
        d = engine_domain
        fp = d["players"]["GK"]
        _add_stat(d["mc"], fp.player, "SAVES", 6)
        _rule(d["fantasy"], "SAVES", 1, "PER_N", {"per_n": 3})
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("2")

    def test_bracket_rule_lower_band(self, engine_domain):
        """BRACKET: 1–59 min → 1 pt."""
        d = engine_domain
        fp = d["players"]["MID"]
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 45)
        _rule(d["fantasy"], "MINUTES_PLAYED", 1, "BRACKET", {"min": 1, "max": 59})
        _rule(d["fantasy"], "MINUTES_PLAYED", 2, "BRACKET", {"min": 60, "max": None})
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("1")

    def test_bracket_rule_upper_band(self, engine_domain):
        """BRACKET: 60+ min → 2 pts."""
        d = engine_domain
        fp = d["players"]["MID"]
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 60)
        _rule(d["fantasy"], "MINUTES_PLAYED", 1, "BRACKET", {"min": 1, "max": 59})
        _rule(d["fantasy"], "MINUTES_PLAYED", 2, "BRACKET", {"min": 60, "max": None})
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("2")

    def test_position_rule_dispatches_by_position(self, engine_domain):
        """POSITION: same rule, different player → different points."""
        d = engine_domain
        conditions = {"positions": {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}}
        _rule(d["fantasy"], "GOALS", 0, "POSITION", conditions)
        for pos, expected in [("GK", 10), ("DEF", 6), ("MID", 5), ("FWD", 4)]:
            _add_stat(d["mc"], d["players"][pos].player, "GOALS", 1)
        score_gameweek(d["gameweek"])
        for pos, expected in [("GK", 10), ("DEF", 6), ("MID", 5), ("FWD", 4)]:
            rec = FantasyPlayerGameweekPoints.objects.get(
                gameweek=d["gameweek"], fantasy_player=d["players"][pos]
            )
            assert rec.base_points == Decimal(str(expected)), (
                f"{pos} goal: expected {expected}, got {rec.base_points}"
            )


# ---------------------------------------------------------------------------
# Part B — Minutes played
# ---------------------------------------------------------------------------

class TestMinutesPlayed:
    def test_zero_minutes_gives_zero_points(self, engine_domain):
        """0 minutes → 0 appearance points. Neither bracket fires."""
        d = engine_domain
        fp = d["players"]["MID"]
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 0)
        _rule(d["fantasy"], "MINUTES_PLAYED", 1, "BRACKET", {"min": 1, "max": 59})
        _rule(d["fantasy"], "MINUTES_PLAYED", 2, "BRACKET", {"min": 60, "max": None})
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("0")

    def test_one_minute_gives_one_point(self, engine_domain):
        """1 minute → 1 pt (lower bracket)."""
        d = engine_domain
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 1)
        _rule(d["fantasy"], "MINUTES_PLAYED", 1, "BRACKET", {"min": 1, "max": 59})
        _rule(d["fantasy"], "MINUTES_PLAYED", 2, "BRACKET", {"min": 60, "max": None})
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("1")

    def test_59_minutes_gives_one_point(self, engine_domain):
        """59 minutes → still lower bracket → 1 pt."""
        d = engine_domain
        fp = d["players"]["DEF"]
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 59)
        _rule(d["fantasy"], "MINUTES_PLAYED", 1, "BRACKET", {"min": 1, "max": 59})
        _rule(d["fantasy"], "MINUTES_PLAYED", 2, "BRACKET", {"min": 60, "max": None})
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("1")

    def test_60_minutes_gives_two_points(self, engine_domain):
        """60 minutes → upper bracket → 2 pts."""
        d = engine_domain
        fp = d["players"]["GK"]
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 60)
        _rule(d["fantasy"], "MINUTES_PLAYED", 1, "BRACKET", {"min": 1, "max": 59})
        _rule(d["fantasy"], "MINUTES_PLAYED", 2, "BRACKET", {"min": 60, "max": None})
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("2")

    def test_90_minutes_gives_two_not_180(self, engine_domain):
        """90 minutes → 2 pts. Must NOT be 90 × 2 = 180 (old PER_UNIT bug)."""
        d = engine_domain
        fp = d["players"]["GK"]
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 90)
        _rule(d["fantasy"], "MINUTES_PLAYED", 1, "BRACKET", {"min": 1, "max": 59})
        _rule(d["fantasy"], "MINUTES_PLAYED", 2, "BRACKET", {"min": 60, "max": None})
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("2"), (
            f"90 minutes must give 2 pts, not {rec.base_points} (PER_UNIT multiplication bug)"
        )


# ---------------------------------------------------------------------------
# Part C — Position-based goals
# ---------------------------------------------------------------------------

class TestPositionGoals:
    """GK=10, DEF=6, MID=5, FWD=4 per goal."""

    def _setup_goal_rule(self, fantasy):
        return _rule(fantasy, "GOALS", 0, "POSITION",
                     {"positions": {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}})

    def test_gk_goal_scores_10(self, engine_domain):
        d = engine_domain
        self._setup_goal_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["GK"].player, "GOALS", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert rec.base_points == Decimal("10")

    def test_def_goal_scores_6(self, engine_domain):
        d = engine_domain
        self._setup_goal_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["DEF"].player, "GOALS", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["DEF"])
        assert rec.base_points == Decimal("6")

    def test_mid_goal_scores_5(self, engine_domain):
        d = engine_domain
        self._setup_goal_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["MID"].player, "GOALS", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["MID"])
        assert rec.base_points == Decimal("5")

    def test_fwd_goal_scores_4(self, engine_domain):
        d = engine_domain
        self._setup_goal_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["FWD"].player, "GOALS", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["FWD"])
        assert rec.base_points == Decimal("4")

    def test_fwd_hattrick_scores_12(self, engine_domain):
        d = engine_domain
        self._setup_goal_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["FWD"].player, "GOALS", 3)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["FWD"])
        assert rec.base_points == Decimal("12")

    def test_gk_hattrick_scores_30(self, engine_domain):
        d = engine_domain
        self._setup_goal_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["GK"].player, "GOALS", 3)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert rec.base_points == Decimal("30")


# ---------------------------------------------------------------------------
# Part D — Assists
# ---------------------------------------------------------------------------

class TestAssists:
    def test_one_assist_gives_3(self, engine_domain):
        d = engine_domain
        _rule(d["fantasy"], "ASSISTS", 3, "PER_UNIT")
        _add_stat(d["mc"], d["players"]["MID"].player, "ASSISTS", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["MID"])
        assert rec.base_points == Decimal("3")

    def test_two_assists_give_6(self, engine_domain):
        d = engine_domain
        _rule(d["fantasy"], "ASSISTS", 3, "PER_UNIT")
        _add_stat(d["mc"], d["players"]["MID"].player, "ASSISTS", 2)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["MID"])
        assert rec.base_points == Decimal("6")


# ---------------------------------------------------------------------------
# Part E — Saves (PER_N, n=3)
# ---------------------------------------------------------------------------

class TestSaves:
    def _saves_rule(self, fantasy):
        return _rule(fantasy, "SAVES", 1, "PER_N", {"per_n": 3})

    def test_0_saves_give_0(self, engine_domain):
        d = engine_domain
        self._saves_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["GK"].player, "SAVES", 0)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert rec.base_points == Decimal("0")

    def test_2_saves_give_0(self, engine_domain):
        d = engine_domain
        self._saves_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["GK"].player, "SAVES", 2)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert rec.base_points == Decimal("0")

    def test_3_saves_give_1(self, engine_domain):
        d = engine_domain
        self._saves_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["GK"].player, "SAVES", 3)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert rec.base_points == Decimal("1")

    def test_5_saves_give_1(self, engine_domain):
        d = engine_domain
        self._saves_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["GK"].player, "SAVES", 5)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert rec.base_points == Decimal("1")

    def test_6_saves_give_2(self, engine_domain):
        d = engine_domain
        self._saves_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["GK"].player, "SAVES", 6)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert rec.base_points == Decimal("2")

    def test_8_saves_give_2(self, engine_domain):
        d = engine_domain
        self._saves_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["GK"].player, "SAVES", 8)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert rec.base_points == Decimal("2")

    def test_9_saves_give_3(self, engine_domain):
        d = engine_domain
        self._saves_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["GK"].player, "SAVES", 9)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert rec.base_points == Decimal("3")


# ---------------------------------------------------------------------------
# Part F — Penalties
# ---------------------------------------------------------------------------

class TestPenalties:
    def test_penalty_saved_flat_5(self, engine_domain):
        """PENALTIES_SAVED=1, FLAT rule → +5."""
        d = engine_domain
        _rule(d["fantasy"], "PENALTIES_SAVED", 5, "FLAT")
        _add_stat(d["mc"], d["players"]["GK"].player, "PENALTIES_SAVED", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert rec.base_points == Decimal("5")

    def test_penalty_missed_neg_2(self, engine_domain):
        """PENALTIES_MISSED=1, PER_UNIT rule -2 → -2."""
        d = engine_domain
        _rule(d["fantasy"], "PENALTIES_MISSED", -2, "PER_UNIT")
        _add_stat(d["mc"], d["players"]["FWD"].player, "PENALTIES_MISSED", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["FWD"])
        assert rec.base_points == Decimal("-2")


# ---------------------------------------------------------------------------
# Part G — Goals conceded (PER_N, n=2, negative)
# ---------------------------------------------------------------------------

class TestGoalsConceded:
    def _gc_rule(self, fantasy):
        return _rule(fantasy, "GOALS_CONCEDED", -1, "PER_N", {"per_n": 2})

    def test_0_conceded_gives_0(self, engine_domain):
        d = engine_domain
        self._gc_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["GK"].player, "GOALS_CONCEDED", 0)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert rec.base_points == Decimal("0")

    def test_1_conceded_gives_0(self, engine_domain):
        d = engine_domain
        self._gc_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["GK"].player, "GOALS_CONCEDED", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert rec.base_points == Decimal("0")

    def test_2_conceded_gives_neg_1(self, engine_domain):
        d = engine_domain
        self._gc_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["GK"].player, "GOALS_CONCEDED", 2)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert rec.base_points == Decimal("-1")

    def test_3_conceded_gives_neg_1(self, engine_domain):
        d = engine_domain
        self._gc_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["GK"].player, "GOALS_CONCEDED", 3)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert rec.base_points == Decimal("-1")

    def test_4_conceded_gives_neg_2(self, engine_domain):
        d = engine_domain
        self._gc_rule(d["fantasy"])
        _add_stat(d["mc"], d["players"]["GK"].player, "GOALS_CONCEDED", 4)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert rec.base_points == Decimal("-2")

    def test_gc_rule_only_fires_for_players_with_the_stat(self, engine_domain):
        """FWD has no GOALS_CONCEDED stat → rule does not fire → 0 pts."""
        d = engine_domain
        self._gc_rule(d["fantasy"])
        # No GOALS_CONCEDED stat for FWD — stat simply isn't in the DB
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["FWD"])
        assert rec.base_points == Decimal("0")


# ---------------------------------------------------------------------------
# Part H — Cards
# ---------------------------------------------------------------------------

class TestCards:
    def test_yellow_card_neg_1(self, engine_domain):
        d = engine_domain
        _rule(d["fantasy"], "YELLOW_CARDS", -1, "PER_UNIT")
        _add_stat(d["mc"], d["players"]["MID"].player, "YELLOW_CARDS", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["MID"])
        assert rec.base_points == Decimal("-1")

    def test_red_card_neg_3(self, engine_domain):
        d = engine_domain
        _rule(d["fantasy"], "RED_CARDS", -3, "PER_UNIT")
        _add_stat(d["mc"], d["players"]["DEF"].player, "RED_CARDS", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["DEF"])
        assert rec.base_points == Decimal("-3")

    def test_second_yellow_convention_yellow_plus_red(self, engine_domain):
        """
        Approved convention: second yellow = YELLOW_CARDS=1 + RED_CARDS=1.
        Total penalty: -1 + -3 = -4.
        """
        d = engine_domain
        _rule(d["fantasy"], "YELLOW_CARDS", -1, "PER_UNIT")
        _rule(d["fantasy"], "RED_CARDS", -3, "PER_UNIT")
        _add_stat(d["mc"], d["players"]["MID"].player, "YELLOW_CARDS", 1)
        _add_stat(d["mc"], d["players"]["MID"].player, "RED_CARDS", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["MID"])
        assert rec.base_points == Decimal("-4")


# ---------------------------------------------------------------------------
# Part I — Own goals
# ---------------------------------------------------------------------------

class TestOwnGoals:
    def test_own_goal_neg_2(self, engine_domain):
        d = engine_domain
        _rule(d["fantasy"], "OWN_GOALS", -2, "PER_UNIT")
        _add_stat(d["mc"], d["players"]["DEF"].player, "OWN_GOALS", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["DEF"])
        assert rec.base_points == Decimal("-2")

    def test_two_own_goals_neg_4(self, engine_domain):
        d = engine_domain
        _rule(d["fantasy"], "OWN_GOALS", -2, "PER_UNIT")
        _add_stat(d["mc"], d["players"]["DEF"].player, "OWN_GOALS", 2)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["DEF"])
        assert rec.base_points == Decimal("-4")


# ---------------------------------------------------------------------------
# Part J — Clean sheets with 60-minute gate
# ---------------------------------------------------------------------------

class TestCleanSheets:
    def _cs_rule(self, fantasy):
        return _rule(fantasy, "CLEAN_SHEETS", 0, "POSITION",
                     {"positions": {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}})

    def _minutes_rules(self, fantasy):
        _rule(fantasy, "MINUTES_PLAYED", 1, "BRACKET", {"min": 1, "max": 59})
        _rule(fantasy, "MINUTES_PLAYED", 2, "BRACKET", {"min": 60, "max": None})

    def test_gk_clean_sheet_90_min_gives_4(self, engine_domain):
        d = engine_domain
        self._cs_rule(d["fantasy"])
        self._minutes_rules(d["fantasy"])
        fp = d["players"]["GK"]
        _add_stat(d["mc"], fp.player, "CLEAN_SHEETS", 1)
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 90)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        # 4 (clean sheet) + 2 (60+ min) = 6
        assert rec.base_points == Decimal("6")

    def test_def_clean_sheet_90_min_gives_4(self, engine_domain):
        d = engine_domain
        self._cs_rule(d["fantasy"])
        self._minutes_rules(d["fantasy"])
        fp = d["players"]["DEF"]
        _add_stat(d["mc"], fp.player, "CLEAN_SHEETS", 1)
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 90)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("6")  # 4 cs + 2 minutes

    def test_mid_clean_sheet_90_min_gives_1(self, engine_domain):
        d = engine_domain
        self._cs_rule(d["fantasy"])
        self._minutes_rules(d["fantasy"])
        fp = d["players"]["MID"]
        _add_stat(d["mc"], fp.player, "CLEAN_SHEETS", 1)
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 90)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("3")  # 1 cs + 2 minutes

    def test_fwd_clean_sheet_gives_0_always(self, engine_domain):
        d = engine_domain
        self._cs_rule(d["fantasy"])
        self._minutes_rules(d["fantasy"])
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "CLEAN_SHEETS", 1)
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 90)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("2")  # 0 cs + 2 minutes

    def test_gk_clean_sheet_below_60_min_gives_zero_cs_points(self, engine_domain):
        """GK played 59 min and team kept clean sheet — gate blocks the 4 pts."""
        d = engine_domain
        self._cs_rule(d["fantasy"])
        self._minutes_rules(d["fantasy"])
        fp = d["players"]["GK"]
        _add_stat(d["mc"], fp.player, "CLEAN_SHEETS", 1)
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 59)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        # 0 clean sheet (gate) + 1 minute bracket = 1
        assert rec.base_points == Decimal("1"), (
            f"GK with 59 min should get 0 CS pts; total should be 1, got {rec.base_points}"
        )

    def test_gk_clean_sheet_exactly_60_min_gives_cs_points(self, engine_domain):
        """Boundary: 60 minutes exactly → gate passes → clean sheet awarded."""
        d = engine_domain
        self._cs_rule(d["fantasy"])
        self._minutes_rules(d["fantasy"])
        fp = d["players"]["GK"]
        _add_stat(d["mc"], fp.player, "CLEAN_SHEETS", 1)
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 60)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("6")  # 4 cs + 2 minutes

    def test_gk_clean_sheet_no_minutes_stat_gives_zero_cs(self, engine_domain):
        """No MINUTES_PLAYED stat → treated as 0 minutes → gate blocks clean sheet."""
        d = engine_domain
        self._cs_rule(d["fantasy"])
        fp = d["players"]["GK"]
        _add_stat(d["mc"], fp.player, "CLEAN_SHEETS", 1)
        # Deliberately no MINUTES_PLAYED stat
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("0")


# ---------------------------------------------------------------------------
# Part K — Participation detection
# ---------------------------------------------------------------------------

class TestParticipation:
    """
    _participated() must return True only for genuine on-pitch time.
    A named substitute who remained on the bench must NOT count.
    """

    def _participated(self, gameweek, fantasy_player):
        from fantasy.services import _participated as _part
        return _part(gameweek, fantasy_player)

    def test_minutes_played_positive_is_participated(self, engine_domain):
        d = engine_domain
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 45)
        assert self._participated(d["gameweek"], fp) is True

    def test_minutes_played_zero_is_not_participated(self, engine_domain):
        """MINUTES_PLAYED=0 stat exists but player did not play."""
        d = engine_domain
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 0)
        assert self._participated(d["gameweek"], fp) is False

    def test_goal_stat_without_minutes_is_still_participated(self, engine_domain):
        """Any non-zero stat is secondary evidence of participation."""
        d = engine_domain
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 1)
        assert self._participated(d["gameweek"], fp) is True

    def test_no_stats_at_all_is_not_participated(self, engine_domain):
        """No MatchPlayerStatistic rows and no lineup → not participated."""
        d = engine_domain
        fp = d["players"]["FWD"]
        assert self._participated(d["gameweek"], fp) is False

    def test_starter_lineup_row_counts_as_participated(self, engine_domain):
        """MatchLineup is_starter=True → final fallback → participated."""
        d = engine_domain
        fp = d["players"]["DEF"]
        MatchLineup.objects.create(
            match_centre=d["mc"],
            participant=fp.player,
            side="HOME",
            position="DEF",
            is_starter=True,
        )
        assert self._participated(d["gameweek"], fp) is True

    def test_substitute_lineup_row_does_not_count(self, engine_domain):
        """
        MatchLineup is_starter=False (named but unused sub) must NOT
        count as participation. This is the confirmed bug in the old code.
        """
        d = engine_domain
        fp = d["players"]["DEF"]
        MatchLineup.objects.create(
            match_centre=d["mc"],
            participant=fp.player,
            side="HOME",
            position="DEF",
            is_starter=False,  # sat on the bench, never came on
        )
        assert self._participated(d["gameweek"], fp) is False

    def test_minutes_played_takes_priority_over_lineup(self, engine_domain):
        """MINUTES_PLAYED=0 present even if lineup row exists → not participated."""
        d = engine_domain
        fp = d["players"]["GK"]
        _add_stat(d["mc"], fp.player, "MINUTES_PLAYED", 0)
        MatchLineup.objects.create(
            match_centre=d["mc"],
            participant=fp.player,
            side="HOME",
            position="GK",
            is_starter=True,
        )
        # MINUTES_PLAYED=0 is an explicit zero — takes priority → not participated
        assert self._participated(d["gameweek"], fp) is False


# ---------------------------------------------------------------------------
# Part L — Existing functionality preserved
# ---------------------------------------------------------------------------

class TestExistingFunctionality:
    """Regression tests ensuring existing behaviour is fully preserved."""

    def test_captain_multiplier(self, engine_domain):
        """Captain earns double: 4 pts base → 4 + 4 bonus = 8 team pts."""
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 4, "PER_UNIT")
        _add_stat(d["mc"], d["players"]["FWD"].player, "GOALS", 1)
        team = _make_team(d["fantasy"], d["players"], captain_pos="FWD", vice_pos="GK")
        score_gameweek(d["gameweek"])
        score = FantasyTeamGameweekScore.objects.get(team=team, gameweek=d["gameweek"])
        assert score.player_points == Decimal("4")
        assert score.captain_bonus == Decimal("4")
        assert score.total_points == Decimal("8")

    def test_vice_captain_fallback_when_captain_does_not_play(self, engine_domain):
        """Captain has no stats → vice becomes effective captain."""
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        # Only vice (GK) has stats, captain (FWD) does not
        _add_stat(d["mc"], d["players"]["GK"].player, "GOALS", 1)
        team = _make_team(d["fantasy"], d["players"], captain_pos="FWD", vice_pos="GK")
        score_gameweek(d["gameweek"])
        score = FantasyTeamGameweekScore.objects.get(team=team, gameweek=d["gameweek"])
        # GK scored 5 pts and is effective captain → bonus = 5
        assert score.captain_bonus == Decimal("5")
        assert score.total_points == Decimal("10")  # 5 player + 5 bonus

    def test_transfer_penalty_deducted(self, engine_domain):
        """transfer_penalty=4 is subtracted from team total."""
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 10, "PER_UNIT")
        _add_stat(d["mc"], d["players"]["FWD"].player, "GOALS", 1)
        team = _make_team(d["fantasy"], d["players"], captain_pos="FWD", vice_pos="GK")
        from fantasy.services import gameweek_state
        state = gameweek_state(team, d["gameweek"])
        state.transfer_penalty = 4
        state.save()
        score_gameweek(d["gameweek"])
        score = FantasyTeamGameweekScore.objects.get(team=team, gameweek=d["gameweek"])
        # FWD 10 pts + captain_bonus 10 - penalty 4 = 16
        assert score.total_points == Decimal("16")

    def test_idempotent_rescoring(self, engine_domain):
        """Calling score_gameweek twice produces identical results — no duplicates."""
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        _add_stat(d["mc"], d["players"]["FWD"].player, "GOALS", 2)
        team = _make_team(d["fantasy"], d["players"], captain_pos="FWD", vice_pos="GK")
        score_gameweek(d["gameweek"])
        score_gameweek(d["gameweek"])
        assert FantasyPlayerGameweekPoints.objects.filter(gameweek=d["gameweek"]).count() == 4
        assert FantasyTeamGameweekScore.objects.filter(gameweek=d["gameweek"]).count() == 1
        score = FantasyTeamGameweekScore.objects.get(team=team, gameweek=d["gameweek"])
        assert score.total_points == Decimal("20")  # 10 player + 10 bonus

    def test_correction_applied_after_rescore(self, engine_domain):
        """FantasyScoringCorrection anchors total_points through a rescore."""
        from fantasy.models import FantasyScoringCorrection
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        _add_stat(d["mc"], d["players"]["MID"].player, "GOALS", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["MID"])
        assert rec.base_points == Decimal("5")
        # actor is NOT NULL on FantasyScoringCorrection — create a real user
        actor = User.objects.create_user(username="corrector", email="corrector@test.com")
        FantasyScoringCorrection.objects.create(
            player_points=rec, previous_value=Decimal("5"),
            new_value=Decimal("8"), reason="test", actor=actor,
        )
        score_gameweek(d["gameweek"])
        rec.refresh_from_db()
        assert rec.total_points == Decimal("8")
        assert rec.correction_points == Decimal("3")

    def test_finalized_gameweek_score_is_not_re_run_by_task(self, engine_domain):
        """FINALIZED gameweek is skipped by score_affected_gameweeks task."""
        from unittest.mock import patch
        from fantasy.tasks import score_affected_gameweeks
        d = engine_domain
        d["gameweek"].status = "FINALIZED"
        d["gameweek"].save()
        with patch("fantasy.services.score_gameweek") as mock_sg:
            score_affected_gameweeks.run([str(d["fixture"].id)])
        mock_sg.assert_not_called()

    def test_no_stats_player_has_zero_points_and_flag_false(self, engine_domain):
        """Player with no stats: base_points=0, statistics_available=False."""
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["FWD"])
        assert rec.base_points == Decimal("0")
        assert rec.statistics_available is False

    def test_bench_player_points_calculated_but_not_counted(self, engine_domain):
        """Bench player earns points but team total excludes them."""
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 10, "PER_UNIT")
        # GK is bench, FWD is starter
        _add_stat(d["mc"], d["players"]["GK"].player, "GOALS", 1)  # bench: 10 pts
        _add_stat(d["mc"], d["players"]["FWD"].player, "GOALS", 1)  # starter: 10 pts

        user = User.objects.create_user(username="bench_u", email="bench@test.com")
        team = FantasyTeam.objects.create(
            owner=user, fantasy_competition=d["fantasy"], name="Bench Team",
            budget_remaining=Decimal("0"),
        )
        # FWD starter + captain, GK bench
        FantasyTeamPlayer.objects.create(
            team=team, fantasy_player=d["players"]["FWD"], is_starter=True,
            is_captain=True, is_vice_captain=False, bench_order=None,
            purchase_price=d["players"]["FWD"].price,
        )
        FantasyTeamPlayer.objects.create(
            team=team, fantasy_player=d["players"]["DEF"], is_starter=True,
            is_captain=False, is_vice_captain=True, bench_order=None,
            purchase_price=d["players"]["DEF"].price,
        )
        FantasyTeamPlayer.objects.create(
            team=team, fantasy_player=d["players"]["MID"], is_starter=True,
            is_captain=False, is_vice_captain=False, bench_order=None,
            purchase_price=d["players"]["MID"].price,
        )
        FantasyTeamPlayer.objects.create(
            team=team, fantasy_player=d["players"]["GK"], is_starter=False,
            is_captain=False, is_vice_captain=False, bench_order=1,
            purchase_price=d["players"]["GK"].price,
        )
        score_gameweek(d["gameweek"])

        gk_rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["GK"])
        assert gk_rec.base_points == Decimal("10")  # calculated

        score = FantasyTeamGameweekScore.objects.get(team=team, gameweek=d["gameweek"])
        # Only FWD starter points (10) + captain bonus (10) = 20; bench GK not counted
        assert score.total_points == Decimal("20")

    def test_breakdown_contains_stat_entries(self, engine_domain):
        """Breakdown JSON is populated with at least the scored stat."""
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        _add_stat(d["mc"], d["players"]["FWD"].player, "GOALS", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(
            gameweek=d["gameweek"], fantasy_player=d["players"]["FWD"])
        assert len(rec.breakdown) >= 1
        entry = next(e for e in rec.breakdown if e["statistic_type"] == "GOALS")
        assert Decimal(entry["points"]) == Decimal("5")

    def test_leaderboard_season_totals(self, engine_domain):
        """Competition leaderboard sums team scores across gameweeks."""
        from rest_framework.test import APIClient
        d = engine_domain
        team = _make_team(d["fantasy"], d["players"], captain_pos="FWD", vice_pos="GK")
        FantasyTeamGameweekScore.objects.create(
            team=team, gameweek=d["gameweek"],
            player_points=Decimal("10"), captain_bonus=Decimal("10"),
            transfer_penalty=Decimal("0"), total_points=Decimal("20"),
        )
        resp = APIClient().get(f"/api/v1/fantasy/competitions/{d['fantasy'].id}/leaderboard/")
        assert resp.status_code == 200
        assert resp.data[0]["total_points"] == Decimal("20")


# ---------------------------------------------------------------------------
# Part M — Serializer validation for new rule types
# ---------------------------------------------------------------------------

class TestScoringRuleSerializer:
    """Serializer accepts valid rule types and rejects malformed conditions."""

    URL = "/api/v1/fantasy/admin/scoring-rules/"

    def _post(self, fantasy, payload):
        from rest_framework.test import APIClient
        from django.contrib.auth import get_user_model
        # Create an admin user with the required fantasy permission
        UserModel = get_user_model()
        admin = UserModel.objects.create_user(
            username=f"admin_{id(payload)}", email=f"admin_{id(payload)}@test.com",
            password="pass",
        )
        # Grant platform.fantasy.manage permission so CanManageFantasy passes
        from authentication.services.permission_service import PermissionService
        try:
            PermissionService.grant_permission(admin, "platform.fantasy.manage")
        except Exception:
            # If no grant method exists, use superuser as fallback
            admin.is_staff = True
            admin.is_superuser = True
            admin.save(update_fields=["is_staff", "is_superuser"])
        client = APIClient()
        client.force_authenticate(user=admin)
        return client.post(self.URL, payload, format="json")

    def test_per_unit_rule_accepted(self, engine_domain):
        d = engine_domain
        r = self._post(d["fantasy"], {
            "fantasy_competition": str(d["fantasy"].id),
            "statistic_type": "GOALS", "points": "5",
            "rule_type": "PER_UNIT", "conditions": {},
        })
        assert r.status_code == 201, r.data

    def test_flat_rule_accepted(self, engine_domain):
        d = engine_domain
        r = self._post(d["fantasy"], {
            "fantasy_competition": str(d["fantasy"].id),
            "statistic_type": "PENALTIES_SAVED", "points": "5",
            "rule_type": "FLAT", "conditions": {},
        })
        assert r.status_code == 201, r.data

    def test_bracket_rule_accepted(self, engine_domain):
        d = engine_domain
        r = self._post(d["fantasy"], {
            "fantasy_competition": str(d["fantasy"].id),
            "statistic_type": "MINUTES_PLAYED", "points": "1",
            "rule_type": "BRACKET", "conditions": {"min": 1, "max": 59},
        })
        assert r.status_code == 201, r.data

    def test_per_n_rule_accepted(self, engine_domain):
        d = engine_domain
        r = self._post(d["fantasy"], {
            "fantasy_competition": str(d["fantasy"].id),
            "statistic_type": "SAVES", "points": "1",
            "rule_type": "PER_N", "conditions": {"per_n": 3},
        })
        assert r.status_code == 201, r.data

    def test_position_rule_accepted(self, engine_domain):
        d = engine_domain
        r = self._post(d["fantasy"], {
            "fantasy_competition": str(d["fantasy"].id),
            "statistic_type": "GOALS", "points": "0",
            "rule_type": "POSITION",
            "conditions": {"positions": {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}},
        })
        assert r.status_code == 201, r.data

    def test_bracket_without_min_rejected(self, engine_domain):
        d = engine_domain
        r = self._post(d["fantasy"], {
            "fantasy_competition": str(d["fantasy"].id),
            "statistic_type": "MINUTES_PLAYED", "points": "1",
            "rule_type": "BRACKET", "conditions": {"max": 59},  # missing min
        })
        assert r.status_code == 400

    def test_per_n_with_zero_rejected(self, engine_domain):
        d = engine_domain
        r = self._post(d["fantasy"], {
            "fantasy_competition": str(d["fantasy"].id),
            "statistic_type": "SAVES", "points": "1",
            "rule_type": "PER_N", "conditions": {"per_n": 0},
        })
        assert r.status_code == 400

    def test_position_with_non_dict_rejected(self, engine_domain):
        d = engine_domain
        r = self._post(d["fantasy"], {
            "fantasy_competition": str(d["fantasy"].id),
            "statistic_type": "GOALS", "points": "0",
            "rule_type": "POSITION", "conditions": {"positions": "bad"},
        })
        assert r.status_code == 400

    def test_invalid_rule_type_rejected(self, engine_domain):
        d = engine_domain
        r = self._post(d["fantasy"], {
            "fantasy_competition": str(d["fantasy"].id),
            "statistic_type": "GOALS", "points": "5",
            "rule_type": "MADE_UP_TYPE", "conditions": {},
        })
        assert r.status_code == 400

    def test_legacy_rule_without_rule_type_defaults_to_per_unit(self, engine_domain):
        """Existing rules with conditions={} and no rule_type keep working."""
        d = engine_domain
        rule = FantasyScoringRule.objects.create(
            fantasy_competition=d["fantasy"],
            statistic_type="ASSISTS",
            points=Decimal("3"),
            conditions={},
            enabled=True,
        )
        # rule_type should default to PER_UNIT without explicit assignment
        assert rule.rule_type == "PER_UNIT"



# ---------------------------------------------------------------------------
# Part N — Multiple rules accumulate correctly (Phase 6)
# ---------------------------------------------------------------------------

class TestMultipleRules:
    """Multiple enabled rules for different stats all contribute to the total."""

    def test_goals_and_assists_sum(self, engine_domain):
        """
        Goals: PER_UNIT × 5 = 10
        Assists: PER_UNIT × 3 = 3
        Total base_points = 13
        """
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        _rule(d["fantasy"], "ASSISTS", 3, "PER_UNIT")
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 2)
        _add_stat(d["mc"], fp.player, "ASSISTS", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("13"), (
            f"Expected 13 (10 goals + 3 assists), got {rec.base_points}"
        )
        assert rec.total_points == Decimal("13")

    def test_multiple_rules_contribute_to_team_total(self, engine_domain):
        """
        Goals: 2 × 5 = 10
        Assists: 1 × 3 = 3
        Player total = 13, captain → team total = 26 (13 + 13 bonus).
        """
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        _rule(d["fantasy"], "ASSISTS", 3, "PER_UNIT")
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 2)
        _add_stat(d["mc"], fp.player, "ASSISTS", 1)
        team = _make_team(d["fantasy"], d["players"], captain_pos="FWD", vice_pos="GK")
        score_gameweek(d["gameweek"])
        score = FantasyTeamGameweekScore.objects.get(team=team, gameweek=d["gameweek"])
        assert score.player_points == Decimal("13")
        assert score.captain_bonus == Decimal("13")
        assert score.total_points == Decimal("26")

    def test_breakdown_lists_both_stats(self, engine_domain):
        """Breakdown must contain an entry for each stat that contributed points."""
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        _rule(d["fantasy"], "ASSISTS", 3, "PER_UNIT")
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 2)
        _add_stat(d["mc"], fp.player, "ASSISTS", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        stat_types = {e["statistic_type"].upper() for e in rec.breakdown}
        assert "GOALS" in stat_types
        assert "ASSISTS" in stat_types


# ---------------------------------------------------------------------------
# Part O — Inactive rules are ignored (Phase 7)
# ---------------------------------------------------------------------------

class TestInactiveRules:
    """enabled=False rules must not participate in scoring."""

    def test_disabled_rule_not_applied(self, engine_domain):
        """
        Active rule: GOALS × 5 = 10
        Inactive rule: GOALS × 10 (enabled=False) — must NOT add extra points
        Expected: 10 (not 20 or 30)
        """
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")       # enabled, conditions={}
        # Inactive rule — use non-empty conditions to satisfy the unique constraint
        # (fantasy_competition, statistic_type, conditions) while keeping PER_UNIT semantics
        FantasyScoringRule.objects.create(
            fantasy_competition=d["fantasy"],
            statistic_type="GOALS",
            points=Decimal("10"),
            rule_type="PER_UNIT",
            conditions={"_disabled_marker": True},        # unique conditions value
            enabled=False,                                  # inactive
        )
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 2)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("10"), (
            f"Inactive rule must be ignored; expected 10 pts (2 × 5), got {rec.base_points}"
        )

    def test_disabled_rule_not_applied_zero_active(self, engine_domain):
        """Only an inactive rule exists → player scores 0."""
        d = engine_domain
        FantasyScoringRule.objects.create(
            fantasy_competition=d["fantasy"],
            statistic_type="GOALS",
            points=Decimal("5"),
            rule_type="PER_UNIT",
            conditions={},
            enabled=False,
        )
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 2)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("0")

    def test_disabled_rule_not_removed_from_db(self, engine_domain):
        """Inactive rule still exists in the database after scoring."""
        d = engine_domain
        inactive = FantasyScoringRule.objects.create(
            fantasy_competition=d["fantasy"],
            statistic_type="GOALS",
            points=Decimal("10"),
            rule_type="PER_UNIT",
            conditions={"_disabled_only": True},
            enabled=False,
        )
        score_gameweek(d["gameweek"])
        # DB row must still exist
        assert FantasyScoringRule.objects.filter(pk=inactive.pk).exists()


# ---------------------------------------------------------------------------
# Part P — Corrections (Phase 8)
# ---------------------------------------------------------------------------

class TestCorrections:
    """Corrections update all related aggregates correctly."""

    def test_correction_changes_player_total(self, engine_domain):
        """
        Initial: GOALS=1 × 5 = 5 pts
        Correction: new_value = 10
        After rescore: total_points = 10, correction_points = 5
        """
        from fantasy.models import FantasyScoringCorrection
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("5")
        actor = User.objects.create_user(username="corr_p", email="corr_p@test.com")
        FantasyScoringCorrection.objects.create(
            player_points=rec, previous_value=Decimal("5"),
            new_value=Decimal("10"), reason="fix", actor=actor,
        )
        score_gameweek(d["gameweek"])
        rec.refresh_from_db()
        assert rec.total_points == Decimal("10")
        assert rec.correction_points == Decimal("5")

    def test_correction_updates_team_score(self, engine_domain):
        """After a correction the team's total_points reflects the new value."""
        from fantasy.models import FantasyScoringCorrection
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 1)
        team = _make_team(d["fantasy"], d["players"], captain_pos="FWD", vice_pos="GK")
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        # FWD is captain: 5 + 5 = 10 initial team total
        score = FantasyTeamGameweekScore.objects.get(team=team, gameweek=d["gameweek"])
        assert score.total_points == Decimal("10")
        actor = User.objects.create_user(username="corr_t", email="corr_t@test.com")
        FantasyScoringCorrection.objects.create(
            player_points=rec, previous_value=Decimal("5"),
            new_value=Decimal("10"), reason="upgrade", actor=actor,
        )
        score_gameweek(d["gameweek"])
        score.refresh_from_db()
        # FWD now 10 pts + 10 captain bonus = 20
        assert score.total_points == Decimal("20")

    def test_correction_reduces_points(self, engine_domain):
        """Corrections can reduce points (admin downgrade)."""
        from fantasy.models import FantasyScoringCorrection
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 2)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("10")
        actor = User.objects.create_user(username="corr_r", email="corr_r@test.com")
        FantasyScoringCorrection.objects.create(
            player_points=rec, previous_value=Decimal("10"),
            new_value=Decimal("5"), reason="downgrade", actor=actor,
        )
        score_gameweek(d["gameweek"])
        rec.refresh_from_db()
        assert rec.total_points == Decimal("5")
        assert rec.correction_points == Decimal("-5")


# ---------------------------------------------------------------------------
# Part Q — Scoring idempotency (Phase 9)
# ---------------------------------------------------------------------------

class TestIdempotency:
    """Scoring the same gameweek multiple times must produce identical results."""

    def test_player_points_idempotent_after_three_rescores(self, engine_domain):
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        _rule(d["fantasy"], "ASSISTS", 3, "PER_UNIT")
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 2)
        _add_stat(d["mc"], fp.player, "ASSISTS", 1)
        for _ in range(3):
            score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("13")
        assert rec.total_points == Decimal("13")
        # Only one record per player per gameweek
        assert FantasyPlayerGameweekPoints.objects.filter(
            gameweek=d["gameweek"], fantasy_player=fp
        ).count() == 1

    def test_team_score_idempotent(self, engine_domain):
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 2)
        team = _make_team(d["fantasy"], d["players"], captain_pos="FWD", vice_pos="GK")
        for _ in range(3):
            score_gameweek(d["gameweek"])
        assert FantasyTeamGameweekScore.objects.filter(
            team=team, gameweek=d["gameweek"]
        ).count() == 1
        score = FantasyTeamGameweekScore.objects.get(team=team, gameweek=d["gameweek"])
        # FWD 10 pts + captain bonus 10 = 20
        assert score.total_points == Decimal("20")

    def test_captain_bonus_idempotent(self, engine_domain):
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 4, "PER_UNIT")
        _add_stat(d["mc"], d["players"]["FWD"].player, "GOALS", 1)
        team = _make_team(d["fantasy"], d["players"], captain_pos="FWD", vice_pos="GK")
        score_gameweek(d["gameweek"])
        score_gameweek(d["gameweek"])
        score = FantasyTeamGameweekScore.objects.get(team=team, gameweek=d["gameweek"])
        assert score.captain_bonus == Decimal("4")   # not 8 (doubled from 2 rescores)
        assert score.total_points == Decimal("8")     # not 16


# ---------------------------------------------------------------------------
# Part R — Player aggregate totals via serializer (Phase 1)
# ---------------------------------------------------------------------------

class TestPlayerAggregates:
    """
    FantasyPlayer.total_points and current_gameweek_points are serializer-
    computed from FantasyPlayerGameweekPoints.  After scoring, the API must
    return the correct computed values.
    """

    def test_total_points_reflects_scored_gameweek(self, engine_domain):
        """
        After scoring: FantasyPlayerSerializer.total_points must equal the
        sum of all FantasyPlayerGameweekPoints.total_points for that player.
        """
        from rest_framework.test import APIClient
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 2)
        score_gameweek(d["gameweek"])
        resp = APIClient().get(
            f"/api/v1/fantasy/players/{fp.id}/",
            {"competition": str(d["fantasy"].id)},
        )
        assert resp.status_code == 200
        assert Decimal(str(resp.data["total_points"])) == Decimal("10")

    def test_current_gameweek_points_reflects_latest_scored_gameweek(self, engine_domain):
        """
        current_gameweek_points must equal the most recent non-DRAFT
        gameweek's FantasyPlayerGameweekPoints.total_points.
        """
        from rest_framework.test import APIClient
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 2)
        score_gameweek(d["gameweek"])
        resp = APIClient().get(
            f"/api/v1/fantasy/players/{fp.id}/",
            {"competition": str(d["fantasy"].id)},
        )
        assert resp.status_code == 200
        assert Decimal(str(resp.data["current_gameweek_points"])) == Decimal("10")

    def test_total_points_idempotent_after_double_scoring(self, engine_domain):
        """Scoring the same gameweek twice must NOT double the total_points."""
        from rest_framework.test import APIClient
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 2)
        score_gameweek(d["gameweek"])
        score_gameweek(d["gameweek"])
        resp = APIClient().get(
            f"/api/v1/fantasy/players/{fp.id}/",
            {"competition": str(d["fantasy"].id)},
        )
        assert resp.status_code == 200
        assert Decimal(str(resp.data["total_points"])) == Decimal("10"), (
            f"Expected 10 after double scoring, got {resp.data['total_points']} "
            f"(idempotency failure: base_points doubled)"
        )

    def test_total_points_updates_after_correction(self, engine_domain):
        """
        After a correction the serializer total_points must reflect new_value,
        NOT the original scored total.
        """
        from rest_framework.test import APIClient
        from fantasy.models import FantasyScoringCorrection
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 1)
        score_gameweek(d["gameweek"])
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        actor = User.objects.create_user(username="agg_corr", email="agg_corr@test.com")
        FantasyScoringCorrection.objects.create(
            player_points=rec, previous_value=Decimal("5"),
            new_value=Decimal("10"), reason="agg test", actor=actor,
        )
        score_gameweek(d["gameweek"])
        resp = APIClient().get(
            f"/api/v1/fantasy/players/{fp.id}/",
            {"competition": str(d["fantasy"].id)},
        )
        assert resp.status_code == 200
        assert Decimal(str(resp.data["total_points"])) == Decimal("10")


# ---------------------------------------------------------------------------
# Part S — End-to-end scoring scenario (Phase 11)
# ---------------------------------------------------------------------------

class TestEndToEndScoringScenario:
    """
    Full scenario: Goals PER_UNIT×5 + Assists PER_UNIT×3.
    Player: 2 goals + 1 assist = 13 pts.
    Captain (×2 multiplier): 13 base + 13 bonus = 26 team contribution.
    """

    def test_full_scoring_scenario(self, engine_domain):
        d = engine_domain
        _rule(d["fantasy"], "GOALS", 5, "PER_UNIT")
        _rule(d["fantasy"], "ASSISTS", 3, "PER_UNIT")
        fp = d["players"]["FWD"]
        _add_stat(d["mc"], fp.player, "GOALS", 2)
        _add_stat(d["mc"], fp.player, "ASSISTS", 1)
        team = _make_team(d["fantasy"], d["players"], captain_pos="FWD", vice_pos="GK")
        score_gameweek(d["gameweek"])

        # --- Player points ---
        rec = FantasyPlayerGameweekPoints.objects.get(gameweek=d["gameweek"], fantasy_player=fp)
        assert rec.base_points == Decimal("13"), f"base_points: expected 13, got {rec.base_points}"
        assert rec.total_points == Decimal("13"), f"total_points: expected 13, got {rec.total_points}"

        # --- Team score ---
        score = FantasyTeamGameweekScore.objects.get(team=team, gameweek=d["gameweek"])
        assert score.captain_bonus == Decimal("13"), (
            f"captain_bonus: expected 13, got {score.captain_bonus}"
        )
        assert score.total_points == Decimal("26"), (
            f"team total: expected 26, got {score.total_points}"
        )

        # --- Breakdown contains captain entry ---
        players_detail = score.breakdown.get("players", [])
        captain_entry = next((p for p in players_detail if p["captain"]), None)
        assert captain_entry is not None, "breakdown must contain a captain entry"
        assert Decimal(captain_entry["captain_bonus"]) == Decimal("13")
        assert Decimal(captain_entry["final_points"]) == Decimal("26")

        # --- Leaderboard reflects team total ---
        from rest_framework.test import APIClient
        resp = APIClient().get(f"/api/v1/fantasy/competitions/{d['fantasy'].id}/leaderboard/")
        assert resp.status_code == 200
        assert len(resp.data) == 1
        assert Decimal(str(resp.data[0]["total_points"])) == Decimal("26")
        assert resp.data[0]["rank"] == 1

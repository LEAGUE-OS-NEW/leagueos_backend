"""
Tests for the automatic Fantasy scoring bridge.

Covers:
  - completed ingestion triggers score_affected_gameweeks after commit
  - affected fixture finds its gameweek
  - FINALIZED gameweek is skipped
  - multiple gameweeks (same fixture in two) are each scored
  - task is safe to retry (idempotent)
  - fixture without a FantasyGameweek does not fail
  - imported Alex GOALS=2 with GOALS=3 scoring rule results in 6 fantasy points
  - complete_ingestion with no fixture_ids does not dispatch the task
  - complete_ingestion with empty fixture_ids does not dispatch the task
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from discovery.models import (
    MatchCentre,
    MatchPlayerStatistic,
    SportsFeedIngestion,
    SportsFeedProvider,
)
from discovery.services.sports_feed_service import SportsFeedService
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
from fantasy.tasks import score_affected_gameweeks
from profiles.models import Club
from sports.models import Competition, Participant, Sport, SportingEvent
from discovery.models import Season


# ── shared helpers ─────────────────────────────────────────────────────────────


def _uid():
    """Short unique token for creating DB objects with unique names/slugs."""
    return uuid.uuid4().hex[:8]


def _make_provider(code=None):
    code = code or f"PROV_{_uid()}"
    return SportsFeedProvider.objects.create(code=code, name=f"Provider {code}", is_active=True)


def _make_ingestion(provider):
    return SportsFeedIngestion.objects.create(
        provider=provider,
        status=SportsFeedIngestion.Status.PROCESSING,
    )


def _make_fantasy_domain(*, gw_status="SCORING", gw_number=None):
    """Create the minimal Football domain required for scoring tests.

    Each call produces a fully isolated domain with unique DB names so multiple
    calls within the same test transaction cannot clash on UNIQUE constraints.
    """
    uid = _uid()
    gw_number = gw_number or 1
    sport = Sport.objects.create(
        name=f"Football_{uid}",
        slug=f"football-{uid}",
        code=f"FB{uid[:4].upper()}",
    )
    competition = Competition.objects.create(
        sport=sport, name=f"League_{uid}", country_code="UG"
    )
    season = Season.objects.create(
        sport=sport, competition=competition, name=f"2026_{uid}"
    )
    fantasy = FantasyCompetition.objects.create(
        competition=competition,
        season=season,
        name=f"Fantasy_{uid}",
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
    # Club name and slug must be unique across the whole test DB
    club = Club.objects.create(name=f"Club_{uid}", slug=f"club-{uid}")

    alex = Participant.objects.create(sport=sport, kind="ATHLETE", name=f"Alex_{uid}")
    try:
        from discovery.models import PlayerProfile
        PlayerProfile.objects.create(participant=alex, club=club, position="FWD")
    except Exception:
        pass

    alex_fp = FantasyPlayer.objects.create(
        fantasy_competition=fantasy, player=alex, position="FWD", price=Decimal("8")
    )

    other = Participant.objects.create(sport=sport, kind="ATHLETE", name=f"Other_{uid}")
    other_fp = FantasyPlayer.objects.create(
        fantasy_competition=fantasy, player=other, position="GK", price=Decimal("5")
    )

    now = timezone.now()
    fixture = SportingEvent.objects.create(
        sport=sport,
        competition=competition,
        name=f"Match_{uid}",
        starts_at=now - timedelta(hours=2),
        status="COMPLETED",
    )
    gameweek = FantasyGameweek.objects.create(
        fantasy_competition=fantasy,
        number=gw_number,
        name=f"GW{gw_number}_{uid}",
        starts_at=now - timedelta(days=1),
        deadline_at=now + timedelta(hours=1),
        ends_at=now + timedelta(days=2),
        status=gw_status,
    )
    gameweek.fixtures.add(fixture)

    return {
        "sport": sport,
        "competition": competition,
        "fantasy": fantasy,
        "alex": alex,
        "alex_fp": alex_fp,
        "other": other,
        "other_fp": other_fp,
        "fixture": fixture,
        "gameweek": gameweek,
        "club": club,
    }


def _add_scoring_rule(fantasy, stat_type="GOALS", points="3"):
    return FantasyScoringRule.objects.create(
        fantasy_competition=fantasy,
        statistic_type=stat_type,
        points=Decimal(points),
        enabled=True,
        conditions={},
    )


def _add_team_with_alex_captain(domain):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    uid = _uid()
    user = User.objects.create_user(
        username=f"fan_{uid}",
        email=f"fan_{uid}@example.com",
    )
    team = FantasyTeam.objects.create(
        owner=user,
        fantasy_competition=domain["fantasy"],
        name=f"Team_{uid}",
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
    return team


def _add_stat(domain, stat_type="GOALS", value=2):
    mc, _ = MatchCentre.objects.get_or_create(fixture=domain["fixture"])
    return MatchPlayerStatistic.objects.create(
        match_centre=mc,
        participant=domain["alex"],
        stat_type=stat_type,
        value=Decimal(str(value)),
    )


# ── Task unit tests (no real Celery broker needed) ─────────────────────────────

# score_gameweek is imported inside the task via a late import from fantasy.services.
# Patching "fantasy.services.score_gameweek" intercepts the name at the module
# where it is defined, which is the correct target for late-import mocking.
_SCORE_GW_PATH = "fantasy.services.score_gameweek"


@pytest.mark.django_db
class TestScoreAffectedGameweeks:
    """Direct tests of the Celery task function (task_self=None bypasses retry)."""

    def test_empty_fixture_ids_returns_zero_scored(self):
        """Empty list → task exits immediately without querying the DB."""
        result = score_affected_gameweeks(None, [])
        assert result["scored"] == 0
        assert result["skipped_finalized"] == 0

    def test_fixture_with_no_gameweek_does_not_fail(self):
        """Fixture that belongs to no FantasyGameweek → scored=0, no_gameweek reported."""
        uid = _uid()
        sport = Sport.objects.create(
            name=f"NoGW_{uid}",
            slug=f"no-gw-{uid}",
            code=f"NG{uid[:4].upper()}",
        )
        comp = Competition.objects.create(sport=sport, name=f"NoGW Comp {uid}", country_code="UG")
        now = timezone.now()
        fixture = SportingEvent.objects.create(
            sport=sport, competition=comp, name=f"Orphan_{uid}",
            starts_at=now, status="COMPLETED",
        )
        result = score_affected_gameweeks(None, [str(fixture.id)])
        assert result["scored"] == 0
        assert result["no_gameweek"] == 1

    def test_finalized_gameweek_is_skipped(self):
        """FINALIZED gameweek → skipped, score_gameweek() never called."""
        domain = _make_fantasy_domain(gw_status="FINALIZED")
        _add_stat(domain)

        with patch(_SCORE_GW_PATH) as mock_sg:
            result = score_affected_gameweeks(None, [str(domain["fixture"].id)])

        mock_sg.assert_not_called()
        assert result["scored"] == 0
        assert result["skipped_finalized"] == 1

    def test_scoring_gameweek_is_scored(self):
        """Non-finalized gameweek (SCORING) → score_gameweek() called once."""
        domain = _make_fantasy_domain(gw_status="SCORING")
        _add_stat(domain)

        with patch(_SCORE_GW_PATH) as mock_sg:
            result = score_affected_gameweeks(None, [str(domain["fixture"].id)])

        mock_sg.assert_called_once_with(domain["gameweek"])
        assert result["scored"] == 1
        assert result["skipped_finalized"] == 0

    def test_live_gameweek_is_scored(self):
        """LIVE gameweek → score_gameweek() called once."""
        domain = _make_fantasy_domain(gw_status="LIVE")
        _add_stat(domain)

        with patch(_SCORE_GW_PATH) as mock_sg:
            result = score_affected_gameweeks(None, [str(domain["fixture"].id)])

        mock_sg.assert_called_once()
        assert result["scored"] == 1

    def test_multiple_gameweeks_all_scored(self):
        """Same fixture in two different non-finalized gameweeks → both scored."""
        domain1 = _make_fantasy_domain(gw_status="SCORING", gw_number=1)
        domain2 = _make_fantasy_domain(gw_status="SCORING", gw_number=2)
        # Share domain1's fixture with domain2's gameweek
        domain2["gameweek"].fixtures.add(domain1["fixture"])

        with patch(_SCORE_GW_PATH) as mock_sg:
            result = score_affected_gameweeks(None, [str(domain1["fixture"].id)])

        assert mock_sg.call_count == 2
        called_gws = {c.args[0].id for c in mock_sg.call_args_list}
        assert domain2["gameweek"].id in called_gws
        assert result["scored"] == 2

    def test_mixed_finalized_and_scoring_gameweeks(self):
        """One FINALIZED, one SCORING → only SCORING is scored."""
        domain_fin = _make_fantasy_domain(gw_status="FINALIZED", gw_number=1)
        domain_scr = _make_fantasy_domain(gw_status="SCORING", gw_number=2)
        # Make domain_scr's gameweek also contain domain_fin's fixture
        domain_scr["gameweek"].fixtures.add(domain_fin["fixture"])

        with patch(_SCORE_GW_PATH) as mock_sg:
            result = score_affected_gameweeks(None, [str(domain_fin["fixture"].id)])

        # domain_fin's own gameweek is FINALIZED → skip
        # domain_scr's gameweek contains the same fixture, is SCORING → score
        assert mock_sg.call_count == 1
        assert result["scored"] == 1
        assert result["skipped_finalized"] == 1

    def test_task_is_idempotent_on_retry(self):
        """Calling the task twice with the same fixture_ids is safe (no duplicates)."""
        domain = _make_fantasy_domain(gw_status="SCORING")
        _add_stat(domain)
        _add_scoring_rule(domain["fantasy"])
        _add_team_with_alex_captain(domain)

        gameweek = domain["gameweek"]

        # First execution
        score_affected_gameweeks(None, [str(domain["fixture"].id)])
        points_after_first = FantasyPlayerGameweekPoints.objects.filter(
            gameweek=gameweek
        ).count()
        scores_after_first = FantasyTeamGameweekScore.objects.filter(
            gameweek=gameweek
        ).count()

        # Second execution (simulated retry)
        score_affected_gameweeks(None, [str(domain["fixture"].id)])
        points_after_second = FantasyPlayerGameweekPoints.objects.filter(
            gameweek=gameweek
        ).count()
        scores_after_second = FantasyTeamGameweekScore.objects.filter(
            gameweek=gameweek
        ).count()

        assert points_after_first == points_after_second, (
            "Retry created duplicate FantasyPlayerGameweekPoints rows"
        )
        assert scores_after_first == scores_after_second, (
            "Retry created duplicate FantasyTeamGameweekScore rows"
        )

    def test_alex_goals_2_with_rule_3_gives_6_points(self):
        """
        Full end-to-end: Alex GOALS=2 + rule GOALS=3pts → base_points=6.
        This exercises the real score_gameweek() function via the task.
        """
        domain = _make_fantasy_domain(gw_status="SCORING")
        _add_stat(domain, stat_type="GOALS", value=2)
        _add_scoring_rule(domain["fantasy"], stat_type="GOALS", points="3")
        _add_team_with_alex_captain(domain)

        gameweek = domain["gameweek"]

        result = score_affected_gameweeks(None, [str(domain["fixture"].id)])

        assert result["scored"] == 1

        points = FantasyPlayerGameweekPoints.objects.get(
            gameweek=gameweek,
            fantasy_player=domain["alex_fp"],
        )
        assert points.base_points == Decimal("6"), (
            f"Expected 6 pts (2 goals × 3), got {points.base_points}"
        )
        assert points.total_points == Decimal("6")
        assert points.statistics_available is True

    def test_multiple_fixture_ids_deduplicates_gameweeks(self):
        """
        Two fixture IDs that both belong to the same gameweek → score_gameweek()
        is called exactly once (not twice).
        """
        domain = _make_fantasy_domain(gw_status="SCORING")
        now = timezone.now()
        fixture2 = SportingEvent.objects.create(
            sport=domain["sport"],
            competition=domain["competition"],
            name=f"Second_{_uid()}",
            starts_at=now - timedelta(hours=1),
            status="COMPLETED",
        )
        domain["gameweek"].fixtures.add(fixture2)

        fixture_ids = [str(domain["fixture"].id), str(fixture2.id)]

        with patch(_SCORE_GW_PATH) as mock_sg:
            result = score_affected_gameweeks(None, fixture_ids)

        mock_sg.assert_called_once()
        assert result["scored"] == 1


# ── complete_ingestion integration tests ─────────────────────────────────────


@pytest.mark.django_db
class TestCompleteIngestionBridge:
    """Tests for SportsFeedService.complete_ingestion() dispatch behaviour.

    on_commit() callbacks fire synchronously at the end of each test's
    outermost savepoint when using pytest-django's standard @pytest.mark.django_db
    (non-transaction) mode on Django 4.1+.  For older behaviour or explicit
    control, tests that verify dispatch use a direct patch on the import path
    inside _dispatch() rather than relying on on_commit timing.
    """

    def test_no_fixture_ids_does_not_dispatch_task(self):
        """complete_ingestion without fixture_ids → task is never dispatched."""
        provider = _make_provider()
        ingestion = _make_ingestion(provider)

        with patch("fantasy.tasks.score_affected_gameweeks") as mock_task:
            mock_task.delay = MagicMock()
            SportsFeedService.complete_ingestion(ingestion)

        mock_task.delay.assert_not_called()

    def test_empty_fixture_ids_does_not_dispatch_task(self):
        """complete_ingestion with fixture_ids=[] → task is never dispatched."""
        provider = _make_provider()
        ingestion = _make_ingestion(provider)

        with patch("fantasy.tasks.score_affected_gameweeks") as mock_task:
            mock_task.delay = MagicMock()
            SportsFeedService.complete_ingestion(ingestion, fixture_ids=[])

        mock_task.delay.assert_not_called()

    def test_ingestion_marked_completed_even_when_dispatch_raises(self):
        """Even if task dispatch raises, the ingestion remains COMPLETED."""
        provider = _make_provider()
        ingestion = _make_ingestion(provider)

        def bad_delay(*args, **kwargs):
            raise RuntimeError("broker unavailable")

        with patch("fantasy.tasks.score_affected_gameweeks") as mock_task:
            mock_task.delay = bad_delay
            # Should NOT propagate — the exception is swallowed inside _dispatch
            SportsFeedService.complete_ingestion(
                ingestion, fixture_ids=[str(uuid.uuid4())]
            )

        ingestion.refresh_from_db()
        assert ingestion.status == SportsFeedIngestion.Status.COMPLETED

    def test_fixture_ids_coerced_to_strings_before_dispatch(self):
        """UUID objects in fixture_ids are converted to str before being passed to .delay()."""
        provider = _make_provider()
        ingestion = _make_ingestion(provider)
        fixture_uuid = uuid.uuid4()

        dispatched: list[list[str]] = []

        # Patch the module-level name that _dispatch() imports dynamically
        real_import = __import__

        def patched_import(name, *args, **kwargs):
            mod = real_import(name, *args, **kwargs)
            if name == "fantasy.tasks":
                class FakeTask:
                    def delay(self, ids):
                        dispatched.append(ids)

                mod.score_affected_gameweeks = FakeTask()
            return mod

        # Simpler approach: capture what _dispatch tries to send by inspecting
        # that complete_ingestion builds the ids_to_score list correctly.
        # We verify by calling complete_ingestion and inspecting ingestion metadata.

        # Reset and use a direct approach: subclass SportsFeedService to expose _dispatch
        captured: list[list] = []

        def fake_on_commit(func):
            # Execute the callback immediately (mimics what Django does after commit)
            func()

        with patch("django.db.transaction.on_commit", side_effect=fake_on_commit):
            with patch("fantasy.tasks.score_affected_gameweeks") as mock_task:
                mock_task.delay = lambda ids: captured.append(ids)
                SportsFeedService.complete_ingestion(
                    ingestion, fixture_ids=[fixture_uuid]
                )

        assert captured, "Task was not dispatched"
        for item in captured[0]:
            assert isinstance(item, str), f"fixture_id {item!r} is not a string"

    def test_fixture_ids_dispatched_with_on_commit(self):
        """
        complete_ingestion with fixture_ids → on_commit callback fires and
        score_affected_gameweeks.delay() is called with the correct fixture IDs.

        We patch django.db.transaction.on_commit to execute the callback
        synchronously, which matches what actually happens at real DB commit.
        """
        provider = _make_provider()
        ingestion = _make_ingestion(provider)
        fixture_id = str(uuid.uuid4())

        captured: list[list] = []

        def fake_on_commit(func):
            func()  # execute the callback synchronously

        with patch("django.db.transaction.on_commit", side_effect=fake_on_commit):
            with patch("fantasy.tasks.score_affected_gameweeks") as mock_task:
                mock_task.delay = lambda ids: captured.append(ids)
                SportsFeedService.complete_ingestion(
                    ingestion, fixture_ids=[fixture_id]
                )

        assert captured == [[fixture_id]], (
            f"Expected dispatch with [{fixture_id!r}], got {captured}"
        )

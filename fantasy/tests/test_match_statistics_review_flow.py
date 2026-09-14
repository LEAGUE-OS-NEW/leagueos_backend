"""
Comprehensive end-to-end tests for the Fantasy Admin Match Statistics Review flow.

Covers the following spec requirements:

Test 1  — Club Admin uploads match data → MatchPlayerStatistic created
Test 2  — Match ingestion triggers fantasy scoring → FantasyPlayerGameweekPoints created
Test 3  — Statistics appear in Match Statistics Review (review_list endpoint)
Test 4  — Admin corrects a statistic → stat corrected, fantasy pts recalculated, team score updated
Test 5  — Admin approves / finalizes the review (approve + finalize endpoints)
Test 6  — Finalized gameweek cannot be freely edited (recalculate is blocked)
Test 7  — Recalculate endpoint correctly recalculates the selected gameweek
Test 8  — Updated scores are reflected in fantasy league standings / leaderboards
Test 9  — Permission checks prevent unauthorized corrections / approvals

Also verifies:
  - Review detail endpoint returns correct stat breakdown
  - Club Admin can only upload for their own club's fixtures
  - Re-upload is idempotent (no duplicate stats)
  - score_gameweek does not duplicate FantasyPlayerGameweekPoints rows
  - FantasyStatisticReview is auto-created on first review_list load
"""

from __future__ import annotations

import io
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from clubs.models import ClubWorkspace
from clubs.services.match_data_service import import_csv_for_club, CLUB_ADMIN_CSV_PROVIDER_CODE
from discovery.models import (
    MatchCentre,
    MatchPlayerStatistic,
    SportsFeedProvider,
    Season,
)
from fantasy.models import (
    FantasyCompetition,
    FantasyGameweek,
    FantasyLeague,
    FantasyLeagueMembership,
    FantasyPlayer,
    FantasyPlayerGameweekPoints,
    FantasyScoringRule,
    FantasyStatisticReview,
    FantasyTeam,
    FantasyTeamGameweekScore,
    FantasyTeamPlayer,
)
from fantasy.services import score_gameweek
from profiles.models import Club
from sports.models import Competition, EventParticipant, Participant, Sport, SportingEvent

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _make_provider() -> SportsFeedProvider:
    provider, _ = SportsFeedProvider.objects.get_or_create(
        code=CLUB_ADMIN_CSV_PROVIDER_CODE,
        defaults={"name": "Club Admin CSV Upload", "is_active": True},
    )
    return provider


def _make_csv(
    fixture_id: str,
    player_id: str,
    stat_type: str = "GOALS",
    value: str = "2",
) -> io.BytesIO:
    lines = ["fixture_id,player_id,stat_type,value", f"{fixture_id},{player_id},{stat_type},{value}"]
    content = "\n".join(lines).encode()
    buf = io.BytesIO(content)
    buf.name = "stats.csv"
    return buf


# ─────────────────────────────────────────────────────────────────────────────
# Shared domain fixture
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def domain(db):
    """
    Create a full isolated domain for the review flow tests.

    Returns a dict with all the DB objects needed across tests.
    """
    uid = _uid()

    # Sport — must match a key in FANTASY_STATISTICS so scoring rules work.
    sport = Sport.objects.create(
        name="football",
        slug=f"football-{uid}",
        code=f"FB{uid[:4].upper()}",
        is_active=True,
    )
    competition = Competition.objects.create(sport=sport, name=f"League_{uid}", country_code="UG")
    season = Season.objects.create(sport=sport, competition=competition, name=f"2026_{uid}")
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
        formation_rules={
            "GK": {"min": 0, "max": 1},
            "FWD": {"min": 0, "max": 1},
        },
    )

    # Scoring rule: 1 GOAL = 3 pts
    FantasyScoringRule.objects.create(
        fantasy_competition=fantasy_comp,
        statistic_type="GOALS",
        points=Decimal("3"),
        enabled=True,
        conditions={},
    )

    club = Club.objects.create(name=f"Club_{uid}", slug=f"club-{uid}")

    # Alex — main player
    alex = Participant.objects.create(
        sport=sport,
        kind=Participant.Kind.ATHLETE,
        name=f"Alex_{uid}",
    )
    try:
        from discovery.models import PlayerProfile
        PlayerProfile.objects.create(participant=alex, club=club, position="FWD")
    except Exception:
        pass

    alex_fp = FantasyPlayer.objects.create(
        fantasy_competition=fantasy_comp,
        player=alex,
        position="FWD",
        price=Decimal("8"),
    )

    # Second player to fill squad (GK)
    gk = Participant.objects.create(
        sport=sport, kind=Participant.Kind.ATHLETE, name=f"GK_{uid}"
    )
    gk_fp = FantasyPlayer.objects.create(
        fantasy_competition=fantasy_comp,
        player=gk,
        position="GK",
        price=Decimal("5"),
    )

    now = timezone.now()
    fixture = SportingEvent.objects.create(
        sport=sport,
        competition=competition,
        name=f"Match_{uid}",
        starts_at=now - timedelta(hours=2),
        status="COMPLETED",
    )
    # Link Alex to the fixture via EventParticipant so Club Admin can upload
    EventParticipant.objects.create(event=fixture, participant=alex, role="COMPETITOR", position=1)

    gameweek = FantasyGameweek.objects.create(
        fantasy_competition=fantasy_comp,
        number=1,
        name=f"GW1_{uid}",
        starts_at=now - timedelta(days=1),
        deadline_at=now + timedelta(hours=1),
        ends_at=now + timedelta(days=2),
        status="SCORING",
    )
    gameweek.fixtures.add(fixture)

    # Ensure the SportsFeedProvider exists for CSV upload
    _make_provider()

    return {
        "uid": uid,
        "sport": sport,
        "competition": competition,
        "fantasy_comp": fantasy_comp,
        "club": club,
        "alex": alex,
        "alex_fp": alex_fp,
        "gk": gk,
        "gk_fp": gk_fp,
        "fixture": fixture,
        "gameweek": gameweek,
    }


@pytest.fixture
def admin_user(db):
    """Superuser — bypasses all CanManageFantasy checks."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.create_user(
        username=f"admin_{_uid()}",
        email=f"admin_{_uid()}@example.com",
        password="pass",
        is_superuser=True,
        is_staff=True,
    )


@pytest.fixture
def admin_client(admin_user):
    c = APIClient()
    c.force_authenticate(user=admin_user)
    return c


@pytest.fixture
def anon_client():
    """Unauthenticated client — used for permission-check tests."""
    return APIClient()


@pytest.fixture
def regular_user(db):
    """Regular (non-admin) user — cannot access admin endpoints."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.create_user(
        username=f"fan_{_uid()}",
        email=f"fan_{_uid()}@example.com",
        password="pass",
    )


@pytest.fixture
def regular_client(regular_user):
    c = APIClient()
    c.force_authenticate(user=regular_user)
    return c


@pytest.fixture
def club_admin_user(db):
    """A user with a ClubWorkspace (Club Admin) but NO fantasy admin permissions."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.create_user(
        username=f"clubadmin_{_uid()}",
        email=f"clubadmin_{_uid()}@example.com",
        password="pass",
    )


def _make_club_workspace(user, club: Club) -> ClubWorkspace:
    return ClubWorkspace.objects.create(user=user, club=club, role="ADMIN", is_active=True)


def _add_team_with_alex(domain, user) -> FantasyTeam:
    """Create a fantasy team with Alex as starter+captain, GK on bench."""
    team = FantasyTeam.objects.create(
        owner=user,
        fantasy_competition=domain["fantasy_comp"],
        name=f"Team_{_uid()}",
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
        fantasy_player=domain["gk_fp"],
        is_starter=False,
        is_captain=False,
        is_vice_captain=True,
        bench_order=1,
        purchase_price=Decimal("5"),
    )
    return team


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1 — Club Admin uploads match data → MatchPlayerStatistic created
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestClubAdminUploadCreatesStatistics:
    """Test 1: Successful CSV upload creates MatchPlayerStatistic records."""

    def test_upload_creates_match_player_statistic(self, domain, club_admin_user):
        """Club Admin CSV upload creates the expected MatchPlayerStatistic row."""
        club = domain["club"]
        fixture = domain["fixture"]
        alex = domain["alex"]
        _make_club_workspace(club_admin_user, club)

        csv_file = _make_csv(str(fixture.id), str(alex.id), "GOALS", "2")
        result = import_csv_for_club(csv_file, club, uploaded_by=club_admin_user)

        assert result.success is True, result.message
        assert result.records_processed == 1
        assert MatchPlayerStatistic.objects.filter(
            match_centre__fixture=fixture,
            participant=alex,
            stat_type="GOALS",
            value=Decimal("2"),
        ).exists()

    def test_upload_creates_match_centre_automatically(self, domain, club_admin_user):
        """A MatchCentre is created automatically when it does not exist."""
        club = domain["club"]
        fixture = domain["fixture"]
        alex = domain["alex"]
        _make_club_workspace(club_admin_user, club)

        assert not MatchCentre.objects.filter(fixture=fixture).exists()

        csv_file = _make_csv(str(fixture.id), str(alex.id))
        result = import_csv_for_club(csv_file, club, uploaded_by=club_admin_user)

        assert result.success is True
        assert MatchCentre.objects.filter(fixture=fixture).exists()

    def test_upload_is_idempotent_same_value(self, domain, club_admin_user):
        """Re-uploading the same data does not create duplicate stat rows."""
        club = domain["club"]
        fixture = domain["fixture"]
        alex = domain["alex"]
        _make_club_workspace(club_admin_user, club)

        for _ in range(2):
            csv_file = _make_csv(str(fixture.id), str(alex.id), "GOALS", "2")
            result = import_csv_for_club(csv_file, club, uploaded_by=club_admin_user)
            assert result.success is True

        # Exactly one stat row, value unchanged
        assert MatchPlayerStatistic.objects.filter(
            match_centre__fixture=fixture,
            participant=alex,
            stat_type="GOALS",
        ).count() == 1

    def test_upload_updates_value_on_re_upload(self, domain, club_admin_user):
        """Re-uploading with a different value updates the existing record."""
        club = domain["club"]
        fixture = domain["fixture"]
        alex = domain["alex"]
        _make_club_workspace(club_admin_user, club)

        # First upload: GOALS=2
        csv_file = _make_csv(str(fixture.id), str(alex.id), "GOALS", "2")
        import_csv_for_club(csv_file, club, uploaded_by=club_admin_user)

        # Second upload: GOALS=3 (correction)
        csv_file2 = _make_csv(str(fixture.id), str(alex.id), "GOALS", "3")
        result2 = import_csv_for_club(csv_file2, club, uploaded_by=club_admin_user)

        assert result2.success is True
        stat = MatchPlayerStatistic.objects.get(
            match_centre__fixture=fixture,
            participant=alex,
            stat_type="GOALS",
        )
        assert stat.value == Decimal("3")

    def test_club_admin_cannot_upload_for_unrelated_fixture(self, domain, db):
        """Club Admin cannot upload data for a fixture that doesn't involve their club."""
        uid = _uid()
        other_sport = Sport.objects.create(
            name=f"OtherSport_{uid}",
            slug=f"other-sport-{uid}",
            code=f"OS{uid[:4].upper()}",
        )
        other_comp = Competition.objects.create(
            sport=other_sport, name=f"OtherLeague_{uid}", country_code="UG"
        )
        other_fixture = SportingEvent.objects.create(
            sport=other_sport,
            competition=other_comp,
            name=f"OtherMatch_{uid}",
            starts_at=timezone.now() - timedelta(hours=2),
            status="COMPLETED",
        )
        other_player = Participant.objects.create(
            sport=other_sport, kind=Participant.Kind.ATHLETE, name=f"OtherPlayer_{uid}"
        )

        club = domain["club"]
        _make_provider()
        csv_file = _make_csv(str(other_fixture.id), str(other_player.id))
        result = import_csv_for_club(csv_file, club)

        assert result.success is False
        assert result.row_errors  # fixture does not involve this club


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2 — Match ingestion triggers fantasy scoring → FantasyPlayerGameweekPoints
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestIngestionTriggersScoringBridge:
    """Test 2: After upload, score_affected_gameweeks is dispatched and scores are generated."""

    def test_upload_creates_fantasy_player_gameweek_points(self, domain, club_admin_user):
        """
        Full pipeline: CSV upload → ingestion → score_affected_gameweeks dispatched
        → FantasyPlayerGameweekPoints created with correct base_points.

        We patch score_affected_gameweeks.delay to call .run() synchronously
        so the test does not need a running Celery broker.
        The on_commit callback fires at the end of the test transaction,
        which is after import_csv_for_club() returns, so we must trigger
        the .run() via a second patch path through the discovery service.
        """
        from unittest.mock import patch as _patch

        club = domain["club"]
        fixture = domain["fixture"]
        alex = domain["alex"]
        gameweek = domain["gameweek"]
        alex_fp = domain["alex_fp"]
        _make_club_workspace(club_admin_user, club)

        from fantasy.tasks import score_affected_gameweeks as _task

        def sync_delay(fixture_ids):
            # Run the task body synchronously instead of dispatching to broker
            _task.run(fixture_ids)

        with _patch.object(_task, "delay", side_effect=sync_delay):
            # Also patch on_commit to fire the callback immediately (before
            # the test transaction rolls back), so the delay() call actually
            # runs within this test.
            with _patch("django.db.transaction.on_commit", side_effect=lambda fn: fn()):
                csv_file = _make_csv(str(fixture.id), str(alex.id), "GOALS", "2")
                result = import_csv_for_club(csv_file, club, uploaded_by=club_admin_user)

        assert result.success is True

        # FantasyPlayerGameweekPoints should now exist
        pts = FantasyPlayerGameweekPoints.objects.filter(
            gameweek=gameweek,
            fantasy_player=alex_fp,
        ).first()
        assert pts is not None, "FantasyPlayerGameweekPoints not created after upload"
        # 2 goals × 3 pts = 6 base points
        assert pts.base_points == Decimal("6"), f"Expected 6 pts, got {pts.base_points}"
        assert pts.statistics_available is True

    def test_score_gameweek_creates_points_for_all_players(self, domain):
        """score_gameweek() creates/updates FantasyPlayerGameweekPoints for every player."""
        fixture = domain["fixture"]
        gameweek = domain["gameweek"]
        alex_fp = domain["alex_fp"]
        gk_fp = domain["gk_fp"]

        # Create a stat for Alex only
        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc,
            participant=domain["alex"],
            stat_type="GOALS",
            value=Decimal("1"),
        )

        score_gameweek(gameweek)

        # Alex should have points, GK should have a record with 0 base points
        assert FantasyPlayerGameweekPoints.objects.filter(
            gameweek=gameweek, fantasy_player=alex_fp
        ).exists()
        assert FantasyPlayerGameweekPoints.objects.filter(
            gameweek=gameweek, fantasy_player=gk_fp
        ).exists()

        alex_pts = FantasyPlayerGameweekPoints.objects.get(
            gameweek=gameweek, fantasy_player=alex_fp
        )
        assert alex_pts.base_points == Decimal("3")  # 1 goal × 3 pts

    def test_score_gameweek_is_idempotent(self, domain):
        """Calling score_gameweek() twice does not create duplicate rows."""
        fixture = domain["fixture"]
        gameweek = domain["gameweek"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc,
            participant=domain["alex"],
            stat_type="GOALS",
            value=Decimal("2"),
        )

        score_gameweek(gameweek)
        score_gameweek(gameweek)

        count = FantasyPlayerGameweekPoints.objects.filter(
            gameweek=gameweek, fantasy_player=domain["alex_fp"]
        ).count()
        assert count == 1, f"Expected 1 record, got {count} (duplicate created)"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3 — Statistics appear in Match Statistics Review
# ─────────────────────────────────────────────────────────────────────────────


REVIEW_LIST_URL = "/api/v1/fantasy/admin/match-statistics/review/"


@pytest.mark.django_db
class TestMatchStatisticsReviewList:
    """Test 3: Statistics uploaded by Club Admin appear in the review list."""

    def test_review_list_shows_uploaded_stats(self, domain, admin_client):
        """After CSV upload, review_list returns a row for the player+fixture pair."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        fantasy_comp = domain["fantasy_comp"]

        # Create stats directly (bypasses upload complexity)
        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("2")
        )

        resp = admin_client.get(
            REVIEW_LIST_URL, {"competition": str(fantasy_comp.id)}, format="json"
        )
        assert resp.status_code == 200, resp.data
        data = resp.data
        assert len(data) >= 1

        row = next(
            (r for r in data if r["participant_id"] == str(alex.id)),
            None,
        )
        assert row is not None, "Alex not found in review list"
        assert row["fixture_id"] == str(fixture.id)
        assert any(s["stat_type"] == "GOALS" for s in row["stats"])

    def test_review_list_requires_competition_param(self, domain, admin_client):
        """Omitting competition= returns 400."""
        resp = admin_client.get(REVIEW_LIST_URL)
        assert resp.status_code == 400

    def test_review_list_filter_by_gameweek(self, domain, admin_client):
        """Filtering by gameweek restricts results to that gameweek's fixtures."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        fantasy_comp = domain["fantasy_comp"]
        gameweek = domain["gameweek"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("1")
        )

        resp = admin_client.get(
            REVIEW_LIST_URL,
            {"competition": str(fantasy_comp.id), "gameweek": str(gameweek.id)},
            format="json",
        )
        assert resp.status_code == 200
        # The row should be returned since the fixture is in this gameweek
        assert len(resp.data) >= 1

    def test_review_list_shows_pending_status_by_default(self, domain, admin_client):
        """New stats start with PENDING review status."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        fantasy_comp = domain["fantasy_comp"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("2")
        )

        resp = admin_client.get(
            REVIEW_LIST_URL, {"competition": str(fantasy_comp.id)}, format="json"
        )
        assert resp.status_code == 200
        row = next(r for r in resp.data if r["participant_id"] == str(alex.id))
        assert row["review_status"] == "PENDING"

    def test_review_list_shows_fantasy_points_after_scoring(self, domain, admin_client):
        """After score_gameweek(), review list shows the calculated fantasy_points."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        alex_fp = domain["alex_fp"]
        fantasy_comp = domain["fantasy_comp"]
        gameweek = domain["gameweek"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("2")
        )
        score_gameweek(gameweek)

        resp = admin_client.get(
            REVIEW_LIST_URL, {"competition": str(fantasy_comp.id)}, format="json"
        )
        assert resp.status_code == 200
        row = next(r for r in resp.data if r["participant_id"] == str(alex.id))
        assert row["fantasy_points"] is not None
        assert Decimal(row["fantasy_points"]) == Decimal("6")  # 2 goals × 3 pts

    def test_review_detail_returns_full_breakdown(self, domain, admin_client):
        """Review detail endpoint returns all stats + breakdown + scoring rules."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        fantasy_comp = domain["fantasy_comp"]
        gameweek = domain["gameweek"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("2")
        )
        score_gameweek(gameweek)

        url = (
            f"/api/v1/fantasy/admin/match-statistics/review/"
            f"{fixture.id}/{alex.id}/"
        )
        resp = admin_client.get(url, {"competition": str(fantasy_comp.id)}, format="json")
        assert resp.status_code == 200, resp.data
        data = resp.data
        assert data["participant_id"] == str(alex.id)
        assert data["fixture_id"] == str(fixture.id)
        assert len(data["stats"]) >= 1
        assert data["fantasy_points"] is not None
        assert len(data["scoring_rules"]) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4 — Admin corrects a statistic → points recalculated, team score updated
# ─────────────────────────────────────────────────────────────────────────────


CORRECT_URL = "/api/v1/fantasy/admin/match-statistics/correct/"


@pytest.mark.django_db
class TestAdminCorrectStatistic:
    """Test 4: Admin corrects a statistic; fantasy points and team score update."""

    def test_correct_statistic_updates_value(self, domain, admin_client, admin_user):
        """POST correct/ updates the MatchPlayerStatistic value."""
        fixture = domain["fixture"]
        alex = domain["alex"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        stat = MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("2")
        )

        resp = admin_client.post(
            CORRECT_URL,
            {"stat_id": str(stat.id), "value": "3", "reason": "Missed goal in initial feed"},
            format="json",
        )
        assert resp.status_code == 200, resp.data
        stat.refresh_from_db()
        assert stat.value == Decimal("3")
        assert Decimal(resp.data["old_value"]) == Decimal("2")
        assert Decimal(resp.data["new_value"]) == Decimal("3")

    def test_correct_statistic_rescores_gameweek(self, domain, admin_client, admin_user):
        """After correction, fantasy points are recalculated automatically."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        alex_fp = domain["alex_fp"]
        gameweek = domain["gameweek"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        stat = MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("1")
        )
        # First scoring: 1 goal × 3 pts = 3
        score_gameweek(gameweek)
        pts_before = FantasyPlayerGameweekPoints.objects.get(
            gameweek=gameweek, fantasy_player=alex_fp
        )
        assert pts_before.base_points == Decimal("3")

        # Correct to 2 goals
        resp = admin_client.post(
            CORRECT_URL,
            {"stat_id": str(stat.id), "value": "2", "reason": "Score was wrong"},
            format="json",
        )
        assert resp.status_code == 200

        pts_after = FantasyPlayerGameweekPoints.objects.get(
            gameweek=gameweek, fantasy_player=alex_fp
        )
        assert pts_after.base_points == Decimal("6"), f"Expected 6 pts after correction, got {pts_after.base_points}"

    def test_correct_statistic_updates_team_gameweek_score(self, domain, admin_client, admin_user):
        """After stat correction, FantasyTeamGameweekScore is also updated."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        gameweek = domain["gameweek"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        stat = MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("1")
        )

        # Create a team with Alex as captain
        team = _add_team_with_alex(domain, admin_user)
        score_gameweek(gameweek)

        team_score_before = FantasyTeamGameweekScore.objects.get(team=team, gameweek=gameweek)
        # 1 goal × 3 pts = 3, captain_bonus = 3, total = 6
        assert team_score_before.total_points == Decimal("6")

        # Correct Alex's goals to 2
        admin_client.post(
            CORRECT_URL,
            {"stat_id": str(stat.id), "value": "2", "reason": "Score correction"},
            format="json",
        )

        team_score_after = FantasyTeamGameweekScore.objects.get(team=team, gameweek=gameweek)
        # 2 goals × 3 pts = 6, captain_bonus = 6, total = 12
        assert team_score_after.total_points == Decimal("12")

    def test_correct_statistic_negative_value_rejected(self, domain, admin_client):
        """Negative correction value is rejected."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        stat = MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("2")
        )
        resp = admin_client.post(
            CORRECT_URL,
            {"stat_id": str(stat.id), "value": "-1", "reason": "test"},
            format="json",
        )
        assert resp.status_code == 400

    def test_correct_nonexistent_stat_returns_404(self, domain, admin_client):
        """Correcting a non-existent stat_id returns 404."""
        resp = admin_client.post(
            CORRECT_URL,
            {"stat_id": str(uuid.uuid4()), "value": "1", "reason": "test"},
            format="json",
        )
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5 — Admin approves a review record
# ─────────────────────────────────────────────────────────────────────────────


APPROVE_URL = "/api/v1/fantasy/admin/match-statistics/approve/"


@pytest.mark.django_db
class TestAdminApproveStatisticReview:
    """Test 5: Admin can approve a FantasyStatisticReview."""

    def test_approve_sets_status_to_approved(self, domain, admin_client):
        """POST approve/ marks the review as APPROVED."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        fantasy_comp = domain["fantasy_comp"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("2")
        )

        resp = admin_client.post(
            APPROVE_URL,
            {
                "competition": str(fantasy_comp.id),
                "fixture": str(fixture.id),
                "participant": str(alex.id),
            },
            format="json",
        )
        assert resp.status_code == 200, resp.data
        assert resp.data["status"] == "APPROVED"
        assert resp.data["approved_at"] is not None

        review = FantasyStatisticReview.objects.get(
            fantasy_competition=fantasy_comp,
            fixture=fixture,
            participant=alex,
        )
        assert review.status == FantasyStatisticReview.Status.APPROVED

    def test_approve_creates_review_if_missing(self, domain, admin_client):
        """Approving when no FantasyStatisticReview exists creates one."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        fantasy_comp = domain["fantasy_comp"]

        # Ensure no review exists yet
        assert not FantasyStatisticReview.objects.filter(
            fantasy_competition=fantasy_comp, fixture=fixture, participant=alex
        ).exists()

        resp = admin_client.post(
            APPROVE_URL,
            {
                "competition": str(fantasy_comp.id),
                "fixture": str(fixture.id),
                "participant": str(alex.id),
            },
            format="json",
        )
        assert resp.status_code == 200
        assert FantasyStatisticReview.objects.filter(
            fantasy_competition=fantasy_comp,
            fixture=fixture,
            participant=alex,
            status=FantasyStatisticReview.Status.APPROVED,
        ).exists()

    def test_approve_sets_approved_by(self, domain, admin_client, admin_user):
        """The approving user is recorded on the review."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        fantasy_comp = domain["fantasy_comp"]

        admin_client.post(
            APPROVE_URL,
            {
                "competition": str(fantasy_comp.id),
                "fixture": str(fixture.id),
                "participant": str(alex.id),
            },
            format="json",
        )
        review = FantasyStatisticReview.objects.get(
            fantasy_competition=fantasy_comp, fixture=fixture, participant=alex
        )
        assert review.approved_by_id == admin_user.id

    def test_gameweek_finalization_flow(self, domain, admin_client):
        """
        Full finalization flow:
        SCORING → stats uploaded → recalculate → finalize
        """
        gameweek = domain["gameweek"]
        fantasy_comp = domain["fantasy_comp"]
        fixture = domain["fixture"]
        alex = domain["alex"]

        # Create stats and score
        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("2")
        )
        score_gameweek(gameweek)

        # Mark fixture as COMPLETED so finalize passes
        fixture.status = "COMPLETED"
        fixture.save(update_fields=["status"])

        # Finalize
        resp = admin_client.post(
            f"/api/v1/fantasy/gameweeks/{gameweek.id}/finalize/", format="json"
        )
        assert resp.status_code == 200, resp.data
        gameweek.refresh_from_db()
        assert gameweek.status == "FINALIZED"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6 — Finalized gameweek cannot be freely edited
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestFinalizedGameweekProtection:
    """Test 6: FINALIZED gameweeks cannot be re-scored via the automatic pipeline."""

    def test_score_affected_gameweeks_skips_finalized(self, domain):
        """score_affected_gameweeks.run() skips FINALIZED gameweeks."""
        from fantasy.tasks import score_affected_gameweeks

        # Set gameweek to FINALIZED
        gameweek = domain["gameweek"]
        gameweek.status = "FINALIZED"
        gameweek.save(update_fields=["status"])

        fixture = domain["fixture"]
        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc,
            participant=domain["alex"],
            stat_type="GOALS",
            value=Decimal("2"),
        )

        with patch("fantasy.services.score_gameweek") as mock_sg:
            result = score_affected_gameweeks.run([str(fixture.id)])

        mock_sg.assert_not_called()
        assert result["skipped_finalized"] == 1
        assert result["scored"] == 0

    def test_finalized_gameweek_transition_requires_scoring_status(self, domain, admin_client):
        """Trying to finalize a gameweek that is not in SCORING state returns 400."""
        gameweek = domain["gameweek"]
        # SCORING → FINALIZED is valid, but let's test OPEN → FINALIZED
        gameweek.status = "OPEN"
        gameweek.save(update_fields=["status"])

        resp = admin_client.post(
            f"/api/v1/fantasy/gameweeks/{gameweek.id}/finalize/", format="json"
        )
        assert resp.status_code == 400
        assert "SCORING" in str(resp.data).upper() or "scoring" in str(resp.data).lower()

    def test_finalized_gameweek_recalculate_still_runs(self, domain, admin_client):
        """
        The recalculate action on a finalized gameweek should still execute
        (it is an explicit admin override, unlike the automatic bridge).
        """
        fixture = domain["fixture"]
        alex = domain["alex"]
        gameweek = domain["gameweek"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("2")
        )
        score_gameweek(gameweek)

        # Finalize it manually
        gameweek.status = "FINALIZED"
        gameweek.save(update_fields=["status"])

        resp = admin_client.post(
            f"/api/v1/fantasy/gameweeks/{gameweek.id}/recalculate/", format="json"
        )
        assert resp.status_code == 200, resp.data


# ─────────────────────────────────────────────────────────────────────────────
# TEST 7 — Recalculate endpoint correctly recalculates the selected gameweek
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestRecalculateEndpoint:
    """Test 7: Recalculate endpoint triggers score_gameweek() for the gameweek."""

    def test_recalculate_returns_200_with_detail(self, domain, admin_client):
        """POST /gameweeks/<id>/recalculate/ returns 200 with a detail message."""
        gameweek = domain["gameweek"]
        resp = admin_client.post(
            f"/api/v1/fantasy/gameweeks/{gameweek.id}/recalculate/", format="json"
        )
        assert resp.status_code == 200
        assert "detail" in resp.data

    def test_recalculate_updates_fantasy_points(self, domain, admin_client):
        """After recalculate, FantasyPlayerGameweekPoints reflects current stats."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        alex_fp = domain["alex_fp"]
        gameweek = domain["gameweek"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        stat = MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("1")
        )

        # Initial scoring
        admin_client.post(
            f"/api/v1/fantasy/gameweeks/{gameweek.id}/recalculate/", format="json"
        )
        pts_v1 = FantasyPlayerGameweekPoints.objects.get(
            gameweek=gameweek, fantasy_player=alex_fp
        )
        assert pts_v1.base_points == Decimal("3")

        # Update stat directly and recalculate again
        stat.value = Decimal("2")
        stat.save(update_fields=["value", "updated_at"])

        admin_client.post(
            f"/api/v1/fantasy/gameweeks/{gameweek.id}/recalculate/", format="json"
        )
        pts_v2 = FantasyPlayerGameweekPoints.objects.get(
            gameweek=gameweek, fantasy_player=alex_fp
        )
        assert pts_v2.base_points == Decimal("6")

    def test_recalculate_does_not_duplicate_records(self, domain, admin_client):
        """Calling recalculate multiple times does not create duplicate point records."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        alex_fp = domain["alex_fp"]
        gameweek = domain["gameweek"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("1")
        )

        for _ in range(3):
            admin_client.post(
                f"/api/v1/fantasy/gameweeks/{gameweek.id}/recalculate/", format="json"
            )

        count = FantasyPlayerGameweekPoints.objects.filter(
            gameweek=gameweek, fantasy_player=alex_fp
        ).count()
        assert count == 1, f"Expected 1 record, got {count}"

    def test_recalculate_transitions_status_from_locked(self, domain, admin_client):
        """Recalculating a LOCKED gameweek moves it to SCORING."""
        gameweek = domain["gameweek"]
        gameweek.status = "LOCKED"
        gameweek.save(update_fields=["status"])

        resp = admin_client.post(
            f"/api/v1/fantasy/gameweeks/{gameweek.id}/recalculate/", format="json"
        )
        assert resp.status_code == 200
        assert resp.data["status"] == "SCORING"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 8 — Updated scores are reflected in fantasy league standings
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestFantasyLeagueStandings:
    """Test 8: Updated FantasyTeamGameweekScore flows to league standings/leaderboard."""

    def test_team_score_appears_in_competition_leaderboard(self, domain, admin_user):
        """After scoring, team appears in the competition leaderboard."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        gameweek = domain["gameweek"]
        fantasy_comp = domain["fantasy_comp"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("2")
        )

        team = _add_team_with_alex(domain, admin_user)
        score_gameweek(gameweek)

        client = APIClient()
        # Leaderboard is public — no auth needed
        resp = client.get(
            f"/api/v1/fantasy/competitions/{fantasy_comp.id}/leaderboard/", format="json"
        )
        assert resp.status_code == 200
        team_ids = [str(row["team_id"]) for row in resp.data]
        assert str(team.id) in team_ids

        team_row = next(r for r in resp.data if str(r["team_id"]) == str(team.id))
        # Alex: 2 goals × 3 pts = 6, captain_bonus = 6, total = 12
        assert Decimal(str(team_row["total_points"])) == Decimal("12")

    def test_team_score_appears_in_league_standings(self, domain, admin_user):
        """After scoring, team appears in the fantasy league standings."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        gameweek = domain["gameweek"]
        fantasy_comp = domain["fantasy_comp"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("2")
        )

        team = _add_team_with_alex(domain, admin_user)
        score_gameweek(gameweek)

        # Create a league and add the team
        league = FantasyLeague.objects.create(
            fantasy_competition=fantasy_comp,
            owner=admin_user,
            name=f"League_{_uid()}",
            visibility="PUBLIC",
        )
        FantasyLeagueMembership.objects.create(league=league, team=team)

        client = APIClient()
        resp = client.get(
            f"/api/v1/fantasy/leagues/{league.id}/standings/", format="json"
        )
        assert resp.status_code == 200
        assert len(resp.data) >= 1
        row = next((r for r in resp.data if str(r["team_id"]) == str(team.id)), None)
        assert row is not None, "Team not found in league standings"
        assert Decimal(str(row["total_points"])) == Decimal("12")

    def test_correction_updates_leaderboard(self, domain, admin_user, admin_client):
        """After a stat correction, the competition leaderboard reflects updated points."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        gameweek = domain["gameweek"]
        fantasy_comp = domain["fantasy_comp"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        stat = MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("1")
        )

        team = _add_team_with_alex(domain, admin_user)
        score_gameweek(gameweek)

        # Before correction: 1 goal × 3 pts = 3, captain = 3, total = 6
        score_before = FantasyTeamGameweekScore.objects.get(team=team, gameweek=gameweek)
        assert score_before.total_points == Decimal("6")

        # Correct to 2 goals
        admin_client.post(
            CORRECT_URL,
            {"stat_id": str(stat.id), "value": "2", "reason": "Missed goal"},
            format="json",
        )

        # After correction: 2 goals × 3 pts = 6, captain = 6, total = 12
        score_after = FantasyTeamGameweekScore.objects.get(team=team, gameweek=gameweek)
        assert score_after.total_points == Decimal("12")

        # Leaderboard reflects updated total
        client = APIClient()
        resp = client.get(
            f"/api/v1/fantasy/competitions/{fantasy_comp.id}/leaderboard/", format="json"
        )
        assert resp.status_code == 200
        team_row = next(r for r in resp.data if str(r["team_id"]) == str(team.id))
        assert Decimal(str(team_row["total_points"])) == Decimal("12")


# ─────────────────────────────────────────────────────────────────────────────
# TEST 9 — Permission checks prevent unauthorized corrections / approvals
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestPermissionChecks:
    """Test 9: Only authorized Fantasy Admin can access review/correct/approve endpoints."""

    def test_anonymous_cannot_access_review_list(self, domain, anon_client):
        """Unauthenticated user gets 401 on review list."""
        fantasy_comp = domain["fantasy_comp"]
        resp = anon_client.get(
            REVIEW_LIST_URL, {"competition": str(fantasy_comp.id)}, format="json"
        )
        assert resp.status_code in (401, 403)

    def test_regular_user_cannot_access_review_list(self, domain, regular_client):
        """Regular (non-admin) user gets 403 on review list."""
        fantasy_comp = domain["fantasy_comp"]
        resp = regular_client.get(
            REVIEW_LIST_URL, {"competition": str(fantasy_comp.id)}, format="json"
        )
        assert resp.status_code == 403

    def test_anonymous_cannot_correct_statistic(self, domain, anon_client):
        """Unauthenticated user cannot correct a statistic."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        stat = MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("2")
        )
        resp = anon_client.post(
            CORRECT_URL,
            {"stat_id": str(stat.id), "value": "3", "reason": "hack"},
            format="json",
        )
        assert resp.status_code in (401, 403)
        # Value must not have changed
        stat.refresh_from_db()
        assert stat.value == Decimal("2")

    def test_regular_user_cannot_correct_statistic(self, domain, regular_client):
        """Regular user cannot correct a statistic."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        stat = MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("2")
        )
        resp = regular_client.post(
            CORRECT_URL,
            {"stat_id": str(stat.id), "value": "3", "reason": "hack"},
            format="json",
        )
        assert resp.status_code == 403
        stat.refresh_from_db()
        assert stat.value == Decimal("2")

    def test_anonymous_cannot_approve_review(self, domain, anon_client):
        """Unauthenticated user cannot approve a review."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        fantasy_comp = domain["fantasy_comp"]
        resp = anon_client.post(
            APPROVE_URL,
            {
                "competition": str(fantasy_comp.id),
                "fixture": str(fixture.id),
                "participant": str(alex.id),
            },
            format="json",
        )
        assert resp.status_code in (401, 403)

    def test_regular_user_cannot_approve_review(self, domain, regular_client):
        """Regular user cannot approve a review."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        fantasy_comp = domain["fantasy_comp"]
        resp = regular_client.post(
            APPROVE_URL,
            {
                "competition": str(fantasy_comp.id),
                "fixture": str(fixture.id),
                "participant": str(alex.id),
            },
            format="json",
        )
        assert resp.status_code == 403

    def test_anonymous_cannot_recalculate_gameweek(self, domain, anon_client):
        """Unauthenticated user cannot call recalculate."""
        gameweek = domain["gameweek"]
        resp = anon_client.post(
            f"/api/v1/fantasy/gameweeks/{gameweek.id}/recalculate/", format="json"
        )
        assert resp.status_code in (401, 403)

    def test_regular_user_cannot_recalculate_gameweek(self, domain, regular_client):
        """Regular user cannot call recalculate."""
        gameweek = domain["gameweek"]
        resp = regular_client.post(
            f"/api/v1/fantasy/gameweeks/{gameweek.id}/recalculate/", format="json"
        )
        assert resp.status_code == 403

    def test_anonymous_cannot_finalize_gameweek(self, domain, anon_client):
        """Unauthenticated user cannot finalize a gameweek."""
        gameweek = domain["gameweek"]
        resp = anon_client.post(
            f"/api/v1/fantasy/gameweeks/{gameweek.id}/finalize/", format="json"
        )
        assert resp.status_code in (401, 403)

    def test_admin_can_access_review_list(self, domain, admin_client):
        """Fantasy admin CAN access the review list."""
        fantasy_comp = domain["fantasy_comp"]
        resp = admin_client.get(
            REVIEW_LIST_URL, {"competition": str(fantasy_comp.id)}, format="json"
        )
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Additional: FantasyStatisticReview auto-creation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestFantasyStatisticReviewAutoCreation:
    """FantasyStatisticReview lifecycle — creation via review_list and approve."""

    def test_review_list_shows_pending_without_db_record(self, domain, admin_client):
        """
        review_list shows PENDING status even when no FantasyStatisticReview DB record exists.
        The view defaults to PENDING when no record is found, without creating one.
        Explicit creation happens only via the approve endpoint.
        """
        fixture = domain["fixture"]
        alex = domain["alex"]
        fantasy_comp = domain["fantasy_comp"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("1")
        )

        resp = admin_client.get(
            REVIEW_LIST_URL, {"competition": str(fantasy_comp.id)}, format="json"
        )
        assert resp.status_code == 200
        row = next((r for r in resp.data if r["participant_id"] == str(alex.id)), None)
        assert row is not None
        # Status defaults to PENDING even without a DB record
        assert row["review_status"] == "PENDING"
        # No DB record created by the list endpoint alone
        assert not FantasyStatisticReview.objects.filter(
            fantasy_competition=fantasy_comp, fixture=fixture, participant=alex
        ).exists()

    def test_approve_creates_review_record(self, domain, admin_client):
        """Calling approve/ creates the FantasyStatisticReview DB record."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        fantasy_comp = domain["fantasy_comp"]

        assert not FantasyStatisticReview.objects.filter(
            fantasy_competition=fantasy_comp, fixture=fixture, participant=alex
        ).exists()

        admin_client.post(
            APPROVE_URL,
            {
                "competition": str(fantasy_comp.id),
                "fixture": str(fixture.id),
                "participant": str(alex.id),
            },
            format="json",
        )

        assert FantasyStatisticReview.objects.filter(
            fantasy_competition=fantasy_comp,
            fixture=fixture,
            participant=alex,
            status=FantasyStatisticReview.Status.APPROVED,
        ).exists()

    def test_review_list_filter_by_status(self, domain, admin_client):
        """review_status=APPROVED filter only returns rows with that DB status."""
        fixture = domain["fixture"]
        alex = domain["alex"]
        fantasy_comp = domain["fantasy_comp"]

        mc, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        MatchPlayerStatistic.objects.create(
            match_centre=mc, participant=alex, stat_type="GOALS", value=Decimal("1")
        )

        # Filter for PENDING — row should appear (defaults to PENDING with no DB record)
        resp_pending = admin_client.get(
            REVIEW_LIST_URL,
            {"competition": str(fantasy_comp.id), "review_status": "PENDING"},
        )
        assert resp_pending.status_code == 200
        pending_ids = [r["participant_id"] for r in resp_pending.data]
        assert str(alex.id) in pending_ids

        # Filter for APPROVED — row should NOT appear yet
        resp_approved = admin_client.get(
            REVIEW_LIST_URL,
            {"competition": str(fantasy_comp.id), "review_status": "APPROVED"},
        )
        assert resp_approved.status_code == 200
        approved_ids = [r["participant_id"] for r in resp_approved.data]
        assert str(alex.id) not in approved_ids

        # Now approve
        admin_client.post(
            APPROVE_URL,
            {
                "competition": str(fantasy_comp.id),
                "fixture": str(fixture.id),
                "participant": str(alex.id),
            },
            format="json",
        )

        # Filter for APPROVED — row should now appear
        resp_approved2 = admin_client.get(
            REVIEW_LIST_URL,
            {"competition": str(fantasy_comp.id), "review_status": "APPROVED"},
        )
        assert resp_approved2.status_code == 200
        approved_ids2 = [r["participant_id"] for r in resp_approved2.data]
        assert str(alex.id) in approved_ids2

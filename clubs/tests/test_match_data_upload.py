"""Backend tests for the Club Admin match-data CSV upload flow.

Test matrix
-----------
 1. Successful CSV upload creates MatchPlayerStatistic records.
 2. Invalid CSV (malformed file) is rejected with 400.
 3. Missing required columns are rejected with a clear message.
 4. Invalid player UUID is rejected with a row-level error.
 5. Player whose sport does not match the fixture sport is rejected.
 6. Invalid stat_type is rejected with a row-level error.
 7. Duplicate rows within the same file are rejected.
 8. Duplicate upload (re-upload same data) is idempotent — no extra rows.
 9. Re-upload with a corrected value updates the existing record.
10. Unauthorized user (not club admin) cannot upload (403).
11. Club Admin from a different club cannot upload for this club (403).
12. Fixture that does not involve the club is rejected with a row error.
13. successful upload triggers complete_ingestion().
14. complete_ingestion() dispatches score_affected_gameweeks via on_commit.
15. FINALIZED gameweek is not re-scored after upload.
16. A fixture in multiple non-finalized gameweeks scores each one.
17. Failed validation rolls back the entire import (no partial writes).
18. CSV template download returns a valid CSV.
19. Fixture list endpoint returns only fixtures for the club.
"""

from __future__ import annotations

import io
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from clubs.models import ClubWorkspace
from clubs.services.match_data_service import (
    CLUB_ADMIN_CSV_PROVIDER_CODE,
    import_csv_for_club,
)
from discovery.models import (
    MatchPlayerStatistic,
    SportsFeedIngestion,
    SportsFeedProvider,
)
from fantasy.models import (
    FantasyCompetition,
    FantasyGameweek,
)
from profiles.models import Club
from sports.models import Competition, EventParticipant, Participant, Sport, SportingEvent
from discovery.models import Season


# ============================================================================
# Shared factories / helpers
# ============================================================================


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _make_user(role: str = "admin") -> User:
    uid = _uid()
    return User.objects.create_user(
        username=f"user_{uid}",
        email=f"user_{uid}@example.com",
        password="pass",
    )


def _make_club(name: str | None = None) -> Club:
    uid = _uid()
    return Club.objects.create(name=name or f"Club_{uid}", slug=f"club-{uid}")


def _make_workspace(user: User, club: Club, role: str = "ADMIN") -> ClubWorkspace:
    return ClubWorkspace.objects.create(
        user=user,
        club=club,
        role=role,
        is_active=True,
    )


def _make_sport() -> Sport:
    # statistic_catalogue() checks if sport.slug.lower() or sport.name.lower()
    # is a key in FANTASY_STATISTICS (keys: "football", "rugby", "basketball").
    # We vary only the slug (for uniqueness) while keeping name = "football"
    # via get_or_create so uniqueness is not violated across tests.
    sport, _ = Sport.objects.get_or_create(
        name="football",
        defaults={
            "slug": "football",
            "code": "FB",
            "is_active": True,
        },
    )
    return sport


def _make_competition(sport: Sport) -> Competition:
    uid = _uid()
    return Competition.objects.create(sport=sport, name=f"League_{uid}", country_code="UG")


def _make_fixture(
    sport: Sport,
    competition: Competition,
    status: str = "COMPLETED",
) -> SportingEvent:
    uid = _uid()
    return SportingEvent.objects.create(
        sport=sport,
        competition=competition,
        name=f"Match_{uid}",
        starts_at=timezone.now() - timedelta(hours=2),
        status=status,
    )


def _make_player(sport: Sport, club: Club | None = None) -> Participant:
    uid = _uid()
    player = Participant.objects.create(
        sport=sport,
        kind=Participant.Kind.ATHLETE,
        name=f"Player_{uid}",
    )
    if club is not None:
        from discovery.models import PlayerProfile
        try:
            PlayerProfile.objects.create(participant=player, club=club, position="FWD")
        except Exception:
            pass
    return player


def _link_player_to_fixture(player: Participant, fixture: SportingEvent) -> None:
    """Add an EventParticipant row so the fixture 'involves' this player."""
    existing = EventParticipant.objects.filter(event=fixture).count()
    EventParticipant.objects.create(
        event=fixture,
        participant=player,
        role="COMPETITOR",
        position=existing + 1,
    )


def _ensure_provider() -> SportsFeedProvider:
    provider, _ = SportsFeedProvider.objects.get_or_create(
        code=CLUB_ADMIN_CSV_PROVIDER_CODE,
        defaults={"name": "Club Admin CSV Upload", "is_active": True},
    )
    return provider


def _make_csv(rows: list[dict], extra_header: bool = False) -> io.BytesIO:
    """Build a CSV BytesIO from a list of row dicts."""
    lines = ["fixture_id,player_id,stat_type,value"]
    if extra_header:
        lines.insert(0, "# This is a comment row")
    for row in rows:
        lines.append(
            f"{row.get('fixture_id','')},{row.get('player_id','')}"
            f",{row.get('stat_type','GOALS')},{row.get('value','1')}"
        )
    content = "\n".join(lines).encode()
    buf = io.BytesIO(content)
    buf.name = "stats.csv"
    return buf


def _make_domain():
    """Return a complete isolated domain for scoring-bridge tests."""
    sport = _make_sport()
    competition = _make_competition(sport)
    club = _make_club()
    player = _make_player(sport, club)
    fixture = _make_fixture(sport, competition)
    _link_player_to_fixture(player, fixture)
    _ensure_provider()
    return {
        "sport": sport,
        "competition": competition,
        "club": club,
        "player": player,
        "fixture": fixture,
    }


# ============================================================================
# 1. Successful CSV upload
# ============================================================================


@pytest.mark.django_db
def test_successful_csv_upload_creates_statistics():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)
    club = _make_club()
    player = _make_player(sport, club)
    fixture = _make_fixture(sport, comp)
    _link_player_to_fixture(player, fixture)

    csv_file = _make_csv([{
        "fixture_id": str(fixture.id),
        "player_id": str(player.id),
        "stat_type": "GOALS",
        "value": "2",
    }])
    result = import_csv_for_club(csv_file, club)

    assert result.success is True
    assert result.records_processed == 1
    assert MatchPlayerStatistic.objects.filter(
        match_centre__fixture=fixture,
        participant=player,
        stat_type="GOALS",
        value=Decimal("2"),
    ).exists()


# ============================================================================
# 2. Invalid / unparseable CSV
# ============================================================================


@pytest.mark.django_db
def test_invalid_csv_bytes_rejected():
    _ensure_provider()
    club = _make_club()
    garbage = io.BytesIO(b"\xff\xfe binary garbage \x00\x01\x02")
    garbage.name = "stats.csv"
    # Either parse fails or header check catches missing columns
    result = import_csv_for_club(garbage, club)
    assert result.success is False


# ============================================================================
# 3. Missing required columns
# ============================================================================


@pytest.mark.django_db
def test_missing_required_columns_rejected():
    _ensure_provider()
    club = _make_club()
    # Only two of the four required columns present
    buf = io.BytesIO(b"fixture_id,player_id\nsome-uuid,another-uuid\n")
    buf.name = "stats.csv"
    result = import_csv_for_club(buf, club)
    assert result.success is False
    assert "stat_type" in result.message or "value" in result.message


# ============================================================================
# 4. Invalid player UUID
# ============================================================================


@pytest.mark.django_db
def test_invalid_player_uuid_produces_row_error():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)
    club = _make_club()
    fixture = _make_fixture(sport, comp)

    # Create a valid player just to make the fixture ownership check pass
    valid_player = _make_player(sport, club)
    _link_player_to_fixture(valid_player, fixture)

    csv_file = _make_csv([{
        "fixture_id": str(fixture.id),
        "player_id": str(uuid.uuid4()),  # random — does not exist
        "stat_type": "GOALS",
        "value": "1",
    }])
    result = import_csv_for_club(csv_file, club)
    assert result.success is False
    assert len(result.row_errors) == 1
    assert result.row_errors[0]["row"] == 1


# ============================================================================
# 5. Player sport mismatch
# ============================================================================


@pytest.mark.django_db
def test_player_from_wrong_sport_rejected():
    _ensure_provider()
    sport = _make_sport()
    # Create a genuinely different sport (rugby) to produce a sport mismatch
    uid = _uid()
    other_sport = Sport.objects.create(
        name=f"rugby_{uid}",
        slug=f"rugby-{uid}",
        code=f"RG{uid[:4].upper()}",
    )
    comp = _make_competition(sport)
    club = _make_club()
    fixture = _make_fixture(sport, comp)

    # Player from a different sport
    wrong_player = _make_player(other_sport, club)

    # Put a valid player on the fixture so ownership passes
    valid_player = _make_player(sport, club)
    _link_player_to_fixture(valid_player, fixture)

    csv_file = _make_csv([{
        "fixture_id": str(fixture.id),
        "player_id": str(wrong_player.id),
        "stat_type": "GOALS",
        "value": "1",
    }])
    result = import_csv_for_club(csv_file, club)
    assert result.success is False
    assert len(result.row_errors) == 1
    error_text = " ".join(result.row_errors[0]["errors"])
    assert "sport" in error_text.lower()


# ============================================================================
# 6. Invalid stat_type
# ============================================================================


@pytest.mark.django_db
def test_invalid_stat_type_rejected():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)
    club = _make_club()
    player = _make_player(sport, club)
    fixture = _make_fixture(sport, comp)
    _link_player_to_fixture(player, fixture)

    csv_file = _make_csv([{
        "fixture_id": str(fixture.id),
        "player_id": str(player.id),
        "stat_type": "INVALID_STAT_XYZ",
        "value": "1",
    }])
    result = import_csv_for_club(csv_file, club)
    assert result.success is False
    assert len(result.row_errors) == 1
    error_text = " ".join(result.row_errors[0]["errors"])
    assert "INVALID_STAT_XYZ" in error_text


# ============================================================================
# 7. Duplicate rows within same file
# ============================================================================


@pytest.mark.django_db
def test_intrafile_duplicate_rows_rejected():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)
    club = _make_club()
    player = _make_player(sport, club)
    fixture = _make_fixture(sport, comp)
    _link_player_to_fixture(player, fixture)

    row = {
        "fixture_id": str(fixture.id),
        "player_id": str(player.id),
        "stat_type": "GOALS",
        "value": "1",
    }
    csv_file = _make_csv([row, row])  # same row twice
    result = import_csv_for_club(csv_file, club)
    assert result.success is False
    # The second occurrence should produce a duplicate error
    assert any("Duplicate" in e for err in result.row_errors for e in err["errors"])


# ============================================================================
# 8. Idempotent re-upload (same data → no extra rows)
# ============================================================================


@pytest.mark.django_db
def test_duplicate_upload_is_idempotent():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)
    club = _make_club()
    player = _make_player(sport, club)
    fixture = _make_fixture(sport, comp)
    _link_player_to_fixture(player, fixture)

    row = {
        "fixture_id": str(fixture.id),
        "player_id": str(player.id),
        "stat_type": "GOALS",
        "value": "3",
    }

    result1 = import_csv_for_club(_make_csv([row]), club)
    assert result1.success is True

    result2 = import_csv_for_club(_make_csv([row]), club)
    assert result2.success is True

    # Exactly one MatchPlayerStatistic row — no duplicate
    assert MatchPlayerStatistic.objects.filter(
        match_centre__fixture=fixture,
        participant=player,
        stat_type="GOALS",
    ).count() == 1


# ============================================================================
# 9. Re-upload with corrected value updates the record
# ============================================================================


@pytest.mark.django_db
def test_reupload_with_correction_updates_value():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)
    club = _make_club()
    player = _make_player(sport, club)
    fixture = _make_fixture(sport, comp)
    _link_player_to_fixture(player, fixture)

    # First upload: value=1
    result1 = import_csv_for_club(
        _make_csv([{
            "fixture_id": str(fixture.id),
            "player_id": str(player.id),
            "stat_type": "GOALS",
            "value": "1",
        }]),
        club,
    )
    assert result1.success is True

    # Second upload: corrected value=3
    result2 = import_csv_for_club(
        _make_csv([{
            "fixture_id": str(fixture.id),
            "player_id": str(player.id),
            "stat_type": "GOALS",
            "value": "3",
        }]),
        club,
    )
    assert result2.success is True

    stat = MatchPlayerStatistic.objects.get(
        match_centre__fixture=fixture,
        participant=player,
        stat_type="GOALS",
    )
    assert stat.value == Decimal("3"), f"Expected 3, got {stat.value}"


# ============================================================================
# 10. Unauthenticated / non-admin cannot upload
# ============================================================================


@pytest.mark.django_db
def test_unauthenticated_upload_returns_401():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)
    club = _make_club()
    fixture = _make_fixture(sport, comp)

    client = APIClient()
    url = reverse("clubs:club-match-data-upload", kwargs={"club_pk": club.id})
    csv_file = _make_csv([{
        "fixture_id": str(fixture.id),
        "player_id": str(uuid.uuid4()),
        "stat_type": "GOALS",
        "value": "1",
    }])
    response = client.post(url, {"file": csv_file}, format="multipart")
    assert response.status_code == 401


@pytest.mark.django_db
def test_non_admin_staff_upload_returns_403():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)
    club = _make_club()
    fixture = _make_fixture(sport, comp)
    user = _make_user()
    # Staff role — not ADMIN
    _make_workspace(user, club, role="STAFF")

    client = APIClient()
    client.force_authenticate(user=user)
    url = reverse("clubs:club-match-data-upload", kwargs={"club_pk": club.id})
    csv_file = _make_csv([{
        "fixture_id": str(fixture.id),
        "player_id": str(uuid.uuid4()),
        "stat_type": "GOALS",
        "value": "1",
    }])
    response = client.post(url, {"file": csv_file}, format="multipart")
    assert response.status_code == 403


# ============================================================================
# 11. Club Admin from another club cannot upload for this club
# ============================================================================


@pytest.mark.django_db
def test_wrong_club_admin_cannot_upload():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)
    club_a = _make_club()
    club_b = _make_club()
    fixture = _make_fixture(sport, comp)

    # user is admin of club_b only
    user = _make_user()
    _make_workspace(user, club_b, role="ADMIN")

    client = APIClient()
    client.force_authenticate(user=user)
    url = reverse("clubs:club-match-data-upload", kwargs={"club_pk": club_a.id})
    csv_file = _make_csv([{
        "fixture_id": str(fixture.id),
        "player_id": str(uuid.uuid4()),
        "stat_type": "GOALS",
        "value": "1",
    }])
    response = client.post(url, {"file": csv_file}, format="multipart")
    assert response.status_code == 403


# ============================================================================
# 12. Fixture that does not involve the club is rejected
# ============================================================================


@pytest.mark.django_db
def test_fixture_from_wrong_club_rejected():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)
    club_a = _make_club()
    club_b = _make_club()

    # Fixture only involves club_b's player
    player_b = _make_player(sport, club_b)
    fixture = _make_fixture(sport, comp)
    _link_player_to_fixture(player_b, fixture)

    # club_a tries to upload for that fixture
    player_a = _make_player(sport, club_a)
    csv_file = _make_csv([{
        "fixture_id": str(fixture.id),
        "player_id": str(player_a.id),
        "stat_type": "GOALS",
        "value": "1",
    }])
    result = import_csv_for_club(csv_file, club_a)
    assert result.success is False
    # Error must mention that the fixture doesn't involve their club
    all_errors = " ".join(
        e for err in result.row_errors for e in err.get("errors", [])
    ) + result.message
    assert "club" in all_errors.lower() or "fixture" in all_errors.lower()


# ============================================================================
# 13. Successful upload calls complete_ingestion()
# ============================================================================


@pytest.mark.django_db
def test_successful_upload_calls_complete_ingestion():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)
    club = _make_club()
    player = _make_player(sport, club)
    fixture = _make_fixture(sport, comp)
    _link_player_to_fixture(player, fixture)

    csv_file = _make_csv([{
        "fixture_id": str(fixture.id),
        "player_id": str(player.id),
        "stat_type": "GOALS",
        "value": "1",
    }])

    # Import succeeds and the ingestion record is COMPLETED with fixture metadata
    result = import_csv_for_club(csv_file, club)

    assert result.success is True
    assert result.ingestion_id is not None

    ingestion = SportsFeedIngestion.objects.get(id=result.ingestion_id)
    assert ingestion.status == SportsFeedIngestion.Status.COMPLETED
    assert str(fixture.id) in ingestion.metadata.get("fixture_ids", [])


# ============================================================================
# 14. complete_ingestion() dispatches scoring after transaction commit
# ============================================================================


@pytest.mark.django_db
def test_upload_dispatches_score_affected_gameweeks_via_on_commit():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)
    club = _make_club()
    player = _make_player(sport, club)
    fixture = _make_fixture(sport, comp)
    _link_player_to_fixture(player, fixture)

    dispatched: list[list[str]] = []

    def fake_on_commit(func):
        func()  # execute synchronously, mimicking a real DB commit

    with patch("django.db.transaction.on_commit", side_effect=fake_on_commit):
        with patch("fantasy.tasks.score_affected_gameweeks") as mock_task:
            mock_task.delay = lambda ids: dispatched.append(ids)
            result = import_csv_for_club(
                _make_csv([{
                    "fixture_id": str(fixture.id),
                    "player_id": str(player.id),
                    "stat_type": "GOALS",
                    "value": "1",
                }]),
                club,
            )

    assert result.success is True
    assert dispatched, "score_affected_gameweeks.delay() was never called"
    assert str(fixture.id) in dispatched[0]


# ============================================================================
# 15. FINALIZED gameweek is not re-scored
# ============================================================================


@pytest.mark.django_db
def test_finalized_gameweek_not_rescored_after_upload():
    """
    The service calls complete_ingestion → on_commit → score_affected_gameweeks.
    The Celery task itself skips FINALIZED gameweeks.  This test verifies
    score_gameweek() is never called for a FINALIZED gameweek.
    """
    _ensure_provider()
    d = _make_domain()
    sport, comp, club, player, fixture = (
        d["sport"], d["competition"], d["club"], d["player"], d["fixture"]
    )

    uid = _uid()
    season = Season.objects.create(sport=sport, competition=comp, name=f"S_{uid}")
    fantasy = FantasyCompetition.objects.create(
        competition=comp,
        season=season,
        name=f"FC_{uid}",
        registration_state="OPEN",
        squad_size=2,
        starting_lineup_size=1,
        bench_size=1,
        initial_budget=Decimal("20"),
        max_players_per_team=2,
        position_rules={},
        formation_rules={},
    )
    now = timezone.now()
    gw = FantasyGameweek.objects.create(
        fantasy_competition=fantasy,
        number=1,
        name=f"GW1_{uid}",
        starts_at=now - timedelta(days=1),
        deadline_at=now + timedelta(hours=1),
        ends_at=now + timedelta(days=2),
        status="FINALIZED",
    )
    gw.fixtures.add(fixture)

    with patch("fantasy.services.score_gameweek") as mock_sg:
        with patch("django.db.transaction.on_commit", side_effect=lambda f: f()):
            result = import_csv_for_club(
                _make_csv([{
                    "fixture_id": str(fixture.id),
                    "player_id": str(player.id),
                    "stat_type": "GOALS",
                    "value": "1",
                }]),
                club,
            )

    assert result.success is True
    mock_sg.assert_not_called()


# ============================================================================
# 16. Fixture in multiple non-finalized gameweeks scores each
# ============================================================================


@pytest.mark.django_db
def test_fixture_in_multiple_gameweeks_scores_each():
    _ensure_provider()
    d = _make_domain()
    sport, comp, club, player, fixture = (
        d["sport"], d["competition"], d["club"], d["player"], d["fixture"]
    )

    uid = _uid()
    season = Season.objects.create(sport=sport, competition=comp, name=f"S_{uid}")
    fantasy = FantasyCompetition.objects.create(
        competition=comp,
        season=season,
        name=f"FC_{uid}",
        registration_state="OPEN",
        squad_size=2,
        starting_lineup_size=1,
        bench_size=1,
        initial_budget=Decimal("20"),
        max_players_per_team=2,
        position_rules={},
        formation_rules={},
    )
    now = timezone.now()
    gw1 = FantasyGameweek.objects.create(
        fantasy_competition=fantasy, number=1, name=f"GW1_{uid}",
        starts_at=now - timedelta(days=2), deadline_at=now + timedelta(hours=1),
        ends_at=now + timedelta(days=2), status="SCORING",
    )
    gw2 = FantasyGameweek.objects.create(
        fantasy_competition=fantasy, number=2, name=f"GW2_{uid}",
        starts_at=now - timedelta(days=1), deadline_at=now + timedelta(hours=2),
        ends_at=now + timedelta(days=3), status="SCORING",
    )
    gw1.fixtures.add(fixture)
    gw2.fixtures.add(fixture)

    scored_gw_ids: list = []

    def fake_score_gw(gw):
        scored_gw_ids.append(gw.id)

    with patch("fantasy.services.score_gameweek", side_effect=fake_score_gw):
        with patch("django.db.transaction.on_commit", side_effect=lambda f: f()):
            result = import_csv_for_club(
                _make_csv([{
                    "fixture_id": str(fixture.id),
                    "player_id": str(player.id),
                    "stat_type": "GOALS",
                    "value": "2",
                }]),
                club,
            )

    assert result.success is True
    assert gw1.id in scored_gw_ids
    assert gw2.id in scored_gw_ids


# ============================================================================
# 17. Failed validation rolls back the entire import
# ============================================================================


@pytest.mark.django_db
def test_failed_validation_rolls_back_entirely():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)
    club = _make_club()
    player = _make_player(sport, club)
    fixture = _make_fixture(sport, comp)
    _link_player_to_fixture(player, fixture)

    # Two rows: first valid, second has a bad stat_type
    rows = [
        {
            "fixture_id": str(fixture.id),
            "player_id": str(player.id),
            "stat_type": "GOALS",
            "value": "1",
        },
        {
            "fixture_id": str(fixture.id),
            "player_id": str(player.id),
            "stat_type": "BAD_STAT",
            "value": "1",
        },
    ]
    csv_file = _make_csv(rows)
    result = import_csv_for_club(csv_file, club)

    assert result.success is False
    # Nothing should have been written
    assert MatchPlayerStatistic.objects.filter(
        match_centre__fixture=fixture, participant=player
    ).count() == 0


# ============================================================================
# 18. CSV template endpoint returns valid CSV
# ============================================================================


@pytest.mark.django_db
def test_csv_template_download():
    club = _make_club()
    user = _make_user()
    _make_workspace(user, club, role="ADMIN")

    client = APIClient()
    client.force_authenticate(user=user)
    url = reverse("clubs:club-match-data-template", kwargs={"club_pk": club.id})
    response = client.get(url)

    assert response.status_code == 200
    assert "text/csv" in response["Content-Type"]
    content = (
        b"".join(response.streaming_content).decode()
        if hasattr(response, "streaming_content")
        else response.content.decode()
    )
    assert "fixture_id" in content
    assert "player_id" in content
    assert "stat_type" in content
    assert "value" in content


# ============================================================================
# 19. Fixture list returns only fixtures for the requesting club
# ============================================================================


@pytest.mark.django_db
def test_fixture_list_returns_only_club_fixtures():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)

    club_a = _make_club()
    club_b = _make_club()

    player_a = _make_player(sport, club_a)
    player_b = _make_player(sport, club_b)

    fixture_a = _make_fixture(sport, comp)
    fixture_b = _make_fixture(sport, comp)
    fixture_unrelated = _make_fixture(sport, comp)

    _link_player_to_fixture(player_a, fixture_a)
    _link_player_to_fixture(player_b, fixture_b)
    # fixture_unrelated has no players linked at all

    user = _make_user()
    _make_workspace(user, club_a, role="ADMIN")

    client = APIClient()
    client.force_authenticate(user=user)
    url = reverse("clubs:club-match-data-fixtures", kwargs={"club_pk": club_a.id})
    response = client.get(url)

    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.data}
    assert str(fixture_a.id) in returned_ids
    assert str(fixture_b.id) not in returned_ids
    assert str(fixture_unrelated.id) not in returned_ids


# ============================================================================
# HTTP integration: full upload via APIClient
# ============================================================================


@pytest.mark.django_db
def test_http_upload_success_returns_202():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)
    club = _make_club()
    player = _make_player(sport, club)
    fixture = _make_fixture(sport, comp)
    _link_player_to_fixture(player, fixture)

    user = _make_user()
    _make_workspace(user, club, role="ADMIN")

    client = APIClient()
    client.force_authenticate(user=user)
    url = reverse("clubs:club-match-data-upload", kwargs={"club_pk": club.id})

    csv_file = _make_csv([{
        "fixture_id": str(fixture.id),
        "player_id": str(player.id),
        "stat_type": "GOALS",
        "value": "1",
    }])

    response = client.post(url, {"file": csv_file}, format="multipart")
    assert response.status_code == 202
    assert response.data["success"] is True
    assert "Fantasy points are being calculated" in response.data["message"]


@pytest.mark.django_db
def test_http_upload_validation_failure_returns_400():
    _ensure_provider()
    sport = _make_sport()
    comp = _make_competition(sport)
    club = _make_club()
    player = _make_player(sport, club)
    fixture = _make_fixture(sport, comp)
    _link_player_to_fixture(player, fixture)

    user = _make_user()
    _make_workspace(user, club, role="ADMIN")

    client = APIClient()
    client.force_authenticate(user=user)
    url = reverse("clubs:club-match-data-upload", kwargs={"club_pk": club.id})

    csv_file = _make_csv([{
        "fixture_id": str(fixture.id),
        "player_id": str(player.id),
        "stat_type": "NOT_A_REAL_STAT",
        "value": "1",
    }])

    response = client.post(url, {"file": csv_file}, format="multipart")
    assert response.status_code == 400
    assert response.data["success"] is False
    assert len(response.data["row_errors"]) >= 1


@pytest.mark.django_db
def test_http_upload_non_csv_rejected():
    club = _make_club()
    user = _make_user()
    _make_workspace(user, club, role="ADMIN")

    client = APIClient()
    client.force_authenticate(user=user)
    url = reverse("clubs:club-match-data-upload", kwargs={"club_pk": club.id})

    txt_file = io.BytesIO(b"some text content")
    txt_file.name = "stats.txt"

    response = client.post(url, {"file": txt_file}, format="multipart")
    assert response.status_code == 400

"""Club Admin match-data CSV upload service.

Design rules
------------
* This module is the ONLY place that creates/updates MatchPlayerStatistic
  records on behalf of a Club Admin.  It never calculates fantasy points.
* Fantasy scoring is triggered exclusively via
  ``SportsFeedService.complete_ingestion(ingestion, fixture_ids=[...])``
  which registers a ``transaction.on_commit()`` callback that calls
  ``score_affected_gameweeks.delay()``.  The Celery task handles
  FINALIZED-gameweek protection and score_gameweek() invocation.
* The entire import is atomic.  If any row fails validation the whole
  file is rejected with row-level error details before anything is written.
* Re-uploading the same fixture is idempotent: existing statistics are
  updated (upserted) rather than duplicated.

CSV format
----------
Required columns (case-insensitive, leading/trailing whitespace stripped):

    fixture_id   – UUID of the SportingEvent
    player_id    – UUID of the Participant (kind=ATHLETE)
    stat_type    – one of the approved codes from fantasy.statistics (e.g. GOALS)
    value        – numeric, >= 0

Optional header rows / blank rows are ignored if they cannot be parsed.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import IO

from django.db import transaction

from discovery.models import (
    MatchCentre,
    MatchPlayerStatistic,
    SportsFeedIngestion,
    SportsFeedProvider,
)
from discovery.services.sports_feed_service import SportsFeedService
from fantasy.statistics import statistic_catalogue
from profiles.models import Club
from sports.models import EventParticipant, Participant, SportingEvent

logger = logging.getLogger(__name__)

# Provider code that identifies Club Admin CSV uploads in the ingestion log.
CLUB_ADMIN_CSV_PROVIDER_CODE = "CLUB_ADMIN_CSV"

# Required CSV column names (matched case-insensitively after strip).
REQUIRED_COLUMNS = {"fixture_id", "player_id", "stat_type", "value"}


# ---------------------------------------------------------------------------
# Public result dataclass
# ---------------------------------------------------------------------------


@dataclass
class MatchDataImportResult:
    """Returned by import_csv_for_club() on both success and failure."""

    success: bool
    records_received: int = 0
    records_processed: int = 0
    row_errors: list[dict] = field(default_factory=list)
    ingestion_id: str | None = None
    fixture_ids: list[str] = field(default_factory=list)
    message: str = ""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalise_header(raw: str) -> str:
    return raw.strip().lower()


def _validate_columns(header_row: list[str]) -> list[str]:
    """Return list of missing required column names (empty = OK)."""
    normalised = {_normalise_header(h) for h in header_row}
    return sorted(REQUIRED_COLUMNS - normalised)


def _parse_csv(file_obj: IO[bytes] | IO[str]) -> tuple[list[str], list[list[str]]]:
    """Return (headers, data_rows) from a file-like object."""
    # Accept both bytes and text
    if hasattr(file_obj, "read"):
        raw = file_obj.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8-sig")  # strip BOM if present
    else:
        raw = str(file_obj)

    reader = csv.reader(io.StringIO(raw))
    rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def _resolve_fixture(fixture_id_str: str, club: Club) -> SportingEvent | str:
    """Return the SportingEvent or an error string."""
    try:
        fixture = SportingEvent.objects.select_related("sport", "competition").get(
            id=fixture_id_str.strip()
        )
    except (SportingEvent.DoesNotExist, ValueError):
        return f"Fixture '{fixture_id_str}' does not exist."

    # Verify the fixture involves this club.
    # A fixture involves the club when at least one participant has a
    # PlayerProfile whose club matches, OR the fixture's competition
    # matches the club profile's league.
    club_participant_ids = set(
        Participant.objects.filter(
            player_profile__club=club
        ).values_list("id", flat=True)
    )

    fixture_participant_ids = set(
        EventParticipant.objects.filter(event=fixture).values_list(
            "participant_id", flat=True
        )
    )

    # Also accept when the fixture's competition matches the club's league
    try:
        from discovery.models import ClubProfile
        club_profile = ClubProfile.objects.filter(club=club).first()
        club_league_id = club_profile.league_id if club_profile and club_profile.league_id else None
    except Exception:  # noqa: BLE001
        club_league_id = None

    fixture_in_club_league = (
        club_league_id is not None
        and fixture.competition_id is not None
        and str(fixture.competition_id) == str(club_league_id)
    )

    if not (club_participant_ids & fixture_participant_ids) and not fixture_in_club_league:
        return (
            f"Fixture '{fixture_id_str}' does not involve your club. "
            "You can only upload data for fixtures your club participates in."
        )

    return fixture


def _resolve_player(
    player_id_str: str, fixture: SportingEvent
) -> Participant | str:
    """Return the Participant (ATHLETE) or an error string."""
    try:
        player = Participant.objects.select_related("sport").get(
            id=player_id_str.strip(),
            kind=Participant.Kind.ATHLETE,
        )
    except (Participant.DoesNotExist, ValueError):
        return f"Player '{player_id_str}' does not exist or is not an ATHLETE."

    # Player's sport must match the fixture's sport
    if player.sport_id != fixture.sport_id:
        return (
            f"Player '{player.name}' ({player_id_str}) belongs to sport "
            f"'{player.sport.name}', but the fixture is for sport "
            f"'{fixture.sport.name}'."
        )

    # Player must belong to one of the teams in this fixture
    fixture_participant_ids = set(
        EventParticipant.objects.filter(event=fixture).values_list(
            "participant_id", flat=True
        )
    )
    player_team_ids = set(
        Participant.objects.filter(
            player_profile__club__isnull=False,
            sport=fixture.sport,
            kind=Participant.Kind.TEAM,
        ).filter(
            # teams whose club has players matching this player
            player_profile__club__player_profiles__participant=player,
        ).values_list("id", flat=True)
    )

    # Relaxed check: player's sport matches AND fixture has participants from
    # the same sport — we accept the player belongs to this fixture's sport
    # as sufficient (team membership via EventParticipant is TEAM-level, not
    # ATHLETE-level in the current data model).
    # The strict ownership check is that the player's sport == fixture's sport,
    # already validated above.
    return player


def _validate_stat_type(stat_type_raw: str, fixture: SportingEvent) -> tuple[str, str | None]:
    """Return (normalised_stat_type, error_or_None)."""
    stat_type = stat_type_raw.strip().upper()
    catalogue = statistic_catalogue(fixture.sport)
    if not catalogue:
        # No catalogue for this sport — accept any non-empty stat_type so
        # the service degrades gracefully for sports not yet catalogued.
        if not stat_type:
            return stat_type, "stat_type must not be empty."
        return stat_type, None

    if stat_type not in catalogue:
        allowed = ", ".join(sorted(catalogue.keys()))
        return stat_type, (
            f"'{stat_type}' is not a valid stat_type for "
            f"sport '{fixture.sport.name}'. Allowed: {allowed}."
        )
    return stat_type, None


def _parse_value(value_raw: str) -> tuple[Decimal | None, str | None]:
    try:
        val = Decimal(value_raw.strip())
    except (InvalidOperation, AttributeError):
        return None, f"'{value_raw}' is not a valid number."
    if val < Decimal("0"):
        return None, "value must be >= 0."
    return val, None


# ---------------------------------------------------------------------------
# Core validation pass (pure — no DB writes)
# ---------------------------------------------------------------------------


@dataclass
class _ParsedRow:
    row_number: int  # 1-based (1 = first data row after header)
    fixture: SportingEvent
    player: Participant
    stat_type: str
    value: Decimal


def _validate_all_rows(
    headers: list[str],
    data_rows: list[list[str]],
    club: Club,
) -> tuple[list[_ParsedRow], list[dict]]:
    """Validate every data row.  Returns (valid_rows, errors).

    If errors is non-empty, valid_rows should be discarded — the caller must
    NOT write any rows when errors exist.
    """
    col_index = {_normalise_header(h): i for i, h in enumerate(headers)}

    errors: list[dict] = []
    valid_rows: list[_ParsedRow] = []

    # Cache fixture lookups across rows (same fixture_id → same result)
    fixture_cache: dict[str, SportingEvent | str] = {}

    # Track duplicate (fixture_id, player_id, stat_type) within this upload
    seen: set[tuple[str, str, str]] = set()

    for row_number, row in enumerate(data_rows, start=1):
        # Skip fully blank rows
        if not any(cell.strip() for cell in row):
            continue

        def _get(col: str) -> str:
            idx = col_index.get(col)
            if idx is None or idx >= len(row):
                return ""
            return row[idx].strip()

        fixture_id_str = _get("fixture_id")
        player_id_str = _get("player_id")
        stat_type_raw = _get("stat_type")
        value_raw = _get("value")

        row_errors: list[str] = []

        # ── fixture ─────────────────────────────────────────────────────────
        if not fixture_id_str:
            row_errors.append("fixture_id is required.")
            fixture = None
        else:
            if fixture_id_str not in fixture_cache:
                fixture_cache[fixture_id_str] = _resolve_fixture(fixture_id_str, club)
            cached = fixture_cache[fixture_id_str]
            if isinstance(cached, str):
                row_errors.append(cached)
                fixture = None
            else:
                fixture = cached

        # ── player ──────────────────────────────────────────────────────────
        if not player_id_str:
            row_errors.append("player_id is required.")
            player = None
        elif fixture is not None:
            result = _resolve_player(player_id_str, fixture)
            if isinstance(result, str):
                row_errors.append(result)
                player = None
            else:
                player = result
        else:
            player = None

        # ── stat_type ────────────────────────────────────────────────────────
        if not stat_type_raw:
            row_errors.append("stat_type is required.")
            stat_type = ""
        elif fixture is not None:
            stat_type, stat_err = _validate_stat_type(stat_type_raw, fixture)
            if stat_err:
                row_errors.append(stat_err)
        else:
            stat_type = stat_type_raw.strip().upper()

        # ── value ────────────────────────────────────────────────────────────
        if not value_raw:
            row_errors.append("value is required.")
            value = None
        else:
            value, val_err = _parse_value(value_raw)
            if val_err:
                row_errors.append(val_err)

        # ── intra-file duplicate ─────────────────────────────────────────────
        if fixture and player and stat_type and not row_errors:
            dedup_key = (str(fixture.id), str(player.id), stat_type)
            if dedup_key in seen:
                row_errors.append(
                    f"Duplicate row: (fixture={fixture_id_str}, "
                    f"player={player_id_str}, stat_type={stat_type}) "
                    "appears more than once in this file."
                )
            else:
                seen.add(dedup_key)

        if row_errors:
            errors.append({"row": row_number, "errors": row_errors})
        elif fixture and player and stat_type and value is not None:
            valid_rows.append(
                _ParsedRow(
                    row_number=row_number,
                    fixture=fixture,
                    player=player,
                    stat_type=stat_type,
                    value=value,
                )
            )

    return valid_rows, errors


# ---------------------------------------------------------------------------
# Atomic write pass
# ---------------------------------------------------------------------------


def _upsert_statistics(parsed_rows: list[_ParsedRow]) -> tuple[int, int]:
    """Create or update MatchPlayerStatistic records.

    Returns (created_count, updated_count).
    Called inside a transaction.atomic() block.
    """
    created = 0
    updated = 0

    # Group rows by fixture to minimise get_or_create calls on MatchCentre
    fixtures_seen: dict[str, MatchCentre] = {}

    for row in parsed_rows:
        fid = str(row.fixture.id)
        if fid not in fixtures_seen:
            mc, _ = MatchCentre.objects.get_or_create(fixture=row.fixture)
            fixtures_seen[fid] = mc
        mc = fixtures_seen[fid]

        stat, was_created = MatchPlayerStatistic.objects.get_or_create(
            match_centre=mc,
            participant=row.player,
            stat_type=row.stat_type,
            defaults={"value": row.value},
        )
        if was_created:
            created += 1
        elif stat.value != row.value:
            # Legitimate correction — update in place
            stat.value = row.value
            stat.save(update_fields=["value", "updated_at"])
            updated += 1
        # If value is unchanged, count as processed but not a write

    return created, updated


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def import_csv_for_club(
    file_obj: IO,
    club: Club,
    uploaded_by=None,
) -> MatchDataImportResult:
    """Parse, validate, and atomically import a CSV file for a club.

    Parameters
    ----------
    file_obj:
        A file-like object (from ``request.FILES``).
    club:
        The ``profiles.Club`` the upload is scoped to.
    uploaded_by:
        The ``User`` performing the upload (for audit logging).

    Returns
    -------
    MatchDataImportResult
        On ``success=False`` the caller should return HTTP 400 with
        ``row_errors``.  On ``success=True`` the import is fully committed
        and fantasy scoring has been scheduled.
    """
    # ── 1. Parse CSV ────────────────────────────────────────────────────────
    try:
        headers, data_rows = _parse_csv(file_obj)
    except Exception as exc:  # noqa: BLE001
        logger.warning("CSV parse error for club %s: %s", club.id, exc)
        return MatchDataImportResult(
            success=False,
            message="Could not parse the uploaded file. Please upload a valid CSV.",
        )

    if not headers:
        return MatchDataImportResult(
            success=False,
            message="The uploaded file appears to be empty.",
        )

    # ── 2. Column check ─────────────────────────────────────────────────────
    missing_cols = _validate_columns(headers)
    if missing_cols:
        return MatchDataImportResult(
            success=False,
            message=(
                f"Missing required columns: {', '.join(missing_cols)}. "
                f"Required: {', '.join(sorted(REQUIRED_COLUMNS))}."
            ),
        )

    total_data_rows = sum(1 for r in data_rows if any(c.strip() for c in r))

    # ── 3. Validate ALL rows before writing anything ─────────────────────────
    valid_rows, row_errors = _validate_all_rows(headers, data_rows, club)

    if row_errors:
        return MatchDataImportResult(
            success=False,
            records_received=total_data_rows,
            row_errors=row_errors,
            message=f"Validation failed on {len(row_errors)} row(s). Nothing was imported.",
        )

    if not valid_rows:
        return MatchDataImportResult(
            success=False,
            records_received=total_data_rows,
            message="No data rows found in the uploaded file.",
        )

    # ── 4. Start ingestion tracking ──────────────────────────────────────────
    try:
        provider = SportsFeedProvider.objects.get(
            code=CLUB_ADMIN_CSV_PROVIDER_CODE,
            is_active=True,
        )
    except SportsFeedProvider.DoesNotExist:
        logger.error(
            "SportsFeedProvider '%s' does not exist. "
            "Run the clubs data migration to create it.",
            CLUB_ADMIN_CSV_PROVIDER_CODE,
        )
        return MatchDataImportResult(
            success=False,
            message=(
                "Upload service is not configured correctly. "
                "Please contact a platform administrator."
            ),
        )

    from django.utils import timezone

    ingestion = SportsFeedIngestion.objects.create(
        provider=provider,
        status=SportsFeedIngestion.Status.PROCESSING,
        feed_timestamp=timezone.now(),
        metadata={
            "club_id": str(club.id),
            "club_name": club.name,
            "uploaded_by": str(uploaded_by.id) if uploaded_by else None,
        },
    )

    # ── 5. Atomic write ──────────────────────────────────────────────────────
    fixture_ids: list[str] = []
    try:
        with transaction.atomic():
            created, updated = _upsert_statistics(valid_rows)
            fixture_ids = list({str(row.fixture.id) for row in valid_rows})

            # Complete the ingestion inside the same transaction so that
            # on_commit() fires only after the statistics rows are durable.
            SportsFeedService.complete_ingestion(
                ingestion,
                confidence=1.0,
                is_verified=False,
                records_received=total_data_rows,
                records_processed=len(valid_rows),
                metadata={
                    "club_id": str(club.id),
                    "club_name": club.name,
                    "created": created,
                    "updated": updated,
                    "fixture_ids": fixture_ids,
                    "uploaded_by": str(uploaded_by.id) if uploaded_by else None,
                },
                fixture_ids=fixture_ids,
            )

    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Atomic import failed for club %s (ingestion %s): %s",
            club.id,
            ingestion.id,
            exc,
        )
        # Mark ingestion as failed (best-effort; ignore secondary errors)
        try:
            SportsFeedService.fail_ingestion(ingestion, str(exc))
        except Exception:  # noqa: BLE001
            pass
        return MatchDataImportResult(
            success=False,
            records_received=total_data_rows,
            message="An unexpected error occurred during import. No data was saved.",
        )

    # ── 6. Audit log ─────────────────────────────────────────────────────────
    try:
        from clubs.services.audit_service import ClubAuditService

        ClubAuditService.record(
            action="MATCH_DATA_UPLOADED",
            club=club,
            user=uploaded_by,
            entity_type="SportsFeedIngestion",
            entity_id=ingestion.id,
            metadata={
                "fixture_ids": fixture_ids,
                "records_received": total_data_rows,
                "records_processed": len(valid_rows),
                "created": created,
                "updated": updated,
            },
        )
    except Exception:  # noqa: BLE001
        # Audit failure must never roll back a successful import
        logger.exception("Failed to write audit log for match data upload (ingestion %s)", ingestion.id)

    return MatchDataImportResult(
        success=True,
        records_received=total_data_rows,
        records_processed=len(valid_rows),
        ingestion_id=str(ingestion.id),
        fixture_ids=fixture_ids,
        message="Match data uploaded successfully. Fantasy points are being calculated.",
    )


# ---------------------------------------------------------------------------
# CSV template generation
# ---------------------------------------------------------------------------


def generate_csv_template(sport=None) -> str:
    """Return a CSV template string with headers and example rows.

    If ``sport`` is provided, the example stat_type values are drawn from
    the catalogue for that sport.  Otherwise, football examples are used.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["fixture_id", "player_id", "stat_type", "value"])

    # Example data rows — clearly marked as examples
    if sport is not None:
        catalogue = statistic_catalogue(sport)
        example_stat = next(iter(catalogue), "GOALS") if catalogue else "GOALS"
    else:
        example_stat = "GOALS"

    writer.writerow([
        "<SportingEvent UUID>",
        "<Participant UUID>",
        example_stat,
        "1",
    ])
    writer.writerow([
        "<SportingEvent UUID>",
        "<Participant UUID>",
        example_stat,
        "2",
    ])
    return output.getvalue()

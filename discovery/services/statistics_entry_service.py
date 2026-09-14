"""Statistics Entry Service — Sports Data & Statistics Admin write path.

This service is the authoritative backend for the Sports Data Admin
statistics-entry workflow.  It sits alongside the existing Club Admin CSV
upload path (clubs/services/match_data_service.py) and uses the **same**
underlying model (discovery.MatchPlayerStatistic) and the **same** scoring
trigger (SportsFeedService.complete_ingestion → on_commit →
score_affected_gameweeks.delay).

Design rules
------------
* All rows are validated before any row is written (atomic, all-or-nothing).
* Uses update_or_create so re-submitting a fixture is fully idempotent.
* trigger_scoring=False → statistics are saved without triggering Fantasy
  scoring. Intended for LIVE/partial submissions mid-match.
* trigger_scoring=True  → complete_ingestion() is called with the fixture id
  so that score_affected_gameweeks is dispatched via on_commit after the
  transaction commits.  Intended for COMPLETED/final submissions.
* The SPORTS_DATA_ADMIN SportsFeedProvider must have been seeded by the
  discovery/migrations/0008_sports_data_admin_provider.py data migration
  before this service can be used.
* Imports statistic_catalogue from fantasy/statistics.py — the same catalogue
  already used by clubs/services/match_data_service.py.  This cross-app
  import is intentional and established by existing code.

Downstream consumers
--------------------
Because this service writes to the same MatchPlayerStatistic model that the
Fantasy scoring engine reads, no changes are needed to:
  - score_gameweek()
  - FantasyPlayerGameweekPoints
  - FantasyTeamGameweekScore
  - the Fantasy Match Statistics Review endpoints
  - any fan-side component
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from discovery.models import (
    MatchCentre,
    MatchPlayerStatistic,
    SportsFeedIngestion,
    SportsFeedProvider,
)
from discovery.services.sports_feed_service import SportsFeedService
from fantasy.statistics import statistic_catalogue
from sports.models import EventParticipant, Participant, SportingEvent

logger = logging.getLogger(__name__)

SPORTS_DATA_ADMIN_PROVIDER_CODE = "SPORTS_DATA_ADMIN"


# ---------------------------------------------------------------------------
# Input dataclass — one row from the caller
# ---------------------------------------------------------------------------

@dataclass
class StatisticRow:
    """Single validated statistic row ready for DB write."""

    participant: Participant
    stat_type: str       # already normalised to UPPER
    value: Decimal


# ---------------------------------------------------------------------------
# Validation errors — row-level
# ---------------------------------------------------------------------------

@dataclass
class RowValidationError:
    index: int           # 0-based position in the incoming list
    participant_id: str
    stat_type: str
    error: str


# ---------------------------------------------------------------------------
# Service result dataclass
# ---------------------------------------------------------------------------

@dataclass
class StatisticsEntryResult:
    """Returned by save_fixture_statistics() on both success and failure."""

    success: bool
    records_created: int = 0
    records_updated: int = 0
    records_unchanged: int = 0
    row_errors: list[RowValidationError] = field(default_factory=list)
    ingestion_id: str | None = None
    scoring_scheduled: bool = False
    message: str = ""


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------

class StatisticsEntryService:
    """Sports Data Admin statistics write path."""

    # ── GET: build the statistics display payload ──────────────────────────

    @staticmethod
    def get_fixture_statistics(fixture: SportingEvent) -> dict:
        """
        Return all current MatchPlayerStatistic records for *fixture*,
        grouped by participant, alongside Fantasy pool membership flags.

        Player list is the union of:
          1. Athletes linked to the fixture via EventParticipant.
          2. FantasyPlayer pool members for any FantasyGameweek that includes
             this fixture (catches players added directly to the pool who may
             not have EventParticipant rows).

        Each player entry has:
          participant_id, participant_name, fantasy_player_id, in_fantasy_pool,
          stats: [{id, stat_type, value}]
        """
        # Determine the sport statistic catalogue for column headers.
        sport = fixture.sport
        catalogue = statistic_catalogue(sport)  # {CODE: label}
        stat_types_ordered = list(catalogue.keys())

        # ── Gather participant IDs from all sources ────────────────────────

        # Source 1: EventParticipant rows (HOME/AWAY/COMPETITOR athletes)
        ep_participant_ids = set(
            EventParticipant.objects.filter(
                event=fixture,
            ).values_list("participant_id", flat=True)
        )

        # Source 2: FantasyPlayer pool members whose gameweek contains this fixture
        from fantasy.models import FantasyGameweek, FantasyPlayer

        fantasy_player_qs = FantasyPlayer.objects.filter(
            fantasy_competition__gameweeks__fixtures=fixture,
        ).select_related("player").distinct()

        # Map participant_id → FantasyPlayer for quick lookup
        fp_by_participant: dict = {
            str(fp.player_id): fp for fp in fantasy_player_qs
        }

        all_participant_ids = ep_participant_ids | {
            fp.player_id for fp in fantasy_player_qs
        }

        # Fetch athlete Participants only (Teams may appear via EventParticipant)
        participants = {
            str(p.id): p
            for p in Participant.objects.filter(
                id__in=all_participant_ids,
                kind=Participant.Kind.ATHLETE,
            ).order_by("name")
        }

        # ── Fetch existing stats for this fixture ──────────────────────────

        try:
            match_centre = MatchCentre.objects.get(fixture=fixture)
            stats_qs = MatchPlayerStatistic.objects.filter(
                match_centre=match_centre,
            ).values("id", "participant_id", "stat_type", "value")
        except MatchCentre.DoesNotExist:
            stats_qs = []

        # Group stats by participant_id
        stats_by_participant: dict[str, list[dict]] = {}
        for row in stats_qs:
            pid = str(row["participant_id"])
            if pid not in stats_by_participant:
                stats_by_participant[pid] = []
            stats_by_participant[pid].append(
                {
                    "id": str(row["id"]),
                    "stat_type": row["stat_type"],
                    "value": str(row["value"]),
                }
            )

        # ── Build per-player rows ──────────────────────────────────────────

        players = []
        for pid, participant in participants.items():
            fp = fp_by_participant.get(pid)
            players.append(
                {
                    "participant_id": pid,
                    "participant_name": participant.name,
                    "fantasy_player_id": str(fp.id) if fp else None,
                    "in_fantasy_pool": fp is not None,
                    "stats": stats_by_participant.get(pid, []),
                }
            )

        return {
            "fixture_id": str(fixture.id),
            "fixture_name": fixture.name,
            "fixture_status": fixture.status,
            "sport": sport.slug or sport.name.lower(),
            "stat_types": stat_types_ordered,
            "stat_labels": catalogue,
            "players": players,
        }

    # ── POST: validate and save statistics ────────────────────────────────

    @staticmethod
    def validate_rows(
        fixture: SportingEvent,
        raw_rows: list[dict],
    ) -> tuple[list[StatisticRow], list[RowValidationError]]:
        """
        Validate all incoming rows and return (valid_rows, errors).

        Validation rules (mirrors clubs/services/match_data_service.py):
          1. participant UUID exists and is kind=ATHLETE
          2. participant.sport matches fixture.sport
          3. stat_type is in statistic_catalogue(fixture.sport)
          4. value is numeric and >= 0

        All rows are validated before any DB write.  If *any* row has errors,
        the caller must NOT call save_fixture_statistics().
        """
        catalogue = statistic_catalogue(fixture.sport)
        valid_rows: list[StatisticRow] = []
        errors: list[RowValidationError] = []

        # Cache participant lookups within a single call
        participant_cache: dict[str, Participant | str] = {}

        for index, row in enumerate(raw_rows):
            participant_id_raw = str(row.get("participant", "")).strip()
            stat_type_raw = str(row.get("stat_type", "")).strip()
            value_raw = row.get("value")

            row_errors: list[str] = []

            # ── Participant ────────────────────────────────────────────────
            if not participant_id_raw:
                row_errors.append("participant is required.")
                participant = None
            else:
                if participant_id_raw not in participant_cache:
                    try:
                        p = Participant.objects.select_related("sport").get(
                            id=participant_id_raw,
                            kind=Participant.Kind.ATHLETE,
                        )
                        participant_cache[participant_id_raw] = p
                    except (Participant.DoesNotExist, ValueError):
                        participant_cache[participant_id_raw] = (
                            f"Participant '{participant_id_raw}' does not exist "
                            "or is not an ATHLETE."
                        )
                cached = participant_cache[participant_id_raw]
                if isinstance(cached, str):
                    row_errors.append(cached)
                    participant = None
                else:
                    participant = cached
                    if participant.sport_id != fixture.sport_id:
                        row_errors.append(
                            f"Participant '{participant.name}' sport "
                            f"'{participant.sport.name}' does not match "
                            f"fixture sport '{fixture.sport.name}'."
                        )
                        participant = None

            # ── stat_type ──────────────────────────────────────────────────
            stat_type = stat_type_raw.upper()
            if not stat_type:
                row_errors.append("stat_type is required.")
            elif catalogue and stat_type not in catalogue:
                allowed = ", ".join(sorted(catalogue.keys()))
                row_errors.append(
                    f"'{stat_type}' is not a valid stat_type for sport "
                    f"'{fixture.sport.name}'. Allowed: {allowed}."
                )

            # ── value ──────────────────────────────────────────────────────
            try:
                value = Decimal(str(value_raw)).normalize()
                if value < Decimal("0"):
                    row_errors.append("value must be >= 0.")
                    value = None
            except Exception:
                row_errors.append(f"'{value_raw}' is not a valid number.")
                value = None

            if row_errors:
                errors.append(
                    RowValidationError(
                        index=index,
                        participant_id=participant_id_raw,
                        stat_type=stat_type,
                        error="; ".join(row_errors),
                    )
                )
            elif participant and stat_type and value is not None:
                valid_rows.append(
                    StatisticRow(
                        participant=participant,
                        stat_type=stat_type,
                        value=value,
                    )
                )

        return valid_rows, errors

    @staticmethod
    @transaction.atomic
    def save_fixture_statistics(
        fixture: SportingEvent,
        raw_rows: list[dict],
        actor,
        trigger_scoring: bool = True,
    ) -> StatisticsEntryResult:
        """
        Validate all rows then atomically upsert MatchPlayerStatistic records.

        On success (trigger_scoring=True), calls
        SportsFeedService.complete_ingestion(fixture_ids=[fixture.id]) inside
        the same transaction, which registers an on_commit callback that
        dispatches score_affected_gameweeks.delay([fixture.id]).

        On trigger_scoring=False, the statistics are saved but complete_ingestion
        is called with fixture_ids=[] so no scoring is triggered.

        Returns StatisticsEntryResult.  On validation failure (any row error),
        returns success=False with row_errors populated and writes nothing.
        """
        if not raw_rows:
            return StatisticsEntryResult(
                success=False,
                message="No statistics rows provided.",
            )

        # ── Validate all rows first ────────────────────────────────────────
        valid_rows, errors = StatisticsEntryService.validate_rows(fixture, raw_rows)

        if errors:
            return StatisticsEntryResult(
                success=False,
                row_errors=errors,
                message=(
                    f"Validation failed on {len(errors)} row(s). "
                    "Nothing was saved."
                ),
            )

        # ── Fetch the provider ─────────────────────────────────────────────
        try:
            provider = SportsFeedProvider.objects.get(
                code=SPORTS_DATA_ADMIN_PROVIDER_CODE,
                is_active=True,
            )
        except SportsFeedProvider.DoesNotExist:
            logger.error(
                "StatisticsEntryService: SportsFeedProvider '%s' not found. "
                "Run the discovery data migration to create it.",
                SPORTS_DATA_ADMIN_PROVIDER_CODE,
            )
            return StatisticsEntryResult(
                success=False,
                message=(
                    "Statistics service is not configured correctly. "
                    "Please contact a platform administrator."
                ),
            )

        # ── Create ingestion record ────────────────────────────────────────
        ingestion = SportsFeedIngestion.objects.create(
            provider=provider,
            status=SportsFeedIngestion.Status.PROCESSING,
            feed_timestamp=timezone.now(),
            metadata={
                "fixture_id": str(fixture.id),
                "fixture_name": fixture.name,
                "entered_by": str(actor.id) if actor else None,
                "trigger_scoring": trigger_scoring,
            },
        )

        # ── Upsert statistics ──────────────────────────────────────────────
        match_centre, _ = MatchCentre.objects.get_or_create(fixture=fixture)

        created_count = 0
        updated_count = 0
        unchanged_count = 0

        for row in valid_rows:
            stat, was_created = MatchPlayerStatistic.objects.get_or_create(
                match_centre=match_centre,
                participant=row.participant,
                stat_type=row.stat_type,
                defaults={"value": row.value},
            )
            if was_created:
                created_count += 1
            elif stat.value != row.value:
                stat.value = row.value
                stat.save(update_fields=["value", "updated_at"])
                updated_count += 1
            else:
                unchanged_count += 1

        fixture_ids_to_score = [str(fixture.id)] if trigger_scoring else []

        # ── Complete ingestion (registers on_commit scoring callback) ──────
        SportsFeedService.complete_ingestion(
            ingestion,
            confidence=1.0,
            is_verified=True,   # Sports Data Admin is considered authoritative
            records_received=len(raw_rows),
            records_processed=len(valid_rows),
            metadata={
                "fixture_id": str(fixture.id),
                "fixture_name": fixture.name,
                "entered_by": str(actor.id) if actor else None,
                "created": created_count,
                "updated": updated_count,
                "unchanged": unchanged_count,
                "fixture_ids": fixture_ids_to_score,
                "trigger_scoring": trigger_scoring,
            },
            fixture_ids=fixture_ids_to_score,
        )

        logger.info(
            "StatisticsEntryService: fixture=%s created=%d updated=%d "
            "unchanged=%d trigger_scoring=%s",
            fixture.id,
            created_count,
            updated_count,
            unchanged_count,
            trigger_scoring,
        )

        return StatisticsEntryResult(
            success=True,
            records_created=created_count,
            records_updated=updated_count,
            records_unchanged=unchanged_count,
            ingestion_id=str(ingestion.id),
            scoring_scheduled=trigger_scoring,
            message=(
                "Statistics saved. Fantasy scoring has been scheduled."
                if trigger_scoring
                else "Statistics saved. Fantasy scoring was not triggered (partial/live save)."
            ),
        )


statistics_entry_service = StatisticsEntryService()

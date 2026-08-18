"""Sports data feed service."""

from __future__ import annotations

import logging
from typing import Sequence

from django.db import transaction
from django.utils import timezone

from discovery.models import (
    MatchCentre,
    SportsFeedIngestion,
    SportsFeedProvider,
)

logger = logging.getLogger(__name__)


class SportsFeedService:
    """Service for consuming approved sports data feeds."""

    @staticmethod
    @transaction.atomic
    def start_ingestion(provider_code: str) -> SportsFeedIngestion:
        """Start a feed ingestion for a provider."""
        provider = SportsFeedProvider.objects.get(
            code=provider_code,
            is_active=True,
        )
        return SportsFeedIngestion.objects.create(
            provider=provider,
            status=SportsFeedIngestion.Status.PROCESSING,
            feed_timestamp=timezone.now(),
        )

    @staticmethod
    @transaction.atomic
    def complete_ingestion(
        ingestion: SportsFeedIngestion,
        confidence: float = 0.0,
        is_verified: bool = False,
        records_received: int = 0,
        records_processed: int = 0,
        metadata: dict | None = None,
        fixture_ids: Sequence[str] | None = None,
    ) -> SportsFeedIngestion:
        """Mark an ingestion as completed with confidence and verification.

        Parameters
        ----------
        fixture_ids:
            Optional list of ``SportingEvent`` UUID strings whose player
            statistics were written during this ingestion batch.  When
            provided, a ``score_affected_gameweeks`` Celery task is dispatched
            via ``transaction.on_commit()`` so that Fantasy scoring runs only
            after all statistics are durably committed to the database.
            Pass an empty list or omit to skip automatic scoring.
        """
        ingestion.status = SportsFeedIngestion.Status.COMPLETED
        ingestion.confidence = confidence
        ingestion.is_verified = is_verified
        ingestion.records_received = records_received
        ingestion.records_processed = records_processed
        ingestion.metadata = metadata or {}
        ingestion.completed_at = timezone.now()
        ingestion.save(
            update_fields=[
                "status",
                "confidence",
                "is_verified",
                "records_received",
                "records_processed",
                "metadata",
                "completed_at",
                "updated_at",
            ]
        )

        # ------------------------------------------------------------------ #
        # Automatic Fantasy scoring bridge                                    #
        # ------------------------------------------------------------------ #
        # Dispatch scoring AFTER the current transaction commits so the new
        # MatchPlayerStatistic rows are visible to the Celery worker.
        # transaction.on_commit() is a no-op in tests that run inside their
        # own transactions (the callback fires when the outermost savepoint
        # is released), which is the desired behaviour for unit tests that
        # mock the task.
        ids_to_score: list[str] = [str(fid) for fid in (fixture_ids or []) if fid]
        if ids_to_score:
            logger.info(
                "complete_ingestion: ingestion %s completed — scheduling "
                "score_affected_gameweeks for %d fixture(s): %s",
                ingestion.id,
                len(ids_to_score),
                ids_to_score,
            )

            def _dispatch():
                try:
                    from fantasy.tasks import score_affected_gameweeks

                    score_affected_gameweeks.delay(ids_to_score)
                    logger.info(
                        "complete_ingestion: score_affected_gameweeks task dispatched "
                        "for ingestion %s.",
                        ingestion.id,
                    )
                except Exception:  # noqa: BLE001
                    # Do not let a task-dispatch failure roll back the ingestion
                    # completion.  The admin can trigger recalculate manually.
                    logger.exception(
                        "complete_ingestion: failed to dispatch score_affected_gameweeks "
                        "for ingestion %s — scoring must be triggered manually.",
                        ingestion.id,
                    )

            transaction.on_commit(_dispatch)
        else:
            logger.info(
                "complete_ingestion: ingestion %s completed with no fixture_ids — "
                "automatic Fantasy scoring not triggered.",
                ingestion.id,
            )

        return ingestion

    @staticmethod
    @transaction.atomic
    def fail_ingestion(ingestion: SportsFeedIngestion, error_message: str) -> SportsFeedIngestion:
        """Mark an ingestion as failed."""
        ingestion.status = SportsFeedIngestion.Status.FAILED
        ingestion.error_message = error_message
        ingestion.completed_at = timezone.now()
        ingestion.save(
            update_fields=[
                "status",
                "error_message",
                "completed_at",
                "updated_at",
            ]
        )
        return ingestion

    @staticmethod
    def update_match_centre_feed(
        fixture_id: str,
        confidence: float,
        feed_status: str,
        is_verified: bool = False,
    ) -> MatchCentre | None:
        """Update the feed status and confidence of a match centre."""
        try:
            mc = MatchCentre.objects.get(fixture_id=fixture_id)
        except MatchCentre.DoesNotExist:
            return None

        mc.data_confidence = confidence
        mc.feed_status = feed_status
        mc.is_verified = is_verified
        mc.save(
            update_fields=[
                "data_confidence",
                "feed_status",
                "is_verified",
                "last_updated",
                "updated_at",
            ]
        )
        return mc


sports_feed_service = SportsFeedService()

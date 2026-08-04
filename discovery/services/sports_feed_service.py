"""Sports data feed service."""

from __future__ import annotations

import logging

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
    ) -> SportsFeedIngestion:
        """Mark an ingestion as completed with confidence and verification."""
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

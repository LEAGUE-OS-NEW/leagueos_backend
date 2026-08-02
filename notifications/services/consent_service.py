"""Service layer for communication consent operations.

Handles consent management with immutable history tracking.
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from notifications.models import CommunicationConsent, NotificationPreferenceAudit

logger = logging.getLogger(__name__)
User = get_user_model()


class ConsentService:
    """Service for communication consent operations."""

    @staticmethod
    @transaction.atomic
    def record_consent(
        user: User,
        consent_type: str,
        granted: bool,
        source: str = "WEB",
        ip_address: str | None = None,
        user_agent: str = "",
    ) -> CommunicationConsent:
        """Record user consent.

        Creates a new immutable record. Never overwrites existing consents.

        Args:
            user: The user granting/withdrawing consent.
            consent_type: Type of consent.
            granted: True if granting, False if withdrawing.
            source: Source of consent (WEB, MOBILE, API, ADMIN).
            ip_address: IP address of the request.
            user_agent: User agent string of the request.

        Returns:
            The created CommunicationConsent instance.

        Raises:
            ValueError: If consent_type is invalid.
        """
        # Validate consent_type
        valid_types = [choice[0] for choice in CommunicationConsent.CONSENT_TYPES]
        if consent_type not in valid_types:
            raise ValueError(f"Invalid consent_type: {consent_type}. Valid types: {valid_types}")

        # Validate source
        valid_sources = ["WEB", "MOBILE", "API", "ADMIN"]
        if source not in valid_sources:
            raise ValueError(f"Invalid source: {source}. Valid sources: {valid_sources}")

        # Create new immutable record
        consent = CommunicationConsent.objects.create(
            user=user,
            consent_type=consent_type,
            granted=granted,
            granted_at=timezone.now(),
            source=source,
            ip_address=ip_address,
            user_agent=user_agent or "",
        )

        # Record audit log
        action = "CONSENT_GRANTED" if granted else "CONSENT_WITHDRAWN"
        NotificationPreferenceAudit.objects.create(
            user=user,
            action=action,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={
                "consent_type": consent_type,
                "granted": granted,
                "source": source,
            },
        )

        logger.info(
            "Consent %s for user %s: %s (%s)",
            "granted" if granted else "withdrawn",
            user,
            consent_type,
            source,
        )

        return consent

    @staticmethod
    def get_current_consents(user: User) -> dict[str, bool]:
        """Get current consent status for all consent types.

        Returns the most recent consent decision for each type.

        Args:
            user: The user whose consents to retrieve.

        Returns:
            Dict mapping consent_type to granted boolean.
        """
        consents = {}
        for consent_type, _ in CommunicationConsent.CONSENT_TYPES:
            latest = (
                CommunicationConsent.objects.filter(user=user, consent_type=consent_type)
                .order_by("-granted_at")
                .first()
            )
            consents[consent_type] = latest.granted if latest else False

        return consents

    @staticmethod
    def get_consent_history(
        user: User,
        consent_type: str | None = None,
        limit: int = 100,
    ) -> list[CommunicationConsent]:
        """Get consent history for a user.

        Args:
            user: The user whose consent history to retrieve.
            consent_type: Optional filter by consent type.
            limit: Maximum number of records to return.

        Returns:
            List of CommunicationConsent instances, ordered by most recent first.
        """
        queryset = CommunicationConsent.objects.filter(user=user)

        if consent_type:
            queryset = queryset.filter(consent_type=consent_type)

        return list(queryset.order_by("-granted_at")[:limit])

    @staticmethod
    def get_consent_status(user: User, consent_type: str) -> dict[str, Any]:
        """Get detailed status for a specific consent type.

        Args:
            user: The user to check.
            consent_type: The consent type to check.

        Returns:
            Dict with consent status details.
        """
        latest = (
            CommunicationConsent.objects.filter(user=user, consent_type=consent_type)
            .order_by("-granted_at")
            .first()
        )

        if not latest:
            return {
                "consent_type": consent_type,
                "granted": False,
                "granted_at": None,
                "withdrawn_at": None,
                "source": None,
            }

        return {
            "consent_type": consent_type,
            "granted": latest.granted,
            "granted_at": latest.granted_at,
            "withdrawn_at": latest.withdrawn_at,
            "source": latest.source,
        }

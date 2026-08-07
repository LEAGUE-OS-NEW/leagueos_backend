"""Audit service for club audit logging."""

from __future__ import annotations

import logging

from clubs.models import ClubAuditLog

logger = logging.getLogger(__name__)


class ClubAuditService:
    """Service for club audit logging."""

    @staticmethod
    def record(
        action,
        club,
        user,
        entity_type="",
        entity_id=None,
        request=None,
        metadata=None,
    ):
        """Record an audit log entry."""
        try:
            return ClubAuditLog.objects.create(
                club=club,
                user=user if user and user.is_authenticated else None,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
                user_agent=getattr(request, "META", {}).get("HTTP_USER_AGENT", ""),
                metadata=metadata or {},
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to record club audit log for action %s", action)
            return None

    @staticmethod
    def get_club_audit_logs(club, limit=100, offset=0):
        """Get audit logs for a club."""
        return ClubAuditLog.objects.filter(club=club).order_by("-created_at")[
            offset : offset + limit
        ]


club_audit_service = ClubAuditService()

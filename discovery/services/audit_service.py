"""Audit logging service."""

from __future__ import annotations

import logging

from discovery.models import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    """Service for recording audit logs."""

    @staticmethod
    def record(
        action: str,
        user=None,
        entity_type: str = "",
        entity_id=None,
        request=None,
        metadata: dict | None = None,
    ) -> AuditLog | None:
        """Record an audit log entry."""
        try:
            return AuditLog.objects.create(
                user=user if user and user.is_authenticated else None,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
                user_agent=getattr(request, "META", {}).get("HTTP_USER_AGENT", ""),
                metadata=metadata or {},
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to record audit log for action %s", action)
            return None


audit_service = AuditService()

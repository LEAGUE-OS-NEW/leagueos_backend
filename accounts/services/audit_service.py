import uuid
from typing import Any

from accounts.models import AuditLog


class AuditService:
    """Centralized audit logging for sensitive administrative operations."""

    @staticmethod
    def record(
        actor,
        action: str,
        resource_type: str | None = None,
        resource_id=None,
        metadata: dict[str, Any] | None = None,
        request=None,
        previous_state: dict[str, Any] | None = None,
        new_state: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Create an audit record.

        Captures actor, action, resource, IP address, user agent and
        request ID where supported.

        Args:
            actor: The user performing the action (may be None for system events).
            action: One of the ``AuditLog.ACTION_CHOICES`` values.
            resource_type: Optional resource type label (e.g. ``role``, ``market``).
            resource_id: Optional UUID of the affected resource.
            metadata: Optional dictionary of extra context.
            request: Optional Django request used to derive IP, user agent
                and request ID.
            previous_state: Optional previous state snapshot.
            new_state: Optional new state snapshot.

        Returns:
            The created ``AuditLog`` record.
        """
        ip_address = None
        user_agent = ""
        request_id = ""

        if request is not None:
            ip_address = request.META.get("REMOTE_ADDR")
            user_agent = request.META.get("HTTP_USER_AGENT", "")
            request_id = request.META.get("HTTP_X_REQUEST_ID", "")

        if resource_id is not None and not isinstance(resource_id, uuid.UUID):
            try:
                resource_id = uuid.UUID(str(resource_id))
            except (ValueError, TypeError):
                resource_id = None

        merged_metadata: dict[str, Any] = {}
        if metadata:
            merged_metadata.update(metadata)
        if previous_state is not None:
            merged_metadata["previous_state"] = previous_state
        if new_state is not None:
            merged_metadata["new_state"] = new_state

        return AuditLog.objects.create(
            user=actor if getattr(actor, "is_authenticated", False) else None,
            action=action,
            resource_type=resource_type or "",
            resource_id=resource_id,
            request_id=request_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=merged_metadata,
        )

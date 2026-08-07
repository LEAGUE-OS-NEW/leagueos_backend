"""Club workspace service for managing club-scoped access."""

from __future__ import annotations

import logging

from clubs.models import ClubAuditLog, ClubWorkspace

logger = logging.getLogger(__name__)


class ClubWorkspaceService:
    """Service for club workspace operations."""

    @staticmethod
    def get_active_workspace(user, club):
        """Get active workspace for user and club."""
        try:
            return ClubWorkspace.objects.get(user=user, club=club, is_active=True)
        except ClubWorkspace.DoesNotExist:
            return None

    @staticmethod
    def get_user_clubs(user):
        """Get all clubs user has access to."""
        return ClubWorkspace.objects.filter(
            user=user,
            is_active=True,
        ).select_related("club")

    @staticmethod
    def switch_workspace(user, club, request=None):
        """Switch user's active workspace to a club."""
        workspaces = ClubWorkspace.objects.filter(user=user, is_active=True)
        target = None
        for ws in workspaces:
            if ws.club_id == club.id:
                target = ws
                break

        if not target:
            return None, "User does not have access to this club."

        # Record audit
        ClubAuditLog.objects.create(
            club=club,
            user=user,
            action="WORKSPACE_SWITCHED",
            entity_type="Club",
            entity_id=club.id,
            ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
            user_agent=getattr(request, "META", {}).get("HTTP_USER_AGENT", ""),
            metadata={"club_name": club.name},
        )

        return target, None

    @staticmethod
    def check_permission(user, club, permission):
        """Check if user has specific permission for club."""
        workspace = ClubWorkspaceService.get_active_workspace(user, club)
        if not workspace or not workspace.is_active:
            return False

        # Admins have all permissions
        if workspace.role == ClubWorkspace.WorkspaceRole.ADMIN:
            return True

        # Check granular permissions
        return permission in workspace.permissions


club_workspace_service = ClubWorkspaceService()

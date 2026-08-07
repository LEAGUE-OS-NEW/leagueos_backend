"""Permissions for club management."""

from __future__ import annotations

from rest_framework.permissions import BasePermission

from clubs.services.club_workspace_service import ClubWorkspaceService


class IsClubAdmin(BasePermission):
    """Permission for club admins."""

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        club = getattr(obj, "club", None)
        if not club:
            return False
        workspace = ClubWorkspaceService.get_active_workspace(request.user, club)
        return workspace is not None and workspace.role == "ADMIN"


class IsClubStaff(BasePermission):
    """Permission for club staff."""

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        club = getattr(obj, "club", None)
        if not club:
            return False
        workspace = ClubWorkspaceService.get_active_workspace(request.user, club)
        return workspace is not None and workspace.is_active


class HasClubPermission(BasePermission):
    """Permission based on workspace permissions."""

    def has_permission(self, request, view):
        required_permission = getattr(view, "required_permission", None)
        if not required_permission:
            return True

        club_id = request.data.get("club") or request.query_params.get("club")
        if not club_id:
            return False

        from profiles.models import Club

        try:
            club = Club.objects.get(id=club_id)
        except Club.DoesNotExist:
            return False

        return ClubWorkspaceService.check_permission(request.user, club, required_permission)

    def has_object_permission(self, request, view, obj):
        club = getattr(obj, "club", None)
        if not club:
            return False
        required_permission = getattr(view, "required_permission", None)
        if not required_permission:
            return True
        return ClubWorkspaceService.check_permission(request.user, club, required_permission)

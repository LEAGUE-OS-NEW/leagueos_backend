from rest_framework.permissions import BasePermission

from authentication.services.permission_service import PermissionService


class CanManageFantasy(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        required = getattr(view, "fantasy_permission", None)
        if callable(required):
            required = required()
        return PermissionService.has_permission(request.user, "platform.fantasy.manage") or bool(
            required and PermissionService.has_permission(request.user, required)
        )

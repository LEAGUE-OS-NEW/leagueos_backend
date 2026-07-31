from django.contrib.auth import get_user_model

from authentication.services.permission_service import PermissionService

User = get_user_model()


class HasPermission:
    """Generic permission engine that checks database-backed permissions."""

    def __init__(self, permission_name: str):
        self.permission_name = permission_name

    def __call__(self, request, view, obj=None) -> bool:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        return PermissionService.has_permission(user, self.permission_name)

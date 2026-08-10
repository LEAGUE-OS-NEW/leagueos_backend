from django.core.exceptions import ImproperlyConfigured
from rest_framework.permissions import BasePermission

from authentication.services.permission_service import (
    PermissionService,
)


class HasPermission(BasePermission):
    message = "You do not have permission to perform this action."

    def has_permission(self, request, view) -> bool:
        required_permissions = getattr(
            view,
            "required_permission",  # For backward compatibility with single permission
            getattr(view, "required_permissions", None),  # New: for multiple permissions
        )

        if not required_permissions:
            raise ImproperlyConfigured(
                f"{view.__class__.__name__} must define "
                "'required_permission' or 'required_permissions' when using HasPermission."
            )

        if isinstance(required_permissions, str):
            required_permissions = [required_permissions]

        return PermissionService.has_any_permission(
            request.user,
            required_permissions,
        )

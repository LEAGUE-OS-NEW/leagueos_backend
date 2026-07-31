from django.core.exceptions import ImproperlyConfigured
from rest_framework.permissions import BasePermission

from authentication.services.permission_service import (
    PermissionService,
)


class HasPermission(BasePermission):
    message = "You do not have permission to perform this action."

    def has_permission(self, request, view) -> bool:
        required_permission = getattr(
            view,
            "required_permission",
            None,
        )

        if not required_permission:
            raise ImproperlyConfigured(
                f"{view.__class__.__name__} must define "
                "'required_permission' when using HasPermission."
            )

        return PermissionService.has_permission(
            request.user,
            required_permission,
        )

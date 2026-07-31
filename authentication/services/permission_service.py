import logging

from django.contrib.auth import get_user_model

from authentication.models import RolePermission

logger = logging.getLogger(__name__)
User = get_user_model()


class PermissionService:
    @staticmethod
    def get_user_permissions(user) -> list[str]:
        role_ids = user.user_roles.values_list("role_id", flat=True)
        permission_names = RolePermission.objects.filter(role_id__in=role_ids).values_list(
            "permission__name", flat=True
        )
        return list(permission_names)

    @staticmethod
    def has_permission(user, permission_name: str) -> bool:
        return permission_name in PermissionService.get_user_permissions(user)

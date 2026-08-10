from django.db.models import Q
from django.utils import timezone

from authentication.models import Permission, RolePermission, UserRole, UserPermission


class PermissionService:
    """Resolve effective permissions for a user.

    Effective permissions are the union of:
    - ``RolePermission`` entries granted through active user roles, and
    - direct ``UserPermission`` grants.

    Superusers implicitly hold every permission in the database.
    """

    @staticmethod
    def get_user_permissions(user) -> list[str]:
        if user is None or not user.is_authenticated or not user.is_active:
            return []

        if user.is_superuser:
            return list(
                Permission.objects.filter(active=True).order_by("code").values_list(
                    "code",
                    flat=True,
                )
            )

        now = timezone.now()
        active_user_roles = UserRole.objects.filter(
            user=user, is_active=True
        ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))

        role_perm_codes = set(
            Permission.objects.filter(
                role_permissions__role__in=active_user_roles.values("role"), active=True
            ).values_list("code", flat=True)
        )

        direct_perm_codes = set(
            UserPermission.objects.filter(
                user=user, is_active=True, permission__active=True
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .values_list("permission__code", flat=True)
        )

        return sorted(list(role_perm_codes | direct_perm_codes))

    @staticmethod
    def has_permission(
        user,
        permission_code: str,
    ) -> bool:
        if user is None or not user.is_authenticated or not user.is_active:
            return False

        if user.is_superuser:
            return True
        
        now = timezone.now()
        role_perm = RolePermission.objects.filter(
            role__user_roles__user=user,
            role__user_roles__is_active=True,
            permission__code=permission_code,
            permission__active=True,
        ).filter(
            Q(role__user_roles__expires_at__isnull=True)
            | Q(role__user_roles__expires_at__gt=now)
        )

        if role_perm.exists():
            return True

        return UserPermission.objects.filter(
            user=user,
            permission__code=permission_code,
            permission__active=True,
            is_active=True,
        ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).exists()

    @staticmethod
    def has_any_permission(
        user,
        permission_names: list[str] | tuple[str, ...],
    ) -> bool:
        return any(
            PermissionService.has_permission(
                user,
                permission_name,
            )
            for permission_name in permission_names
        )

    @staticmethod
    def has_all_permissions(
        user,
        permission_names: list[str] | tuple[str, ...],
    ) -> bool:
        return all(
            PermissionService.has_permission(
                user,
                permission_name,
            )
            for permission_name in permission_names
        )

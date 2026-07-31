from authentication.models import Permission, RolePermission


class PermissionService:
    @staticmethod
    def get_user_permissions(user) -> list[str]:
        if user is None or not user.is_authenticated or not user.is_active:
            return []

        if user.is_superuser:
            return list(
                Permission.objects.order_by("name").values_list(
                    "name",
                    flat=True,
                )
            )

        return list(
            RolePermission.objects.filter(
                role__user_roles__user=user,
            )
            .order_by("permission__name")
            .values_list(
                "permission__name",
                flat=True,
            )
            .distinct()
        )

    @staticmethod
    def has_permission(
        user,
        permission_name: str,
    ) -> bool:
        if user is None or not user.is_authenticated or not user.is_active:
            return False

        if user.is_superuser:
            return True

        return RolePermission.objects.filter(
            role__user_roles__user=user,
            permission__name=permission_name,
        ).exists()

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

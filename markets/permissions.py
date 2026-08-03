from rest_framework.permissions import (
    SAFE_METHODS,
    BasePermission,
)

from authentication.services.permission_service import (
    PermissionService,
)


class HasMarketAdminAccess(BasePermission):
    message = "You do not have permission to access " "market administration."

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS:
            return PermissionService.has_any_permission(
                request.user,
                (
                    "manage_market",
                    "approve_market",
                ),
            )

        return PermissionService.has_permission(
            request.user,
            "manage_market",
        )


class HasManageMarketPermission(BasePermission):
    message = "You do not have the manage_market " "permission."

    def has_permission(self, request, view) -> bool:
        return PermissionService.has_permission(
            request.user,
            "manage_market",
        )


class HasAnyMarketPermission(BasePermission):
    message = "You do not have permission to moderate market proposals."

    def has_permission(self, request, view) -> bool:
        return PermissionService.has_any_permission(
            request.user, ("manage_market", "approve_market")
        )


class HasApproveMarketPermission(BasePermission):
    message = "You do not have the approve_market " "permission."

    def has_permission(self, request, view) -> bool:
        return PermissionService.has_permission(
            request.user,
            "approve_market",
        )


class HasManageCompliancePermission(BasePermission):
    message = "You do not have the manage_compliance permission."

    def has_permission(self, request, view) -> bool:
        return PermissionService.has_permission(request.user, "manage_compliance")

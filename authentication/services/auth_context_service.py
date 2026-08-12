from authentication.models import RolePermission
from authentication.services.role_service import RoleService


class AuthContextService:
    """Build the single authenticated-user contract used by auth endpoints."""

    @staticmethod
    def user_context(user) -> dict:
        roles = RoleService.get_user_roles(user)
        highest_role = RoleService.get_highest_priority_role(user)
        role_ids = [role.id for role in roles]
        permissions = list(
            RolePermission.objects.filter(role_id__in=role_ids)
            .values_list("permission__name", flat=True)
            .distinct()
            .order_by("permission__name")
        )
        onboarding = getattr(user, "onboarding", None)
        entitlements = [
            {
                "role": role.name,
                "dashboard_url": role.dashboard_url,
            }
            for role in roles
        ]
        kyc = getattr(user, "kyc_verification", None)
        kyc_status = kyc.status if kyc else "NOT_STARTED"

        return {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone_number": user.phone_number,
            "is_verified": user.is_verified,
            "kyc_status": kyc_status,
            "roles": [role.name for role in roles],
            "permissions": permissions,
            "dashboard_access": {
                "entitlements": entitlements,
                "default_entitlement": highest_role.name if highest_role else None,
                "default_route": highest_role.dashboard_url if highest_role else "",
            },
            "onboarding": {
                "completed": bool(onboarding and onboarding.completed),
                "current_step": onboarding.current_step if onboarding else None,
            },
        }

    @classmethod
    def authenticated_data(cls, user, access=None, refresh=None) -> dict:
        data = {"user": cls.user_context(user)}
        if access is not None:
            data["access"] = access
        if refresh is not None:
            data["refresh"] = refresh
        return data

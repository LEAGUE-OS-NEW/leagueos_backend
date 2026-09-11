from authentication.models import Role
from authentication.services.role_service import RoleService


class KYCMarketAccessService:
    VERIFIED_MARKET_USER_ROLE = "Verified Market User"

    @classmethod
    def grant_verified_participant_role(cls, *, user, assigned_by=None):
        """Idempotently grant only the canonical market participant role."""
        role = Role.objects.filter(name=cls.VERIFIED_MARKET_USER_ROLE).first()
        if role is None:
            return None
        return RoleService.assign_role(user=user, role=role, assigned_by=assigned_by)

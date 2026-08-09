from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from authentication.models import Role, UserRole

SUPER_ADMIN_ROLE_NAME = "Super Admin"


class RoleService:
    @staticmethod
    def count_active_super_admins() -> int:
        """Return the number of users with an effective Super Admin role."""
        return (
            UserRole.objects.filter(
                role__name=SUPER_ADMIN_ROLE_NAME,
                is_active=True,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
            .values("user_id")
            .distinct()
            .count()
        )

    @staticmethod
    def _validate_not_last_super_admin(user, role: Role) -> None:
        """Prevent removing or disabling the final active Super Admin."""
        if role.name != SUPER_ADMIN_ROLE_NAME:
            return

        user_role = UserRole.objects.filter(
            user=user,
            role=role,
            is_active=True,
        ).first()

        if not user_role:
            return

        if user_role.is_expired:
            return

        if RoleService.count_active_super_admins() <= 1:
            raise ValidationError(
                "Cannot remove the final active Super Admin. "
                "Assign another Super Admin before revoking this role."
            )

    @staticmethod
    def assign_role(
        user,
        role: Role,
        assigned_by=None,
        expires_at=None,
    ) -> UserRole:
        user_role, _ = UserRole.objects.get_or_create(
            user=user,
            role=role,
            defaults={
                "assigned_by": assigned_by,
                "expires_at": expires_at,
            },
        )

        return user_role

    @staticmethod
    def remove_role(
        user,
        role: Role,
        revoked_by=None,
    ) -> UserRole | None:
        RoleService._validate_not_last_super_admin(user, role)

        user_role = UserRole.objects.filter(
            user=user,
            role=role,
            is_active=True,
        ).first()

        if user_role:
            user_role.is_active = False
            user_role.revoked_at = timezone.now()
            user_role.revoked_by = revoked_by
            user_role.save(update_fields=["is_active", "revoked_at", "revoked_by"])

        return user_role

    @staticmethod
    def get_user_roles(user) -> list[Role]:
        return list(
            Role.objects.filter(
                user_roles__user=user,
                user_roles__is_active=True,
            )
            .filter(
                Q(user_roles__expires_at__isnull=True)
                | Q(user_roles__expires_at__gt=timezone.now())
            )
            .distinct()
            .order_by("name")
        )

    @staticmethod
    def get_highest_priority_role(user) -> Role | None:
        roles = RoleService.get_user_roles(user)

        if not roles:
            return None

        priority = {
            "Super Admin": 1,
            "General Admin": 2,
            "Club Admin": 3,
            "Customer Support Admin": 4,
            "Finance Admin": 5,
            "Market Approval Admin": 6,
            "Compliance Admin": 7,
            "Result Verification Admin": 8,
            "Market Operations Admin": 9,
            "Sports Data & Statistics Admin": 10,
            "Club Specialist Staff": 11,
            "Ticket Holder": 12,
            "Customer": 13,
            "Fantasy Manager": 14,
            "Verified Market User": 15,
            "Fan": 16,
            "Visitor": 17,
        }

        return min(
            roles,
            key=lambda role: priority.get(
                role.name,
                99,
            ),
        )

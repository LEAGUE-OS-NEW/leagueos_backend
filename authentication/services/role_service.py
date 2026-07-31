from authentication.models import Role, UserRole


class RoleService:
    @staticmethod
    def assign_role(
        user,
        role: Role,
        assigned_by=None,
    ) -> UserRole:
        user_role, _ = UserRole.objects.get_or_create(
            user=user,
            role=role,
            defaults={
                "assigned_by": assigned_by,
            },
        )

        return user_role

    @staticmethod
    def remove_role(
        user,
        role: Role,
    ) -> None:
        UserRole.objects.filter(
            user=user,
            role=role,
        ).delete()

    @staticmethod
    def get_user_roles(user) -> list[Role]:
        return list(
            Role.objects.filter(
                user_roles__user=user,
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

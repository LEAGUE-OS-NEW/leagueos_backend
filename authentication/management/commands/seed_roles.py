from django.core.management.base import (
    BaseCommand,
    CommandError,
)

from authentication.models import (
    Permission,
    Role,
    RolePermission,
)

SYSTEM_ROLES = [
    {
        "name": "Visitor",
        "display_name": "Visitor",
        "description": "Basic visitor access",
        "dashboard_url": "",
    },
    {
        "name": "Fan",
        "display_name": "Fan",
        "description": "Registered fan",
        "dashboard_url": "",
    },
    {
        "name": "Verified Market User",
        "display_name": "Verified Market User",
        "description": "Verified market participant",
        "dashboard_url": "",
    },
    {
        "name": "Fantasy Manager",
        "display_name": "Fantasy Manager",
        "description": "Fantasy league manager",
        "dashboard_url": "",
    },
    {
        "name": "Club Member",
        "display_name": "Club Member",
        "description": "Club membership access",
        "dashboard_url": "",
    },
    {
        "name": "Ticket Holder",
        "display_name": "Ticket Holder",
        "description": "Ticket holder",
        "dashboard_url": "",
    },
    {
        "name": "Customer",
        "display_name": "Customer",
        "description": "General customer",
        "dashboard_url": "",
    },
    {
        "name": "Club Admin",
        "display_name": "Club Admin",
        "description": "Club administrator",
        "dashboard_url": "/admin/club",
    },
    {
        "name": "Club Specialist Staff",
        "display_name": "Club Specialist Staff",
        "description": "Club specialist staff",
        "dashboard_url": "/admin/club-staff",
    },
    {
        "name": "General Admin",
        "display_name": "General Admin",
        "description": "General administrator",
        "dashboard_url": "/admin",
    },
    {
        "name": "Sports Data & Statistics Admin",
        "display_name": "Sports Data & Statistics Admin",
        "description": "Sports data administrator",
        "dashboard_url": "/admin/statistics",
    },
    {
        "name": "Market Operations Admin",
        "display_name": "Market Operations Admin",
        "description": "Market operations administrator",
        "dashboard_url": "/admin/market",
    },
    {
        "name": "Market Approval Admin",
        "display_name": "Market Approval Admin",
        "description": "Market approval administrator",
        "dashboard_url": "/admin/market-approval",
    },
    {
        "name": "Result Verification Admin",
        "display_name": "Result Verification Admin",
        "description": "Result verification administrator",
        "dashboard_url": "/admin/result-verification",
    },
    {
        "name": "Compliance Admin",
        "display_name": "Compliance Admin",
        "description": "Compliance administrator",
        "dashboard_url": "/admin/compliance",
    },
    {
        "name": "Finance Admin",
        "display_name": "Finance Admin",
        "description": "Finance administrator",
        "dashboard_url": "/admin/finance",
    },
    {
        "name": "Customer Support Admin",
        "display_name": "Customer Support Admin",
        "description": "Customer support administrator",
        "dashboard_url": "/admin/support",
    },
    {
        "name": "Super Admin",
        "display_name": "Super Admin",
        "description": "Super administrator with full access",
        "dashboard_url": "/admin",
    },
    {
        "name": "External Systems",
        "display_name": "External Systems",
        "description": "External system integration",
        "dashboard_url": "",
    },
]


SYSTEM_PERMISSIONS = [
    {
        "name": "manage_users",
        "resource": "users",
        "action": "manage",
        "description": "Manage users.",
    },
    {
        "name": "manage_market",
        "resource": "market",
        "action": "manage",
        "description": "Create, edit and submit market drafts.",
    },
    {
        "name": "approve_market",
        "resource": "market",
        "action": "approve",
        "description": "Approve, reject and publish markets.",
    },
    {
        "name": "participate_market",
        "resource": "market",
        "action": "participate",
        "description": "Participate in eligible markets.",
    },
    {
        "name": "verify_results",
        "resource": "results",
        "action": "verify",
        "description": "Verify market and sporting results.",
    },
    {
        "name": "manage_compliance",
        "resource": "compliance",
        "action": "manage",
        "description": "Manage eligibility and compliance reviews.",
    },
    {
        "name": "manage_finance",
        "resource": "finance",
        "action": "manage",
        "description": "Manage finance.",
    },
    {
        "name": "manage_clubs",
        "resource": "clubs",
        "action": "manage",
        "description": "Manage clubs.",
    },
    {
        "name": "manage_statistics",
        "resource": "statistics",
        "action": "manage",
        "description": "Manage sports data and statistics.",
    },
    {
        "name": "manage_support",
        "resource": "support",
        "action": "manage",
        "description": "Manage customer support.",
    },
    {
        "name": "manage_configuration",
        "resource": "configuration",
        "action": "manage",
        "description": "Manage system configuration.",
    },
    {
        "name": "manage_roles",
        "resource": "roles",
        "action": "manage",
        "description": "Manage roles and permissions.",
    },
    {
        "name": "buy_ticket",
        "resource": "tickets",
        "action": "buy",
        "description": "Buy tickets.",
    },
    {
        "name": "join_fantasy",
        "resource": "fantasy",
        "action": "join",
        "description": "Join fantasy leagues.",
    },
]


ROLE_PERMISSIONS = {
    "Fan": [
        "buy_ticket",
        "join_fantasy",
    ],
    "Verified Market User": [
        "buy_ticket",
        "join_fantasy",
        "participate_market",
    ],
    "Fantasy Manager": [
        "join_fantasy",
    ],
    "Club Member": [
        "buy_ticket",
        "join_fantasy",
    ],
    "Ticket Holder": [
        "buy_ticket",
    ],
    "Customer": [
        "buy_ticket",
    ],
    "Club Admin": [
        "manage_clubs",
    ],
    "Club Specialist Staff": [
        "manage_clubs",
    ],
    "General Admin": [
        "manage_users",
        "manage_clubs",
        "manage_statistics",
        "manage_support",
    ],
    "Sports Data & Statistics Admin": [
        "manage_statistics",
    ],
    "Market Operations Admin": [
        "manage_market",
    ],
    "Market Approval Admin": [
        "approve_market",
    ],
    "Result Verification Admin": [
        "verify_results",
    ],
    "Compliance Admin": [
        "manage_compliance",
    ],
    "Finance Admin": [
        "manage_finance",
    ],
    "Customer Support Admin": [
        "manage_support",
    ],
    "External Systems": [
        "manage_statistics",
    ],
}

ROLE_PERMISSIONS["Super Admin"] = [permission["name"] for permission in SYSTEM_PERMISSIONS]


class Command(BaseCommand):
    help = "Seed system roles, permissions and role mappings"

    def handle(self, *args, **options):
        self.stdout.write("Seeding roles, permissions and mappings...")

        for permission_data in SYSTEM_PERMISSIONS:
            permission_name = permission_data["name"]
            defaults = {key: value for key, value in permission_data.items() if key != "name"}

            permission, created = Permission.objects.update_or_create(
                name=permission_name,
                defaults=defaults,
            )

            action = "Created" if created else "Updated"
            self.stdout.write(f"{action} permission: {permission.name}")

        for role_data in SYSTEM_ROLES:
            role_name = role_data["name"]
            defaults = {key: value for key, value in role_data.items() if key != "name"}

            role, created = Role.objects.update_or_create(
                name=role_name,
                defaults={
                    **defaults,
                    "is_system": True,
                },
            )

            action = "Created" if created else "Updated"
            self.stdout.write(f"{action} role: {role.display_name}")

        for role_name, permission_names in ROLE_PERMISSIONS.items():
            try:
                role = Role.objects.get(name=role_name)
            except Role.DoesNotExist as exc:
                raise CommandError(f"Role '{role_name}' was not created.") from exc

            permissions = {
                permission.name: permission
                for permission in Permission.objects.filter(
                    name__in=permission_names,
                )
            }

            missing_permission_names = set(permission_names) - set(permissions)

            if missing_permission_names:
                raise CommandError(
                    f"Missing permissions for role "
                    f"'{role_name}': "
                    f"{sorted(missing_permission_names)}"
                )

            for permission_name in permission_names:
                RolePermission.objects.get_or_create(
                    role=role,
                    permission=permissions[permission_name],
                )

        self.stdout.write(
            self.style.SUCCESS("Successfully seeded roles, permissions " "and role mappings.")
        )

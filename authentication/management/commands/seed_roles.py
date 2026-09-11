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
        "name": "Market Operations & Approval Admin",
        "display_name": "Market Operations & Approval Admin",
        "description": "Market operations and approval administrator",
        "dashboard_url": "/admin/market",
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
    {
        "name": "view_market",
        "resource": "market",
        "action": "view",
        "description": "View markets.",
    },
    {
        "name": "edit_market",
        "resource": "market",
        "action": "edit",
        "description": "Edit markets.",
    },
    {
        "name": "configure_market",
        "resource": "market",
        "action": "configure",
        "description": "Configure market parameters.",
    },
    {
        "name": "publish_market",
        "resource": "market",
        "action": "publish",
        "description": "Publish markets.",
    },
    {
        "name": "open_market",
        "resource": "market",
        "action": "open",
        "description": "Open markets for trading.",
    },
    {
        "name": "suspend_market",
        "resource": "market",
        "action": "suspend",
        "description": "Suspend markets.",
    },
    {
        "name": "resume_market",
        "resource": "market",
        "action": "resume",
        "description": "Resume suspended markets.",
    },
    {
        "name": "close_market",
        "resource": "market",
        "action": "close",
        "description": "Close markets.",
    },
    {
        "name": "archive_market",
        "resource": "market",
        "action": "archive",
        "description": "Archive markets.",
    },
    {
        "name": "view_market_audit",
        "resource": "market",
        "action": "audit.view",
        "description": "View market audit history.",
    },
    {
        "name": "review_market",
        "resource": "market",
        "action": "review",
        "description": "Review markets.",
    },
    {
        "name": "reject_market",
        "resource": "market",
        "action": "reject",
        "description": "Reject markets.",
    },
    {
        "name": "request_market_changes",
        "resource": "market",
        "action": "request_changes",
        "description": "Request changes to markets.",
    },
    {
        "name": "view_result",
        "resource": "result",
        "action": "view",
        "description": "View results.",
    },
    {
        "name": "reject_result",
        "resource": "result",
        "action": "reject",
        "description": "Reject results.",
    },
    {
        "name": "reverify_result",
        "resource": "result",
        "action": "reverify",
        "description": "Request re-verification of results.",
    },
    {
        "name": "view_compliance",
        "resource": "compliance",
        "action": "view",
        "description": "View compliance data.",
    },
    {
        "name": "review_compliance",
        "resource": "compliance",
        "action": "review",
        "description": "Review compliance cases.",
    },
    {
        "name": "apply_restriction",
        "resource": "compliance",
        "action": "restrict",
        "description": "Apply account restrictions.",
    },
    {
        "name": "view_support",
        "resource": "support",
        "action": "view",
        "description": "View customer support cases.",
    },
    {
        "name": "manage_support_cases",
        "resource": "support",
        "action": "manage",
        "description": "Manage customer support cases.",
    },
    {
        "name": "view_finance",
        "resource": "finance",
        "action": "view",
        "description": "View financial data.",
    },
    {
        "name": "reconcile_finance",
        "resource": "finance",
        "action": "reconcile",
        "description": "Reconcile financial transactions.",
    },
    {
        "name": "review_withdrawal",
        "resource": "finance",
        "action": "withdrawal.review",
        "description": "Review withdrawal requests.",
    },
    {
        "name": "view_audit",
        "resource": "audit",
        "action": "view",
        "description": "View audit logs.",
    },
    {
        "name": "invite_admins",
        "resource": "admin",
        "action": "invite",
        "description": "Invite administrators.",
    },
    {
        "name": "view_sports",
        "resource": "sports",
        "action": "view",
        "description": "View sports data.",
    },
    {
        "name": "create_sports",
        "resource": "sports",
        "action": "create",
        "description": "Create sports data.",
    },
    {
        "name": "update_sports",
        "resource": "sports",
        "action": "update",
        "description": "Update sports data.",
    },
    {
        "name": "delete_sports",
        "resource": "sports",
        "action": "delete",
        "description": "Delete sports data.",
    },
    {
        "name": "manage_sports",
        "resource": "sports",
        "action": "manage",
        "description": "Manage sports data.",
    },
    {
        "name": "view_news",
        "resource": "news",
        "action": "view",
        "description": "View the news moderation queue and articles.",
    },
    {
        "name": "manage_news",
        "resource": "news",
        "action": "manage",
        "description": "Edit, approve, reject, and curate news articles.",
    },
    {
        "name": "admin.users.view",
        "resource": "admin",
        "action": "users.view",
        "description": "View administrative users.",
    },
    {
        "name": "admin.users.manage",
        "resource": "admin",
        "action": "users.manage",
        "description": "Manage administrative users.",
    },
    {
        "name": "admin.users.invite",
        "resource": "admin",
        "action": "users.invite",
        "description": "Invite administrators.",
    },
    {
        "name": "admin.roles.view",
        "resource": "admin",
        "action": "roles.view",
        "description": "View roles.",
    },
    {
        "name": "admin.permissions.view",
        "resource": "admin",
        "action": "permissions.view",
        "description": "View permissions.",
    },
    {
        "name": "admin.audit.view",
        "resource": "admin",
        "action": "audit.view",
        "description": "View audit logs.",
    },
    {
        "name": "admin.dashboard.view",
        "resource": "admin",
        "action": "dashboard.view",
        "description": "View administrative dashboard.",
    },
    {
        "name": "admin.configuration.manage",
        "resource": "admin",
        "action": "configuration.manage",
        "description": "Manage platform configuration.",
    },
    {
        "name": "admin.memberships.manage",
        "resource": "admin",
        "action": "memberships.manage",
        "description": "Manage platform membership plans and subscribers.",
    },
    {
        "name": "admin.clubs.manage",
        "resource": "admin",
        "action": "clubs.manage",
        "description": (
            "Create clubs and act as a club admin on any club, "
            "independent of individual club workspace membership."
        ),
    },
]

ROLE_PERMISSIONS = {
    "Fan": [
        "buy_ticket",
        "join_fantasy",
    ],
    "Verified Market User": [
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
        "admin.dashboard.view",
        "view_sports",
        "create_sports",
        "update_sports",
        "delete_sports",
        "manage_sports",
        "view_news",
        "manage_news",
    ],
    "Market Operations & Approval Admin": [
        "admin.dashboard.view",
        "view_market",
        "manage_market",
        "edit_market",
        "configure_market",
        "review_market",
        "approve_market",
        "reject_market",
        "request_market_changes",
        "publish_market",
        "open_market",
        "suspend_market",
        "resume_market",
        "close_market",
        "archive_market",
        "view_market_audit",
    ],
    "Result Verification Admin": [
        "admin.dashboard.view",
        "view_result",
        "verify_results",
        "reject_result",
        "reverify_result",
    ],
    "Compliance Admin": [
        "admin.dashboard.view",
        "view_compliance",
        "manage_compliance",
        "review_compliance",
        "apply_restriction",
    ],
    "Finance Admin": [
        "admin.dashboard.view",
        "view_finance",
        "manage_finance",
        "reconcile_finance",
        "review_withdrawal",
    ],
    "Customer Support Admin": [
        "admin.dashboard.view",
        "view_support",
        "manage_support_cases",
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
            defaults = {
                key: value for key, value in permission_data.items() if key not in ("name", "code")
            }
            defaults.setdefault("code", permission_name)

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

            managed_permission_names = [permission["name"] for permission in SYSTEM_PERMISSIONS]

            RolePermission.objects.filter(
                role=role,
                permission__name__in=managed_permission_names,
            ).exclude(
                permission__name__in=permission_names,
            ).delete()

            for permission_name in permission_names:
                RolePermission.objects.get_or_create(
                    role=role,
                    permission=permissions[permission_name],
                )

        # Super Admin is intentionally permission-complete.
        #
        # Permissions can be introduced by other apps/migrations (for example,
        # Fantasy) and therefore may not appear in this command's legacy
        # SYSTEM_PERMISSIONS catalogue. Always synchronize Super Admin against
        # the complete current Permission table.
        super_admin = Role.objects.get(name="Super Admin")

        for permission in Permission.objects.all():
            RolePermission.objects.get_or_create(
                role=super_admin,
                permission=permission,
            )

        self.stdout.write(
            self.style.SUCCESS("Successfully seeded roles, permissions " "and role mappings.")
        )

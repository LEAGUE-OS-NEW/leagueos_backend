import logging

from django.core.management.base import BaseCommand

from authentication.models import Permission, Role

logger = logging.getLogger(__name__)

SYSTEM_ROLES = [
    {
        "name": "Visitor",
        "display_name": "Visitor",
        "description": "Basic visitor access",
        "dashboard_url": "",
    },
    {"name": "Fan", "display_name": "Fan", "description": "Registered fan", "dashboard_url": ""},
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
        "description": "Manage users",
    },
    {
        "name": "approve_market",
        "resource": "market",
        "action": "approve",
        "description": "Approve market items",
    },
    {
        "name": "manage_finance",
        "resource": "finance",
        "action": "manage",
        "description": "Manage finance",
    },
    {
        "name": "manage_clubs",
        "resource": "clubs",
        "action": "manage",
        "description": "Manage clubs",
    },
    {
        "name": "verify_results",
        "resource": "results",
        "action": "verify",
        "description": "Verify results",
    },
    {
        "name": "manage_statistics",
        "resource": "statistics",
        "action": "manage",
        "description": "Manage statistics",
    },
    {
        "name": "manage_support",
        "resource": "support",
        "action": "manage",
        "description": "Manage support",
    },
    {
        "name": "manage_configuration",
        "resource": "configuration",
        "action": "manage",
        "description": "Manage configuration",
    },
    {
        "name": "manage_roles",
        "resource": "roles",
        "action": "manage",
        "description": "Manage roles",
    },
    {"name": "buy_ticket", "resource": "tickets", "action": "buy", "description": "Buy tickets"},
    {
        "name": "join_fantasy",
        "resource": "fantasy",
        "action": "join",
        "description": "Join fantasy leagues",
    },
    {
        "name": "participate_market",
        "resource": "market",
        "action": "participate",
        "description": "Participate in market",
    },
]


class Command(BaseCommand):
    help = "Seed initial system roles and permissions"

    def handle(self, *args, **options):
        self.stdout.write("Seeding roles and permissions...")
        for perm_data in SYSTEM_PERMISSIONS:
            permission, _ = Permission.objects.get_or_create(
                name=perm_data["name"], defaults=perm_data
            )
            if _:
                self.stdout.write(f"Created permission: {permission.name}")

        for role_data in SYSTEM_ROLES:
            role, _ = Role.objects.get_or_create(name=role_data["name"], defaults=role_data)
            if _:
                self.stdout.write(f"Created role: {role.display_name}")

        self.stdout.write(self.style.SUCCESS("Successfully seeded roles and permissions"))

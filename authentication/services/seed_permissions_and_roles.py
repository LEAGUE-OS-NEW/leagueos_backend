# ruff: noqa: E501

import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from authentication.models import Permission, Role, RolePermission

logger = logging.getLogger(__name__)

# fmt: off
PERMISSIONS = [
    # Club Permissions
    {"code": "club.profile.view", "name": "View Club Profile", "category": "Club Management", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.profile.manage", "name": "Manage Club Profile", "category": "Club Management", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.news.view", "name": "View Club News", "category": "Content Management", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.news.manage", "name": "Manage Club News", "category": "Content Management", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.media.view", "name": "View Club Media", "category": "Content Management", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.media.manage", "name": "Manage Club Media", "category": "Content Management", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.memberships.view", "name": "View Club Memberships", "category": "Membership Management", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.memberships.manage", "name": "Manage Club Memberships", "category": "Membership Management", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.tickets.view", "name": "View Club Tickets", "category": "Ticketing", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.tickets.manage", "name": "Manage Club Tickets", "category": "Ticketing", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.store.view", "name": "View Club Store", "category": "E-commerce", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.store.manage", "name": "Manage Club Store", "category": "E-commerce", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.inventory.view", "name": "View Club Inventory", "category": "E-commerce", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.inventory.manage", "name": "Manage Club Inventory", "category": "E-commerce", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.analytics.view", "name": "View Club Analytics", "category": "Analytics", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.analytics.export", "name": "Export Club Analytics", "category": "Analytics", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.audit.view", "name": "View Club Audit Log", "category": "Club Administration", "scope": Permission.Scope.CLUB, "delegatable": True},
    {"code": "club.users.manage", "name": "Manage Club Users", "category": "Club Administration", "scope": Permission.Scope.CLUB, "delegatable": True},

    # Platform Permissions
    {"code": "platform.users.manage", "name": "Manage Platform Users", "category": "Platform Administration", "scope": Permission.Scope.PLATFORM, "delegatable": True},
    {"code": "platform.roles.manage", "name": "Manage Platform Roles", "category": "Platform Administration", "scope": Permission.Scope.PLATFORM, "delegatable": False},
    {"code": "platform.sports_data.view", "name": "View Sports Data", "category": "Sports Data", "scope": Permission.Scope.PLATFORM, "delegatable": True},
    {"code": "platform.sports_data.manage", "name": "Manage Sports Data", "category": "Sports Data", "scope": Permission.Scope.PLATFORM, "delegatable": True},
    {"code": "platform.markets.view", "name": "View Markets", "category": "Markets", "scope": Permission.Scope.PLATFORM, "delegatable": True},
    {"code": "platform.markets.manage", "name": "Manage Markets", "category": "Markets", "scope": Permission.Scope.PLATFORM, "delegatable": True},
    {"code": "platform.markets.approve", "name": "Approve Markets", "category": "Markets", "scope": Permission.Scope.PLATFORM, "delegatable": True},
    {"code": "platform.results.view", "name": "View Results", "category": "Results", "scope": Permission.Scope.PLATFORM, "delegatable": True},
    {"code": "platform.results.verify", "name": "Verify Results", "category": "Results", "scope": Permission.Scope.PLATFORM, "delegatable": True},
    {"code": "platform.compliance.view", "name": "View Compliance Data", "category": "Compliance", "scope": Permission.Scope.PLATFORM, "delegatable": True},
    {"code": "platform.compliance.manage", "name": "Manage Compliance Cases", "category": "Compliance", "scope": Permission.Scope.PLATFORM, "delegatable": True},
    {"code": "platform.support.view", "name": "View Support Tickets", "category": "Support", "scope": Permission.Scope.PLATFORM, "delegatable": True},
    {"code": "platform.support.manage", "name": "Manage Support Tickets", "category": "Support", "scope": Permission.Scope.PLATFORM, "delegatable": True},
    {"code": "platform.finance.view", "name": "View Financial Data", "category": "Finance", "scope": Permission.Scope.PLATFORM, "delegatable": True},
    {"code": "platform.finance.manage", "name": "Manage Financial Operations", "category": "Finance", "scope": Permission.Scope.PLATFORM, "delegatable": True},
    {"code": "platform.audit.view", "name": "View Platform Audit Log", "category": "Platform Administration", "scope": Permission.Scope.PLATFORM, "delegatable": True},
]

ROLES = {
    # Platform Roles
    "Super Admin": {"scope": Role.Scope.PLATFORM, "is_system": True, "permissions": [p["code"] for p in PERMISSIONS]},
    "Platform Admin": {"scope": Role.Scope.PLATFORM, "permissions": ["platform.users.manage", "platform.audit.view"]},
    "Platform Assistant": {"scope": Role.Scope.PLATFORM, "permissions": ["platform.users.manage"]},
    "Sports Data Admin": {"scope": Role.Scope.PLATFORM, "permissions": ["platform.sports_data.view", "platform.sports_data.manage"]},
    "Market Operations & Approval Admin": {"scope": Role.Scope.PLATFORM, "permissions": ["platform.markets.view", "platform.markets.manage", "platform.markets.approve"]},
    "Result Verification Admin": {"scope": Role.Scope.PLATFORM, "permissions": ["platform.results.view", "platform.results.verify"]},
    "Compliance Admin": {"scope": Role.Scope.PLATFORM, "permissions": ["platform.compliance.view", "platform.compliance.manage"]},
    "Customer Support Admin": {"scope": Role.Scope.PLATFORM, "permissions": ["platform.support.view", "platform.support.manage"]},
    "Finance Admin": {"scope": Role.Scope.PLATFORM, "permissions": ["platform.finance.view", "platform.finance.manage"]},

    # Club Roles
    "Club Admin": {
        "scope": Role.Scope.CLUB,
        "permissions": [p["code"] for p in PERMISSIONS if p["scope"] == Permission.Scope.CLUB]
    },
    "Club Assistant": {"scope": Role.Scope.CLUB, "permissions": ["club.users.manage", "club.audit.view"]},
    "Club Content Manager": {"scope": Role.Scope.CLUB, "permissions": ["club.news.view", "club.news.manage", "club.media.view", "club.media.manage"]},
    "Club Membership Manager": {"scope": Role.Scope.CLUB, "permissions": ["club.memberships.view", "club.memberships.manage"]},
    "Club Ticketing Manager": {"scope": Role.Scope.CLUB, "permissions": ["club.tickets.view", "club.tickets.manage"]},
    "Club Store Manager": {"scope": Role.Scope.CLUB, "permissions": ["club.store.view", "club.store.manage", "club.inventory.view", "club.inventory.manage"]},
    "Club Media Manager": {"scope": Role.Scope.CLUB, "permissions": ["club.media.view", "club.media.manage"]},
    "Club Support Staff": {"scope": Role.Scope.CLUB, "permissions": ["club.support.view"]},
    "Club Analytics/Reporting Staff": {"scope": Role.Scope.CLUB, "permissions": ["club.analytics.view", "club.analytics.export"]},
}
# fmt: on


class Command(BaseCommand):
    """
    Seeds the database with a comprehensive set of roles and permissions.

    This command is idempotent. It uses `update_or_create` to ensure that
    running it multiple times will not create duplicate entries. It will update
    existing entries if their definitions in the code have changed.

    It performs the following actions:
    1. Creates all defined `Permission` objects.
    2. Creates all defined `Role` objects.
    3. Associates permissions with roles via `RolePermission`.
    4. Cleans up any stale `RolePermission` associations that are no longer
       defined in the configuration.
    """

    help = "Seeds the database with roles and permissions."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Seeding permissions and roles...")

        try:
            self._seed_permissions()
            self._seed_roles_and_associations()
            self.stdout.write(self.style.SUCCESS("Successfully seeded permissions and roles."))

        except Exception as e:
            raise CommandError(f"An error occurred during seeding: {e}") from e

    def _seed_permissions(self):
        """Create or update all Permission objects."""
        self.stdout.write("  - Seeding permissions...")
        created_count = 0
        updated_count = 0

        for perm_data in PERMISSIONS:
            code = perm_data["code"]

            # Derive resource and action from the permission code.
            # e.g., "club.profile.view" -> resource="club.profile", action="view"
            parts = code.split(".")
            if len(parts) < 2:
                self.stdout.write(
                    self.style.ERROR(f"    - Invalid permission code format: {code}. Skipping.")
                )
                continue
            resource = ".".join(parts[:-1])
            action = parts[-1]

            defaults = {
                "name": perm_data["name"],
                "resource": resource,
                "action": action,
                "category": perm_data["category"],
                "scope": perm_data["scope"],
                "delegatable": perm_data.get("delegatable", False),
                "active": True,
            }
            _, created = Permission.objects.update_or_create(code=code, defaults=defaults)
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(f"    - Permissions: {created_count} created, {updated_count} updated.")

    def _seed_roles_and_associations(self):
        """Create or update Roles and their Permission associations."""
        self.stdout.write("  - Seeding roles and role-permission associations...")
        roles_created_count = 0
        roles_updated_count = 0
        perms_assigned_count = 0
        perms_revoked_count = 0

        all_defined_perms = {p.code: p for p in Permission.objects.all()}

        for role_name, role_data in ROLES.items():
            # 1. Create or update the Role
            defaults = {
                "display_name": role_name,
                "scope": role_data["scope"],
                "is_system": role_data.get("is_system", False),
                "description": f"Role for {role_name}",
            }
            role, created = Role.objects.update_or_create(name=role_name, defaults=defaults)

            if created:
                roles_created_count += 1
            else:
                roles_updated_count += 1

            # 2. Sync permissions for the role
            defined_perm_codes = set(role_data.get("permissions", []))
            current_perm_codes = set(
                role.role_permissions.values_list("permission__code", flat=True)
            )

            # Permissions to add
            perms_to_add = defined_perm_codes - current_perm_codes
            for code in perms_to_add:
                if code in all_defined_perms:
                    permission = all_defined_perms[code]
                    RolePermission.objects.create(role=role, permission=permission)
                    perms_assigned_count += 1
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"      - Warning: Permission code '{code}' for role '{role_name}' not found."
                        )
                    )

            # Permissions to remove
            perms_to_remove = current_perm_codes - defined_perm_codes
            if perms_to_remove:
                revoked_count = RolePermission.objects.filter(
                    role=role, permission__code__in=perms_to_remove
                ).delete()[0]
                perms_revoked_count += revoked_count

        self.stdout.write(
            f"    - Roles: {roles_created_count} created, {roles_updated_count} updated."
        )
        self.stdout.write(
            f"    - Role-Permissions: {perms_assigned_count} assigned, {perms_revoked_count} revoked."
        )

        # Final cleanup: Remove permissions from roles that are no longer defined
        self.stdout.write("  - Cleaning up stale role-permission associations...")
        stale_count = 0
        for role in Role.objects.prefetch_related("role_permissions__permission"):
            if role.name not in ROLES:
                continue  # Skip roles not managed by this seeder

            defined_perms = set(ROLES[role.name].get("permissions", []))
            for rp in role.role_permissions.all():
                if rp.permission.code not in defined_perms:
                    rp.delete()
                    stale_count += 1

        if stale_count > 0:
            self.stdout.write(f"    - Cleaned up {stale_count} stale associations.")

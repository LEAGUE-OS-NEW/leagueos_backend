"""Provision the system account used by scheduled market automation.

`markets.tasks.close_due_markets` needs a real, permissioned `User` to pass
as the `actor` of `MarketLifecycleService.close()` — there is no anonymous
or system-actor concept anywhere in that service layer, and every close is
recorded against a real user for the audit trail. This command creates that
one account, scoped to exactly the `approve_market` permission it needs and
nothing else (not a superuser — this account should never be able to do
anything beyond closing a market). It has no usable password: it is never
meant to log in interactively, only to be looked up by email and passed as
`actor=`.

Idempotent — safe to run on every deploy, mirrors
`authentication.management.commands.bootstrap_admins`.
"""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from authentication.models import Permission, Role, RolePermission
from authentication.services.role_service import RoleService

AUTOMATION_ACTOR_EMAIL = "market-automation@leagueos.internal"
AUTOMATION_ROLE_NAME = "Market Close Automation"


class Command(BaseCommand):
    help = "Provision the system account scheduled market automation acts as (idempotent)."

    def handle(self, *args, **options):
        try:
            approve_permission = Permission.objects.get(code="approve_market")
        except Permission.DoesNotExist as error:
            raise CommandError(
                "Permission 'approve_market' does not exist. Run 'python manage.py "
                "seed_roles' before bootstrapping the market automation actor."
            ) from error

        role, role_created = Role.objects.get_or_create(
            name=AUTOMATION_ROLE_NAME,
            defaults={
                "display_name": AUTOMATION_ROLE_NAME,
                "description": (
                    "System account used only by scheduled market-close automation. "
                    "Grants exactly one permission: approve_market."
                ),
                "is_system": True,
                "scope": Role.Scope.PLATFORM,
            },
        )
        _, permission_linked = RolePermission.objects.get_or_create(
            role=role,
            permission=approve_permission,
        )

        user, user_created = User.objects.get_or_create(
            email=AUTOMATION_ACTOR_EMAIL,
            defaults={
                "username": AUTOMATION_ACTOR_EMAIL,
                "first_name": "Market",
                "last_name": "Automation",
                "is_staff": True,
                "is_superuser": False,
                "is_verified": True,
                "account_status": User.AccountStatus.ACTIVE,
            },
        )
        if user_created:
            user.set_unusable_password()
            user.save(update_fields=["password"])

        RoleService.assign_role(user=user, role=role)

        self.stdout.write(
            self.style.SUCCESS(
                f"Market automation actor ready: {AUTOMATION_ACTOR_EMAIL} "
                f"(user {'created' if user_created else 'already existed'}, "
                f"role {'created' if role_created else 'already existed'}, "
                f"permission link {'created' if permission_linked else 'already existed'})."
            )
        )

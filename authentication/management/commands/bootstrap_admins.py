"""Management command to bootstrap the initial administrator accounts.

This command provisions the initial Super Admin and Club Admin accounts together
with their database-backed roles, permission associations and (for the Club
Admin) club workspace membership.

Purpose & scope
---------------
This command is intended for **local / development** environments and for the
very first boot of a fresh environment. It is deliberately kept idempotent so it
is safe to run many times. It will never:

* create a duplicate user, role, permission, role-permission association,
  user-role assignment or club workspace membership;
* overwrite an existing user's password on a subsequent run.

Passwords
---------
* ``SUPER_ADMIN_INITIAL_PASSWORD`` and ``CLUB_ADMIN_INITIAL_PASSWORD``
  environment variables override the default.
* If they are not set, the local development fallback ``Strong123!`` is used
  **only** when ``DEBUG=True``.

.. warning::

    The development fallback password (``Strong123!``) is for local development
    only and MUST be replaced before any production deployment. In any
    non-development environment (``DEBUG=False``) this command **refuses** to run
    with the development fallback and requires the strong password to be supplied
    via the environment variables above.

Security notes
--------------
* Passwords are always stored with Django's secure password hashing via
  ``User.set_password()`` -- never in plain text.
* The resolved password is never logged and never returned from the command.
* No database IDs are hard-coded; roles, permissions and the club are resolved
  by stable, human-readable lookups (name/code/slug).
"""

import logging
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import User
from authentication.models import Permission, Role, RolePermission
from authentication.services.role_service import RoleService
from clubs.models import ClubWorkspace
from profiles.models import Club

logger = logging.getLogger(__name__)

# Local development fallback only. Must never be used in production -- the
# command enforces this by refusing to run with it whenever DEBUG is disabled.
DEV_FALLBACK_PASSWORD = "Strong123!"

SUPER_ADMIN_EMAIL = "admin@leagueos.com"
CLUB_ADMIN_EMAIL = "clubadmin@leagueos.com"

SUPER_ADMIN_ROLE_NAME = "Super Admin"
CLUB_ADMIN_ROLE_NAME = "Club Admin"

# Default development club to which the Club Admin is bound. Override with
# CLUB_ADMIN_CLUB_NAME env var or the --club-name CLI option.
DEFAULT_CLUB_NAME = "League OS Development"


class Command(BaseCommand):
    help = (
        "Provision the initial Super Admin and Club Admin accounts "
        "(idempotent; dev/demo only)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--club-name",
            default=None,
            help=(
                "Name of the club to associate the Club Admin with. Defaults to "
                "the CLUB_ADMIN_CLUB_NAME environment variable or the development "
                "club '%s'." % DEFAULT_CLUB_NAME
            ),
        )

    # ------------------------------------------------------------------ helpers

    def _resolve_password(self, env_var: str, user_label: str) -> str:
        """Return the configured password, guarding against production misuse.

        The dev fallback is allowed only when Django is running in DEBUG mode.
        In production the operator MUST supply a strong password via env var,
        otherwise we refuse to run rather than silently provisioning with the
        development default.
        """
        password = os.environ.get(env_var)
        if password:
            return password

        if settings.DEBUG:
            self.stdout.write(
                self.style.WARNING(
                    f"{env_var} is not set -- using the LOCAL DEVELOPMENT password "
                    f"for {user_label}. This MUST be changed for any production use."
                )
            )
            return DEV_FALLBACK_PASSWORD

        raise CommandError(
            f"{env_var} is not set. The default development password must not be "
            f"used in a non-development environment ({user_label}). Set a strong "
            "password via the environment variable before running this command."
        )

    @staticmethod
    def _mark_password_change_required(user: User) -> None:
        """Best-effort: flag the account for a forced password change.

        The project does not currently persist a forced-password-change flag, so
        this is a defensive no-op. If/when a field such as
        ``user.password_change_required`` (or ``must_change_password``) is added
        to the ``accounts.User`` model, this method will automatically start
        marking freshly bootstrapped development accounts so they are forced to
        rotate their password on first login.
        """
        for field_name in ("password_change_required", "must_change_password"):
            if hasattr(user, field_name):
                setattr(user, field_name, True)

    def _ensure_role(
        self, name: str, display_name: str, description: str, scope: str
    ) -> Role:
        role, _ = Role.objects.get_or_create(
            name=name,
            defaults={
                "display_name": display_name,
                "description": description,
                "scope": scope,
                "is_system": True,
            },
        )
        return role

    def _sync_role_permissions(self, role: Role, permissions) -> int:
        """Idempotently associate the given permissions with ``role``.

        Only matching associations are added; nothing is removed. Returns the
        number of newly created links.
        """
        assigned = 0
        for permission in permissions:
            _, created = RolePermission.objects.get_or_create(
                role=role,
                permission=permission,
            )
            if created:
                assigned += 1
        return assigned

    def _ensure_user(self, email: str, defaults: dict) -> tuple[User, bool]:
        user, created = User.objects.get_or_create(
            email=email,
            defaults=defaults,
        )
        return user, created

    @staticmethod
    def _resolve_club_name(cli_value: str | None) -> str:
        if cli_value:
            return cli_value
        return os.environ.get("CLUB_ADMIN_CLUB_NAME", DEFAULT_CLUB_NAME)

    def _ensure_club(self, name: str) -> tuple[Club, bool]:
        club, created = Club.objects.get_or_create(
            name=name,
            defaults={
                "slug": slugify(name),
                "is_active": True,
            },
        )
        return club, created


    # ------------------------------------------------------------------- handle

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Bootstrapping administrator accounts...")

        # 1. Database-backed roles (idempotent).
        super_admin_role = self._ensure_role(
            SUPER_ADMIN_ROLE_NAME,
            display_name=SUPER_ADMIN_ROLE_NAME,
            description="Super administrator with full platform access.",
            scope=Role.Scope.PLATFORM,
        )
        club_admin_role = self._ensure_role(
            CLUB_ADMIN_ROLE_NAME,
            display_name=CLUB_ADMIN_ROLE_NAME,
            description="Administrator for one or more club workspaces.",
            scope=Role.Scope.CLUB,
        )

        # 1b. Idempotently link the appropriate database-backed permissions.
        all_active_permissions = Permission.objects.filter(active=True)
        club_permissions = all_active_permissions.filter(
            scope=Permission.Scope.CLUB
        )

        super_admin_links = self._sync_role_permissions(
            super_admin_role, all_active_permissions
        )
        club_admin_links = self._sync_role_permissions(
            club_admin_role, club_permissions
        )
        self.stdout.write(
            f"  - Roles ensured: '{SUPER_ADMIN_ROLE_NAME}' "
            f"(+{super_admin_links} permission links), "
            f"'{CLUB_ADMIN_ROLE_NAME}' (+{club_admin_links} permission links)."
        )
        self.stdout.write(
            self.style.WARNING(
                "  - Roles carry all currently-defined permissions. Run "
                "'python manage.py seed_roles' to (re)build the full permission "
                "catalogue before trusting role-level checks."
            )
        )

        # 2. Super Admin account.
        super_admin, super_admin_created = self._ensure_user(
            SUPER_ADMIN_EMAIL,
            defaults={
                "username": SUPER_ADMIN_EMAIL,
                "first_name": "Super",
                "last_name": "Admin",
                "is_staff": True,
                "is_superuser": True,
                "is_verified": True,
                "account_status": User.AccountStatus.ACTIVE,
            },
        )
        if super_admin_created:
            self._set_password_for(super_admin, "SUPER_ADMIN_INITIAL_PASSWORD")
            self.stdout.write(
                self.style.SUCCESS(f"  - Created Super Admin: {SUPER_ADMIN_EMAIL}")
            )
        else:
            self.stdout.write(
                "  - Super Admin already exists "
                f"(password untouched): {SUPER_ADMIN_EMAIL}"
            )

        RoleService.assign_role(user=super_admin, role=super_admin_role)

        # 3. Club Admin account.
        club_admin, club_admin_created = self._ensure_user(
            CLUB_ADMIN_EMAIL,
            defaults={
                "username": CLUB_ADMIN_EMAIL,
                "first_name": "Club",
                "last_name": "Admin",
                "is_staff": True,
                "is_verified": True,
                "account_status": User.AccountStatus.ACTIVE,
            },
        )
        if club_admin_created:
            self._set_password_for(club_admin, "CLUB_ADMIN_INITIAL_PASSWORD")
            self.stdout.write(
                self.style.SUCCESS(f"  - Created Club Admin: {CLUB_ADMIN_EMAIL}")
            )
        else:
            self.stdout.write(
                "  - Club Admin already exists "
                f"(password untouched): {CLUB_ADMIN_EMAIL}"
            )

        RoleService.assign_role(user=club_admin, role=club_admin_role)

        # 4. Bind the Club Admin to the appropriate club workspace (idempotent).
        club_name = self._resolve_club_name(options.get("club_name"))
        club, _club_created = self._ensure_club(club_name)
        _workspace, workspace_created = ClubWorkspace.objects.get_or_create(
            user=club_admin,
            club=club,
            defaults={
                "role": ClubWorkspace.WorkspaceRole.ADMIN,
                "is_active": True,
                "accepted_at": timezone.now(),
            },
        )
        if workspace_created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"  - Linked Club Admin to workspace of "
                    f"'{club.name}' ({club.slug})."
                )
            )
        else:
            self.stdout.write(
                f"  - Club Admin workspace membership already exists "
                f"for '{club.name}'."
            )

        self.stdout.write(
            self.style.SUCCESS("Administrator bootstrapping complete.")
        )

    def _set_password_for(self, user: User, env_var: str) -> None:
        """Hash and store the user's initial password (dev fallback or env).

        The resolved password is never logged and never returned. Only called
        when the account is first created, so existing passwords are untouched.
        """
        password = self._resolve_password(env_var, user.email)
        user.set_password(password)
        self._mark_password_change_required(user)
        user.save()


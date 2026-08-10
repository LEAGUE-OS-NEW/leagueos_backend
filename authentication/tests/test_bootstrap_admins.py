"""Tests for the ``bootstrap_admins`` management command.

Covers idempotency, role/permission assignment, workspace membership,
password hashing and the production guard against the development password.
"""

import os
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import User
from authentication.models import Permission, Role, RolePermission, UserRole
from clubs.models import ClubWorkspace
from profiles.models import Club

SUPER_ADMIN_EMAIL = "admin@leagueos.com"
CLUB_ADMIN_EMAIL = "clubadmin@leagueos.com"


class BootstrapAdminsCommandTests(TestCase):
    @mock.patch.dict(os.environ, {}, clear=False)
    @override_settings(DEBUG=True)
    def test_creates_admin_users_roles_and_workspace(self):
        call_command("bootstrap_admins", verbosity=0)

        super_admin = User.objects.get(email=SUPER_ADMIN_EMAIL)
        self.assertTrue(super_admin.is_superuser)
        self.assertTrue(super_admin.is_staff)

        club_admin = User.objects.get(email=CLUB_ADMIN_EMAIL)
        self.assertTrue(club_admin.is_staff)

        # Super Admin receives the Super Admin role.
        self.assertTrue(
            UserRole.objects.filter(
                user=super_admin, role__name="Super Admin", is_active=True
            ).exists()
        )
        # Club Admin receives the Club Admin role.
        self.assertTrue(
            UserRole.objects.filter(
                user=club_admin, role__name="Club Admin", is_active=True
            ).exists()
        )

        # Club Admin is bound to a club workspace with the ADMIN role.
        workspace = ClubWorkspace.objects.get(user=club_admin, is_active=True)
        self.assertEqual(workspace.role, ClubWorkspace.WorkspaceRole.ADMIN)
        self.assertIsInstance(workspace.club, Club)

    @mock.patch.dict(os.environ, {}, clear=False)
    @override_settings(DEBUG=True)
    def test_passwords_are_hashed_not_plaintext(self):
        call_command("bootstrap_admins", verbosity=0)

        for email in (SUPER_ADMIN_EMAIL, CLUB_ADMIN_EMAIL):
            with self.subTest(email=email):
                user = User.objects.get(email=email)
                # Stored hash must not equal the raw password and must validate.
                self.assertNotEqual(user.password, "Strong123!")
                self.assertTrue(user.check_password("Strong123!"))

    @mock.patch.dict(
        os.environ,
        {
            "SUPER_ADMIN_INITIAL_PASSWORD": "EnvSuperPass!1",
            "CLUB_ADMIN_INITIAL_PASSWORD": "EnvClubPass!1",
        },
        clear=False,
    )
    @override_settings(DEBUG=True)
    def test_uses_environment_passwords(self):
        call_command("bootstrap_admins", verbosity=0)

        self.assertTrue(User.objects.get(email=SUPER_ADMIN_EMAIL).check_password("EnvSuperPass!1"))
        self.assertTrue(User.objects.get(email=CLUB_ADMIN_EMAIL).check_password("EnvClubPass!1"))

    @mock.patch.dict(os.environ, {}, clear=False)
    @override_settings(DEBUG=True)
    def test_is_idempotent_and_does_not_overwrite_passwords(self):
        call_command("bootstrap_admins", verbosity=0)

        counts_before = {
            "users": User.objects.count(),
            "roles": Role.objects.count(),
            "permissions": Permission.objects.count(),
            "role_permissions": RolePermission.objects.count(),
            "user_roles": UserRole.objects.count(),
            "workspaces": ClubWorkspace.objects.count(),
            "clubs": Club.objects.count(),
        }

        # Change the super admin's password before the second run.
        super_admin = User.objects.get(email=SUPER_ADMIN_EMAIL)
        super_admin.set_password("ChangedPass!2")
        super_admin.save()

        call_command("bootstrap_admins", verbosity=0)

        self.assertEqual(User.objects.count(), counts_before["users"])
        self.assertEqual(Role.objects.count(), counts_before["roles"])
        self.assertEqual(Permission.objects.count(), counts_before["permissions"])
        self.assertEqual(RolePermission.objects.count(), counts_before["role_permissions"])
        self.assertEqual(UserRole.objects.count(), counts_before["user_roles"])
        self.assertEqual(ClubWorkspace.objects.count(), counts_before["workspaces"])
        self.assertEqual(Club.objects.count(), counts_before["clubs"])

        # Existing user's password must not be overwritten.
        self.assertTrue(User.objects.get(email=SUPER_ADMIN_EMAIL).check_password("ChangedPass!2"))

    @override_settings(DEBUG=False)
    def test_production_refuses_development_password(self):
        # Remove any externally-set password vars so the dev fallback would apply.
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CommandError):
                call_command("bootstrap_admins", verbosity=0)

        # No user may have been created by the refused run.
        self.assertFalse(User.objects.filter(email=SUPER_ADMIN_EMAIL).exists())

    @mock.patch.dict(
        os.environ,
        {
            "SUPER_ADMIN_INITIAL_PASSWORD": "ProdSuperPass!9",
            "CLUB_ADMIN_INITIAL_PASSWORD": "ProdClubPass!9",
        },
        clear=False,
    )
    @override_settings(DEBUG=False)
    def test_production_accepts_environment_passwords(self):
        call_command("bootstrap_admins", verbosity=0)

        self.assertTrue(User.objects.get(email=SUPER_ADMIN_EMAIL).check_password("ProdSuperPass!9"))
        self.assertTrue(User.objects.get(email=CLUB_ADMIN_EMAIL).check_password("ProdClubPass!9"))

    @mock.patch.dict(os.environ, {}, clear=False)
    @override_settings(DEBUG=True)
    def test_club_name_option_controls_workspace(self):
        call_command("bootstrap_admins", "--club-name", "Aston Villa", verbosity=0)

        workspace = ClubWorkspace.objects.get(user__email=CLUB_ADMIN_EMAIL, is_active=True)
        self.assertEqual(workspace.club.name, "Aston Villa")
        self.assertEqual(workspace.club.slug, "aston-villa")

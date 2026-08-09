import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

from authentication.models import Role, UserRole
from authentication.services.role_service import RoleService

from .factories import UserFactory


@pytest.fixture
def seeded_roles(db):
    call_command("seed_roles", verbosity=0)


class TestRoleAssignment:
    def test_assign_role(self, db):
        user = UserFactory()
        role = Role.objects.create(name="Test Role", display_name="Test Role")

        user_role = RoleService.assign_role(user, role)

        assert user_role.is_active is True
        assert UserRole.objects.filter(user=user, role=role, is_active=True).exists()

    def test_assign_multiple_roles(self, db):
        user = UserFactory()
        role1 = Role.objects.create(name="Role One", display_name="Role One")
        role2 = Role.objects.create(name="Role Two", display_name="Role Two")

        RoleService.assign_role(user, role1)
        RoleService.assign_role(user, role2)

        roles = RoleService.get_user_roles(user)
        assert len(roles) == 2

    def test_assign_same_role_twice_is_idempotent(self, db):
        user = UserFactory()
        role = Role.objects.create(name="Test Role", display_name="Test Role")

        RoleService.assign_role(user, role)
        RoleService.assign_role(user, role)

        assert UserRole.objects.filter(user=user, role=role).count() == 1


class TestRoleRevocation:
    def test_revoke_role(self, db):
        user = UserFactory()
        role = Role.objects.create(name="Test Role", display_name="Test Role")
        RoleService.assign_role(user, role)

        user_role = RoleService.remove_role(user, role)

        assert user_role is not None
        assert user_role.is_active is False
        assert user_role.revoked_at is not None

    def test_revoke_unassigned_role_returns_none(self, db):
        user = UserFactory()
        role = Role.objects.create(name="Test Role", display_name="Test Role")

        user_role = RoleService.remove_role(user, role)

        assert user_role is None

    def test_revoked_role_not_in_user_roles(self, db):
        user = UserFactory()
        role = Role.objects.create(name="Test Role", display_name="Test Role")
        RoleService.assign_role(user, role)
        RoleService.remove_role(user, role)

        roles = RoleService.get_user_roles(user)
        assert role not in roles


class TestLastSuperAdminProtection:
    def test_cannot_revoke_last_super_admin(self, db, seeded_roles):
        user = UserFactory()
        super_admin_role = Role.objects.get(name="Super Admin")
        RoleService.assign_role(user, super_admin_role)

        with pytest.raises(ValidationError):
            RoleService.remove_role(user, super_admin_role)

        assert UserRole.objects.filter(user=user, role=super_admin_role, is_active=True).exists()

    def test_can_revoke_super_admin_when_another_exists(self, db, seeded_roles):
        user1 = UserFactory()
        user2 = UserFactory()
        super_admin_role = Role.objects.get(name="Super Admin")
        RoleService.assign_role(user1, super_admin_role)
        RoleService.assign_role(user2, super_admin_role)

        user_role = RoleService.remove_role(user1, super_admin_role)

        assert user_role is not None
        assert user_role.is_active is False

    def test_can_revoke_non_super_admin_role(self, db, seeded_roles):
        user = UserFactory()
        finance_role = Role.objects.get(name="Finance Admin")
        RoleService.assign_role(user, finance_role)

        user_role = RoleService.remove_role(user, finance_role)

        assert user_role is not None
        assert user_role.is_active is False


class TestCountActiveSuperAdmins:
    def test_count_zero_when_none(self, db, seeded_roles):
        assert RoleService.count_active_super_admins() == 0

    def test_count_one(self, db, seeded_roles):
        user = UserFactory()
        super_admin_role = Role.objects.get(name="Super Admin")
        RoleService.assign_role(user, super_admin_role)

        assert RoleService.count_active_super_admins() == 1

    def test_count_two(self, db, seeded_roles):
        user1 = UserFactory()
        user2 = UserFactory()
        super_admin_role = Role.objects.get(name="Super Admin")
        RoleService.assign_role(user1, super_admin_role)
        RoleService.assign_role(user2, super_admin_role)

        assert RoleService.count_active_super_admins() == 2

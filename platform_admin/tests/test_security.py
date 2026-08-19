import pytest
from django.core.management import call_command
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import AuditLog
from authentication.models import Role, UserRole
from authentication.services.role_service import RoleService

from .factories import UserFactory, UserSessionFactory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def seeded_roles(db):
    call_command("seed_roles", verbosity=0)


def authenticate(client, user):
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


class TestSessionInvalidation:
    def test_role_assignment_invalidates_sessions(self, db, seeded_roles):
        from authentication.services.session_service import SessionService

        user = UserFactory()
        session = UserSessionFactory(user=user, is_active=True)

        SessionService.invalidate_user_sessions(user)

        session.refresh_from_db()
        assert session.is_active is False

    def test_role_revocation_invalidates_sessions(self, db, seeded_roles):
        from authentication.services.session_service import SessionService

        user = UserFactory()
        session = UserSessionFactory(user=user, is_active=True)
        role = Role.objects.get(name="Finance Admin")
        RoleService.assign_role(user, role)

        SessionService.invalidate_user_sessions(user)

        session.refresh_from_db()
        assert session.is_active is False


class TestPrivilegeEscalationPrevention:
    def test_regular_user_cannot_assign_roles(self, api_client, seeded_roles):
        user = UserFactory()
        target = UserFactory()
        role = Role.objects.get(name="Finance Admin")
        authenticate(api_client, user)

        response = api_client.post(
            f"/api/v1/admin/users/{target.id}/roles/assign/",
            {"role_id": str(role.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not UserRole.objects.filter(user=target, role=role, is_active=True).exists()

    def test_regular_user_cannot_invite_admins(self, api_client, seeded_roles):
        user = UserFactory()
        role = Role.objects.get(name="Finance Admin")
        authenticate(api_client, user)

        response = api_client.post(
            "/api/v1/admin/invitations/",
            {
                "login_email": "hacker@example.com",
                "notify_email": "notify-hacker@example.com",
                "role_ids": [str(role.id)],
                "expires_in_days": 7,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_regular_user_cannot_view_audit(self, api_client, db):
        user = UserFactory()
        authenticate(api_client, user)

        response = api_client.get("/api/v1/admin/audit/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_regular_user_cannot_view_dashboard(self, api_client, db):
        user = UserFactory()
        authenticate(api_client, user)

        response = api_client.get("/api/v1/admin/dashboard/")

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestLastSuperAdminAPIProtection:
    def test_cannot_disable_last_super_admin(self, api_client, seeded_roles):
        super_admin = UserFactory(is_superuser=True)
        target = UserFactory()
        super_admin_role = Role.objects.get(name="Super Admin")
        RoleService.assign_role(target, super_admin_role)
        authenticate(api_client, super_admin)

        response = api_client.patch(
            f"/api/v1/admin/users/{target.id}/",
            {"is_active": False},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        target.refresh_from_db()
        assert target.is_active is True

    def test_cannot_revoke_last_super_admin_role(self, api_client, seeded_roles):
        super_admin = UserFactory(is_superuser=True)
        target = UserFactory()
        super_admin_role = Role.objects.get(name="Super Admin")
        RoleService.assign_role(target, super_admin_role)
        authenticate(api_client, super_admin)

        response = api_client.delete(
            f"/api/v1/admin/users/{target.id}/roles/{super_admin_role.id}/"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert UserRole.objects.filter(user=target, role=super_admin_role, is_active=True).exists()


class TestAuditLogging:
    def test_role_assignment_is_audited(self, api_client, seeded_roles):
        super_admin = UserFactory(is_superuser=True)
        target = UserFactory()
        role = Role.objects.get(name="Finance Admin")
        authenticate(api_client, super_admin)

        api_client.post(
            f"/api/v1/admin/users/{target.id}/roles/assign/",
            {"role_id": str(role.id)},
            format="json",
        )

        assert AuditLog.objects.filter(action="ROLE_ASSIGNED").exists()

    def test_role_revocation_is_audited(self, api_client, seeded_roles):
        super_admin = UserFactory(is_superuser=True)
        target = UserFactory()
        role = Role.objects.get(name="Finance Admin")
        RoleService.assign_role(target, role)
        authenticate(api_client, super_admin)

        api_client.delete(f"/api/v1/admin/users/{target.id}/roles/{role.id}/")

        assert AuditLog.objects.filter(action="ROLE_REVOKED").exists()

    def test_admin_invitation_is_audited(self, api_client, seeded_roles):
        super_admin = UserFactory(is_superuser=True)
        role = Role.objects.get(name="Finance Admin")
        authenticate(api_client, super_admin)

        api_client.post(
            "/api/v1/admin/invitations/",
            {
                "login_email": "audit@example.com",
                "notify_email": "notify-audit@example.com",
                "role_ids": [str(role.id)],
                "expires_in_days": 7,
            },
            format="json",
        )

        assert AuditLog.objects.filter(action="ADMIN_INVITED").exists()

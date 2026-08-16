import pytest
from django.core.management import call_command
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import AuditLog
from authentication.models import Role, UserRole
from authentication.services.role_service import RoleService

from .factories import (
    UserFactory,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    user = UserFactory(is_active=True, is_verified=True)
    return user


@pytest.fixture
def super_admin_user(db):
    user = UserFactory(is_active=True, is_verified=True, is_superuser=True)
    return user


@pytest.fixture
def seeded_roles(db):
    call_command("seed_roles", verbosity=0)


def authenticate(client, user):
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


class TestAdminMe:
    def test_me_returns_roles_and_permissions(self, api_client, admin_user, seeded_roles):
        role = Role.objects.get(name="Super Admin")
        RoleService.assign_role(admin_user, role)
        authenticate(api_client, admin_user)

        response = api_client.get("/api/v1/admin/me/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["email"] == admin_user.email
        assert "Super Admin" in response.data["roles"]
        assert "admin.users.view" in response.data["permissions"]

    def test_me_roles_endpoint(self, api_client, admin_user, seeded_roles):
        role = Role.objects.get(name="Finance Admin")
        RoleService.assign_role(admin_user, role)
        authenticate(api_client, admin_user)

        response = api_client.get("/api/v1/admin/me/roles/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["roles"][0]["name"] == "Finance Admin"

    def test_me_permissions_endpoint(self, api_client, admin_user, seeded_roles):
        role = Role.objects.get(name="Finance Admin")
        RoleService.assign_role(admin_user, role)
        authenticate(api_client, admin_user)

        response = api_client.get("/api/v1/admin/me/permissions/")

        assert response.status_code == status.HTTP_200_OK
        assert "view_finance" in response.data["permissions"]


class TestAdminUserList:
    def test_super_admin_can_list_users(self, api_client, super_admin_user, admin_user):
        authenticate(api_client, super_admin_user)

        response = api_client.get("/api/v1/admin/users/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 2

    def test_user_without_permission_is_forbidden(self, api_client, admin_user):
        authenticate(api_client, admin_user)

        response = api_client.get("/api/v1/admin/users/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_is_rejected(self, api_client):
        response = api_client.get("/api/v1/admin/users/")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestAdminUserDetail:
    def test_super_admin_can_view_user(self, api_client, super_admin_user, admin_user):
        authenticate(api_client, super_admin_user)

        response = api_client.get(f"/api/v1/admin/users/{admin_user.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["email"] == admin_user.email

    def test_user_not_found(self, api_client, super_admin_user):
        authenticate(api_client, super_admin_user)

        response = api_client.get("/api/v1/admin/users/00000000-0000-0000-0000-000000000000/")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestAdminUserRoles:
    def test_assign_role(self, api_client, super_admin_user, admin_user, seeded_roles):
        authenticate(api_client, super_admin_user)
        role = Role.objects.get(name="Finance Admin")

        response = api_client.post(
            f"/api/v1/admin/users/{admin_user.id}/roles/assign/",
            {"role_id": str(role.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert UserRole.objects.filter(user=admin_user, role=role, is_active=True).exists()

    def test_assign_role_requires_permission(self, api_client, admin_user, seeded_roles):
        authenticate(api_client, admin_user)
        role = Role.objects.get(name="Finance Admin")

        response = api_client.post(
            f"/api/v1/admin/users/{admin_user.id}/roles/assign/",
            {"role_id": str(role.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_revoke_role(self, api_client, super_admin_user, admin_user, seeded_roles):
        authenticate(api_client, super_admin_user)
        role = Role.objects.get(name="Finance Admin")
        RoleService.assign_role(admin_user, role)

        response = api_client.delete(f"/api/v1/admin/users/{admin_user.id}/roles/{role.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert not UserRole.objects.filter(user=admin_user, role=role, is_active=True).exists()

    def test_list_user_roles(self, api_client, super_admin_user, admin_user, seeded_roles):
        authenticate(api_client, super_admin_user)
        role = Role.objects.get(name="Finance Admin")
        RoleService.assign_role(admin_user, role)

        response = api_client.get(f"/api/v1/admin/users/{admin_user.id}/roles/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["name"] == "Finance Admin"


class TestAdminRoles:
    def test_list_roles(self, api_client, super_admin_user, seeded_roles):
        authenticate(api_client, super_admin_user)

        response = api_client.get("/api/v1/admin/roles/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 7

    def test_role_detail(self, api_client, super_admin_user, seeded_roles):
        authenticate(api_client, super_admin_user)
        role = Role.objects.get(name="Super Admin")

        response = api_client.get(f"/api/v1/admin/roles/{role.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Super Admin"


class TestAdminPermissions:
    def test_list_permissions(self, api_client, super_admin_user, seeded_roles):
        authenticate(api_client, super_admin_user)

        response = api_client.get("/api/v1/admin/permissions/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 50


class TestAdminInvitations:
    def test_create_invitation(self, api_client, super_admin_user, seeded_roles):
        authenticate(api_client, super_admin_user)
        role = Role.objects.get(name="Finance Admin")

        response = api_client.post(
            "/api/v1/admin/invitations/",
            {
                "email": "newadmin@example.com",
                "role_ids": [str(role.id)],
                "expires_in_days": 7,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["email"] == "newadmin@example.com"
        assert AuditLog.objects.filter(action="ADMIN_INVITED").exists()

    def test_duplicate_invitation_rejected(self, api_client, super_admin_user, seeded_roles):
        authenticate(api_client, super_admin_user)
        role = Role.objects.get(name="Finance Admin")

        api_client.post(
            "/api/v1/admin/invitations/",
            {
                "email": "dup@example.com",
                "role_ids": [str(role.id)],
                "expires_in_days": 7,
            },
            format="json",
        )

        response = api_client.post(
            "/api/v1/admin/invitations/",
            {
                "email": "dup@example.com",
                "role_ids": [str(role.id)],
                "expires_in_days": 7,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invitation_requires_permission(self, api_client, admin_user, seeded_roles):
        authenticate(api_client, admin_user)
        role = Role.objects.get(name="Finance Admin")

        response = api_client.post(
            "/api/v1/admin/invitations/",
            {
                "email": "newadmin@example.com",
                "role_ids": [str(role.id)],
                "expires_in_days": 7,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_revoke_invitation(self, api_client, super_admin_user, seeded_roles):
        authenticate(api_client, super_admin_user)
        role = Role.objects.get(name="Finance Admin")

        create_response = api_client.post(
            "/api/v1/admin/invitations/",
            {
                "email": "revokeme@example.com",
                "role_ids": [str(role.id)],
                "expires_in_days": 7,
            },
            format="json",
        )
        invitation_id = create_response.data["id"]

        response = api_client.post(f"/api/v1/admin/invitations/{invitation_id}/revoke/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "REVOKED"

    def test_accept_invitation_assigns_role_and_logs_in(self, api_client, admin_user, super_admin_user, seeded_roles):
        from authentication.models import AdminInvitation

        authenticate(api_client, super_admin_user)
        role = Role.objects.get(name="Finance Admin")

        api_client.post(
            "/api/v1/admin/invitations/",
            {
                "email": admin_user.email,
                "role_ids": [str(role.id)],
                "expires_in_days": 7,
            },
            format="json",
        )
        invitation = AdminInvitation.objects.get(email=admin_user.email)

        api_client.credentials()
        authenticate(api_client, admin_user)

        response = api_client.post(
            "/api/v1/admin/invitations/accept/",
            {"token": invitation.token},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "ACCEPTED"
        assert UserRole.objects.filter(user=admin_user, role=role, is_active=True).exists()

    def test_accept_invalid_invitation_token(self, api_client, admin_user, seeded_roles):
        authenticate(api_client, admin_user)

        response = api_client.post(
            "/api/v1/admin/invitations/accept/",
            {"token": "not-a-real-token"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestAdminAudit:
    def test_audit_list_requires_permission(self, api_client, admin_user):
        authenticate(api_client, admin_user)

        response = api_client.get("/api/v1/admin/audit/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_super_admin_can_view_audit(self, api_client, super_admin_user):
        authenticate(api_client, super_admin_user)

        response = api_client.get("/api/v1/admin/audit/")

        assert response.status_code == status.HTTP_200_OK


class TestAdminDashboard:
    def test_dashboard_requires_permission(self, api_client, admin_user):
        authenticate(api_client, admin_user)

        response = api_client.get("/api/v1/admin/dashboard/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_super_admin_can_view_dashboard(self, api_client, super_admin_user, seeded_roles):
        authenticate(api_client, super_admin_user)

        response = api_client.get("/api/v1/admin/dashboard/")

        assert response.status_code == status.HTTP_200_OK
        assert "active_administrators" in response.data

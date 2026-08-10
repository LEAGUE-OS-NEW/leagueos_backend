import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from authentication.models import Permission, Role, UserRole, WorkspaceMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def super_admin(user_factory, role_factory, role_permission_factory):
    """A super admin user."""
    user = user_factory(is_staff=True, is_superuser=True)
    super_admin_role = role_factory(name="Super Admin", is_system=True)
    UserRole.objects.create(user=user, role=super_admin_role)
    return user


@pytest.fixture
def club_admin_a(user_factory, role_factory, club_workspace_a):
    """A club admin for workspace A."""
    user = user_factory(is_staff=True)
    club_admin_role = role_factory(name="Club Admin", scope=Role.Scope.CLUB)
    UserRole.objects.create(user=user, role=club_admin_role)
    WorkspaceMembership.objects.create(user=user, workspace=club_workspace_a, role="ADMIN")
    return user


@pytest.fixture
def club_workspace_a(club_workspace_factory):
    return club_workspace_factory(name="Club Workspace A")


@pytest.fixture
def club_workspace_b(club_workspace_factory):
    return club_workspace_factory(name="Club Workspace B")


@pytest.fixture
def platform_admin_role(role_factory):
    return role_factory(name="Platform Admin", scope=Role.Scope.PLATFORM)


@pytest.fixture
def club_content_manager_role(role_factory):
    return role_factory(name="Club Content Manager", scope=Role.Scope.CLUB)


@pytest.fixture
def user_in_workspace_a(user_factory, club_workspace_a):
    """A subordinate user in workspace A."""
    user = user_factory(is_staff=True)
    WorkspaceMembership.objects.create(user=user, workspace=club_workspace_a, role="STAFF")
    return user


@pytest.fixture
def user_in_workspace_b(user_factory, club_workspace_b):
    """A subordinate user in workspace B."""
    user = user_factory(is_staff=True)
    WorkspaceMembership.objects.create(user=user, workspace=club_workspace_b, role="STAFF")
    return user


@pytest.fixture
def user_in_both_workspaces(user_factory, club_workspace_a, club_workspace_b):
    """A subordinate user in both workspaces A and B."""
    user = user_factory(is_staff=True)
    WorkspaceMembership.objects.create(user=user, workspace=club_workspace_a, role="STAFF")
    WorkspaceMembership.objects.create(user=user, workspace=club_workspace_b, role="STAFF")
    return user


# Grant necessary permissions for the test classes
@pytest.fixture(autouse=True)
def grant_permissions(super_admin, club_admin_a, permission_factory):
    platform_perm = permission_factory(code="platform.users.manage")
    club_perm = permission_factory(code="club.users.manage", scope=Permission.Scope.CLUB)
    super_admin.user_permissions.add(platform_perm)
    club_admin_a.user_permissions.add(club_perm)


class TestSubordinateUserCreation:
    """Tests for the subordinate user creation endpoint."""

    def test_super_admin_can_create_platform_admin(
        self, api_client, super_admin, platform_admin_role, permission_factory
    ):
        """
        GIVEN a logged-in Super Admin
        WHEN they send a valid request to create a Platform Admin
        THEN a new user is created with the correct role and a 201 status is returned.
        """
        api_client.force_authenticate(user=super_admin)
        url = reverse("admin:subordinate-user-list")
        data = {
            "email": "new.platform.admin@leagueos.com",
            "first_name": "New",
            "last_name": "PlatformAdmin",
            "role_id": str(platform_admin_role.id),
        }

        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert User.objects.filter(email=data["email"]).exists()
        new_user = User.objects.get(email=data["email"])
        assert new_user.account_status == User.AccountStatus.PENDING_INVITATION
        assert new_user.user_roles.filter(role=platform_admin_role).exists()

    def test_club_admin_can_create_club_user(
        self,
        api_client,
        club_admin_a,
        club_content_manager_role,
        club_workspace_a,
        permission_factory,
    ):
        """
        GIVEN a logged-in Club Admin for Workspace A
        WHEN they send a valid request to create a Club Content Manager in Workspace A
        THEN a new user is created with the correct role and workspace membership.
        """
        api_client.force_authenticate(user=club_admin_a)
        url = reverse("admin:subordinate-user-list")
        data = {
            "email": "new.content.manager@club.com",
            "first_name": "New",
            "last_name": "ContentManager",
            "role_id": str(club_content_manager_role.id),
            "workspace_ids": [str(club_workspace_a.id)],
        }

        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        new_user = User.objects.get(email=data["email"])
        assert new_user.account_status == User.AccountStatus.PENDING_INVITATION
        assert new_user.user_roles.filter(role=club_content_manager_role).exists()
        assert new_user.workspace_memberships.filter(workspace=club_workspace_a).exists()

    def test_club_admin_cannot_create_platform_role(
        self, api_client, club_admin_a, platform_admin_role, permission_factory
    ):
        """
        GIVEN a logged-in Club Admin
        WHEN they attempt to create a user with a platform-scoped role
        THEN the request is forbidden with a 403 status.
        """
        api_client.force_authenticate(user=club_admin_a)
        url = reverse("admin:subordinate-user-list")
        data = {
            "email": "hacker@club.com",
            "first_name": "Hacker",
            "last_name": "Man",
            "role_id": str(platform_admin_role.id),
        }

        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not User.objects.filter(email=data["email"]).exists()

    def test_club_admin_cannot_assign_to_unmanaged_workspace(
        self,
        api_client,
        club_admin_a,
        club_content_manager_role,
        club_workspace_b,
        permission_factory,
    ):
        """
        GIVEN a logged-in Club Admin for Workspace A
        WHEN they attempt to create a user and assign them to Workspace B
        THEN the request is forbidden with a 403 status.
        """
        api_client.force_authenticate(user=club_admin_a)
        url = reverse("admin:subordinate-user-list")
        data = {
            "email": "cross.workspace@club.com",
            "first_name": "Cross",
            "last_name": "Workspace",
            "role_id": str(club_content_manager_role.id),
            "workspace_ids": [str(club_workspace_b.id)],
        }

        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestSubordinateUserListingAndRetrieval:
    """Tests for listing and retrieving subordinate users with correct scoping."""

    def test_super_admin_can_list_all_subordinate_users(
        self, api_client, super_admin, user_in_workspace_a, user_in_workspace_b
    ):
        """
        GIVEN a logged-in Super Admin
        WHEN they list subordinate users
        THEN they see all subordinate users regardless of workspace.
        """
        api_client.force_authenticate(user=super_admin)
        url = reverse("admin:subordinate-user-list")

        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        user_ids = {user["id"] for user in response.data["data"]["users"]}
        assert str(user_in_workspace_a.id) in user_ids
        assert str(user_in_workspace_b.id) in user_ids

    def test_club_admin_can_only_list_users_in_their_workspace(
        self,
        api_client,
        club_admin_a,
        user_in_workspace_a,
        user_in_workspace_b,
        user_in_both_workspaces,
    ):
        """
        GIVEN a logged-in Club Admin for Workspace A
        WHEN they list subordinate users
        THEN they only see users who are members of Workspace A.
        """
        api_client.force_authenticate(user=club_admin_a)
        url = reverse("admin:subordinate-user-list")

        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        user_ids = {user["id"] for user in response.data["data"]["users"]}
        assert str(user_in_workspace_a.id) in user_ids
        assert str(user_in_both_workspaces.id) in user_ids
        assert str(user_in_workspace_b.id) not in user_ids

    def test_club_admin_can_retrieve_user_in_their_workspace(
        self, api_client, club_admin_a, user_in_workspace_a
    ):
        """
        GIVEN a logged-in Club Admin for Workspace A
        WHEN they retrieve a user who is a member of Workspace A
        THEN the request is successful.
        """
        api_client.force_authenticate(user=club_admin_a)
        url = reverse("admin:subordinate-user-detail", kwargs={"pk": user_in_workspace_a.id})

        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["data"]["user"]["id"] == str(user_in_workspace_a.id)

    def test_club_admin_cannot_retrieve_user_outside_their_workspace(
        self, api_client, club_admin_a, user_in_workspace_b
    ):
        """
        GIVEN a logged-in Club Admin for Workspace A
        WHEN they attempt to retrieve a user who is only in Workspace B
        THEN the request fails with a 404 Not Found.
        """
        api_client.force_authenticate(user=club_admin_a)
        url = reverse("admin:subordinate-user-detail", kwargs={"pk": user_in_workspace_b.id})

        response = api_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_unauthorized_user_cannot_create_user(self, api_client, user_factory):
        """
        GIVEN a logged-in user without user management permissions
        WHEN they attempt to create a subordinate user
        THEN the request is forbidden with a 403 status.
        """
        regular_user = user_factory(is_staff=True)
        api_client.force_authenticate(user=regular_user)
        url = reverse("admin:subordinate-user-list")
        data = {"email": "test@test.com"}

        response = api_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN

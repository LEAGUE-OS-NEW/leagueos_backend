from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from authentication.tests.factories import (
    PermissionFactory,
    RoleFactory,
    RolePermissionFactory,
    UserFactory,
    UserRoleFactory,
    UserSessionFactory,
)


class AuthenticationTests(APITestCase):
    def test_login_success(self):
        user = UserFactory(password="StrongPass123!")
        url = reverse("authentication:login")
        data = {"email": user.email, "password": "StrongPass123!"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data["data"])
        self.assertIn("refresh", response.data["data"])

    def test_login_wrong_password(self):
        user = UserFactory(password="StrongPass123!")
        url = reverse("authentication:login")
        data = {"email": user.email, "password": "WrongPass123!"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_unknown_email(self):
        url = reverse("authentication:login")
        data = {"email": "unknown@example.com", "password": "StrongPass123!"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_inactive_account(self):
        user = UserFactory(password="StrongPass123!", is_active=False)
        url = reverse("authentication:login")
        data = {"email": user.email, "password": "StrongPass123!"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_unverified_account(self):
        user = UserFactory(password="StrongPass123!", is_verified=False)
        url = reverse("authentication:login")
        data = {"email": user.email, "password": "StrongPass123!"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_locked_account(self):
        user = UserFactory(
            password="StrongPass123!", failed_attempts=5, locked_until="2099-01-01T00:00:00Z"
        )
        url = reverse("authentication:login")
        data = {"email": user.email, "password": "StrongPass123!"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_login_throttling(self):
        user = UserFactory(password="StrongPass123!")
        url = reverse("authentication:login")
        for _ in range(5):
            self.client.post(url, {"email": user.email, "password": "WrongPass123!"})
        response = self.client.post(url, {"email": user.email, "password": "StrongPass123!"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class LogoutTests(APITestCase):
    def test_logout_requires_authentication(self):
        response = self.client.post(
            reverse("authentication:logout"),
            {"refresh": "dummy-refresh-token"},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
            response.data,
        )

    def test_logout_all_requires_authentication(self):
        response = self.client.post(
            reverse("authentication:logout-all"),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
            response.data,
        )


class ProfileTests(APITestCase):
    def test_profile(self):
        user = UserFactory()
        self.client.force_authenticate(user)
        url = reverse("authentication:profile")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["user"]["email"], user.email)


class SessionTests(APITestCase):
    def test_sessions(self):
        user = UserFactory()
        UserSessionFactory.create_batch(2, user=user)
        self.client.force_authenticate(user)
        url = reverse("authentication:sessions")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]["sessions"]), 2)


class RBACTests(APITestCase):
    def test_role_assignment(self):
        user = UserFactory()
        role = RoleFactory()
        from authentication.services.role_service import RoleService

        user_role = RoleService.assign_role(user, role, assigned_by=user)
        self.assertEqual(user_role.user, user)
        self.assertEqual(user_role.role, role)

    def test_permission_lookup(self):
        from authentication.services.permission_service import PermissionService

        role = RoleFactory()
        permission = PermissionFactory()
        RolePermissionFactory(role=role, permission=permission)
        user = UserFactory()
        UserRoleFactory(user=user, role=role)

        self.assertTrue(PermissionService.has_permission(user, permission.name))
        self.assertFalse(PermissionService.has_permission(user, "nonexistent"))

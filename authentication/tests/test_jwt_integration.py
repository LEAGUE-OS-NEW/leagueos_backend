from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from authentication.tests.factories import UserFactory


class JWTAuthenticationIntegrationTests(APITestCase):
    password = "StrongPass123!"

    def setUp(self):
        self.user = UserFactory(
            password=self.password,
            is_active=True,
            is_verified=True,
        )

    def login_and_get_access_token(self):
        response = self.client.post(
            reverse("authentication:login"),
            {
                "email": self.user.email,
                "password": self.password,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        return response.data["data"]["access"]

    def test_login_access_token_authenticates_profile_endpoint(self):
        access_token = self.login_and_get_access_token()

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )

        response = self.client.get(
            reverse("authentication:profile"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["data"]["user"]["email"],
            self.user.email,
        )

    def test_login_access_token_authenticates_me_endpoint(self):
        access_token = self.login_and_get_access_token()

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )

        response = self.client.get(
            reverse("authentication:me"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["data"]["user"]["email"],
            self.user.email,
        )

    def test_login_access_token_authenticates_sessions_endpoint(self):
        access_token = self.login_and_get_access_token()

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )

        response = self.client.get(
            reverse("authentication:sessions"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertIn("sessions", response.data["data"])

    def test_invalid_bearer_token_returns_401(self):
        self.client.credentials(
            HTTP_AUTHORIZATION="Bearer invalid-access-token",
        )

        response = self.client.get(
            reverse("authentication:profile"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
            response.data,
        )

    def test_missing_access_token_returns_401(self):
        response = self.client.get(
            reverse("authentication:profile"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
            response.data,
        )

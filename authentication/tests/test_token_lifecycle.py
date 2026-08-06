from concurrent.futures import ThreadPoolExecutor

from django.db import connection
from django.test import skipUnlessDBFeature
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase
from rest_framework_simplejwt.tokens import RefreshToken

from authentication.models import UserSession
from authentication.tests.factories import UserFactory


class TokenLifecycleTests(APITestCase):
    password = "StrongPass123!"

    def setUp(self):
        self.user = UserFactory(
            password=self.password,
            is_active=True,
            is_verified=True,
        )

    def login(self, user=None):
        user = user or self.user

        response = self.client.post(
            reverse("authentication:login"),
            {
                "email": user.email,
                "password": self.password,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        return response.data["data"]

    def authenticate_with_access_token(self, access_token):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )

    def clear_authentication(self):
        self.client.credentials()

    def test_refresh_rotates_token_and_revokes_previous_refresh(self):
        tokens = self.login()

        response = self.client.post(
            reverse("authentication:token-refresh"),
            {"refresh": tokens["refresh"]},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertIn("access", response.data["data"])
        self.assertIn("refresh", response.data["data"])
        self.assertNotEqual(
            response.data["data"]["refresh"],
            tokens["refresh"],
        )

        reused_response = self.client.post(
            reverse("authentication:token-refresh"),
            {"refresh": tokens["refresh"]},
            format="json",
        )

        self.assertEqual(
            reused_response.status_code,
            status.HTTP_401_UNAUTHORIZED,
            reused_response.data,
        )

    def test_refresh_updates_session_jti_and_last_activity(self):
        tokens = self.login()
        session = UserSession.objects.get(user=self.user)
        old_activity = session.last_activity
        response = self.client.post(
            reverse("authentication:token-refresh"), {"refresh": tokens["refresh"]}, format="json"
        )
        session.refresh_from_db()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            session.refresh_token_jti,
            str(RefreshToken(response.data["data"]["refresh"])["jti"]),
        )
        self.assertGreater(session.last_activity, old_activity)

    def test_predeployment_token_without_session_requires_reauthentication(self):
        refresh = str(RefreshToken.for_user(self.user))
        response = self.client.post(
            reverse("authentication:token-refresh"), {"refresh": refresh}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_blacklists_refresh_token_and_terminates_session(self):
        tokens = self.login()

        self.authenticate_with_access_token(tokens["access"])

        response = self.client.post(
            reverse("authentication:logout"),
            {"refresh": tokens["refresh"]},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertFalse(
            UserSession.objects.filter(
                user=self.user,
                is_active=True,
            ).exists()
        )

        self.clear_authentication()

        refresh_response = self.client.post(
            reverse("authentication:token-refresh"),
            {"refresh": tokens["refresh"]},
            format="json",
        )

        self.assertEqual(
            refresh_response.status_code,
            status.HTTP_401_UNAUTHORIZED,
            refresh_response.data,
        )

    def test_logout_rejects_another_users_refresh_token(self):
        first_user_tokens = self.login()

        second_user = UserFactory(
            password=self.password,
            is_active=True,
            is_verified=True,
        )
        second_user_tokens = self.login(second_user)

        self.authenticate_with_access_token(
            first_user_tokens["access"],
        )

        response = self.client.post(
            reverse("authentication:logout"),
            {"refresh": second_user_tokens["refresh"]},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            response.data,
        )

        self.clear_authentication()

        second_refresh_response = self.client.post(
            reverse("authentication:token-refresh"),
            {"refresh": second_user_tokens["refresh"]},
            format="json",
        )

        self.assertEqual(
            second_refresh_response.status_code,
            status.HTTP_200_OK,
            second_refresh_response.data,
        )

    def test_logout_all_revokes_every_refresh_token(self):
        first_tokens = self.login()
        second_tokens = self.login()

        self.assertEqual(
            UserSession.objects.filter(
                user=self.user,
                is_active=True,
            ).count(),
            2,
        )

        self.authenticate_with_access_token(
            first_tokens["access"],
        )

        response = self.client.post(
            reverse("authentication:logout-all"),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertFalse(
            UserSession.objects.filter(
                user=self.user,
                is_active=True,
            ).exists()
        )

        self.clear_authentication()

        for refresh_token in [
            first_tokens["refresh"],
            second_tokens["refresh"],
        ]:
            with self.subTest(refresh_token=refresh_token):
                refresh_response = self.client.post(
                    reverse("authentication:token-refresh"),
                    {"refresh": refresh_token},
                    format="json",
                )

                self.assertEqual(
                    refresh_response.status_code,
                    status.HTTP_401_UNAUTHORIZED,
                    refresh_response.data,
                )


class ConcurrentRefreshTests(APITransactionTestCase):
    reset_sequences = True

    @skipUnlessDBFeature("has_select_for_update")
    def test_concurrent_refresh_has_exactly_one_winner(self):
        user = UserFactory(password="StrongPass123!", is_active=True, is_verified=True)
        login = APIClient().post(
            reverse("authentication:login"),
            {"identifier": user.email, "password": "StrongPass123!"},
            format="json",
        )
        refresh = login.data["data"]["refresh"]

        def rotate():
            return (
                APIClient()
                .post(reverse("authentication:token-refresh"), {"refresh": refresh}, format="json")
                .status_code
            )

        self.assertEqual(connection.vendor, "postgresql")
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = sorted(pool.map(lambda _index: rotate(), range(2)))
        self.assertEqual(statuses, [status.HTTP_200_OK, status.HTTP_401_UNAUTHORIZED])

from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User


class RegistrationUsernameTests(APITestCase):
    password = "StrongPass123!"

    def registration_payload(self, email):
        return {
            "first_name": "Keith",
            "last_name": "Seruyange",
            "email": email,
            "password": self.password,
            "confirm_password": self.password,
        }

    @patch("accounts.services.email_service." "EmailService.send_verification_email")
    def test_users_with_same_email_prefix_receive_unique_usernames(
        self,
        mock_send_verification_email,
    ):
        first_response = self.client.post(
            reverse("accounts:register"),
            self.registration_payload(
                "keith@example.com",
            ),
            format="json",
        )

        second_response = self.client.post(
            reverse("accounts:register"),
            self.registration_payload(
                "keith@another-domain.com",
            ),
            format="json",
        )

        self.assertEqual(
            first_response.status_code,
            status.HTTP_201_CREATED,
            first_response.data,
        )
        self.assertEqual(
            second_response.status_code,
            status.HTTP_201_CREATED,
            second_response.data,
        )

        first_user = User.objects.get(
            email="keith@example.com",
        )
        second_user = User.objects.get(
            email="keith@another-domain.com",
        )

        self.assertEqual(
            first_user.username,
            "keith",
        )
        self.assertEqual(
            second_user.username,
            "keith_2",
        )
        self.assertNotEqual(
            first_user.username,
            second_user.username,
        )

        self.assertEqual(
            mock_send_verification_email.call_count,
            2,
        )

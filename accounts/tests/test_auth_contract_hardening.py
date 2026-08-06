from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import AuditLog, OTPVerification, User
from accounts.services.otp_service import OTPService
from authentication.models import Role, UserRole, UserSession


class RegistrationContractTests(APITestCase):
    payload = {
        "first_name": "Test",
        "last_name": "Fan",
        "email": "test@example.com",
        "password": "StrongPass123!",
        "confirm_password": "StrongPass123!",
    }

    @patch("accounts.services.email_service.EmailService.send_verification_email")
    def test_supplied_username_and_e164_phone_are_preserved_but_channel_is_email(self, _send):
        response = self.client.post(
            reverse("accounts:register"),
            {**self.payload, "username": "Chosen_Name", "phone_number": "+256772123456"},
        )
        user = User.objects.get(email=self.payload["email"])
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(user.username, "Chosen_Name")
        self.assertEqual(user.phone_number, "+256772123456")
        self.assertEqual(user.verification_channel, "EMAIL")
        self.assertNotEqual(response.data["data"]["destination"], user.email)

    @patch("accounts.services.email_service.EmailService.send_verification_email")
    def test_blank_usernames_are_generated_uniquely(self, _send):
        first = {**self.payload, "username": ""}
        second = {**self.payload, "email": "test2@example.com", "username": ""}
        self.client.post(reverse("accounts:register"), first)
        self.client.post(reverse("accounts:register"), second)
        usernames = list(User.objects.order_by("email").values_list("username", flat=True))
        self.assertEqual(len(set(usernames)), 2)

    @patch("accounts.services.email_service.EmailService.send_verification_email")
    def test_retry_does_not_overwrite_unverified_user(self, send):
        self.client.post(reverse("accounts:register"), {**self.payload, "username": "original"})
        response = self.client.post(
            reverse("accounts:register"),
            {
                **self.payload,
                "username": "replacement",
                "password": "OtherStrong123!",
                "confirm_password": "OtherStrong123!",
            },
        )
        user = User.objects.get(email=self.payload["email"])
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(user.username, "original")
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertEqual(send.call_count, 1)

    @patch(
        "accounts.services.email_service.EmailService.send_verification_email",
        side_effect=RuntimeError("provider unavailable"),
    )
    def test_delivery_failure_is_retryable_and_recoverable(self, _send):
        response = self.client.post(reverse("accounts:register"), self.payload)
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertFalse(User.objects.get(email=self.payload["email"]).is_active)
        otp = OTPVerification.objects.get(user__email=self.payload["email"])
        self.assertTrue(otp.is_used)
        self.assertFalse(
            AuditLog.objects.filter(user=otp.user, action="VERIFICATION_EMAIL_SENT").exists()
        )

    @patch("accounts.services.email_service.EmailService.send_verification_email")
    def test_registration_sends_exactly_one_email_and_returns_delivery_contract(self, send):
        response = self.client.post(reverse("accounts:register"), self.payload)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(
            set(response.data["data"]),
            {
                "verification_required",
                "verification_channel",
                "destination",
                "expires_in",
                "resend_available_in",
            },
        )

    @patch.object(OTPService, "generate_secure_otp", return_value="123456")
    @patch("accounts.services.email_service.EmailService.send_verification_email")
    def test_verification_has_one_nested_user_context_and_creates_session(self, _send, _code):
        self.client.post(reverse("accounts:register"), self.payload)
        response = self.client.post(
            reverse("accounts:verify-otp"), {"email": self.payload["email"], "otp": "123456"}
        )
        data = response.data["data"]
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(data), {"access", "refresh", "user"})
        self.assertEqual(data["user"]["email"], self.payload["email"])
        self.assertTrue(UserSession.objects.filter(user__email=self.payload["email"]).exists())


class PurgeTestUsersCommandTests(APITestCase):
    def test_dry_run_and_confirm(self):
        user = User.objects.create_user(username="purge-me", email="purge@example.com")
        output = StringIO()
        call_command("purge_test_users", "--email", user.email, stdout=output)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        call_command("purge_test_users", "--email", user.email, "--confirm", stdout=output)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())

    def test_refuses_staff(self):
        user = User.objects.create_user(username="staff", email="staff@example.com", is_staff=True)
        with self.assertRaises(CommandError):
            call_command("purge_test_users", "--email", user.email, "--confirm")

    def test_refuses_superuser_and_operational_owner(self):
        superuser = User.objects.create_user(
            username="root", email="root@example.com", is_superuser=True
        )
        owner = User.objects.create_user(username="owner", email="owner@example.com")
        role = Role.objects.create(name="Platform Owner", display_name="Platform Owner")
        UserRole.objects.create(user=owner, role=role)
        for user in (superuser, owner):
            with self.subTest(user=user.email), self.assertRaises(CommandError):
                call_command("purge_test_users", "--email", user.email, "--confirm")
            self.assertTrue(User.objects.filter(pk=user.pk).exists())

    def test_blank_filter_is_never_delete_all(self):
        user = User.objects.create_user(username="safe", email="safe@example.com")
        with self.assertRaises(CommandError):
            call_command("purge_test_users", "--email", " ", "--confirm")
        self.assertTrue(User.objects.filter(pk=user.pk).exists())


class IdentifierLoginTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="CaseSensitiveName",
            email="login-contract@example.com",
            password="StrongPass123!",
            is_active=True,
            is_verified=True,
        )

    def test_login_by_username_is_case_insensitive(self):
        response = self.client.post(
            reverse("authentication:login"),
            {"identifier": "casesensitivename", "password": "StrongPass123!"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["data"]["user"]["username"], "CaseSensitiveName")

    def test_duplicate_username_is_case_insensitive(self):
        payload = {
            **RegistrationContractTests.payload,
            "email": "another@example.com",
            "username": "casesensitivename",
        }
        response = self.client.post(reverse("accounts:register"), payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("username", response.data)

    def test_login_and_me_share_exact_nested_user_shape(self):
        login = self.client.post(
            reverse("authentication:login"),
            {"identifier": self.user.email, "password": "StrongPass123!"},
        )
        self.assertEqual(set(login.data["data"]), {"access", "refresh", "user"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['data']['access']}")
        me = self.client.get(reverse("authentication:me"))
        self.assertEqual(set(me.data["data"]), {"user"})
        self.assertEqual(set(me.data["data"]["user"]), set(login.data["data"]["user"]))

    def test_phone_is_not_a_login_identifier(self):
        self.user.phone_number = "+256772123456"
        self.user.save(update_fields=["phone_number"])
        response = self.client.post(
            reverse("authentication:login"),
            {"identifier": self.user.phone_number, "password": "StrongPass123!"},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

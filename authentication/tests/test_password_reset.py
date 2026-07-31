from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import AuditLog, User
from accounts.services.otp_service import OTPService


class PasswordResetRequestTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="resetfan",
            email="reset@example.com",
            password="OldPass123!",
            first_name="Reset",
            last_name="Fan",
            is_verified=True,
            is_active=True,
        )

    def test_request_with_existing_email(self):
        with patch(
            "accounts.services.email_service.EmailService.send_password_reset_email"
        ) as mock_send:
            url = reverse("authentication:password-reset-request")
            response = self.client.post(url, {"email": "reset@example.com"})
            mock_send.assert_called_once()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("If an account exists", response.data["message"])

    def test_request_with_unknown_email(self):
        with patch(
            "accounts.services.email_service.EmailService.send_password_reset_email"
        ) as mock_send:
            url = reverse("authentication:password-reset-request")
            response = self.client.post(url, {"email": "unknown@example.com"})
            mock_send.assert_not_called()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("If an account exists", response.data["message"])

    def test_request_with_inactive_account(self):
        self.user.is_active = False
        self.user.save()

        with patch(
            "accounts.services.email_service.EmailService.send_password_reset_email"
        ) as mock_send:
            url = reverse("authentication:password-reset-request")
            response = self.client.post(url, {"email": "reset@example.com"})
            mock_send.assert_not_called()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("If an account exists", response.data["message"])

    def test_request_normalizes_email(self):
        with patch(
            "accounts.services.email_service.EmailService.send_password_reset_email"
        ) as mock_send:
            url = reverse("authentication:password-reset-request")
            response = self.client.post(url, {"email": "  RESET@EXAMPLE.COM  "})
            mock_send.assert_called_once()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_audit_log_created_on_request(self):
        with patch("accounts.services.email_service.EmailService.send_password_reset_email"):
            url = reverse("authentication:password-reset-request")
            self.client.post(url, {"email": "reset@example.com"})

        self.assertTrue(
            AuditLog.objects.filter(user=self.user, action="PASSWORD_RESET_REQUESTED").exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(user=self.user, action="PASSWORD_RESET_EMAIL_SENT").exists()
        )


class PasswordResetVerifyTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="verifyreset",
            email="verifyreset@example.com",
            password="OldPass123!",
            first_name="Verify",
            last_name="Reset",
            is_verified=True,
            is_active=True,
        )
        self.otp_obj, self.otp_code = OTPService.create_otp_record(
            self.user, purpose="PASSWORD_RESET", channel="EMAIL"
        )

    def test_verify_valid_otp(self):
        url = reverse("authentication:password-reset-verify")
        response = self.client.post(url, {"email": "verifyreset@example.com", "otp": self.otp_code})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["message"], "OTP verified successfully.")

    def test_verify_invalid_otp(self):
        url = reverse("authentication:password-reset-verify")
        response = self.client.post(url, {"email": "verifyreset@example.com", "otp": "000000"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])

    def test_verify_expired_otp(self):
        self.otp_obj.expires_at = self.otp_obj.created_at
        self.otp_obj.save(update_fields=["expires_at"])

        url = reverse("authentication:password-reset-verify")
        response = self.client.post(url, {"email": "verifyreset@example.com", "otp": self.otp_code})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_used_otp(self):
        self.otp_obj.mark_used()

        url = reverse("authentication:password-reset-verify")
        response = self.client.post(url, {"email": "verifyreset@example.com", "otp": self.otp_code})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_max_attempts(self):
        for _ in range(5):
            self.client.post(
                reverse("authentication:password-reset-verify"),
                {"email": "verifyreset@example.com", "otp": "000000"},
            )

        url = reverse("authentication:password-reset-verify")
        response = self.client.post(url, {"email": "verifyreset@example.com", "otp": self.otp_code})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_unknown_email(self):
        url = reverse("authentication:password-reset-verify")
        response = self.client.post(url, {"email": "unknown@example.com", "otp": "123456"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_audit_log_created(self):
        url = reverse("authentication:password-reset-verify")
        self.client.post(url, {"email": "verifyreset@example.com", "otp": self.otp_code})

        self.assertTrue(
            AuditLog.objects.filter(user=self.user, action="PASSWORD_RESET_VERIFIED").exists()
        )


class PasswordResetConfirmTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="confirmreset",
            email="confirmreset@example.com",
            password="OldPass123!",
            first_name="Confirm",
            last_name="Reset",
            is_verified=True,
            is_active=True,
        )
        self.otp_obj, self.otp_code = OTPService.create_otp_record(
            self.user, purpose="PASSWORD_RESET", channel="EMAIL"
        )

    def test_successful_password_reset(self):
        url = reverse("authentication:password-reset-confirm")
        response = self.client.post(
            url,
            {
                "email": "confirmreset@example.com",
                "otp": self.otp_code,
                "password": "NewStrongPass123!",
                "confirm_password": "NewStrongPass123!",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["message"], "Password reset successfully. Please log in again."
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewStrongPass123!"))

        # OTP should be marked as used
        self.otp_obj.refresh_from_db()
        self.assertTrue(self.otp_obj.is_used)

    def test_password_mismatch(self):
        url = reverse("authentication:password-reset-confirm")
        response = self.client.post(
            url,
            {
                "email": "confirmreset@example.com",
                "otp": self.otp_code,
                "password": "NewStrongPass123!",
                "confirm_password": "DifferentPass123!",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_weak_password_rejected(self):
        url = reverse("authentication:password-reset-confirm")
        response = self.client.post(
            url,
            {
                "email": "confirmreset@example.com",
                "otp": self.otp_code,
                "password": "weak",
                "confirm_password": "weak",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reuse_of_otp_after_successful_reset(self):
        url = reverse("authentication:password-reset-confirm")
        self.client.post(
            url,
            {
                "email": "confirmreset@example.com",
                "otp": self.otp_code,
                "password": "NewStrongPass123!",
                "confirm_password": "NewStrongPass123!",
            },
        )

        # Try to use the same OTP again
        response = self.client.post(
            url,
            {
                "email": "confirmreset@example.com",
                "otp": self.otp_code,
                "password": "AnotherNewPass123!",
                "confirm_password": "AnotherNewPass123!",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_updated_in_database(self):
        url = reverse("authentication:password-reset-confirm")
        self.client.post(
            url,
            {
                "email": "confirmreset@example.com",
                "otp": self.otp_code,
                "password": "NewStrongPass123!",
                "confirm_password": "NewStrongPass123!",
            },
        )

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewStrongPass123!"))

    def test_audit_log_created_on_success(self):
        url = reverse("authentication:password-reset-confirm")
        self.client.post(
            url,
            {
                "email": "confirmreset@example.com",
                "otp": self.otp_code,
                "password": "NewStrongPass123!",
                "confirm_password": "NewStrongPass123!",
            },
        )

        self.assertTrue(
            AuditLog.objects.filter(user=self.user, action="PASSWORD_RESET_SUCCESS").exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(user=self.user, action="ALL_SESSIONS_TERMINATED").exists()
        )

    def test_audit_log_on_failure(self):
        url = reverse("authentication:password-reset-confirm")
        self.client.post(
            url,
            {
                "email": "confirmreset@example.com",
                "otp": "000000",
                "password": "NewStrongPass123!",
                "confirm_password": "NewStrongPass123!",
            },
        )

        self.assertTrue(
            AuditLog.objects.filter(user=self.user, action="PASSWORD_RESET_FAILED").exists()
        )

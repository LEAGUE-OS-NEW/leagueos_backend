from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import AuditLog, OTPVerification, User
from authentication.models import UserRole, UserSession
from onboarding.models import UserOnboarding
from profiles.models import Profile


class RegistrationTests(APITestCase):
    def test_register_with_email(self):
        url = reverse("accounts:register")
        data = {
            "first_name": "Test",
            "last_name": "Fan",
            "email": "testfan@example.com",
            "password": "StrongPass123!",
            "confirm_password": "StrongPass123!",
        }
        with patch(
            "accounts.services.email_service.EmailService.send_verification_email"
        ) as mock_send:
            response = self.client.post(url, data)
            mock_send.assert_called_once()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(email=data["email"]).exists())
        self.assertFalse(User.objects.get(email=data["email"]).is_verified)
        self.assertEqual(response.data["data"]["verification_channel"], "EMAIL")
        self.assertEqual(response.data["success"], True)
        self.assertEqual(
            response.data["message"],
            "Registration successful. Please check your email to verify your account.",
        )

    def test_duplicate_email_rejected(self):
        User.objects.create_user(
            username="existing",
            email="existing@example.com",
            password="Pass123!",
            first_name="Existing",
            last_name="User",
        )
        url = reverse("accounts:register")
        data = {
            "first_name": "New",
            "last_name": "Fan",
            "email": "existing@example.com",
            "password": "StrongPass123!",
            "confirm_password": "StrongPass123!",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_password_mismatch_rejected(self):
        url = reverse("accounts:register")
        data = {
            "first_name": "Mismatch",
            "last_name": "Fan",
            "email": "mismatch@example.com",
            "password": "StrongPass123!",
            "confirm_password": "DifferentPass1!",
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_email_normalized_to_lowercase(self):
        url = reverse("accounts:register")
        data = {
            "first_name": "Test",
            "last_name": "Fan",
            "email": "Test.Fan@EXAMPLE.COM",
            "password": "StrongPass123!",
            "confirm_password": "StrongPass123!",
        }
        with patch("accounts.services.email_service.EmailService.send_verification_email"):
            response = self.client.post(url, data)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertTrue(User.objects.filter(email="test.fan@example.com").exists())

    def test_audit_log_created_on_registration(self):
        url = reverse("accounts:register")
        data = {
            "first_name": "Audit",
            "last_name": "User",
            "email": "audit@example.com",
            "password": "StrongPass123!",
            "confirm_password": "StrongPass123!",
        }
        with patch("accounts.services.email_service.EmailService.send_verification_email"):
            self.client.post(url, data)

        user = User.objects.get(email=data["email"])
        self.assertTrue(AuditLog.objects.filter(user=user, action="USER_REGISTERED").exists())
        self.assertTrue(
            AuditLog.objects.filter(user=user, action="VERIFICATION_EMAIL_SENT").exists()
        )


class OTPVerificationTests(APITestCase):
    def setUp(self):
        from accounts.services.otp_service import OTPService

        self.user = User.objects.create_user(
            username="verifyfan",
            email="verify@example.com",
            password="StrongPass123!",
            first_name="Verify",
            last_name="Fan",
        )
        self.otp_obj, self.otp_code = OTPService.create_otp_record(
            self.user, purpose="REGISTER", channel="EMAIL"
        )

    def test_successful_verification(self):
        url = reverse("accounts:verify-otp")
        response = self.client.post(url, {"email": "verify@example.com", "otp": self.otp_code})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_verified)
        self.assertIn("access", response.data["data"])

    def test_invalid_code_rejected(self):
        url = reverse("accounts:verify-otp")
        response = self.client.post(url, {"email": "verify@example.com", "otp": "000000"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_too_many_failed_attempts_blocked(self):
        from accounts.models import VerificationAttempt

        VerificationAttempt.objects.create(user=self.user, ip_address="127.0.0.1", attempts=5)
        url = reverse("accounts:verify-otp")
        response = self.client.post(url, {"email": "verify@example.com", "otp": self.otp_code})
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_attempt_lock_expires_after_configured_window(self):
        from accounts.models import VerificationAttempt

        attempt = VerificationAttempt.objects.create(
            user=self.user, ip_address="127.0.0.1", attempts=5
        )
        VerificationAttempt.objects.filter(pk=attempt.pk).update(
            last_attempt_at=timezone.now() - timedelta(hours=1)
        )
        response = self.client.post(
            reverse("accounts:verify-otp"),
            {"email": self.user.email, "otp": self.otp_code},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch(
        "authentication.services.session_service.SessionService.create_session",
        side_effect=RuntimeError("database failure"),
    )
    def test_successful_verification_is_atomic(self, _session):
        with self.assertRaises(RuntimeError):
            self.client.post(
                reverse("accounts:verify-otp"),
                {"email": self.user.email, "otp": self.otp_code},
            )
        self.user.refresh_from_db()
        self.otp_obj.refresh_from_db()
        self.assertFalse(self.user.is_verified)
        self.assertFalse(self.otp_obj.is_used)
        self.assertFalse(Profile.objects.filter(user=self.user).exists())
        self.assertFalse(UserOnboarding.objects.filter(user=self.user).exists())
        self.assertFalse(UserRole.objects.filter(user=self.user).exists())

    def test_initialization_is_idempotent(self):
        response = self.client.post(
            reverse("accounts:verify-otp"),
            {"email": self.user.email, "otp": self.otp_code},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Profile.objects.filter(user=self.user).count(), 1)
        self.assertEqual(UserOnboarding.objects.filter(user=self.user).count(), 1)
        self.assertEqual(UserRole.objects.filter(user=self.user, role__name="Fan").count(), 1)
        self.assertEqual(UserSession.objects.filter(user=self.user).count(), 1)


class ResendOTPTests(APITestCase):
    def test_resend_success(self):
        from unittest.mock import patch

        from accounts.services.otp_service import OTPService

        user = User.objects.create_user(
            username="resendfan",
            email="resend@example.com",
            password="StrongPass123!",
            first_name="Resend",
            last_name="Fan",
        )
        otp, code = OTPService.create_otp_record(user, purpose="REGISTER", channel="EMAIL")
        OTPVerification.objects.filter(id=otp.id).update(
            created_at=timezone.now() - timedelta(minutes=10)
        )

        url = reverse("accounts:resend-otp")
        with patch(
            "accounts.services.email_service.EmailService.send_verification_email"
        ) as mock_send:
            response = self.client.post(url, {"email": "resend@example.com"})
            mock_send.assert_called_once()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("expires_in", response.data["data"])

    def test_resend_rate_limited(self):
        from accounts.services.otp_service import OTPService

        user = User.objects.create_user(
            username="ratelimit",
            email="ratelimit@example.com",
            password="StrongPass123!",
            first_name="Rate",
            last_name="Limit",
        )
        OTPService.create_otp_record(user, purpose="REGISTER", channel="EMAIL")
        url = reverse("accounts:resend-otp")
        response = self.client.post(url, {"email": "ratelimit@example.com"})
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_resend_verification_alias(self):
        """Test that resend-verification endpoint works as alias for resend-otp."""
        from accounts.services.otp_service import OTPService

        user = User.objects.create_user(
            username="aliasuser",
            email="alias@example.com",
            password="StrongPass123!",
            first_name="Alias",
            last_name="User",
        )
        otp, code = OTPService.create_otp_record(user, purpose="REGISTER", channel="EMAIL")
        OTPVerification.objects.filter(id=otp.id).update(
            created_at=timezone.now() - timedelta(minutes=10)
        )

        url = reverse("accounts:resend-verification")
        with patch(
            "accounts.services.email_service.EmailService.send_verification_email"
        ) as mock_send:
            response = self.client.post(url, {"email": "alias@example.com"})
            mock_send.assert_called_once()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("expires_in", response.data["data"])

    def test_resend_is_email_even_when_phone_exists_and_supersedes_old_code(self):
        from accounts.services.otp_service import OTPService

        user = User.objects.create_user(
            username="phonefan",
            email="phonefan@example.com",
            phone_number="+256772123456",
            is_active=False,
        )
        old_otp, old_code = OTPService.create_otp_record(user, "REGISTER", "EMAIL")
        OTPVerification.objects.filter(pk=old_otp.pk).update(
            created_at=timezone.now() - timedelta(minutes=10)
        )
        with patch("accounts.services.email_service.EmailService.send_verification_email") as send:
            response = self.client.post(reverse("accounts:resend-otp"), {"email": user.email})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        send.assert_called_once()
        self.assertEqual(response.data["data"]["verification_channel"], "EMAIL")
        with self.assertRaisesRegex(ValueError, "Invalid verification code"):
            OTPService.verify_otp(user, old_code, "REGISTER")

    def test_daily_resend_limit_is_enforced(self):
        from django.conf import settings

        from accounts.services.otp_service import OTPService

        user = User.objects.create_user(username="daily", email="daily@example.com")
        for _ in range(settings.OTP_MAX_DAILY_RESENDS):
            otp, _ = OTPService.create_otp_record(user, "REGISTER", "EMAIL")
            OTPVerification.objects.filter(pk=otp.pk).update(
                created_at=timezone.now() - timedelta(minutes=10)
            )
        with patch("accounts.services.email_service.EmailService.send_verification_email") as send:
            response = self.client.post(reverse("accounts:resend-otp"), {"email": user.email})
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        send.assert_not_called()


class LoginTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="loginfan",
            email="login@example.com",
            password="StrongPass123!",
            first_name="Login",
            last_name="Fan",
            is_verified=True,
            is_active=True,
        )

    def test_login_success(self):
        url = reverse("authentication:login")
        data = {"email": "login@example.com", "password": "StrongPass123!"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data["data"])

    def test_login_blocks_unverified_account(self):
        self.user.is_verified = False
        self.user.save()
        url = reverse("authentication:login")
        data = {"email": "login@example.com", "password": "StrongPass123!"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

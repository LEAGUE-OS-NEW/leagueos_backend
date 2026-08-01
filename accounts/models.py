import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    email = models.EmailField(unique=True, db_index=True)
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^\+?1?\d{9,15}$",
                message="Enter a valid phone number.",
            )
        ],
    )
    is_verified = models.BooleanField(default=False)
    verification_channel = models.CharField(
        max_length=10,
        choices=[("EMAIL", "Email"), ("SMS", "SMS")],
        blank=True,
        default="EMAIL",
    )
    failed_attempts = models.IntegerField(default=0)
    last_failed_attempt = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        indexes = [
            models.Index(fields=["email"]),
        ]

    def __str__(self) -> str:
        return self.email or self.username


class OTPVerification(models.Model):
    PURPOSE_CHOICES = [
        ("REGISTER", "Register"),
        ("LOGIN", "Login"),
        ("PASSWORD_RESET", "Password Reset"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="otp_verifications",
    )
    otp_hash = models.CharField(max_length=128)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    channel = models.CharField(
        max_length=10,
        choices=[("EMAIL", "Email"), ("SMS", "SMS")],
    )
    expires_at = models.DateTimeField()
    attempts = models.IntegerField(default=0)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"OTP for {self.user} - {self.purpose}"

    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    def mark_used(self) -> None:
        self.is_used = True
        self.save(update_fields=["is_used"])


class VerificationAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="verification_attempts",
    )
    ip_address = models.GenericIPAddressField()
    attempts = models.IntegerField(default=1)
    last_attempt_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Verification attempts"
        ordering = ["-last_attempt_at"]
        unique_together = ["user", "ip_address"]

    def __str__(self) -> str:
        return f"Attempts for {self.user}"


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("USER_REGISTERED", "User registered"),
        ("VERIFICATION_EMAIL_SENT", "Verification email sent"),
        ("OTP_VERIFIED", "OTP verified"),
        ("ACCOUNT_ACTIVATED", "Account activated"),
        ("OTP_RESENT", "OTP resent"),
        ("FAILED_VERIFICATION", "Failed verification"),
        ("EMAIL_VERIFICATION_REQUESTED", "Email verification requested"),
        ("EMAIL_VERIFICATION_SENT", "Email verification sent"),
        ("EMAIL_VERIFICATION_RESENT", "Email verification resent"),
        ("EMAIL_VERIFICATION_SUCCESS", "Email verification success"),
        ("EMAIL_VERIFICATION_FAILED", "Email verification failed"),
        ("EMAIL_VERIFICATION_EXPIRED", "Email verification expired"),
        ("PASSWORD_RESET_REQUESTED", "Password reset requested"),
        ("PASSWORD_RESET_EMAIL_SENT", "Password reset email sent"),
        ("PASSWORD_RESET_VERIFIED", "Password reset verified"),
        ("PASSWORD_RESET_SUCCESS", "Password reset successful"),
        ("PASSWORD_RESET_FAILED", "Password reset failed"),
        ("PASSWORD_RESET_EXPIRED", "Password reset token expired"),
        ("PASSWORD_RESET_TOKEN_REUSED", "Password reset token reused"),
        ("ALL_SESSIONS_TERMINATED", "All sessions terminated"),
        ("PROFILE_VIEWED", "Profile viewed"),
        ("PROFILE_UPDATED", "Profile updated"),
        ("FAVOURITE_CLUB_UPDATED", "Favourite club updated"),
        ("AVATAR_UPLOADED", "Avatar uploaded"),
        ("AVATAR_UPDATED", "Avatar updated"),
        ("AVATAR_DELETED", "Avatar deleted"),
        ("UPLOAD_FAILED", "Upload failed"),
        ("ONBOARDING_STARTED", "Onboarding started"),
        ("COUNTRY_SELECTED", "Country selected"),
        ("SPORT_SELECTED", "Sport selected"),
        ("COMPETITION_SELECTED", "Competition selected"),
        ("CLUB_SELECTED", "Club selected"),
        ("STEP_SKIPPED", "Onboarding step skipped"),
        ("ONBOARDING_RESUMED", "Onboarding resumed"),
        ("ONBOARDING_COMPLETED", "Onboarding completed"),
        ("PREFERENCES_UPDATED", "Preferences updated"),
        ("DASHBOARD_CONFIGURATION_GENERATED", "Dashboard configuration generated"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        return f"{self.action} - {self.timestamp.isoformat()}"

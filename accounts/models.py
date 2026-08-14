import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class User(AbstractUser):
    """League OS user.

    ``account_status`` tracks the account lifecycle independently of Django's
    ``is_active`` flag so that suspended/deactivated accounts can be clearly
    distinguished from pending invitations.
    """

    class AccountStatus(models.TextChoices):
        PENDING_INVITATION = "PENDING_INVITATION", "Pending Invitation"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        DEACTIVATED = "DEACTIVATED", "Deactivated"
        INVITATION_EXPIRED = "INVITATION_EXPIRED", "Invitation Expired"

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
    )
    is_verified = models.BooleanField(default=False)
    verification_channel = models.CharField(
        max_length=10,
        choices=[("EMAIL", "Email"), ("SMS", "SMS")],
        blank=True,
        default="EMAIL",
    )
    account_status = models.CharField(
        max_length=20,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE,
        db_index=True,
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
        constraints = [
            models.UniqueConstraint(Lower("email"), name="accounts_user_email_ci_unique"),
            models.UniqueConstraint(Lower("username"), name="accounts_user_username_ci_unique"),
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
        ("MARKET_ORDER_BLOCKED", "Market order blocked"),
        ("ADMIN_INVITED", "Admin invited"),
        ("ADMIN_INVITATION_ACCEPTED", "Admin invitation accepted"),
        ("ADMIN_DISABLED", "Admin disabled"),
        ("ADMIN_ENABLED", "Admin enabled"),
        ("ROLE_ASSIGNED", "Role assigned"),
        ("ROLE_REVOKED", "Role revoked"),
        ("PERMISSION_GRANTED", "Permission granted"),
        ("PERMISSION_REVOKED", "Permission revoked"),
        ("MARKET_CREATED", "Market created"),
        ("MARKET_UPDATED", "Market updated"),
        ("MARKET_REVIEWED", "Market reviewed"),
        ("MARKET_APPROVED", "Market approved"),
        ("MARKET_REJECTED", "Market rejected"),
        ("MARKET_PUBLISHED", "Market published"),
        ("MARKET_SUSPENDED", "Market suspended"),
        ("MARKET_RESUMED", "Market resumed"),
        ("MARKET_CLOSED", "Market closed"),
        ("MARKET_ARCHIVED", "Market archived"),
        ("RESULT_VERIFIED", "Result verified"),
        ("RESULT_REVERIFIED", "Result re-verified"),
        ("COMPLIANCE_ACTION", "Compliance action"),
        ("FINANCIAL_RECONCILIATION", "Financial reconciliation"),
        ("PLATFORM_CONFIGURATION_CHANGED", "Platform configuration changed"),
        ("USER_CREATED", "User created"),
        ("USER_INVITED", "User invited"),
        ("INVITATION_RESENT", "Invitation resent"),
        ("INVITATION_REVOKED", "Invitation revoked"),
        ("ACCOUNT_ACTIVATED", "Account activated"),
        ("ACCOUNT_SUSPENDED", "Account suspended"),
        ("ACCOUNT_DEACTIVATED", "Account deactivated"),
        ("ACCOUNT_REACTIVATED", "Account reactivated"),
        ("PASSWORD_CHANGED", "Password changed"),
        ("PASSWORD_SETUP_COMPLETED", "Password setup completed"),
        ("WORKSPACE_ASSIGNED", "Workspace assigned"),
        ("WORKSPACE_REMOVED", "Workspace removed"),
        ("USER_ROLE_CHANGED", "User role changed"),
        ("USER_PERMISSIONS_UPDATED", "User permissions updated"),
        ("KYC_SUBMITTED", "KYC submitted"),
        ("KYC_PROCESSING_STARTED", "KYC processing started"),
        ("KYC_DOCUMENT_ANALYZED", "KYC document analyzed"),
        ("KYC_SELFIE_ANALYZED", "KYC selfie analyzed"),
        ("KYC_FACE_MATCH_COMPLETED", "KYC face match completed"),
        ("KYC_LIVENESS_COMPLETED", "KYC liveness completed"),
        ("KYC_VERIFIED", "KYC verified"),
        ("KYC_REJECTED", "KYC rejected"),
        ("KYC_RETRY_REQUESTED", "KYC retry requested"),
        ("KYC_REVIEW_REQUIRED", "KYC review required"),
        ("KYC_DOCUMENT_ACCESSED", "KYC document accessed"),
        ("KYC_DATA_EXPORTED", "KYC data exported"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=64, choices=ACTION_CHOICES, db_index=True)
    resource_type = models.CharField(max_length=64, blank=True, db_index=True)
    resource_id = models.UUIDField(null=True, blank=True, db_index=True)
    request_id = models.CharField(max_length=100, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        return f"{self.action} - {self.timestamp.isoformat()}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Audit log entries are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit log entries are immutable.")

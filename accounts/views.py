from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import AuditLog, OTPVerification, User, VerificationAttempt
from accounts.serializers import (
    AccountSetupCompleteSerializer,
    RegistrationStatusQuerySerializer,
    RegistrationStatusSerializer,
    ResendOTPSerializer,
    UserRegistrationSerializer,
    VerificationDeliveryResponseSerializer,
    VerifyOTPSerializer,
    build_response,
)
from accounts.services.email_service import EmailService
from accounts.services.otp_service import OTPService
from authentication.models import Role
from authentication.serializers import AuthTokenResponseSerializer
from authentication.services.account_setup_service import AccountSetupService
from authentication.services.auth_context_service import AuthContextService
from authentication.services.role_service import RoleService
from authentication.services.session_service import SessionService
from authentication.services.token_service import TokenService
from clubs.models import StaffInvitation
from clubs.services.staff_service import StaffService
from onboarding.services.onboarding_service import OnboardingService
from profiles.models import Profile


def get_client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")


def log_audit(user, action, ip_address=None, user_agent="", metadata=None):
    AuditLog.objects.create(
        user=user,
        action=action,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata=metadata or {},
    )


def mask_email(email):
    local, domain = email.rsplit("@", 1)
    visible = local[:1]
    return f"{visible}{'*' * max(2, len(local) - 1)}@{domain}"


def verification_data(user):
    return {
        "verification_required": True,
        "verification_channel": "EMAIL",
        "destination": mask_email(user.email),
        "expires_in": settings.OTP_EXPIRY_MINUTES * 60,
        "resend_available_in": settings.OTP_RESEND_COOLDOWN_MINUTES * 60,
    }


class RegisterView(APIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=UserRegistrationSerializer,
        responses={
            201: VerificationDeliveryResponseSerializer,
            200: VerificationDeliveryResponseSerializer,
        },
    )
    def post(self, request):
        raw_email = str(request.data.get("email", "")).strip().lower()
        existing = User.objects.filter(email__iexact=raw_email).first() if raw_email else None
        if existing and not existing.is_verified and not existing.is_active:
            return Response(
                build_response(
                    True,
                    "Registration requires email verification. Request a new code to continue.",
                    verification_data(existing),
                ),
                status=status.HTTP_200_OK,
            )

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        user.is_active = False
        user.verification_channel = "EMAIL"
        user.save(update_fields=["is_active", "verification_channel"])
        ip_address = get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        otp, code = OTPService.create_otp_record(user, purpose="REGISTER", channel="EMAIL")
        try:
            EmailService.send_verification_email(user, code)
        except Exception:
            otp.mark_used()
            log_audit(user, "USER_REGISTERED", ip_address, user_agent, {"channel": "EMAIL"})
            return Response(
                build_response(
                    False,
                    "Registration was saved, but verification email delivery failed. Please retry.",
                    verification_data(user),
                    {"delivery": ["Verification email could not be sent."]},
                ),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        log_audit(user, "USER_REGISTERED", ip_address, user_agent, {"channel": "EMAIL"})
        log_audit(user, "VERIFICATION_EMAIL_SENT", ip_address, user_agent, {"channel": "EMAIL"})
        return Response(
            build_response(
                True,
                "Registration successful. Please check your email to verify your account.",
                verification_data(user),
            ),
            status=status.HTTP_201_CREATED,
        )


class VerifyOTPView(APIView):
    serializer_class = VerifyOTPSerializer
    permission_classes = [permissions.AllowAny]

    @extend_schema(request=VerifyOTPSerializer, responses={200: AuthTokenResponseSerializer})
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"].strip().lower()
        code = serializer.validated_data["otp"]
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            return Response(
                build_response(
                    False,
                    "Invalid verification code.",
                    errors={"otp": ["Invalid verification code."]},
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )
        ip_address = get_client_ip(request) or "127.0.0.1"
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        now = timezone.now()
        attempt, _ = VerificationAttempt.objects.get_or_create(
            user=user, ip_address=ip_address, defaults={"attempts": 0}
        )
        lock_window = timedelta(minutes=settings.OTP_VERIFICATION_LOCK_MINUTES)
        if attempt.last_attempt_at < now - lock_window:
            attempt.attempts = 0
        if attempt.attempts >= settings.OTP_MAX_VERIFICATION_ATTEMPTS:
            return Response(
                build_response(False, "Too many failed attempts. Try again later."),
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        try:
            with transaction.atomic():
                locked_user = User.objects.select_for_update().get(pk=user.pk)
                otp = OTPService.verify_otp(locked_user, code, "REGISTER")
                locked_user.is_verified = True
                locked_user.is_active = True
                locked_user.verification_channel = "EMAIL"
                locked_user.save(update_fields=["is_verified", "is_active", "verification_channel"])
                fan_role, _ = Role.objects.get_or_create(
                    name="Fan", defaults={"display_name": "Fan", "is_system": True}
                )
                RoleService.assign_role(locked_user, fan_role)
                Profile.objects.get_or_create(user=locked_user)
                OnboardingService.get_or_create_onboarding(locked_user, ip_address)
                access, refresh = TokenService.generate_tokens(locked_user)
                SessionService.create_session(locked_user, refresh, ip_address, user_agent)
                log_audit(
                    locked_user, "OTP_VERIFIED", ip_address, user_agent, {"channel": otp.channel}
                )
                log_audit(locked_user, "ACCOUNT_ACTIVATED", ip_address, user_agent)
        except ValueError:
            attempt.attempts += 1
            attempt.save(update_fields=["attempts", "last_attempt_at"])
            log_audit(
                user, "FAILED_VERIFICATION", ip_address, user_agent, {"reason": "invalid_code"}
            )
            return Response(
                build_response(
                    False,
                    "Invalid verification code.",
                    errors={"otp": ["Invalid verification code."]},
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )
        attempt.delete()
        return Response(
            build_response(
                True,
                "Account verified successfully.",
                AuthContextService.authenticated_data(locked_user, access, refresh),
            ),
            status=status.HTTP_200_OK,
        )


class ResendOTPView(APIView):
    serializer_class = ResendOTPSerializer
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=ResendOTPSerializer, responses={200: VerificationDeliveryResponseSerializer}
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=serializer.validated_data["email"]).first()
        generic = build_response(True, "If verification is required, an email will be sent.")
        if not user:
            return Response(generic)
        if user.is_verified:
            return Response(generic)
        now = timezone.now()
        recent = OTPVerification.objects.filter(
            user=user,
            purpose="REGISTER",
            is_used=False,
            created_at__gte=now - timedelta(minutes=settings.OTP_RESEND_COOLDOWN_MINUTES),
        ).first()
        if recent:
            remaining = max(
                1,
                int(
                    (
                        recent.created_at
                        + timedelta(minutes=settings.OTP_RESEND_COOLDOWN_MINUTES)
                        - now
                    ).total_seconds()
                ),
            )
            return Response(
                build_response(
                    False,
                    "Please wait before requesting another code.",
                    {**verification_data(user), "resend_available_in": remaining},
                ),
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        daily_count = OTPVerification.objects.filter(
            user=user, purpose="REGISTER", created_at__gte=now - timedelta(days=1)
        ).count()
        if daily_count >= settings.OTP_MAX_DAILY_RESENDS:
            return Response(
                build_response(False, "Daily verification email limit reached. Try again later."),
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        otp, code = OTPService.create_otp_record(user, "REGISTER", "EMAIL")
        try:
            EmailService.send_verification_email(user, code)
        except Exception:
            otp.mark_used()
            return Response(
                build_response(False, "Verification email delivery failed. Please retry."),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        log_audit(
            user,
            "OTP_RESENT",
            get_client_ip(request),
            request.META.get("HTTP_USER_AGENT", ""),
            {"channel": "EMAIL"},
        )
        return Response(
            build_response(True, "Verification email sent.", verification_data(user)),
            status=status.HTTP_200_OK,
        )


class RegistrationStatusView(APIView):
    serializer_class = RegistrationStatusQuerySerializer
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        serializer = self.serializer_class(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=serializer.validated_data["email"]).first()
        if not user:
            return Response(build_response(True, "Registration not found.", {"exists": False}))
        return Response(
            build_response(
                True,
                "Registration status fetched.",
                {"exists": True, **RegistrationStatusSerializer(user).data},
            )
        )


class AccountSetupCompleteView(APIView):
    """Consumes an AccountSetupToken to set a password and activate the
    account — the piece AccountSetupService always had but nothing called.

    If a pending StaffInvitation exists for this email (the club-admin
    invite path — see ClubAdminInvitationService), also accepts it in the
    same request so the invitee lands with their ClubWorkspace + Club Admin
    role already granted, instead of a second manual step.
    """

    serializer_class = AccountSetupCompleteSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user, error = AccountSetupService.complete_setup(
            data["token"],
            data["password"],
            data["first_name"],
            data["last_name"],
        )
        if not user:
            return Response(
                build_response(
                    False,
                    error or "Invalid or expired setup token.",
                    errors={"token": [error or "Invalid or expired setup token."]},
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        pending_invitation = (
            StaffInvitation.objects.filter(
                email__iexact=user.email,
                status=StaffInvitation.Status.PENDING,
            )
            .order_by("-created_at")
            .first()
        )
        if pending_invitation:
            StaffService.accept_invitation(token=pending_invitation.token, user=user)

        ip_address = get_client_ip(request) or "127.0.0.1"
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        access, refresh = TokenService.generate_tokens(user)
        SessionService.create_session(user, refresh, ip_address, user_agent)
        log_audit(user, "ACCOUNT_SETUP_COMPLETED", ip_address, user_agent)

        return Response(
            build_response(
                True,
                "Account set up successfully.",
                AuthContextService.authenticated_data(user, access, refresh),
            ),
            status=status.HTTP_200_OK,
        )

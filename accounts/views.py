import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import AuditLog, OTPVerification, User, VerificationAttempt
from accounts.serializers import (
    RegistrationStatusQuerySerializer,
    RegistrationStatusSerializer,
    ResendOTPSerializer,
    UserProfileSerializer,
    UserRegistrationSerializer,
    VerifyOTPSerializer,
    build_response,
)
from accounts.services.email_service import EmailService
from accounts.services.otp_service import OTPService

logger = logging.getLogger(__name__)


def get_client_ip(request):
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0]
    return request.META.get("REMOTE_ADDR")


def log_audit(user, action, ip_address=None, user_agent="", metadata=None):
    AuditLog.objects.create(
        user=user,
        action=action,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata=metadata or {},
    )


class RegisterView(APIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = serializer.save()
        ip_address = get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        channel = user.verification_channel or "EMAIL"

        otp, otp_code = OTPService.create_otp_record(user, purpose="REGISTER", channel=channel)

        if channel == "EMAIL":
            EmailService.send_verification_email(user, otp_code)
        else:
            logger.info("[DEV OTP SMS] to=%s code=%s", user.phone_number, otp_code)

        log_audit(
            user,
            "USER_REGISTERED",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"channel": channel},
        )
        log_audit(
            user,
            "VERIFICATION_EMAIL_SENT",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"channel": channel},
        )

        response_data = {
            "verification_channel": channel,
        }
        if channel == "EMAIL":
            response_data["destination"] = user.email
        else:
            response_data["destination"] = user.phone_number

        return Response(
            build_response(
                success=True,
                message="Registration successful. Please check your email to verify your account.",
                data=response_data,
            ),
            status=status.HTTP_201_CREATED,
        )


class VerifyOTPView(APIView):
    serializer_class = VerifyOTPSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get("email")
        otp_code = request.data.get("otp")

        if not email or not otp_code:
            return Response(
                build_response(
                    success=False,
                    message="Invalid input",
                    errors={"detail": ["email and otp are required."]},
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(email__iexact=email).first()
        if not user:
            return Response(
                build_response(
                    success=False,
                    message="Invalid email or OTP.",
                    errors={"email": ["User not found."]},
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        ip_address = get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        attempt, _ = VerificationAttempt.objects.get_or_create(
            user=user, ip_address=ip_address, defaults={"attempts": 0}
        )

        if attempt.attempts >= settings.OTP_MAX_VERIFICATION_ATTEMPTS:
            log_audit(
                user,
                "FAILED_VERIFICATION",
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"reason": "max_attempts_exceeded"},
            )
            return Response(
                build_response(
                    success=False,
                    message="Too many failed attempts. Try again later.",
                    errors={"detail": ["Too many failed attempts. Try again later."]},
                ),
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            otp = OTPService.verify_otp(user, otp_code, purpose="REGISTER")
        except ValueError as exc:
            attempt.attempts += 1
            attempt.save(update_fields=["attempts"])
            log_audit(
                user,
                "FAILED_VERIFICATION",
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"reason": str(exc)},
            )
            return Response(
                build_response(
                    success=False,
                    message="Invalid or expired OTP.",
                    errors={"otp": [str(exc)]},
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.is_verified = True
        user.is_active = True
        user.save(update_fields=["is_verified", "is_active"])

        attempt.attempts = 0
        attempt.save(update_fields=["attempts"])

        log_audit(
            user,
            "OTP_VERIFIED",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"channel": otp.channel},
        )
        log_audit(
            user,
            "ACCOUNT_ACTIVATED",
            ip_address=ip_address,
            user_agent=user_agent,
        )

        refresh = RefreshToken.for_user(user)
        user_data = UserProfileSerializer(user).data

        return Response(
            build_response(
                success=True,
                message="Account verified successfully",
                data={
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                    "user": user_data,
                },
            ),
            status=status.HTTP_200_OK,
        )


class ResendOTPView(APIView):
    serializer_class = ResendOTPSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get("email")
        if not email:
            return Response(
                build_response(
                    success=False,
                    message="Invalid input",
                    errors={"email": ["Email is required."]},
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(email__iexact=email).first()
        if not user:
            return Response(
                build_response(
                    success=False,
                    message="User not found.",
                    errors={"email": ["User not found."]},
                ),
                status=status.HTTP_404_NOT_FOUND,
            )

        ip_address = get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        channel = user.verification_channel or "EMAIL"

        recent_otps = OTPVerification.objects.filter(
            user=user,
            purpose="REGISTER",
            channel=channel,
            is_used=False,
            created_at__gte=timezone.now()
            - timedelta(minutes=settings.OTP_RESEND_COOLDOWN_MINUTES),
        )
        if recent_otps.exists():
            return Response(
                build_response(
                    success=False,
                    message="Please wait before requesting another OTP.",
                    errors={"detail": ["Please wait before requesting another OTP."]},
                ),
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        otp, otp_code = OTPService.create_otp_record(user, purpose="REGISTER", channel=channel)

        if channel == "EMAIL":
            EmailService.send_verification_email(user, otp_code)
        else:
            logger.info("[DEV OTP SMS] to=%s code=%s", user.phone_number, otp_code)

        log_audit(
            user,
            "OTP_RESENT",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"channel": channel},
        )

        return Response(
            build_response(
                success=True,
                message="Verification email sent.",
                data={"expires_in": settings.OTP_EXPIRY_MINUTES * 60},
            ),
            status=status.HTTP_200_OK,
        )


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get("email")
        password = request.data.get("password")

        if not email or not password:
            return Response(
                build_response(
                    success=False,
                    message="Invalid input",
                    errors={"detail": ["Email and password are required."]},
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response(
                build_response(
                    success=False,
                    message="Invalid credentials.",
                ),
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.check_password(password):
            return Response(
                build_response(
                    success=False,
                    message="Invalid credentials.",
                ),
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.is_active:
            return Response(
                build_response(
                    success=False,
                    message="Account is inactive. Please verify your email.",
                ),
                status=status.HTTP_403_FORBIDDEN,
            )

        if not user.is_verified:
            return Response(
                build_response(
                    success=False,
                    message="Please verify your email before logging in.",
                ),
                status=status.HTTP_403_FORBIDDEN,
            )

        refresh = RefreshToken.for_user(user)
        user_data = UserProfileSerializer(user).data

        log_audit(
            user,
            "ACCOUNT_ACTIVATED",
            ip_address=get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        return Response(
            build_response(
                success=True,
                message="Login successful.",
                data={
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                    "user": user_data,
                },
            ),
            status=status.HTTP_200_OK,
        )


class ProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(
            build_response(
                success=True, message="Profile fetched.", data={"user": serializer.data}
            ),
            status=status.HTTP_200_OK,
        )


class RegistrationStatusView(APIView):
    serializer_class = RegistrationStatusQuerySerializer
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        email = request.query_params.get("email")
        if not email:
            return Response(
                build_response(
                    success=False,
                    message="Invalid input",
                    errors={"email": ["Email query parameter is required."]},
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(email__iexact=email).first()
        if not user:
            return Response(
                build_response(
                    success=True,
                    message="Registration not found.",
                    data={"exists": False},
                ),
                status=status.HTTP_200_OK,
            )

        serializer = RegistrationStatusSerializer(user)
        return Response(
            build_response(
                success=True,
                message="Registration status fetched.",
                data={"exists": True, **serializer.data},
            ),
            status=status.HTTP_200_OK,
        )

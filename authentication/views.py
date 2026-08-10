import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import AuditLog, User
from accounts.serializers import build_response
from authentication.models import UserSession
from authentication.serializers import (
    AuthTokenResponseSerializer,
    EmptySerializer,
    LoginSerializer,
    LogoutSerializer,
    MeResponseSerializer,
    MessageResponseSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    PasswordResetVerifySerializer,
    SessionSerializer,
    UserProfileSerializer,
    ChangePasswordSerializer,
)
from authentication.services.auth_context_service import AuthContextService
from authentication.services.authentication_service import AuthenticationService
from authentication.services.login_history_service import LoginHistoryService
from authentication.services.password_reset_service import PasswordResetService
from authentication.services.password_change_service import PasswordChangeService
from authentication.services.session_service import SessionService
from authentication.services.token_service import TokenService

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


class LoginView(APIView):
    serializer_class = LoginSerializer
    permission_classes = [permissions.AllowAny]

    @extend_schema(request=LoginSerializer, responses={200: AuthTokenResponseSerializer})
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        identifier = serializer.validated_data["identifier"]
        password = serializer.validated_data["password"]
        ip_address = get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")

        # First check if the account is locked before attempting authentication
        user = AuthenticationService.find_user(identifier)
        if user and AuthenticationService.is_account_locked(user):
            log_audit(
                user,
                "LOGIN_LOCKED",
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"locked_until": str(user.locked_until)},
            )
            return Response(
                build_response(success=False, message="Account temporarily locked."),
                status=status.HTTP_403_FORBIDDEN,
            )

        user = AuthenticationService.authenticate(identifier, password, ip_address, user_agent)
        if not user:
            if user is None:
                matched = AuthenticationService.find_user(identifier)
                if (
                    matched
                    and matched.check_password(password)
                    and (not matched.is_active or not matched.is_verified)
                ):
                    return Response(
                        build_response(
                            success=False,
                            message="Account verification is required.",
                            data={
                                "verification_required": True,
                                "verification_channel": "EMAIL",
                            },
                        ),
                        status=status.HTTP_401_UNAUTHORIZED,
                    )
            return Response(
                build_response(success=False, message="Invalid credentials."),
                status=status.HTTP_401_UNAUTHORIZED,
            )

        access, refresh = TokenService.generate_tokens(user)
        session = SessionService.create_session(user, refresh, ip_address, user_agent)
        LoginHistoryService.record_login(user, ip_address, user_agent, successful=True)

        log_audit(
            user,
            "LOGIN_SUCCESS",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"session_id": str(session.id)},
        )

        return Response(
            build_response(
                success=True,
                message="Login successful.",
                data=AuthContextService.authenticated_data(user, access, refresh),
            ),
            status=status.HTTP_200_OK,
        )


class TokenRefreshView(APIView):
    serializer_class = TokenRefreshSerializer
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    @extend_schema(request=TokenRefreshSerializer, responses={200: AuthTokenResponseSerializer})
    def post(self, request):
        raw_refresh = request.data.get("refresh", "")
        try:
            old_token = RefreshToken(raw_refresh)
            old_jti = str(old_token["jti"])
            user_id = old_token["user_id"]
        except (TokenError, KeyError):
            return Response(
                build_response(False, "Invalid, expired or revoked refresh token."),
                status=status.HTTP_401_UNAUTHORIZED,
            )
        try:
            with transaction.atomic():
                session = (
                    UserSession.objects.select_for_update()
                    .filter(refresh_token_jti=old_jti, user_id=user_id, is_active=True)
                    .first()
                )
                if session is None:
                    raise TokenError("session is inactive or token was rotated")
                serializer = TokenRefreshSerializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                refreshed = dict(serializer.validated_data)
                new_refresh = refreshed.get("refresh")
                if new_refresh:
                    session.refresh_token_jti = str(RefreshToken(new_refresh)["jti"])
                session.last_activity = timezone.now()
                session.save(update_fields=["refresh_token_jti", "last_activity", "updated_at"])
        except TokenError:
            return Response(
                build_response(
                    success=False,
                    message="Invalid, expired or revoked refresh token.",
                ),
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user = User.objects.get(pk=user_id)
        refreshed.update(AuthContextService.authenticated_data(user))
        return Response(
            build_response(
                success=True,
                message="Token refreshed successfully.",
                data=refreshed,
            ),
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    serializer_class = LogoutSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=LogoutSerializer, responses={200: MessageResponseSerializer})
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        refresh_token = serializer.validated_data["refresh"]

        try:
            token = RefreshToken(refresh_token)
            jti = str(token["jti"])
        except TokenError:
            return Response(
                build_response(
                    success=False,
                    message="Invalid or expired refresh token.",
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        session = UserSession.objects.filter(
            refresh_token_jti=jti,
            user=request.user,
            is_active=True,
        ).first()

        if session is None:
            return Response(
                build_response(
                    success=False,
                    message="Refresh token does not belong to the authenticated session.",
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            TokenService.blacklist_refresh_token(
                refresh_token,
            )
        except TokenError:
            return Response(
                build_response(
                    success=False,
                    message="Invalid or expired refresh token.",
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )

        SessionService.terminate_session(session)
        LoginHistoryService.record_logout(request.user)
        log_audit(
            request.user,
            "LOGOUT",
            ip_address=get_client_ip(request),
            metadata={"session_id": str(session.id)},
        )

        return Response(
            build_response(
                success=True,
                message="Logged out successfully.",
            ),
            status=status.HTTP_200_OK,
        )


class LogoutAllView(APIView):
    serializer_class = EmptySerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user

        TokenService.blacklist_user_refresh_tokens(user)
        SessionService.terminate_user_sessions(user)

        LoginHistoryService.record_logout(user)
        log_audit(user, "LOGOUT_ALL", ip_address=get_client_ip(request))

        return Response(
            build_response(success=True, message="Logged out from all devices."),
            status=status.HTTP_200_OK,
        )


class ProfileView(APIView):
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(
            build_response(
                success=True, message="Profile fetched.", data={"user": serializer.data}
            ),
            status=status.HTTP_200_OK,
        )


class MeView(APIView):
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: MeResponseSerializer})
    def get(self, request):
        return Response(
            build_response(
                success=True,
                message="Current user.",
                data=AuthContextService.authenticated_data(request.user),
            ),
            status=status.HTTP_200_OK,
        )


class SessionListView(APIView):
    serializer_class = SessionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        sessions = SessionService.get_active_sessions(request.user)
        serializer = SessionSerializer(sessions, many=True)
        return Response(
            build_response(
                success=True, message="Sessions fetched.", data={"sessions": serializer.data}
            ),
            status=status.HTTP_200_OK,
        )


class PasswordResetRequestView(APIView):
    serializer_class = PasswordResetRequestSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        ip_address = get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")

        result = PasswordResetService.request_password_reset(email, ip_address, user_agent)

        return Response(
            build_response(success=result["success"], message=result["message"]),
            status=status.HTTP_200_OK,
        )


class PasswordResetVerifyView(APIView):
    serializer_class = PasswordResetVerifySerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        otp = serializer.validated_data["otp"]
        ip_address = get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")

        result = PasswordResetService.verify_reset_token(email, otp, ip_address, user_agent)

        if result["success"]:
            return Response(
                build_response(success=True, message=result["message"]),
                status=status.HTTP_200_OK,
            )
        return Response(
            build_response(success=False, message=result["message"]),
            status=status.HTTP_400_BAD_REQUEST,
        )


class ChangePasswordView(APIView):
    """Allows an authenticated user to change their own password."""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    @extend_schema(
        request=ChangePasswordSerializer,
        responses={
            200: {"description": "Password changed successfully."},
            400: {"description": "Invalid input or validation error."},
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            PasswordChangeService.change_password(
                user=request.user,
                current_password=serializer.validated_data["current_password"],
                new_password=serializer.validated_data["new_password"],
                ip_address=get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )
        except PermissionError as e:
            return Response(
                build_response(False, str(e), errors={"current_password": [str(e)]}),
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValidationError as e:
            return Response(
                build_response(False, e.message, errors={"new_password": e.messages}),
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(build_response(True, "Password changed successfully."))


class PasswordResetConfirmView(APIView):
    serializer_class = PasswordResetConfirmSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]
        otp = serializer.validated_data["otp"]
        password = serializer.validated_data["password"]
        ip_address = get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")

        result = PasswordResetService.confirm_password_reset(
            email, otp, password, ip_address, user_agent
        )

        if result["success"]:
            return Response(
                build_response(success=True, message=result["message"]),
                status=status.HTTP_200_OK,
            )
        return Response(
            build_response(success=False, message=result["message"]),
            status=status.HTTP_400_BAD_REQUEST,
        )


def build_response(success: bool, message: str, data=None):
    payload = {"success": success, "message": message}
    if data is not None:
        payload["data"] = data
    return payload

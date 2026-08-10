from django.core.exceptions import ValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.serializers import build_response
from accounts.views import get_client_ip
from authentication.serializers import ChangePasswordSerializer
from authentication.services.password_change_service import PasswordChangeService


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

import logging

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.serializers import build_response
from authentication.admin_serializers import (
    AdminPermissionSerializer,
    AdminRoleSerializer,
    SubordinateUserCreateSerializer,
    UserLifecycleSerializer,
)
from authentication.models import ClubWorkspace, Permission, Role
from authentication.permissions import HasPermission
from authentication.serializers import UserProfileSerializer
from authentication.services.delegation_service import DelegationService
from authentication.services.role_service import RoleService
from authentication.services.user_admin_service import UserAdminService

logger = logging.getLogger(__name__)


class AvailableRolesView(APIView):
    """Provides a list of roles the current administrator can delegate."""

    permission_classes = [permissions.IsAuthenticated, HasPermission]
    serializer_class = AdminRoleSerializer
    required_permissions = [
        "platform.users.manage",
        "club.users.manage",
    ]

    @extend_schema(responses={200: AdminRoleSerializer(many=True)})
    def get(self, request, *args, **kwargs):
        delegatable_roles = DelegationService.get_delegatable_roles(request.user)
        serializer = self.serializer_class(delegatable_roles, many=True)
        return Response(
            build_response(True, "Available roles fetched.", {"roles": serializer.data})
        )


class AvailablePermissionsView(APIView):
    """Provides a list of permissions the current administrator can delegate."""

    permission_classes = [permissions.IsAuthenticated, HasPermission]
    serializer_class = AdminPermissionSerializer
    required_permissions = [
        "platform.users.manage",
        "club.users.manage",
    ]

    @extend_schema(responses={200: AdminPermissionSerializer(many=True)})
    def get(self, request, *args, **kwargs):
        delegatable_permissions = DelegationService.get_delegatable_permissions(request.user)
        serializer = self.serializer_class(delegatable_permissions, many=True)
        return Response(
            build_response(True, "Available permissions fetched.", {"permissions": serializer.data})
        )


class SubordinateUserViewSet(viewsets.GenericViewSet):
    """
    ViewSet for administrators to manage subordinate user accounts.
    """

    permission_classes = [permissions.IsAuthenticated, HasPermission]
    queryset = User.objects.filter(is_staff=True, is_superuser=False).order_by("-date_joined")

    def get_queryset(self):
        """
        Scope the queryset based on the admin's role.
        - Super Admins can see all subordinate staff users.
        - Club Admins can only see users within their manageable workspaces.
        """
        user = self.request.user
        base_queryset = super().get_queryset()

        # Super Admins can see everyone.
        if any(r.name == "Super Admin" for r in RoleService.get_user_roles(user)):
            return base_queryset

        # Other admins (e.g., Club Admins) are scoped to their workspaces.
        manageable_workspaces = DelegationService.get_manageable_workspaces(user)
        return base_queryset.filter(
            workspace_memberships__workspace__in=manageable_workspaces
        ).distinct()

    def get_serializer_class(self):
        if self.action == "create":
            return SubordinateUserCreateSerializer
        if self.action in ["suspend", "deactivate"]:
            return UserLifecycleSerializer
        return UserProfileSerializer

    def get_permissions(self):
        """Instantiates and returns the list of permissions that this view requires."""
        # A user needs 'platform.users.manage' OR 'club.users.manage'
        # This logic can be enhanced in a custom permission class later.
        # Using required_permissions to allow either platform or club management
        self.required_permissions = [
            "platform.users.manage",
            "club.users.manage",
        ]

        return super().get_permissions()

    @extend_schema(responses={200: UserProfileSerializer(many=True)})
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(
            build_response(True, "Subordinate users fetched.", {"users": serializer.data})
        )

    @extend_schema(responses={200: UserProfileSerializer})
    def retrieve(self, request, pk=None):
        user = self.get_object()  # get_object() uses get_queryset() internally
        serializer = self.get_serializer(user)
        return Response(
            build_response(True, "Subordinate user fetched.", {"user": serializer.data})
        )

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            role = Role.objects.get(id=data["role_id"])
            permissions = list(Permission.objects.filter(id__in=data["permission_ids"]))
            workspaces = list(ClubWorkspace.objects.filter(id__in=data["workspace_ids"]))

            user = UserAdminService.create_user(
                actor=request.user,
                email=data["email"],
                first_name=data["first_name"],
                last_name=data["last_name"],
                role=role,
                permissions=permissions,
                workspaces=workspaces,
            )
        except (PermissionError, ValueError) as e:
            return Response(build_response(False, str(e)), status=status.HTTP_403_FORBIDDEN)

        response_serializer = UserProfileSerializer(user)
        return Response(
            build_response(
                True, "Subordinate user created successfully.", {"user": response_serializer.data}
            ),
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        user = self.get_object()
        UserAdminService.suspend_user(actor=request.user, user=user)
        return Response(build_response(True, "User suspended successfully."))

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        user = self.get_object()
        UserAdminService.deactivate_user(actor=request.user, user=user)
        return Response(build_response(True, "User deactivated successfully."))

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        user = self.get_object()
        UserAdminService.activate_user(actor=request.user, user=user)
        return Response(build_response(True, "User activated successfully."))

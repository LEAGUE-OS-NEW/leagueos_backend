import logging

from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import AuditLog, User
from authentication.models import Permission, Role, UserRole
from authentication.services.invitation_service import InvitationService
from authentication.services.permission_service import PermissionService
from authentication.services.role_service import RoleService
from platform_admin.serializers import (
    AdminInvitationCreateSerializer,
    AdminInvitationReadSerializer,
    AdminPermissionSerializer,
    AdminRoleAssignmentSerializer,
    AdminRoleSerializer,
    AdminUserListSerializer,
    AdminUserRoleUpdateSerializer,
)

logger = logging.getLogger(__name__)


def log_audit(user, action, ip_address=None, user_agent="", metadata=None):
    AuditLog.objects.create(
        user=user,
        action=action,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata=metadata or {},
    )


class AdminPermissionListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AdminPermissionSerializer

    @extend_schema(
        operation_id="admin_permissions_list",
        responses={200: AdminPermissionSerializer(many=True)},
    )
    def get(self, request):
        if not PermissionService.has_permission(request.user, "admin.permissions.view"):
            return Response(
                {"detail": "You do not have permission to view permissions."},
                status=403,
            )

        permissions = Permission.objects.all().order_by("resource", "action")
        serializer = self.serializer_class(permissions, many=True)
        return Response(serializer.data)


class AdminRoleListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AdminRoleSerializer

    @extend_schema(
        operation_id="admin_roles_list",
        responses={200: AdminRoleSerializer(many=True)},
    )
    def get(self, request):
        if not PermissionService.has_permission(request.user, "admin.roles.view"):
            return Response(
                {"detail": "You do not have permission to view roles."},
                status=403,
            )

        roles = Role.objects.all().order_by("name")
        serializer = self.serializer_class(roles, many=True)
        return Response(serializer.data)


class AdminRoleDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AdminRoleSerializer

    @extend_schema(
        operation_id="admin_role_detail",
        responses={200: AdminRoleSerializer, 404: None},
    )
    def get(self, request, role_id):
        if not PermissionService.has_permission(request.user, "admin.roles.view"):
            return Response(
                {"detail": "You do not have permission to view roles."},
                status=403,
            )

        role = Role.objects.filter(id=role_id).first()
        if not role:
            return Response(
                {"detail": "Role not found."},
                status=404,
            )

        serializer = self.serializer_class(role)
        return Response(serializer.data)


class AdminUserListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AdminUserListSerializer

    @extend_schema(
        operation_id="admin_users_list",
        responses={200: AdminUserListSerializer(many=True)},
    )
    def get(self, request):
        if not PermissionService.has_permission(request.user, "admin.users.view"):
            return Response(
                {"detail": "You do not have permission to view users."},
                status=403,
            )

        users = User.objects.all().order_by("-created_at")
        serializer = self.serializer_class(users, many=True)
        return Response(serializer.data)


class AdminUserDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AdminUserListSerializer

    @extend_schema(
        operation_id="admin_user_detail",
        responses={200: AdminUserListSerializer, 404: None},
    )
    def get(self, request, user_id):
        if not PermissionService.has_permission(request.user, "admin.users.view"):
            return Response(
                {"detail": "You do not have permission to view users."},
                status=403,
            )

        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response(
                {"detail": "User not found."},
                status=404,
            )

        serializer = self.serializer_class(user)
        return Response(serializer.data)

    @extend_schema(
        operation_id="admin_user_update",
        request=AdminUserRoleUpdateSerializer,
        responses={200: AdminUserListSerializer, 400: None, 403: None, 404: None},
    )
    def patch(self, request, user_id):
        if not PermissionService.has_permission(request.user, "admin.users.manage"):
            return Response(
                {"detail": "You do not have permission to manage users."},
                status=403,
            )

        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response(
                {"detail": "User not found."},
                status=404,
            )

        serializer = AdminUserRoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        role_ids = set(serializer.validated_data["role_ids"])

        current_roles = set(
            UserRole.objects.filter(user=user, is_active=True).values_list("role_id", flat=True)
        )
        roles_to_add = role_ids - current_roles
        roles_to_remove = current_roles - role_ids

        for role_id in roles_to_add:
            role = Role.objects.filter(id=role_id).first()
            if role:
                RoleService.assign_role(user, role, assigned_by=request.user)

        for role_id in roles_to_remove:
            role = Role.objects.filter(id=role_id).first()
            if role:
                RoleService.remove_role(user, role, revoked_by=request.user)

        log_audit(
            request.user,
            "USER_ROLES_UPDATED",
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            metadata={
                "target_user_id": str(user.id),
                "added_roles": [str(r) for r in roles_to_add],
                "removed_roles": [str(r) for r in roles_to_remove],
            },
        )

        return Response(self.serializer_class(user).data)


class AdminUserRoleAssignView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AdminUserListSerializer

    @extend_schema(
        operation_id="admin_user_role_assign",
        request=AdminRoleAssignmentSerializer,
        responses={200: AdminUserListSerializer, 400: None, 403: None, 404: None},
    )
    def post(self, request, user_id):
        if not PermissionService.has_permission(request.user, "admin.users.manage"):
            return Response(
                {"detail": "You do not have permission to manage user roles."},
                status=403,
            )

        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response(
                {"detail": "User not found."},
                status=404,
            )

        serializer = AdminRoleAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        role = Role.objects.filter(id=serializer.validated_data["role_id"]).first()
        if not role:
            return Response(
                {"detail": "Role not found."},
                status=404,
            )

        RoleService.assign_role(
            user=user,
            role=role,
            assigned_by=request.user,
            expires_at=serializer.validated_data.get("expires_at"),
        )

        log_audit(
            request.user,
            "ROLE_ASSIGNED",
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            metadata={"target_user_id": str(user.id), "role_id": str(role.id)},
        )

        return Response(self.serializer_class(user).data)


class AdminUserRoleRevokeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AdminUserListSerializer

    @extend_schema(
        operation_id="admin_user_role_revoke",
        responses={200: AdminUserListSerializer, 403: None, 404: None},
    )
    def delete(self, request, user_id, role_id):
        if not PermissionService.has_permission(request.user, "admin.users.manage"):
            return Response(
                {"detail": "You do not have permission to manage user roles."},
                status=403,
            )

        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response(
                {"detail": "User not found."},
                status=404,
            )

        role = Role.objects.filter(id=role_id).first()
        if not role:
            return Response(
                {"detail": "Role not found."},
                status=404,
            )

        user_role = RoleService.remove_role(user, role, revoked_by=request.user)
        if not user_role:
            return Response(
                {"detail": "Role is not assigned to this user."},
                status=404,
            )

        log_audit(
            request.user,
            "ROLE_REVOKED",
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            metadata={"target_user_id": str(user.id), "role_id": str(role.id)},
        )

        return Response(self.serializer_class(user).data)


class AdminInvitationListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AdminInvitationReadSerializer

    @extend_schema(
        operation_id="admin_invitations_list",
        responses={200: AdminInvitationReadSerializer(many=True)},
    )
    def get(self, request):
        if not PermissionService.has_permission(request.user, "admin.users.manage"):
            return Response(
                {"detail": "You do not have permission to view invitations."},
                status=403,
            )

        invitations = InvitationService.get_pending_invitations()
        serializer = self.serializer_class(invitations, many=True)
        return Response(serializer.data)

    @extend_schema(
        operation_id="admin_invitation_create",
        request=AdminInvitationCreateSerializer,
        responses={201: AdminInvitationReadSerializer, 400: None, 403: None},
    )
    def post(self, request):
        if not PermissionService.has_permission(request.user, "admin.users.invite"):
            return Response(
                {"detail": "You do not have permission to invite administrators."},
                status=403,
            )

        serializer = AdminInvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        roles = Role.objects.filter(id__in=serializer.validated_data["role_ids"])
        if not roles.exists():
            return Response(
                {"detail": "No valid roles found."},
                status=400,
            )

        invitation = InvitationService.create_invitation(
            email=serializer.validated_data["email"],
            roles=list(roles),
            invited_by=request.user,
            expires_in_days=serializer.validated_data["expires_in_days"],
        )

        log_audit(
            request.user,
            "ADMIN_INVITED",
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            metadata={
                "invitation_id": str(invitation.id),
                "email": invitation.email,
                "roles": [r.name for r in roles],
            },
        )

        return Response(
            AdminInvitationReadSerializer(invitation).data,
            status=201,
        )


class AdminMeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="admin_me",
        responses={200: dict},
    )
    def get(self, request):
        roles = RoleService.get_user_roles(request.user)
        permissions = PermissionService.get_user_permissions(request.user)

        return Response(
            {
                "id": request.user.id,
                "email": request.user.email,
                "first_name": request.user.first_name,
                "last_name": request.user.last_name,
                "roles": [role.name for role in roles],
                "permissions": permissions,
            }
        )

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import AuditLog, User
from accounts.services.audit_service import AuditService
from authentication.models import AdminInvitation, Permission, Role, UserRole
from authentication.services.invitation_service import InvitationService
from authentication.services.permission_service import PermissionService
from authentication.services.role_service import RoleService, SUPER_ADMIN_ROLE_NAME
from authentication.services.session_service import SessionService
from platform_admin.serializers import (
    AdminAuditLogSerializer,
    AdminDashboardSummarySerializer,
    AdminInvitationCreateSerializer,
    AdminInvitationReadSerializer,
    AdminPermissionSerializer,
    AdminRoleAssignmentSerializer,
    AdminRoleSerializer,
    AdminUserListSerializer,
    AdminUserRoleUpdateSerializer,
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


class AdminUserListView(generics.ListAPIView):
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

        serializer = AdminUserRoleUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        previous_roles = set(
            UserRole.objects.filter(user=user, is_active=True).values_list("role_id", flat=True)
        )

        role_ids = set(serializer.validated_data.get("role_ids", previous_roles))

        # Check if disabling the user would leave zero active super admins
        is_active = serializer.validated_data.get("is_active", user.is_active)
        if not is_active and user.is_active:
            super_admin_role = Role.objects.filter(name=SUPER_ADMIN_ROLE_NAME).first()
            if super_admin_role and str(super_admin_role.id) in {str(r) for r in previous_roles}:
                if RoleService.count_active_super_admins() <= 1:
                    return Response(
                        {"detail": "Cannot disable the final active Super Admin."},
                        status=400,
                    )

        if "is_active" in serializer.validated_data and is_active != user.is_active:
            user.is_active = is_active
            user.save(update_fields=["is_active", "updated_at"])
            if not is_active:
                SessionService.invalidate_user_sessions(user)
                AuditService.record(
                    request.user,
                    "ADMIN_DISABLED",
                    resource_type="user",
                    resource_id=user.id,
                    metadata={"target_user_id": str(user.id), "email": user.email},
                    request=request,
                )
            else:
                AuditService.record(
                    request.user,
                    "ADMIN_ENABLED",
                    resource_type="user",
                    resource_id=user.id,
                    metadata={"target_user_id": str(user.id), "email": user.email},
                    request=request,
                )

        current_roles = set(
            UserRole.objects.filter(user=user, is_active=True).values_list("role_id", flat=True)
        )
        roles_to_add = role_ids - current_roles
        roles_to_remove = current_roles - role_ids

        for role_id in roles_to_add:
            role = Role.objects.filter(id=role_id).first()
            if role:
                RoleService.assign_role(user, role, assigned_by=request.user)
                AuditService.record(
                    request.user,
                    "ROLE_ASSIGNED",
                    resource_type="role",
                    resource_id=role.id,
                    metadata={"target_user_id": str(user.id), "role": role.name},
                    request=request,
                )

        for role_id in roles_to_remove:
            role = Role.objects.filter(id=role_id).first()
            if role:
                try:
                    RoleService.remove_role(user, role, revoked_by=request.user)
                except DjangoValidationError as exc:
                    return Response(
                        {"detail": " ".join(exc.messages)},
                        status=400,
                    )
                AuditService.record(
                    request.user,
                    "ROLE_REVOKED",
                    resource_type="role",
                    resource_id=role.id,
                    metadata={"target_user_id": str(user.id), "role": role.name},
                    request=request,
                )

        if roles_to_add or roles_to_remove:
            SessionService.invalidate_user_sessions(user)
            AuditService.record(
                request.user,
                "USER_ROLES_UPDATED",
                resource_type="user",
                resource_id=user.id,
                metadata={
                    "target_user_id": str(user.id),
                    "added_roles": [str(r) for r in roles_to_add],
                    "removed_roles": [str(r) for r in roles_to_remove],
                },
                request=request,
            )

        return Response(self.serializer_class(user).data)


class AdminUserRoleListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AdminRoleSerializer

    @extend_schema(
        operation_id="admin_user_roles_list",
        responses={200: AdminRoleSerializer(many=True), 403: None, 404: None},
    )
    def get(self, request, user_id):
        if not PermissionService.has_permission(request.user, "admin.users.view"):
            return Response(
                {"detail": "You do not have permission to view user roles."},
                status=403,
            )

        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response(
                {"detail": "User not found."},
                status=404,
            )

        user_roles = UserRole.objects.filter(
            user=user,
            is_active=True,
        ).select_related("role", "assigned_by")

        data = [
            {
                "id": user_role.role.id,
                "name": user_role.role.name,
                "display_name": user_role.role.display_name,
                "description": user_role.role.description,
                "dashboard_url": user_role.role.dashboard_url,
                "is_system": user_role.role.is_system,
                "assigned_by": user_role.assigned_by.email if user_role.assigned_by else None,
                "assigned_at": user_role.assigned_at.isoformat() if user_role.assigned_at else None,
                "expires_at": user_role.expires_at.isoformat() if user_role.expires_at else None,
            }
            for user_role in user_roles
        ]

        return Response(data)


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

        SessionService.invalidate_user_sessions(user)

        AuditService.record(
            request.user,
            "ROLE_ASSIGNED",
            resource_type="role",
            resource_id=role.id,
            metadata={"target_user_id": str(user.id), "role": role.name},
            request=request,
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

        try:
            user_role = RoleService.remove_role(user, role, revoked_by=request.user)
        except DjangoValidationError as exc:
            return Response(
                {"detail": " ".join(exc.messages)},
                status=400,
            )

        if not user_role:
            return Response(
                {"detail": "Role is not assigned to this user."},
                status=404,
            )

        SessionService.invalidate_user_sessions(user)

        AuditService.record(
            request.user,
            "ROLE_REVOKED",
            resource_type="role",
            resource_id=role.id,
            metadata={"target_user_id": str(user.id), "role": role.name},
            request=request,
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

        try:
            invitation = InvitationService.create_invitation(
                email=serializer.validated_data["email"],
                roles=list(roles),
                invited_by=request.user,
                expires_in_days=serializer.validated_data["expires_in_days"],
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=400,
            )

        AuditService.record(
            request.user,
            "ADMIN_INVITED",
            resource_type="invitation",
            resource_id=invitation.id,
            metadata={
                "email": invitation.email,
                "roles": [r.name for r in roles],
            },
            request=request,
        )

        return Response(
            AdminInvitationReadSerializer(invitation).data,
            status=201,
        )


class AdminInvitationRevokeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AdminInvitationReadSerializer

    @extend_schema(
        operation_id="admin_invitation_revoke",
        responses={200: AdminInvitationReadSerializer, 400: None, 403: None, 404: None},
    )
    def post(self, request, invitation_id):
        if not PermissionService.has_permission(request.user, "admin.users.manage"):
            return Response(
                {"detail": "You do not have permission to manage invitations."},
                status=403,
            )

        invitation = AdminInvitation.objects.filter(id=invitation_id).first()
        if not invitation:
            return Response(
                {"detail": "Invitation not found."},
                status=404,
            )

        try:
            InvitationService.revoke_invitation(invitation, request.user)
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=400,
            )

        AuditService.record(
            request.user,
            "ADMIN_INVITED",
            resource_type="invitation",
            resource_id=invitation.id,
            metadata={
                "email": invitation.email,
                "revoked": True,
            },
            request=request,
        )

        return Response(AdminInvitationReadSerializer(invitation).data)


class AdminAuditLogListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AdminAuditLogSerializer

    @extend_schema(
        operation_id="admin_audit_list",
        responses={200: AdminAuditLogSerializer(many=True)},
    )
    def get(self, request):
        if not PermissionService.has_permission(request.user, "admin.audit.view"):
            return Response(
                {"detail": "You do not have permission to view audit logs."},
                status=403,
            )

        queryset = AuditLog.objects.select_related("user").order_by("-timestamp")

        action = request.query_params.get("action")
        if action:
            queryset = queryset.filter(action=action)

        user_id = request.query_params.get("user_id")
        if user_id:
            queryset = queryset.filter(user_id=user_id)

        resource_type = request.query_params.get("resource_type")
        if resource_type:
            queryset = queryset.filter(resource_type=resource_type)

        start_date = request.query_params.get("start_date")
        if start_date:
            from django.utils.dateparse import parse_datetime

            parsed = parse_datetime(start_date)
            if parsed:
                queryset = queryset.filter(timestamp__gte=parsed)

        end_date = request.query_params.get("end_date")
        if end_date:
            from django.utils.dateparse import parse_datetime

            parsed = parse_datetime(end_date)
            if parsed:
                queryset = queryset.filter(timestamp__lte=parsed)

        queryset = queryset[:200]

        serializer = self.serializer_class(queryset, many=True)
        return Response(serializer.data)


class AdminMeRolesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="admin_me_roles",
        responses={200: dict},
    )
    def get(self, request):
        roles = RoleService.get_user_roles(request.user)
        return Response(
            {
                "roles": [
                    {
                        "id": role.id,
                        "name": role.name,
                        "display_name": role.display_name,
                        "dashboard_url": role.dashboard_url,
                    }
                    for role in roles
                ]
            }
        )


class AdminMePermissionsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        operation_id="admin_me_permissions",
        responses={200: dict},
    )
    def get(self, request):
        permissions = PermissionService.get_user_permissions(request.user)
        return Response(
            {
                "permissions": permissions,
            }
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


class AdminDashboardSummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AdminDashboardSummarySerializer

    @extend_schema(
        operation_id="admin_dashboard_summary",
        responses={200: AdminDashboardSummarySerializer},
    )
    def get(self, request):
        if not PermissionService.has_permission(request.user, "admin.dashboard.view"):
            return Response(
                {"detail": "You do not have permission to view the dashboard."},
                status=403,
            )

        data: dict = {}

        if PermissionService.has_permission(request.user, "admin.users.view"):
            data["active_administrators"] = (
                UserRole.objects.filter(
                    role__is_system=True,
                    is_active=True,
                )
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
                .values("user_id")
                .distinct()
                .count()
            )

            data["role_distribution"] = (
                UserRole.objects.filter(is_active=True)
                .values("role__name")
                .annotate(count=Count("user_id"))
                .order_by("role__name")
            )

        if PermissionService.has_permission(request.user, "manage_market"):
            from markets.models import Market

            data["pending_markets"] = Market.objects.filter(status="PENDING_APPROVAL").count()
            data["published_markets"] = Market.objects.filter(status="OPEN").count()
            data["suspended_markets"] = Market.objects.filter(status="SUSPENDED").count()

        if PermissionService.has_permission(request.user, "verify_results"):
            from markets.models import Market

            data["pending_result_verification"] = (
                Market.objects.filter(provisional_result__isnull=False)
                .exclude(status__in=["RESOLVED", "VOIDED"])
                .count()
            )

        if PermissionService.has_permission(request.user, "manage_compliance"):
            from kyc.models import KYCVerification

            data["compliance_cases"] = KYCVerification.objects.filter(
                status__in=[KYCVerification.Status.PENDING, KYCVerification.Status.REVIEW]
            ).count()

        if PermissionService.has_permission(request.user, "manage_support_cases"):
            data["support_cases"] = 0  # Support cases are managed externally

        if PermissionService.has_permission(request.user, "manage_finance"):
            from markets.models import MarketReconciliationRun

            data["financial_reconciliation_status"] = MarketReconciliationRun.objects.filter(
                status="PENDING"
            ).count()

        if PermissionService.has_permission(request.user, "manage_statistics"):
            data["sports_data_issues"] = 0  # Sports data issues tracked externally

        serializer = self.serializer_class(data)
        return Response(serializer.data)

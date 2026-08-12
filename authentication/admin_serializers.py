from rest_framework import serializers

from accounts.models import User
from authentication.models import Permission, Role, UserPermission, UserRole
from clubs.models import ClubWorkspace, WorkspaceMembership


class DelegatableRoleSerializer(serializers.ModelSerializer):
    """Serializer for listing delegatable roles."""

    class Meta:
        model = Role
        fields = ["id", "name", "display_name", "description", "scope"]


class DelegatablePermissionSerializer(serializers.ModelSerializer):
    """Serializer for listing delegatable permissions."""

    class Meta:
        model = Permission
        fields = ["id", "code", "name", "description", "category", "scope"]


class SubordinateUserCreateSerializer(serializers.Serializer):
    """Serializer for creating a new subordinate user."""

    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    role_id = serializers.UUIDField()
    permission_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=[]
    )
    workspace_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=[])

    def validate_email(self, value):
        email = value.lower().strip()
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return email

    def validate_role_id(self, value):
        if not Role.objects.filter(id=value).exists():
            raise serializers.ValidationError("Role not found.")
        return value

    def validate_permission_ids(self, value):
        if value:
            count = Permission.objects.filter(id__in=value).count()
            if count != len(value):
                raise serializers.ValidationError("One or more permissions not found.")
        return value

    def validate_workspace_ids(self, value):
        if value:
            count = ClubWorkspace.objects.filter(id__in=value).count()
            if count != len(value):
                raise serializers.ValidationError("One or more workspaces not found.")
        return value


class UserLifecycleSerializer(serializers.Serializer):
    """Serializer for actions that might include a reason."""

    reason = serializers.CharField(max_length=500, required=True, allow_blank=False)


class UserPermissionAssignmentSerializer(serializers.ModelSerializer):
    """Read-only serializer for a user's direct permission assignment."""

    permission = DelegatablePermissionSerializer(read_only=True)

    class Meta:
        model = UserPermission
        fields = ["id", "permission", "granted_at"]


class UserRoleAssignmentSerializer(serializers.ModelSerializer):
    """Read-only serializer for a user's role assignment."""

    role = DelegatableRoleSerializer(read_only=True)

    class Meta:
        model = UserRole
        fields = ["id", "role", "assigned_at", "is_active"]


class UserWorkspaceMembershipSerializer(serializers.ModelSerializer):
    """Read-only serializer for a user's workspace membership."""

    workspace_name = serializers.CharField(source="workspace.club.name", read_only=True)

    class Meta:
        model = WorkspaceMembership
        fields = ["id", "workspace", "workspace_name", "role", "added_at"]

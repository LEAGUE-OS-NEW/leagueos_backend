from rest_framework import serializers

from accounts.models import User
from authentication.models import AdminInvitation, Permission, Role


class AdminInvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    expires_in_days = serializers.IntegerField(min_value=1, max_value=30, default=7)


class AdminInvitationReadSerializer(serializers.ModelSerializer):
    assigned_roles = serializers.SlugRelatedField(many=True, read_only=True, slug_field="name")
    invited_by_email = serializers.EmailField(source="invited_by.email", read_only=True)

    class Meta:
        model = AdminInvitation
        fields = [
            "id",
            "email",
            "assigned_roles",
            "invited_by_email",
            "status",
            "token_expires_at",
            "accepted_at",
            "created_at",
        ]


class AdminUserListSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "is_active",
            "is_verified",
            "is_superuser",
            "roles",
            "permissions",
            "created_at",
            "updated_at",
        ]

    def get_roles(self, obj) -> list[str]:
        return list(obj.user_roles.values_list("role__name", flat=True))

    def get_permissions(self, obj) -> list[str]:
        from authentication.services.permission_service import PermissionService

        return PermissionService.get_user_permissions(obj)


class AdminRoleSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = [
            "id",
            "name",
            "display_name",
            "description",
            "dashboard_url",
            "is_system",
            "permissions",
            "created_at",
            "updated_at",
        ]

    def get_permissions(self, obj) -> list[str]:
        return list(obj.role_permissions.values_list("permission__name", flat=True))


class AdminPermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = [
            "id",
            "name",
            "resource",
            "action",
            "description",
            "created_at",
            "updated_at",
        ]


class AdminRoleAssignmentSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    role_id = serializers.UUIDField()
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class AdminRoleRevokeSerializer(serializers.Serializer):
    role_id = serializers.UUIDField()


class AdminUserRoleUpdateSerializer(serializers.Serializer):
    role_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=True)

from django.contrib.auth import get_user_model
from rest_framework import serializers

from authentication.models import LoginHistory, Permission, Role, UserSession
from authentication.services.permission_service import PermissionService
from authentication.services.role_service import RoleService

User = get_user_model()


def build_response(success: bool, message: str, data=None):
    payload = {"success": success, "message": message}
    if data is not None:
        payload["data"] = data
    return payload


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "name", "resource", "action", "description"]
        read_only_fields = fields


class RoleSerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True)

    class Meta:
        model = Role
        fields = ["id", "name", "display_name", "description", "dashboard_url", "is_system"]
        read_only_fields = fields


class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSession
        fields = [
            "id",
            "ip_address",
            "device",
            "browser",
            "operating_system",
            "is_active",
            "login_time",
            "last_activity",
        ]
        read_only_fields = fields


class LoginHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = LoginHistory
        fields = ["id", "login_time", "logout_time", "ip_address", "successful", "failure_reason"]
        read_only_fields = fields


class ProfileSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "is_verified",
            "is_active",
            "roles",
            "permissions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_roles(self, user):
        roles = RoleService.get_user_roles(user)
        return RoleSerializer(roles, many=True).data

    def get_permissions(self, user):
        return PermissionService.get_user_permissions(user)

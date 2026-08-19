import re

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from authentication.models import LoginHistory, UserSession

User = get_user_model()


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(required=False, allow_blank=False)
    email = serializers.CharField(required=False, allow_blank=False)
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        identifier = attrs.get("identifier") or attrs.get("email")
        if not identifier:
            raise serializers.ValidationError({"identifier": "Email or username is required."})
        attrs["identifier"] = identifier.strip()
        return attrs

    def validate_email(self, value):
        return value.lower().strip()


class DashboardEntitlementSerializer(serializers.Serializer):
    id = serializers.CharField()
    dashboard = serializers.CharField()
    route = serializers.CharField()
    scope_type = serializers.CharField(allow_null=True)
    scope_id = serializers.CharField(allow_null=True)
    workspace_role = serializers.CharField(allow_null=True)
    permissions = serializers.ListField(child=serializers.CharField())


class DashboardAccessSerializer(serializers.Serializer):
    version = serializers.IntegerField()
    default_entitlement_id = serializers.CharField(allow_null=True)
    entitlements = DashboardEntitlementSerializer(many=True)


class OnboardingAuthContextSerializer(serializers.Serializer):
    completed = serializers.BooleanField()
    current_step = serializers.CharField(allow_null=True)


class AuthUserContextSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    username = serializers.CharField()
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    phone_number = serializers.CharField(allow_null=True)
    is_verified = serializers.BooleanField()
    roles = serializers.ListField(child=serializers.CharField())
    permissions = serializers.ListField(child=serializers.CharField())
    dashboard_access = DashboardAccessSerializer()
    onboarding = OnboardingAuthContextSerializer()


class AuthTokenDataSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = AuthUserContextSerializer()


class AuthTokenResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = AuthTokenDataSerializer()


class MeDataSerializer(serializers.Serializer):
    user = AuthUserContextSerializer()


class MeResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = MeDataSerializer()


class MessageResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class UserProfileSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "phone_number",
            "is_verified",
            "roles",
            "permissions",
        ]

    def get_roles(self, obj) -> list[str]:
        return list(obj.user_roles.values_list("role__name", flat=True))

    def get_permissions(self, obj) -> list[str]:
        role_ids = obj.user_roles.values_list("role_id", flat=True)
        from authentication.models import RolePermission

        return list(
            RolePermission.objects.filter(role_id__in=role_ids).values_list(
                "permission__name", flat=True
            )
        )


class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSession
        fields = [
            "id",
            "ip_address",
            "user_agent",
            "device",
            "browser",
            "operating_system",
            "is_active",
            "login_time",
            "last_activity",
        ]


class LoginHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = LoginHistory
        fields = ["id", "login_time", "ip_address", "user_agent", "successful", "failure_reason"]


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower().strip()


class PasswordResetVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6, min_length=6)

    def validate_email(self, value):
        return value.lower().strip()


class PasswordResetConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6, min_length=6)
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate_email(self, value):
        return value.lower().strip()

    def validate_password(self, value):
        if len(value) < 8:
            raise serializers.ValidationError("Password must be at least 8 characters long.")
        if not re.search(r"[A-Z]", value):
            raise serializers.ValidationError(
                "Password must contain at least one uppercase letter."
            )
        if not re.search(r"[a-z]", value):
            raise serializers.ValidationError(
                "Password must contain at least one lowercase letter."
            )
        if not re.search(r"\d", value):
            raise serializers.ValidationError("Password must contain at least one number.")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=\[\]\\/]", value):
            raise serializers.ValidationError(
                "Password must contain at least one special character."
            )
        validate_password(value)
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs


class EmptySerializer(serializers.Serializer):
    pass


class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for the password change endpoint."""

    current_password = serializers.CharField(
        style={"input_type": "password"}, required=True, write_only=True
    )
    new_password = serializers.CharField(
        style={"input_type": "password"}, required=True, write_only=True
    )
    confirm_new_password = serializers.CharField(
        style={"input_type": "password"}, required=True, write_only=True
    )

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_new_password"]:
            raise serializers.ValidationError({"confirm_new_password": "New passwords must match."})
        return attrs

    def validate_new_password(self, value):
        """
        Validate password strength using Django's built-in validators.
        """
        validate_password(value)
        return value

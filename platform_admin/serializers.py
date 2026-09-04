from rest_framework import serializers

from accounts.models import AuditLog, User
from authentication.models import AdminInvitation, Permission, Role
from platform_admin.models import PlatformMembershipPlan, PlatformMembershipSubscription


class AdminInvitationCreateSerializer(serializers.Serializer):
    login_email = serializers.EmailField()
    notify_email = serializers.EmailField()
    role_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    expires_in_days = serializers.IntegerField(min_value=1, max_value=30, default=7)


class AdminInvitationAcceptSerializer(serializers.Serializer):
    token = serializers.CharField()


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
    user_id = serializers.UUIDField(required=False)
    role_id = serializers.UUIDField()
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class AdminRoleRevokeSerializer(serializers.Serializer):
    role_id = serializers.UUIDField()


class AdminUserRoleUpdateSerializer(serializers.Serializer):
    role_ids = serializers.ListField(
        child=serializers.UUIDField(), allow_empty=True, required=False
    )
    is_active = serializers.BooleanField(required=False)
    account_status = serializers.ChoiceField(choices=User.AccountStatus.choices, required=False)


class AdminAuditLogSerializer(serializers.ModelSerializer):
    actor_email = serializers.EmailField(source="user.email", read_only=True, allow_null=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor_email",
            "action",
            "resource_type",
            "resource_id",
            "request_id",
            "ip_address",
            "user_agent",
            "metadata",
            "timestamp",
        ]


class AdminDashboardSummarySerializer(serializers.Serializer):
    active_administrators = serializers.IntegerField(required=False)
    role_distribution = serializers.ListField(required=False)
    pending_markets = serializers.IntegerField(required=False)
    published_markets = serializers.IntegerField(required=False)
    suspended_markets = serializers.IntegerField(required=False)
    pending_result_verification = serializers.IntegerField(required=False)
    compliance_cases = serializers.IntegerField(required=False)
    support_cases = serializers.IntegerField(required=False)
    financial_reconciliation_status = serializers.IntegerField(required=False)
    sports_data_issues = serializers.IntegerField(required=False)


class PlatformMembershipPlanSerializer(serializers.ModelSerializer):
    subscriber_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = PlatformMembershipPlan
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "price",
            "currency",
            "billing_period",
            "benefits",
            "status",
            "subscriber_count",
            "published_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "slug",
            "subscriber_count",
            "published_at",
            "created_at",
            "updated_at",
        ]

    def validate_benefits(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Benefits must be a list.")
        return [str(item).strip() for item in value if str(item).strip()]


class PlatformMembershipSubscriptionSerializer(serializers.ModelSerializer):
    fan_name = serializers.SerializerMethodField()
    fan_email = serializers.EmailField(source="user.email", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    plan_description = serializers.CharField(source="plan.description", read_only=True)
    plan_benefits = serializers.JSONField(source="plan.benefits", read_only=True)
    billing_period = serializers.CharField(source="plan.billing_period", read_only=True)

    class Meta:
        model = PlatformMembershipSubscription
        fields = [
            "id",
            "fan_name",
            "fan_email",
            "plan",
            "plan_name",
            "plan_description",
            "plan_benefits",
            "billing_period",
            "status",
            "subscribed_at",
            "renews_at",
            "amount_paid",
            "currency",
        ]
        read_only_fields = fields

    def get_fan_name(self, obj) -> str:
        full_name = f"{obj.user.first_name} {obj.user.last_name}".strip()
        return full_name or obj.user.email


class PlatformMembershipSubscribeSerializer(serializers.Serializer):
    plan_id = serializers.UUIDField()
    idempotency_key = serializers.UUIDField(required=False)


class PlatformMembershipStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=PlatformMembershipPlan.Status.choices)

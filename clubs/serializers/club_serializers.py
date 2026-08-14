"""Serializers for club management."""

from __future__ import annotations

from rest_framework import serializers

from clubs.models import (
    ClubAuditLog,
    ClubMedia,
    ClubNews,
    ClubProfileVersion,
    ClubWorkspace,
    MembershipPlan,
    MerchandiseProduct,
    ProductCategory,
    StaffInvitation,
    StoreOrder,
    TicketProduct,
)
from profiles.models import Club


class ClubSerializer(serializers.ModelSerializer):
    class Meta:
        model = Club
        fields = ["id", "name", "slug", "sport", "competition", "founded", "is_active"]


class ClubWorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClubWorkspace
        fields = [
            "id",
            "user",
            "club",
            "role",
            "permissions",
            "is_active",
            "invited_at",
            "accepted_at",
        ]
        read_only_fields = ["id", "club", "invited_at", "accepted_at"]

    def validate(self, attrs):
        user = attrs.get("user")
        club = self.context.get("club")

        if not user:
            raise serializers.ValidationError({"user": "A user is required."})

        if ClubWorkspace.objects.filter(user=user, club=club).exists():
            raise serializers.ValidationError(
                {"user": "This user already has a workspace for this club."}
            )

        return attrs


class ClubProfileVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClubProfileVersion
        fields = [
            "id",
            "club",
            "version",
            "status",
            "display_name",
            "tagline",
            "description",
            "founded",
            "website",
            "email",
            "phone",
            "address",
            "city",
            "country",
            "logo",
            "cover_image",
            "stadium",
            "capacity",
            "coach",
            "league",
            "social_links",
            "published_at",
            "published_by",
            "scheduled_at",
            "created_by",
        ]
        read_only_fields = ["id", "club", "version", "published_at", "published_by", "created_by"]


class ClubMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClubMedia
        fields = [
            "id",
            "club",
            "media_type",
            "title",
            "description",
            "file",
            "url",
            "thumbnail",
            "file_size",
            "mime_type",
            "status",
            "is_featured",
            "display_order",
            "uploaded_by",
            "published_at",
            "published_by",
            "scheduled_at",
        ]
        read_only_fields = [
            "id",
            "club",
            "file_size",
            "uploaded_by",
            "published_at",
            "published_by",
        ]


class ClubNewsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClubNews
        fields = [
            "id",
            "club",
            "title",
            "slug",
            "summary",
            "body",
            "category",
            "sport",
            "cover_image",
            "status",
            "is_featured",
            "is_verified",
            "published_at",
            "published_by",
            "scheduled_at",
            "created_by",
            "source_name",
            "source_reference",
        ]
        read_only_fields = ["id", "slug", "published_at", "published_by", "created_by"]


class MembershipPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = MembershipPlan
        fields = [
            "id",
            "club",
            "name",
            "slug",
            "description",
            "price",
            "currency",
            "billing_period",
            "duration_days",
            "status",
            "is_featured",
            "max_members",
            "benefits",
            "metadata",
            "published_at",
            "published_by",
            "created_by",
        ]
        read_only_fields = ["id", "club", "slug", "published_at", "published_by", "created_by"]


class TicketProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketProduct
        fields = [
            "id",
            "club",
            "name",
            "slug",
            "description",
            "price",
            "currency",
            "event",
            "venue",
            "sales_start",
            "sales_end",
            "capacity",
            "sold",
            "status",
            "is_refundable",
            "metadata",
            "published_at",
            "published_by",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "club",
            "slug",
            "sold",
            "published_at",
            "published_by",
            "created_by",
        ]


class MerchandiseProductSerializer(serializers.ModelSerializer):
    available_stock = serializers.IntegerField(read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = MerchandiseProduct
        fields = [
            "id",
            "club",
            "category",
            "name",
            "slug",
            "description",
            "price",
            "currency",
            "sku",
            "stock",
            "reserved_stock",
            "available_stock",
            "is_low_stock",
            "low_stock_threshold",
            "images",
            "metadata",
            "status",
            "is_featured",
            "published_at",
            "published_by",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "club",
            "slug",
            "available_stock",
            "is_low_stock",
            "published_at",
            "published_by",
            "created_by",
        ]


class StoreOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoreOrder
        fields = [
            "id",
            "user",
            "club",
            "status",
            "total_amount",
            "currency",
            "shipping_address",
            "metadata",
            "fulfilled_at",
            "cancelled_at",
        ]
        read_only_fields = ["id", "total_amount", "fulfilled_at", "cancelled_at"]


class ClubAuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClubAuditLog
        fields = [
            "id",
            "club",
            "user",
            "action",
            "entity_type",
            "entity_id",
            "ip_address",
            "user_agent",
            "metadata",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class StaffInvitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffInvitation
        fields = [
            "id",
            "club",
            "email",
            "role",
            "permissions",
            "token",
            "status",
            "expires_at",
            "invited_by",
            "accepted_by",
            "accepted_at",
        ]
        read_only_fields = [
            "id",
            "club",
            "token",
            "status",
            "expires_at",
            "invited_by",
            "accepted_by",
            "accepted_at",
        ]


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ["id", "club", "name", "slug", "description", "is_active", "display_order"]
        read_only_fields = ["id", "slug"]

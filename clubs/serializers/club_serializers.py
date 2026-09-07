"""Serializers for club management."""

from __future__ import annotations

from rest_framework import serializers

from clubs.models import (
    ClubAuditLog,
    ClubMedia,
    ClubNews,
    ClubPlayer,
    ClubProfileVersion,
    ClubWorkspace,
    MembershipPlan,
    MerchandiseProduct,
    ProductCategory,
    StaffInvitation,
    StoreOrder,
    StoreOrderItem,
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
    club_slug = serializers.CharField(source="club.slug", read_only=True)
    club_name = serializers.CharField(source="club.name", read_only=True)

    class Meta:
        model = MerchandiseProduct
        fields = [
            "id",
            "club",
            "club_slug",
            "club_name",
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

    def validate_sku(self, value):
        normalized = value.strip().upper()
        if not normalized:
            return ""
        club = self.context.get("club") or getattr(self.instance, "club", None)
        duplicate = MerchandiseProduct.objects.filter(club=club, sku__iexact=normalized)
        if self.instance:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if club and duplicate.exists():
            raise serializers.ValidationError("This SKU already exists for the club.")
        return normalized


class StoreOrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = StoreOrderItem
        fields = [
            "id",
            "product",
            "product_name",
            "product_sku",
            "quantity",
            "unit_price",
            "total_price",
        ]
        read_only_fields = fields


class ClubPlayerSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClubPlayer
        fields = [
            "id",
            "club",
            "name",
            "position",
            "nationality",
            "status",
            "contract_end",
            "market_value",
            "jersey_number",
            "photo",
        ]
        read_only_fields = ["id", "club"]


class StoreOrderSerializer(serializers.ModelSerializer):
    items = StoreOrderItemSerializer(many=True, read_only=True)
    status_history = serializers.SerializerMethodField()
    user_email = serializers.EmailField(source="user.email", read_only=True)
    club_name = serializers.CharField(source="club.name", read_only=True)
    payment_reference = serializers.CharField(
        source="payment_transaction.reference", read_only=True
    )
    refund_reference = serializers.CharField(source="refund_transaction.reference", read_only=True)
    payment = serializers.SerializerMethodField()
    refund = serializers.SerializerMethodField()

    def get_status_history(self, obj):
        return [
            {
                "previous_status": row.previous_status,
                "new_status": row.new_status,
                "changed_by": str(row.changed_by_id),
                "changed_by_email": row.changed_by.email,
                "note": row.note,
                "created_at": row.created_at,
            }
            for row in obj.status_history.all()
        ]

    @staticmethod
    def _transaction(value):
        if not value:
            return None
        return {
            "id": str(value.id),
            "reference": value.reference,
            "provider_reference": value.provider_reference,
            "amount": str(value.amount),
            "currency": value.currency,
            "status": value.status,
            "created_at": value.created_at,
            "completed_at": value.completed_at,
            "ledger_entries": [str(entry.id) for entry in value.ledger_entries.all()],
        }

    def get_payment(self, obj):
        return self._transaction(obj.payment_transaction)

    def get_refund(self, obj):
        return self._transaction(obj.refund_transaction)

    class Meta:
        model = StoreOrder
        fields = [
            "id",
            "user",
            "user_email",
            "club",
            "club_name",
            "status",
            "total_amount",
            "currency",
            "shipping_address",
            "metadata",
            "payment_transaction",
            "payment_reference",
            "payment",
            "refund_transaction",
            "refund_reference",
            "refund",
            "checkout_group",
            "delivery_reference",
            "status_history",
            "items",
            "fulfilled_at",
            "cancelled_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class StoreCheckoutItemSerializer(serializers.Serializer):
    product = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)
    size = serializers.CharField(required=False, allow_blank=True)


class StoreCheckoutSerializer(serializers.Serializer):
    idempotency_key = serializers.UUIDField()
    items = StoreCheckoutItemSerializer(many=True, allow_empty=False)
    shipping_address = serializers.JSONField(required=False)
    metadata = serializers.JSONField(required=False)


class StoreFulfilmentSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["PROCESSING", "READY_FOR_COLLECTION", "SHIPPED", "DELIVERED", "CANCELLED"]
    )
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)
    delivery_reference = serializers.CharField(max_length=255, required=False, allow_blank=True)


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


class StaffInvitationAcceptSerializer(serializers.Serializer):
    token = serializers.CharField()


class ClubAdminInviteSerializer(serializers.Serializer):
    """The LeagueOS login identity is distinct from where the invite is
    actually delivered — a brand-new club admin has no working inbox at
    their assigned login address yet."""

    login_email = serializers.EmailField()
    notify_email = serializers.EmailField()


class ClubLogoUploadSerializer(serializers.Serializer):
    """Request body for ClubLogoView.post."""

    logo = serializers.ImageField(max_length=None, use_url=False, required=True)


class ClubLogoResponseSerializer(serializers.Serializer):
    """Response body for ClubLogoView.post."""

    success = serializers.BooleanField()
    logo_url = serializers.CharField()
    updated_at = serializers.CharField()


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ["id", "club", "name", "slug", "description", "is_active", "display_order"]
        read_only_fields = ["id", "slug"]

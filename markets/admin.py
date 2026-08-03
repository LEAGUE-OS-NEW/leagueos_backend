from django.contrib import admin

from markets.models import (
    Market,
    MarketCategory,
    MarketCloseCleanup,
    MarketCloseOrderCancellation,
    MarketOutcome,
    MarketPositionSettlement,
    MarketPositionVoidRefund,
    MarketSettlement,
    MarketStatusTransition,
    MarketTemplate,
    MarketVoidOrderCancellation,
    MarketVoidRefund,
)


@admin.register(MarketCategory)
class MarketCategoryAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "display_order",
        "is_active",
    )
    list_filter = ("is_active",)
    search_fields = (
        "name",
        "description",
    )
    prepopulated_fields = {
        "slug": ("name",),
    }


@admin.register(MarketTemplate)
class MarketTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "category",
        "sport",
        "scope_type",
        "is_active",
    )
    list_filter = (
        "scope_type",
        "sport",
        "category",
        "is_active",
    )
    search_fields = (
        "name",
        "code",
        "question_template",
    )
    prepopulated_fields = {
        "slug": ("name",),
    }


class MarketOutcomeInline(admin.TabularInline):
    model = MarketOutcome
    extra = 0
    max_num = 2


@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    list_display = (
        "question",
        "sport",
        "category",
        "scope_type",
        "status",
        "closes_at",
        "is_featured",
    )
    list_filter = (
        "sport",
        "category",
        "scope_type",
        "status",
        "is_featured",
    )
    search_fields = (
        "question",
        "custom_subject",
        "sporting_event__name",
        "competition__name",
        "participant__name",
    )
    autocomplete_fields = (
        "sport",
        "category",
        "template",
        "sporting_event",
        "competition",
        "participant",
        "created_by",
        "approved_by",
        "resolved_by",
        "winning_outcome",
    )
    inlines = (MarketOutcomeInline,)


@admin.register(MarketOutcome)
class MarketOutcomeAdmin(admin.ModelAdmin):
    list_display = (
        "market",
        "side",
        "position",
        "label",
    )
    list_filter = ("side",)
    search_fields = (
        "market__question",
        "label",
    )
    autocomplete_fields = ("market",)


@admin.register(MarketStatusTransition)
class MarketStatusTransitionAdmin(admin.ModelAdmin):
    list_display = (
        "market",
        "action",
        "from_status",
        "to_status",
        "actor_email",
        "created_at",
    )
    list_filter = (
        "action",
        "from_status",
        "to_status",
    )
    search_fields = (
        "market__question",
        "actor_email",
        "notes",
    )
    readonly_fields = (
        "id",
        "market",
        "action",
        "from_status",
        "to_status",
        "actor",
        "actor_email",
        "notes",
        "metadata",
        "created_at",
        "updated_at",
    )

    def has_add_permission(
        self,
        request,
    ) -> bool:
        return False

    def has_change_permission(
        self,
        request,
        obj=None,
    ) -> bool:
        return False

    def has_delete_permission(
        self,
        request,
        obj=None,
    ) -> bool:
        return False


class ImmutableSettlementAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MarketSettlement)
class MarketSettlementAdmin(ImmutableSettlementAdmin):
    list_display = (
        "market",
        "winning_outcome",
        "settlement_currency",
        "total_position_count",
        "total_payout_amount",
        "executed_by",
        "executed_at",
    )
    list_filter = ("settlement_currency", "executed_at")
    search_fields = ("market__question",)


@admin.register(MarketPositionSettlement)
class MarketPositionSettlementAdmin(ImmutableSettlementAdmin):
    list_display = (
        "market_settlement",
        "market_position",
        "participant",
        "outcome",
        "was_winner",
        "settled_quantity",
        "payout_amount",
        "realized_pnl_delta",
    )
    list_filter = ("was_winner", "created_at")
    search_fields = ("market_settlement__market__question",)


@admin.register(MarketVoidRefund)
class MarketVoidRefundAdmin(ImmutableSettlementAdmin):
    list_display = (
        "market",
        "refund_currency",
        "total_cancelled_order_count",
        "refunded_position_count",
        "total_position_refund_amount",
        "executed_by",
        "executed_at",
    )
    list_filter = ("refund_currency", "executed_at")
    search_fields = ("market__question",)


@admin.register(MarketVoidOrderCancellation)
class MarketVoidOrderCancellationAdmin(ImmutableSettlementAdmin):
    list_display = (
        "market_void_refund",
        "market_order",
        "order_side",
        "remaining_quantity_cancelled",
        "released_wallet_reservation_amount",
        "released_position_reservation_quantity",
    )
    list_filter = ("order_side", "created_at")
    search_fields = ("market_void_refund__market__question",)


@admin.register(MarketCloseCleanup)
class MarketCloseCleanupAdmin(ImmutableSettlementAdmin):
    list_display = (
        "market",
        "total_cancelled_order_count",
        "cancelled_buy_order_count",
        "cancelled_sell_order_count",
        "executed_by",
        "executed_at",
    )
    list_filter = ("executed_at",)
    search_fields = ("market__question",)


@admin.register(MarketCloseOrderCancellation)
class MarketCloseOrderCancellationAdmin(ImmutableSettlementAdmin):
    list_display = (
        "market_close_cleanup",
        "market_order",
        "order_side",
        "remaining_quantity_cancelled",
        "released_wallet_reservation_amount",
        "released_position_reservation_quantity",
    )
    list_filter = ("order_side", "created_at")
    search_fields = ("market_close_cleanup__market__question",)


@admin.register(MarketPositionVoidRefund)
class MarketPositionVoidRefundAdmin(ImmutableSettlementAdmin):
    list_display = (
        "market_void_refund",
        "market_position",
        "participant",
        "outcome",
        "refunded_quantity",
        "refund_amount",
    )
    list_filter = ("created_at",)
    search_fields = ("market_void_refund__market__question",)

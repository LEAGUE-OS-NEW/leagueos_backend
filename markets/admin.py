from django.contrib import admin

from markets.models import (
    Market,
    MarketCategory,
    MarketOutcome,
    MarketStatusTransition,
    MarketTemplate,
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

"""Serializers for the dashboard module."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from rest_framework import serializers

from dashboard.models import (
    DashboardAnalytics,
    DashboardModule,
    DashboardUserPreference,
    DashboardWidget,
    NavigationMenu,
)

User = get_user_model()


# =============================================================================
# Configuration Serializers
# =============================================================================


class DashboardModuleSerializer(serializers.ModelSerializer):
    """Serializer for dashboard modules."""

    class Meta:
        model = DashboardModule
        fields = [
            "id",
            "code",
            "name",
            "description",
            "display_order",
            "icon",
            "route",
            "enabled",
            "cache_timeout",
            "is_active",
        ]
        read_only_fields = fields


class DashboardWidgetSerializer(serializers.ModelSerializer):
    """Serializer for dashboard widgets."""

    module_code = serializers.CharField(source="module.code", read_only=True)
    module_name = serializers.CharField(source="module.name", read_only=True)

    class Meta:
        model = DashboardWidget
        fields = [
            "id",
            "module",
            "module_code",
            "module_name",
            "code",
            "title",
            "description",
            "display_order",
            "permission_required",
            "cache_timeout",
            "is_active",
        ]
        read_only_fields = fields


class NavigationMenuSerializer(serializers.ModelSerializer):
    """Serializer for navigation menu items."""

    children = serializers.SerializerMethodField()

    class Meta:
        model = NavigationMenu
        fields = [
            "id",
            "name",
            "route",
            "icon",
            "parent",
            "display_order",
            "permission_required",
            "is_active",
            "children",
        ]
        read_only_fields = fields

    def get_children(self, obj: NavigationMenu) -> list[dict[str, Any]]:
        """Recursively serialize child menu items."""
        if obj.children.filter(is_active=True).exists():
            return NavigationMenuSerializer(obj.children.filter(is_active=True), many=True).data
        return []


# =============================================================================
# Preference Serializers
# =============================================================================


class DashboardSerializer(serializers.Serializer):
    """Serializer for the main dashboard response."""

    user_summary = serializers.DictField()
    navigation = serializers.ListField()
    widgets = serializers.ListField()
    modules = serializers.DictField()
    module_metadata = serializers.DictField()
    preferences = serializers.DictField()
    recommendations = serializers.ListField()


class DashboardUserPreferenceSerializer(serializers.ModelSerializer):
    """Serializer for user dashboard preferences."""

    class Meta:
        model = DashboardUserPreference
        fields = [
            "id",
            "widget_order",
            "hidden_widgets",
            "layout_config",
        ]
        read_only_fields = ["id"]


class DashboardAnalyticsSerializer(serializers.ModelSerializer):
    """Serializer for dashboard analytics events."""

    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = DashboardAnalytics
        fields = [
            "id",
            "user",
            "user_email",
            "module",
            "widget",
            "interaction_type",
            "timestamp",
            "metadata",
        ]
        read_only_fields = fields


class DashboardAnalyticsCreateSerializer(serializers.Serializer):
    """Serializer for creating analytics events."""

    module = serializers.CharField(max_length=100)
    widget = serializers.CharField(max_length=100, required=False, allow_blank=True)
    interaction_type = serializers.ChoiceField(choices=DashboardAnalytics.InteractionType.choices)
    metadata = serializers.DictField(required=False, default=dict)

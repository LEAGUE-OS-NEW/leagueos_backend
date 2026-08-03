"""Dashboard models for personalized fan dashboard and navigation aggregation.

All dashboard configuration is database-driven with no hardcoded values.
"""

import uuid

from django.conf import settings
from django.db import models


class DashboardModule(models.Model):
    """Configurable dashboard module.

    Defines available modules that can be enabled for the dashboard.
    Examples: Fixtures, Favourites, Markets, Notifications, etc.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    display_order = models.IntegerField(default=0, db_index=True)
    icon = models.CharField(max_length=100, blank=True)
    route = models.CharField(max_length=255, blank=True)
    enabled = models.BooleanField(default=True, db_index=True)
    cache_timeout = models.IntegerField(default=300, help_text="Cache timeout in seconds")
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name"]
        indexes = [
            models.Index(fields=["is_active", "enabled", "display_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class DashboardWidget(models.Model):
    """Dashboard widget definition.

    Widgets are the visual components displayed within dashboard modules.
    Each widget belongs to a module and can have permission requirements.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module = models.ForeignKey(
        DashboardModule,
        on_delete=models.CASCADE,
        related_name="widgets",
    )
    code = models.CharField(max_length=100, db_index=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    display_order = models.IntegerField(default=0, db_index=True)
    permission_required = models.CharField(
        max_length=100,
        blank=True,
        help_text="Optional permission required to view this widget",
    )
    cache_timeout = models.IntegerField(
        default=300,
        help_text="Widget-specific cache timeout in seconds",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["module__display_order", "display_order", "title"]
        indexes = [
            models.Index(fields=["module", "is_active", "display_order"]),
            models.Index(fields=["code", "is_active"]),
        ]
        unique_together = ["module", "code"]

    def __str__(self) -> str:
        return f"{self.module.code}: {self.title}"


class NavigationMenu(models.Model):
    """Hierarchical navigation menu structure.

    Supports parent-child relationships for nested navigation.
    All navigation is database-driven and permission-filtered.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    route = models.CharField(max_length=255)
    icon = models.CharField(max_length=100, blank=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )
    display_order = models.IntegerField(default=0, db_index=True)
    permission_required = models.CharField(
        max_length=100,
        blank=True,
        help_text="Optional permission required to view this menu item",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name"]
        indexes = [
            models.Index(fields=["parent", "is_active", "display_order"]),
            models.Index(fields=["is_active", "display_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.route})"


class DashboardAnalytics(models.Model):
    """Dashboard interaction analytics.

    Tracks user interactions with dashboard components for analytics
    and personalization improvements.
    """

    class InteractionType(models.TextChoices):
        VIEWED = "VIEWED", "Dashboard viewed"
        WIDGET_CLICKED = "WIDGET_CLICKED", "Widget clicked"
        NAVIGATION_CLICKED = "NAVIGATION_CLICKED", "Navigation clicked"
        MODULE_OPENED = "MODULE_OPENED", "Module opened"
        WIDGET_REORDERED = "WIDGET_REORDERED", "Widget reordered"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dashboard_analytics",
    )
    module = models.CharField(max_length=100, db_index=True)
    widget = models.CharField(max_length=100, blank=True, db_index=True)
    interaction_type = models.CharField(
        max_length=30,
        choices=InteractionType.choices,
        db_index=True,
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user", "interaction_type", "-timestamp"]),
            models.Index(fields=["user", "module", "-timestamp"]),
            models.Index(fields=["-timestamp"]),
        ]

    def __str__(self) -> str:
        return f"{self.user} - {self.interaction_type} - {self.module}"


class DashboardUserPreference(models.Model):
    """User-specific dashboard layout preferences.

    Stores user customizations like widget order, hidden widgets,
    and layout configuration.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dashboard_preferences",
    )
    widget_order = models.JSONField(
        default=list,
        blank=True,
        help_text="Ordered list of widget codes",
    )
    hidden_widgets = models.JSONField(
        default=list,
        blank=True,
        help_text="List of hidden widget codes",
    )
    layout_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Layout configuration (grid positions, sizes, etc.)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user"]),
        ]

    def __str__(self) -> str:
        return f"Dashboard preferences for {self.user}"

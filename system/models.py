"""System configuration and feature flag models."""

import uuid

from django.db import models


class FeatureFlag(models.Model):
    """Database-driven feature flag configuration."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=100, unique=True, db_index=True)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=False, db_index=True)
    rollout_percentage = models.PositiveSmallIntegerField(
        default=100,
        help_text="Percentage of users for whom this flag is active (0-100).",
    )
    environment = models.CharField(
        max_length=50,
        default="ALL",
        help_text="Environment this flag applies to (ALL, dev, staging, production).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Feature flag"
        verbose_name_plural = "Feature flags"

    def __str__(self) -> str:
        state = "enabled" if self.enabled else "disabled"
        return f"{self.code} ({state})"


class SystemConfiguration(models.Model):
    """Key-value system configuration store."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(max_length=200, unique=True, db_index=True)
    value = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True)
    is_public = models.BooleanField(
        default=False,
        help_text="Whether this configuration is exposed to clients.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]
        verbose_name = "System configuration"
        verbose_name_plural = "System configurations"

    def __str__(self) -> str:
        return self.key
"""Dashboard signals for cache invalidation.

Automatically invalidates dashboard cache when user preferences,
profile, or notifications change.
"""

from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from dashboard.services.dashboard_cache_service import DashboardCacheService

User = get_user_model()
logger = logging.getLogger(__name__)


# =============================================================================
# Profile Signals
# =============================================================================


@receiver(post_save, sender="profiles.Profile")
def invalidate_dashboard_on_profile_update(sender, instance, **kwargs):
    """Invalidate dashboard cache when user profile is updated."""
    try:
        DashboardCacheService.invalidate_all(instance.user)
        logger.debug("Dashboard cache invalidated for profile update: user=%s", instance.user_id)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to invalidate dashboard cache for profile update")


# =============================================================================
# User Preferences Signals
# =============================================================================


@receiver(post_save, sender="onboarding.UserSportPreference")
@receiver(post_save, sender="onboarding.UserCompetitionPreference")
@receiver(post_save, sender="onboarding.UserClubPreference")
def invalidate_dashboard_on_preference_change(sender, instance, **kwargs):
    """Invalidate dashboard cache when user preferences change."""
    try:
        DashboardCacheService.invalidate_all(instance.user)
        logger.debug(
            "Dashboard cache invalidated for preference change: user=%s, preference=%s",
            instance.user_id,
            sender.__name__,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to invalidate dashboard cache for preference change")


@receiver(post_delete, sender="onboarding.UserSportPreference")
@receiver(post_delete, sender="onboarding.UserCompetitionPreference")
@receiver(post_delete, sender="onboarding.UserClubPreference")
def invalidate_dashboard_on_preference_delete(sender, instance, **kwargs):
    """Invalidate dashboard cache when user preferences are deleted."""
    try:
        DashboardCacheService.invalidate_all(instance.user)
        logger.debug(
            "Dashboard cache invalidated for preference delete: user=%s, preference=%s",
            instance.user_id,
            sender.__name__,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to invalidate dashboard cache for preference delete")


# =============================================================================
# Notification Signals
# =============================================================================


# Note: Notification model doesn't exist in notifications app yet.
# Uncomment when Notification model is added.
# @receiver(post_save, sender="notifications.Notification")
# def invalidate_dashboard_on_notification(sender, instance, **kwargs):
#     """Invalidate dashboard cache when new notification is created."""
#     try:
#         if hasattr(instance, "user"):
#             DashboardCacheService.invalidate_dashboard(instance.user)
#             logger.debug(
#                 "Dashboard cache invalidated for notification: user=%s",
#                 instance.user_id,
#             )
#     except Exception:  # noqa: BLE001
#         logger.exception("Failed to invalidate dashboard cache for notification")


# =============================================================================
# Onboarding Signals
# =============================================================================


@receiver(post_save, sender="onboarding.UserOnboarding")
def invalidate_dashboard_on_onboarding_update(sender, instance, **kwargs):
    """Invalidate dashboard cache when onboarding status changes."""
    try:
        DashboardCacheService.invalidate_all(instance.user)
        logger.debug("Dashboard cache invalidated for onboarding update: user=%s", instance.user_id)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to invalidate dashboard cache for onboarding update")


# =============================================================================
# Dashboard Preference Signals
# =============================================================================


@receiver(post_save, sender="dashboard.DashboardUserPreference")
def invalidate_dashboard_on_preference_update(sender, instance, **kwargs):
    """Invalidate dashboard cache when dashboard preferences change."""
    try:
        DashboardCacheService.invalidate_all(instance.user)
        logger.debug(
            "Dashboard cache invalidated for dashboard preference update: user=%s", instance.user_id
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to invalidate dashboard cache for dashboard preference update")

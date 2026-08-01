"""Admin registrations for the Fan Onboarding & Personalization module."""

from django.contrib import admin

from onboarding.models import (
    OnboardingAnalyticsEvent,
    UserClubPreference,
    UserCompetitionPreference,
    UserOnboarding,
    UserSportPreference,
)


@admin.register(UserOnboarding)
class UserOnboardingAdmin(admin.ModelAdmin):
    """Admin for the UserOnboarding model."""

    list_display = ["user", "current_step", "completed", "completed_at", "created_at"]
    list_filter = ["current_step", "completed"]
    search_fields = ["user__email", "user__first_name", "user__last_name"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(UserSportPreference)
class UserSportPreferenceAdmin(admin.ModelAdmin):
    """Admin for the UserSportPreference model."""

    list_display = ["user", "sport", "created_at"]
    list_filter = ["sport"]
    search_fields = ["user__email", "sport__name"]
    autocomplete_fields = ["user", "sport"]


@admin.register(UserCompetitionPreference)
class UserCompetitionPreferenceAdmin(admin.ModelAdmin):
    """Admin for the UserCompetitionPreference model."""

    list_display = ["user", "competition", "created_at"]
    list_filter = ["competition"]
    search_fields = ["user__email", "competition__name"]
    autocomplete_fields = ["user", "competition"]


@admin.register(UserClubPreference)
class UserClubPreferenceAdmin(admin.ModelAdmin):
    """Admin for the UserClubPreference model."""

    list_display = ["user", "club", "created_at"]
    list_filter = ["club"]
    search_fields = ["user__email", "club__name"]
    autocomplete_fields = ["user", "club"]


@admin.register(OnboardingAnalyticsEvent)
class OnboardingAnalyticsEventAdmin(admin.ModelAdmin):
    """Admin for the OnboardingAnalyticsEvent model."""

    list_display = ["user", "event_type", "created_at"]
    list_filter = ["event_type", "created_at"]
    search_fields = ["user__email"]
    readonly_fields = ["id", "created_at"]

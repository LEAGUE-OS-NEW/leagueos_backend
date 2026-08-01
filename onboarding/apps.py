"""App configuration for the onboarding module."""

from django.apps import AppConfig


class OnboardingConfig(AppConfig):
    """Configuration for the Fan Onboarding & Personalization module."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "onboarding"
    verbose_name = "Fan Onboarding & Personalization"

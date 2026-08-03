"""Dashboard app configuration."""

from django.apps import AppConfig


class DashboardConfig(AppConfig):
    """Dashboard app configuration."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "dashboard"
    verbose_name = "Fan Dashboard & Navigation"

    def ready(self):
        """Import signals when app is ready."""
        import dashboard.signals  # noqa: F401

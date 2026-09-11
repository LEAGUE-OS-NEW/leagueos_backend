from django.apps import AppConfig


class FantasyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "fantasy"

    def ready(self):
        """Autodiscover Fantasy Celery tasks when the app registry is ready."""
        try:
            from config.celery import discover_fantasy_tasks

            discover_fantasy_tasks()
        except Exception:  # noqa: BLE001
            # Celery may not be installed in all environments (e.g. CI without a broker).
            # The app must still start cleanly.
            pass

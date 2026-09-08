from django.apps import AppConfig


class MarketsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "markets"

    def ready(self):
        try:
            from config.celery import discover_markets_tasks

            discover_markets_tasks()
        except Exception:
            pass

from django.apps import AppConfig


class ClubsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "clubs"
    verbose_name = "Club Management & Administration"

    def ready(self):
        try:
            from config.celery import discover_club_tasks

            discover_club_tasks()
        except Exception:
            pass

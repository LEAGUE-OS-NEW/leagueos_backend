import os

try:
    from celery import Celery

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    app = Celery("leagueos_backend")

    app.config_from_object("django.conf:settings", namespace="CELERY")

except ImportError:
    app = None


def discover_kyc_tasks():
    if app is None:
        return
    app.autodiscover_tasks()

    @app.on_after_configure.connect
    def setup_periodic_tasks(sender, **kwargs):
        sender.add_periodic_task(86400, retention_cleanup_task.s(), name="kyc-retention-cleanup")


def discover_club_tasks():
    if app is None:
        return
    app.autodiscover_tasks(["clubs"])

    @app.on_after_configure.connect
    def setup_club_periodic_tasks(sender, **kwargs):
        sender.add_periodic_task(
            300,
            publish_scheduled_club_content_task.s(),
            name="club-publish-scheduled-content",
        )


def discover_markets_tasks():
    if app is None:
        return
    app.autodiscover_tasks(["markets"])

    @app.on_after_configure.connect
    def setup_markets_periodic_tasks(sender, **kwargs):
        sender.add_periodic_task(300, close_due_markets_task.s(), name="markets-close-due")


def _retention_cleanup_task():
    from kyc.services.retention_service import KYCRetentionService

    return KYCRetentionService.cleanup_expired_files()


def _publish_scheduled_club_content_task():
    from clubs.tasks import publish_scheduled_content

    return publish_scheduled_content()


def _close_due_markets_task():
    from markets.tasks import close_due_markets

    return close_due_markets()


if app is not None:
    retention_cleanup_task = app.task(_retention_cleanup_task)
    publish_scheduled_club_content_task = app.task(_publish_scheduled_club_content_task)
    close_due_markets_task = app.task(_close_due_markets_task)
else:
    retention_cleanup_task = None
    publish_scheduled_club_content_task = None
    close_due_markets_task = None

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
        sender.add_periodic_task(
            86400, retention_cleanup_task.s(), name="kyc-retention-cleanup"
        )

    @app.task
    def retention_cleanup_task():
        from kyc.services.retention_service import KYCRetentionService

        return KYCRetentionService.cleanup_expired_files()

import hashlib
import json
import logging

from django.db import transaction

from notifications.services.notification_service import NotificationService
from notifications.services.permission_recipient_service import PermissionRecipientService

logger = logging.getLogger(__name__)


class OperationalAlertService:
    @classmethod
    def create(
        cls, *, permissions, event_type, title, message, source_key, data=None, severity="WARNING"
    ):
        safe_data = data or {}
        digest = hashlib.sha256(
            json.dumps(safe_data, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]

        def notify():
            for recipient in PermissionRecipientService.resolve(permissions):
                try:
                    NotificationService.create(
                        recipient=recipient,
                        category_code="MARKET_OPERATIONAL_ALERTS",
                        event_type=event_type,
                        title=title,
                        message=message,
                        data=safe_data,
                        deduplication_key=f"operational:{source_key}:{digest}",
                        severity=severity,
                        mandatory=True,
                    )
                except Exception:
                    logger.exception("Unable to create operational alert")

        transaction.on_commit(notify)

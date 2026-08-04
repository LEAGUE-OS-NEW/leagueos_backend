import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from notifications.models import Notification, NotificationCategory, NotificationDelivery
from notifications.services.notification_policy_service import NotificationPolicyService


class NotificationService:
    FORBIDDEN_DATA_KEYS = {
        "secret",
        "signature",
        "password",
        "credential",
        "raw_payload",
        "internal_notes",
    }

    @classmethod
    def _validate_data(cls, data):
        try:
            json.dumps(data)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Notification data must be JSON-compatible.") from exc

        def inspect(value):
            if isinstance(value, dict):
                for key, nested in value.items():
                    normalized = str(key).lower()
                    if any(fragment in normalized for fragment in cls.FORBIDDEN_DATA_KEYS):
                        raise ValidationError("Notification data contains a prohibited field.")
                    inspect(nested)
            elif isinstance(value, list):
                for nested in value:
                    inspect(nested)

        inspect(data)

    @classmethod
    @transaction.atomic
    def create(
        cls,
        *,
        recipient,
        category_code,
        event_type,
        title,
        message,
        deduplication_key,
        severity="INFO",
        data=None,
        deep_link_path="",
        market_id=None,
        actor=None,
        mandatory=None,
        occurred_at=None,
    ):
        safe_data = {} if data is None else data
        cls._validate_data(safe_data)
        category = NotificationCategory.objects.get(code=category_code, is_active=True)
        notification, created = Notification.objects.get_or_create(
            recipient=recipient,
            deduplication_key=deduplication_key,
            defaults={
                "category": category,
                "event_type": event_type,
                "title": title,
                "message": message,
                "severity": severity,
                "data": safe_data,
                "deep_link_path": deep_link_path,
                "market_id": market_id,
                "actor": actor,
                "mandatory": category.mandatory if mandatory is None else mandatory,
                "occurred_at": occurred_at or timezone.now(),
            },
        )
        if not created:
            return notification, False
        for channel, defer_until in NotificationPolicyService.channels(
            recipient=recipient,
            category=category,
            mandatory=notification.mandatory,
            severity=severity,
        ):
            NotificationDelivery.objects.get_or_create(
                notification=notification,
                channel=channel,
                defaults={
                    "idempotency_key": f"{notification.id}:{channel.code}",
                    "status": "DEFERRED" if defer_until else "PENDING",
                    "next_attempt_at": defer_until or timezone.now(),
                },
            )
        return notification, True

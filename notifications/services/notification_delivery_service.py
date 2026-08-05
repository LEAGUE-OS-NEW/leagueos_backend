import re
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from notifications.models import NotificationDelivery, NotificationDeliveryAttempt


def _sanitize(value):
    return re.sub(r"[\r\n]+", " ", str(value))[:500]


class NotificationDeliveryService:
    @classmethod
    def process(cls, *, limit=100, channel=None, max_attempts=5, dry_run=False):
        now = timezone.now()
        with transaction.atomic():
            stale = now - timedelta(minutes=15)
            if not dry_run:
                NotificationDelivery.objects.filter(
                    status="PROCESSING", last_attempt_at__lt=stale
                ).update(status="PENDING", next_attempt_at=now)
            query = (
                NotificationDelivery.objects.select_for_update(skip_locked=True)
                .filter(status__in=["PENDING", "DEFERRED"], next_attempt_at__lte=now)
                .select_related("notification__recipient", "channel")
                .order_by("next_attempt_at", "created_at", "id")
            )
            if channel:
                query = query.filter(channel__code=channel)
            rows = list(query[:limit])
            if dry_run:
                return rows
            for row in rows:
                row.status, row.last_attempt_at = "PROCESSING", now
                row.save(update_fields=["status", "last_attempt_at", "updated_at"])
        for row in rows:
            cls.deliver(row, max_attempts=max_attempts)
        return rows

    @classmethod
    def deliver(cls, delivery, *, max_attempts):
        started = timezone.now()
        outcome = "DELIVERED"
        code = message = reference = ""
        try:
            if delivery.channel.code == "IN_APP":
                pass
            elif delivery.channel.code == "EMAIL":
                note = delivery.notification
                if not note.recipient.email:
                    raise RuntimeError("MISSING_RECIPIENT")
                email = EmailMultiAlternatives(
                    note.title, note.message, settings.DEFAULT_FROM_EMAIL, [note.recipient.email]
                )
                email.attach_alternative(
                    f"<p>{__import__('html').escape(note.message)}</p>", "text/html"
                )
                email.send(fail_silently=False)
            else:
                outcome, code, message = "CANCELLED", "UNSUPPORTED_CHANNEL", "Channel unsupported"
        except Exception as exc:
            outcome, code, message = "FAILED", type(exc).__name__[:100], _sanitize(exc)
        completed = timezone.now()
        with transaction.atomic():
            delivery = NotificationDelivery.objects.select_for_update().get(pk=delivery.pk)
            if delivery.status == "DELIVERED":
                return delivery
            delivery.attempt_count += 1
            delivery.last_attempt_at = completed
            NotificationDeliveryAttempt.objects.create(
                delivery=delivery,
                attempt_number=delivery.attempt_count,
                started_at=started,
                completed_at=completed,
                outcome=outcome,
                provider_reference=reference,
                error_code=code,
                error_message=message,
            )
            if outcome == "DELIVERED":
                delivery.status, delivery.delivered_at = "DELIVERED", completed
            elif outcome == "CANCELLED":
                delivery.status = "CANCELLED"
            elif delivery.attempt_count >= max_attempts:
                delivery.status = "FAILED"
            else:
                delivery.status = "PENDING"
                delivery.next_attempt_at = completed + timedelta(
                    minutes=min(2**delivery.attempt_count, 60)
                )
            delivery.last_error_code, delivery.last_error_message = code, message
            delivery.save()
            terminal_failure = outcome == "FAILED" and delivery.status == "FAILED"
        if terminal_failure and delivery.notification.event_type != "NOTIFICATION_DELIVERY_FAILED":
            from notifications.services.operational_alert_service import OperationalAlertService

            OperationalAlertService.create(
                permissions=("manage_compliance", "manage_market"),
                event_type="NOTIFICATION_DELIVERY_FAILED",
                title="Notification delivery failed",
                message="A notification delivery reached its retry limit.",
                source_key=f"notification-delivery:{delivery.id}",
                data={
                    "delivery_id": str(delivery.id),
                    "channel": delivery.channel.code,
                    "error_code": code,
                },
                severity="CRITICAL",
            )
        return delivery

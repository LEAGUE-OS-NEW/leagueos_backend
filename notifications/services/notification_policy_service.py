from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from notifications.models import (
    CommunicationConsent,
    NotificationChannel,
    UserNotificationPreference,
)


class NotificationPolicyService:
    @classmethod
    def channels(cls, *, recipient, category, mandatory, severity):
        result = []
        for channel in NotificationChannel.objects.filter(is_active=True).order_by("display_order"):
            if channel.code == "PUSH":
                continue
            if not channel.capabilities.filter(capability="send", is_supported=True).exists():
                continue
            preference = UserNotificationPreference.objects.filter(
                user=recipient, notification_category=category, notification_channel=channel
            ).first()
            enabled = preference.enabled if preference else category.default_enabled
            if channel.code == "EMAIL" and not mandatory:
                consent = (
                    CommunicationConsent.objects.filter(
                        user=recipient,
                        consent_type="EMAIL_NOTIFICATIONS",
                    )
                    .order_by("-granted_at", "-created_at")
                    .first()
                )
                if consent is None or not consent.granted:
                    continue
            if channel.code == "IN_APP" or mandatory or enabled:
                if channel.code != "EMAIL" or recipient.email:
                    result.append(
                        (
                            channel,
                            (
                                cls.defer_until(recipient)
                                if not mandatory and severity != "CRITICAL"
                                else None
                            ),
                        )
                    )
        return result

    @staticmethod
    def defer_until(recipient):
        try:
            quiet = recipient.quiet_hours
        except recipient._meta.get_field("quiet_hours").related_model.DoesNotExist:
            return None
        if not quiet.enabled:
            return None
        try:
            zone = ZoneInfo(quiet.timezone)
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("UTC")
        now = timezone.now().astimezone(zone)
        current = now.time().replace(tzinfo=None)
        inside = (
            quiet.start_time <= current < quiet.end_time
            if quiet.start_time < quiet.end_time
            else current >= quiet.start_time or current < quiet.end_time
        )
        if not inside:
            return None
        target = datetime.combine(now.date(), quiet.end_time, tzinfo=zone)
        if target <= now:
            target += timedelta(days=1)
        return target.astimezone(ZoneInfo("UTC"))

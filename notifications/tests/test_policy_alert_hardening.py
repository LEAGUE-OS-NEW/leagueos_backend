from datetime import time, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from authentication.models import Permission, Role, RolePermission, UserRole
from notifications.models import (
    CommunicationConsent,
    Notification,
    NotificationChannel,
    QuietHours,
)
from notifications.services.notification_delivery_service import NotificationDeliveryService
from notifications.services.notification_policy_service import NotificationPolicyService
from notifications.services.notification_service import NotificationService
from notifications.services.operational_alert_service import OperationalAlertService
from notifications.services.permission_recipient_service import PermissionRecipientService


def make_user(email):
    return get_user_model().objects.create_user(email=email, username=email, password="test")


@pytest.mark.django_db(transaction=True)
def test_operational_alert_recipients_are_permission_scoped_and_deduplicated(
    seed_notification_data,
):
    allowed, unrelated = make_user("allowed@example.com"), make_user("unrelated@example.com")
    permission = Permission.objects.create(
        name="manage_compliance", resource="compliance", action="manage"
    )
    role = Role.objects.create(name="compliance_alerts", display_name="Compliance")
    RolePermission.objects.create(role=role, permission=permission)
    UserRole.objects.create(user=allowed, role=role)
    for _ in range(2):
        OperationalAlertService.create(
            permissions=("manage_compliance",),
            event_type="TEST_ALERT",
            title="Alert",
            message="Safe alert",
            source_key="source-1",
            data={"reason_code": "SAFE"},
        )
    assert Notification.objects.filter(recipient=allowed, event_type="TEST_ALERT").count() == 1
    assert not Notification.objects.filter(recipient=unrelated, event_type="TEST_ALERT").exists()


@pytest.mark.django_db
def test_optional_email_requires_consent_and_mandatory_bypasses(seed_notification_data):
    recipient = make_user("policy@example.com")
    optional, _ = NotificationService.create(
        recipient=recipient,
        category_code="MARKET_ORDERS",
        event_type="OPTIONAL",
        title="Optional",
        message="Optional",
        deduplication_key="optional-no-consent",
        mandatory=False,
    )
    assert optional.deliveries.filter(channel__code="IN_APP").exists()
    assert not optional.deliveries.filter(channel__code="EMAIL").exists()
    CommunicationConsent.objects.create(
        user=recipient, consent_type="EMAIL_NOTIFICATIONS", granted=True
    )
    enabled, _ = NotificationService.create(
        recipient=recipient,
        category_code="MARKET_ORDERS",
        event_type="OPTIONAL",
        title="Optional",
        message="Optional",
        deduplication_key="optional-consent",
        mandatory=False,
    )
    assert enabled.deliveries.filter(channel__code="EMAIL").exists()
    CommunicationConsent.objects.create(
        user=recipient, consent_type="EMAIL_NOTIFICATIONS", granted=False
    )
    mandatory, _ = NotificationService.create(
        recipient=recipient,
        category_code="MARKET_COMPLIANCE",
        event_type="MANDATORY",
        title="Mandatory",
        message="Mandatory",
        deduplication_key="mandatory-withdrawn",
        mandatory=True,
    )
    assert mandatory.deliveries.filter(channel__code="EMAIL").exists()


@pytest.mark.django_db
def test_dry_run_has_zero_mutations_and_terminal_delivery_is_immutable(seed_notification_data):
    recipient = make_user("dry@example.com")
    note, _ = NotificationService.create(
        recipient=recipient,
        category_code="MARKET_COMPLIANCE",
        event_type="DRY",
        title="Dry",
        message="Dry",
        deduplication_key="dry",
        mandatory=True,
    )
    stale = note.deliveries.filter(channel__code="IN_APP").get()
    stale.status = "PROCESSING"
    stale.last_attempt_at = timezone.now() - timedelta(hours=1)
    stale.save()
    NotificationDeliveryService.process(dry_run=True)
    stale.refresh_from_db()
    assert stale.status == "PROCESSING"
    NotificationDeliveryService.deliver(stale, max_attempts=3)
    stale.refresh_from_db()
    stale.status = "PENDING"
    with pytest.raises(ValidationError):
        stale.save()


@pytest.mark.django_db
def test_notification_data_rejects_non_json_and_secret_fields(seed_notification_data):
    recipient = make_user("privacy@example.com")
    with pytest.raises(ValidationError):
        NotificationService.create(
            recipient=recipient,
            category_code="MARKET_ORDERS",
            event_type="BAD",
            title="Bad",
            message="Bad",
            deduplication_key="bad-object",
            data={"object": recipient},
        )
    with pytest.raises(ValidationError):
        NotificationService.create(
            recipient=recipient,
            category_code="MARKET_ORDERS",
            event_type="BAD",
            title="Bad",
            message="Bad",
            deduplication_key="bad-secret",
            data={"callback_signature": "x"},
        )


@pytest.mark.django_db
def test_quiet_hours_invalid_timezone_missing_email_and_critical_bypass(seed_notification_data):
    recipient = make_user("quiet@example.com")
    CommunicationConsent.objects.create(
        user=recipient, consent_type="EMAIL_NOTIFICATIONS", granted=True
    )
    QuietHours.objects.create(
        user=recipient,
        enabled=True,
        start_time=time(0),
        end_time=time(23, 59),
        timezone="Invalid/Zone",
    )
    category = Notification.objects.model._meta.get_field("category").related_model.objects.get(
        code="MARKET_ORDERS"
    )
    optional = NotificationPolicyService.channels(
        recipient=recipient, category=category, mandatory=False, severity="INFO"
    )
    assert any(deferred is not None for _, deferred in optional)
    critical = NotificationPolicyService.channels(
        recipient=recipient, category=category, mandatory=False, severity="CRITICAL"
    )
    assert all(deferred is None for _, deferred in critical)
    recipient.email = ""
    recipient.save(update_fields=["email"])
    assert all(
        channel.code != "EMAIL"
        for channel, _ in NotificationPolicyService.channels(
            recipient=recipient, category=category, mandatory=True, severity="INFO"
        )
    )


@pytest.mark.django_db
def test_delivery_retry_terminal_failure_push_and_replay(seed_notification_data, monkeypatch):
    recipient = make_user("failure@example.com")
    note, _ = NotificationService.create(
        recipient=recipient,
        category_code="MARKET_COMPLIANCE",
        event_type="FAIL",
        title="Fail",
        message="safe\nmessage",
        deduplication_key="failure",
        mandatory=True,
    )
    email_delivery = note.deliveries.get(channel__code="EMAIL")
    monkeypatch.setattr(
        "notifications.services.notification_delivery_service.EmailMultiAlternatives.send",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("smtp\nsecret")),
    )
    first = NotificationDeliveryService.deliver(email_delivery, max_attempts=2)
    assert first.status == "PENDING" and "\n" not in first.last_error_message
    failed = NotificationDeliveryService.deliver(first, max_attempts=2)
    assert failed.status == "FAILED"
    in_app = note.deliveries.get(channel__code="IN_APP")
    delivered = NotificationDeliveryService.deliver(in_app, max_attempts=2)
    assert NotificationDeliveryService.deliver(delivered, max_attempts=2).status == "DELIVERED"
    push = NotificationChannel.objects.get(code="PUSH")
    push_delivery = note.deliveries.create(channel=push, idempotency_key="push-test")
    assert NotificationDeliveryService.deliver(push_delivery, max_attempts=2).status == "CANCELLED"


@pytest.mark.django_db
def test_empty_permission_resolution():
    assert not PermissionRecipientService.resolve(()).exists()

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import override_settings
from rest_framework.test import APIClient

from notifications.models import NotificationDeliveryAttempt
from notifications.services.notification_delivery_service import NotificationDeliveryService
from notifications.services.notification_service import NotificationService


@pytest.fixture
def inbox_user(db):
    return get_user_model().objects.create_user(
        email="inbox@example.com", username="inbox", password="test"
    )


@pytest.mark.django_db
def test_notification_creation_is_idempotent_and_isolated(seed_notification_data, inbox_user):
    note, created = NotificationService.create(
        recipient=inbox_user,
        category_code="MARKET_COMPLIANCE",
        event_type="KYC_VERIFIED",
        title="Verified",
        message="Your verification is complete.",
        deduplication_key="kyc:1",
        mandatory=True,
    )
    replay, replay_created = NotificationService.create(
        recipient=inbox_user,
        category_code="MARKET_COMPLIANCE",
        event_type="KYC_VERIFIED",
        title="Changed",
        message="Changed",
        deduplication_key="kyc:1",
        mandatory=True,
    )
    assert created and not replay_created and replay.id == note.id
    client = APIClient()
    client.force_authenticate(inbox_user)
    response = client.get("/api/v1/notifications/")
    assert response.status_code == 200 and response.data["results"][0]["id"] == str(note.id)


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_email_and_in_app_delivery(seed_notification_data, inbox_user):
    note, _ = NotificationService.create(
        recipient=inbox_user,
        category_code="MARKET_COMPLIANCE",
        event_type="KYC_VERIFIED",
        title="Verified",
        message="Complete",
        deduplication_key="kyc:delivery",
        mandatory=True,
    )
    rows = NotificationDeliveryService.process(limit=10, max_attempts=3)
    assert len(rows) == 2
    assert note.deliveries.filter(status="DELIVERED").count() == 2
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_delivery_attempt_is_immutable(seed_notification_data, inbox_user):
    note, _ = NotificationService.create(
        recipient=inbox_user,
        category_code="MARKET_COMPLIANCE",
        event_type="NOTICE",
        title="Notice",
        message="Message",
        deduplication_key="attempt:1",
        mandatory=True,
    )
    NotificationDeliveryService.process(limit=10, max_attempts=3)
    attempt = NotificationDeliveryAttempt.objects.first()
    attempt.outcome = "FAILED"
    with pytest.raises(ValidationError):
        attempt.save()
    with pytest.raises(ValidationError):
        NotificationDeliveryAttempt.objects.all().delete()

"""Factory Boy factories for notifications app tests."""

import uuid

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone

from notifications.models import (
    CommunicationConsent,
    NotificationCategory,
    NotificationChannel,
    NotificationChannelCapability,
    NotificationPreferenceAudit,
    QuietHours,
    UserNotificationPreference,
)

User = get_user_model()


class NotificationCategoryFactory(factory.django.DjangoModelFactory):
    """Factory for NotificationCategory."""

    class Meta:
        model = NotificationCategory

    id = factory.LazyFunction(uuid.uuid4)
    code = factory.Sequence(lambda n: f"CATEGORY_{n}")
    name = factory.Sequence(lambda n: f"Test Category {n}")
    description = factory.Faker("text")
    mandatory = False
    default_enabled = True
    priority = factory.Sequence(lambda n: n)
    display_order = factory.Sequence(lambda n: n)
    is_active = True


class NotificationChannelFactory(factory.django.DjangoModelFactory):
    """Factory for NotificationChannel."""

    class Meta:
        model = NotificationChannel

    id = factory.LazyFunction(uuid.uuid4)
    code = factory.Sequence(lambda n: f"CHANNEL_{n}")
    name = factory.Sequence(lambda n: f"Test Channel {n}")
    description = factory.Faker("text")
    provider = factory.Faker("word")
    display_order = factory.Sequence(lambda n: n)
    is_active = True


class NotificationChannelCapabilityFactory(factory.django.DjangoModelFactory):
    """Factory for NotificationChannelCapability."""

    class Meta:
        model = NotificationChannelCapability

    id = factory.LazyFunction(uuid.uuid4)
    channel = factory.SubFactory(NotificationChannelFactory)
    capability = factory.Faker("word")
    is_supported = True


class UserNotificationPreferenceFactory(factory.django.DjangoModelFactory):
    """Factory for UserNotificationPreference."""

    class Meta:
        model = UserNotificationPreference

    id = factory.LazyFunction(uuid.uuid4)
    user = factory.SubFactory("authentication.tests.factories.UserFactory")
    notification_category = factory.SubFactory(NotificationCategoryFactory)
    notification_channel = factory.SubFactory(NotificationChannelFactory)
    enabled = True


class CommunicationConsentFactory(factory.django.DjangoModelFactory):
    """Factory for CommunicationConsent."""

    class Meta:
        model = CommunicationConsent

    id = factory.LazyFunction(uuid.uuid4)
    user = factory.SubFactory("authentication.tests.factories.UserFactory")
    consent_type = "MARKETING"
    granted = True
    granted_at = factory.LazyFunction(timezone.now)
    withdrawn_at = None
    source = "WEB"
    ip_address = factory.Faker("ipv4")
    user_agent = factory.Faker("user_agent")


class QuietHoursFactory(factory.django.DjangoModelFactory):
    """Factory for QuietHours."""

    class Meta:
        model = QuietHours

    id = factory.LazyFunction(uuid.uuid4)
    user = factory.SubFactory("authentication.tests.factories.UserFactory")
    enabled = True
    start_time = factory.Faker("time", pattern="%H:%M:%S")
    end_time = factory.Faker("time", pattern="%H:%M:%S")
    timezone = "UTC"


class NotificationPreferenceAuditFactory(factory.django.DjangoModelFactory):
    """Factory for NotificationPreferenceAudit."""

    class Meta:
        model = NotificationPreferenceAudit

    id = factory.LazyFunction(uuid.uuid4)
    user = factory.SubFactory("authentication.tests.factories.UserFactory")
    action = "NOTIFICATION_PREFERENCES_VIEWED"
    category = None
    channel = None
    ip_address = factory.Faker("ipv4")
    user_agent = factory.Faker("user_agent")
    metadata = factory.Dict({})
    timestamp = factory.LazyFunction(timezone.now)

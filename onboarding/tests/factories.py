"""Factory Boy factories for onboarding app models."""

from __future__ import annotations

import uuid

import factory
from factory.django import DjangoModelFactory
from faker import Faker

from accounts.models import User
from onboarding.models import (
    OnboardingAnalyticsEvent,
    UserClubPreference,
    UserCompetitionPreference,
    UserOnboarding,
    UserSportPreference,
)
from profiles.models import Club, Country
from sports.models import Competition, Sport

fake = Faker()


class UserFactory(DjangoModelFactory):
    """Factory for the User model."""

    class Meta:
        model = User
        django_get_or_create = ("email",)

    id = factory.LazyFunction(uuid.uuid4)
    email = factory.Sequence(lambda n: f"user{n}@leagueos.com")
    username = factory.Sequence(lambda n: f"user{n}")
    first_name = fake.first_name()
    last_name = fake.last_name()
    is_verified = True
    is_active = True


class CountryFactory(DjangoModelFactory):
    """Factory for the Country model."""

    class Meta:
        model = Country
        django_get_or_create = ("name",)

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"Country {n}")
    iso_code = factory.Sequence(lambda n: f"{chr(65 + n % 26)}{chr(65 + (n // 26) % 26)}")
    is_active = True


class SportFactory(DjangoModelFactory):
    """Factory for the Sport model."""

    class Meta:
        model = Sport
        django_get_or_create = ("name",)

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"Sport {n}")
    code = factory.Sequence(lambda n: f"SPORT{n}")
    slug = factory.Sequence(lambda n: f"sport-{n}")
    is_active = True


class CompetitionFactory(DjangoModelFactory):
    """Factory for the Competition model."""

    class Meta:
        model = Competition
        django_get_or_create = ("name",)

    id = factory.LazyFunction(uuid.uuid4)
    sport = factory.SubFactory(SportFactory)
    name = factory.Sequence(lambda n: f"Competition {n}")
    slug = factory.Sequence(lambda n: f"competition-{n}")
    country_code = "UG"
    is_active = True


class ClubFactory(DjangoModelFactory):
    """Factory for the Club model."""

    class Meta:
        model = Club
        django_get_or_create = ("name",)

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"Club {n}")
    slug = factory.Sequence(lambda n: f"club-{n}")
    sport = None
    competition = None
    is_active = True


class UserOnboardingFactory(DjangoModelFactory):
    """Factory for the UserOnboarding model."""

    class Meta:
        model = UserOnboarding

    id = factory.LazyFunction(uuid.uuid4)
    user = factory.SubFactory(UserFactory)
    current_step = UserOnboarding.Step.COUNTRY
    completed = False
    completed_at = None
    skipped_steps = []


class UserSportPreferenceFactory(DjangoModelFactory):
    """Factory for the UserSportPreference model."""

    class Meta:
        model = UserSportPreference

    id = factory.LazyFunction(uuid.uuid4)
    user = factory.SubFactory(UserFactory)
    sport = factory.SubFactory(SportFactory)


class UserCompetitionPreferenceFactory(DjangoModelFactory):
    """Factory for the UserCompetitionPreference model."""

    class Meta:
        model = UserCompetitionPreference

    id = factory.LazyFunction(uuid.uuid4)
    user = factory.SubFactory(UserFactory)
    competition = factory.SubFactory(CompetitionFactory)


class UserClubPreferenceFactory(DjangoModelFactory):
    """Factory for the UserClubPreference model."""

    class Meta:
        model = UserClubPreference

    id = factory.LazyFunction(uuid.uuid4)
    user = factory.SubFactory(UserFactory)
    club = factory.SubFactory(ClubFactory)


class OnboardingAnalyticsEventFactory(DjangoModelFactory):
    """Factory for the OnboardingAnalyticsEvent model."""

    class Meta:
        model = OnboardingAnalyticsEvent

    id = factory.LazyFunction(uuid.uuid4)
    user = factory.SubFactory(UserFactory)
    event_type = OnboardingAnalyticsEvent.EventType.STARTED
    metadata = {}

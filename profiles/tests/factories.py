"Factory Boy factories for profiles app models."

from __future__ import annotations

import uuid

import factory
from factory.django import DjangoModelFactory

from profiles.models import Club, Country, Gender, Language, Profile, Timezone


class UserFactory(DjangoModelFactory):
    class Meta:
        model = "accounts.User"
        django_get_or_create = ("email",)

    id = factory.LazyFunction(uuid.uuid4)
    email = factory.Sequence(lambda n: f"user{n}@leagueos.com")
    username = factory.Sequence(lambda n: f"user{n}")
    first_name = "Test"
    last_name = "User"
    is_verified = True
    is_active = True


class CountryFactory(DjangoModelFactory):
    class Meta:
        model = Country
        django_get_or_create = ("name",)

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"Country {n}")
    iso_code = factory.Sequence(lambda n: f"C{n:02d}")
    is_active = True


class LanguageFactory(DjangoModelFactory):
    class Meta:
        model = Language
        django_get_or_create = ("name",)

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"Language {n}")
    code = factory.Sequence(lambda n: f"lang-{n}")
    is_active = True


class TimezoneFactory(DjangoModelFactory):
    class Meta:
        model = Timezone
        django_get_or_create = ("timezone_name",)

    id = factory.LazyFunction(uuid.uuid4)
    timezone_name = factory.Sequence(lambda n: f"Zone/{n}")
    utc_offset = "+00:00"
    is_active = True


class GenderFactory(DjangoModelFactory):
    class Meta:
        model = Gender
        django_get_or_create = ("name",)

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"Gender {n}")
    code = factory.Sequence(lambda n: f"g-{n}")
    is_active = True


class ClubFactory(DjangoModelFactory):
    class Meta:
        model = Club
        django_get_or_create = ("name",)

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"Club {n}")
    slug = factory.Sequence(lambda n: f"club-{n}")
    is_active = True


class ProfileFactory(DjangoModelFactory):
    class Meta:
        model = Profile

    id = factory.LazyFunction(uuid.uuid4)
    user = factory.SubFactory(UserFactory)
    display_name = ""
    city = ""
    biography = ""

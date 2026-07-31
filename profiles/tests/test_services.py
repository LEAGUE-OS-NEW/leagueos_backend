"""Tests for profiles services."""

from __future__ import annotations

from datetime import date
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from profiles.services.lookup_service import LookupService
from profiles.services.profile_service import ProfileService
from profiles.tests.factories import (
    ClubFactory,
    CountryFactory,
    GenderFactory,
    LanguageFactory,
    ProfileFactory,
    TimezoneFactory,
    UserFactory,
)

User = get_user_model()


@pytest.mark.django_db
class TestProfileService:
    def test_get_or_create_profile_creates_new(self):
        user = UserFactory()
        profile = ProfileService.get_or_create_profile(user)
        assert profile.user == user

    def test_get_or_create_profile_returns_existing(self):
        user = UserFactory()
        profile1 = ProfileService.get_or_create_profile(user)
        profile2 = ProfileService.get_or_create_profile(user)
        assert profile1.id == profile2.id

    def test_record_profile_view_creates_audit_log(self):
        user = UserFactory()
        ProfileService.record_profile_view(user)
        assert user.audit_logs.filter(action="PROFILE_VIEWED").exists()

    def test_update_profile(self):
        user = UserFactory()
        country = CountryFactory()
        data = {
            "first_name": "Updated",
            "last_name": "Name",
            "display_name": "Display",
            "city": "New City",
            "country": country,
        }
        profile = ProfileService.update_profile(user, data)
        assert profile.user.first_name == "Updated"
        assert profile.user.last_name == "Name"
        assert profile.display_name == "Display"
        assert profile.city == "New City"
        assert profile.country == country

    def test_update_profile_audit_log(self):
        user = UserFactory()
        data = {"first_name": "Updated"}
        ProfileService.update_profile(user, data)
        assert user.audit_logs.filter(action="PROFILE_UPDATED").exists()

    def test_validate_date_of_birth_in_future(self):
        future = timezone.now().date() + timezone.timedelta(days=1)
        with pytest.raises(ValueError):
            ProfileService.validate_date_of_birth(future)

    def test_validate_date_of_birth_too_young(self):
        from django.conf import settings

        min_age = getattr(settings, "PROFILE_MIN_AGE_YEARS", 13)
        young = date(
            timezone.now().year - min_age + 1,
            timezone.now().month,
            timezone.now().day,
        )
        with pytest.raises(ValueError):
            ProfileService.validate_date_of_birth(young)


@pytest.mark.django_db
class TestLookupService:
    def test_get_countries(self):
        CountryFactory()
        countries = LookupService.get_countries()
        assert len(countries) == 1

    def test_get_countries_only_active(self):
        active = CountryFactory(is_active=True)
        inactive = CountryFactory(is_active=False)
        countries = LookupService.get_countries()
        assert active in countries
        assert inactive not in countries

    def test_get_languages(self):
        LanguageFactory()
        languages = LookupService.get_languages()
        assert len(languages) == 1

    def test_get_timezones(self):
        TimezoneFactory()
        timezones = LookupService.get_timezones()
        assert len(timezones) == 1

    def test_get_genders(self):
        GenderFactory()
        genders = LookupService.get_genders()
        assert len(genders) == 1

    def test_get_clubs(self):
        ClubFactory()
        clubs = LookupService.get_clubs()
        assert len(clubs) == 1

    def test_get_country_by_id(self):
        country = CountryFactory()
        result = LookupService.get_country_by_id(str(country.id))
        assert result == country

    def test_get_country_by_id_inactive(self):
        country = CountryFactory(is_active=False)
        result = LookupService.get_country_by_id(str(country.id))
        assert result is None

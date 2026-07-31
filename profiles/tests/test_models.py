 ."""Tests for profiles models."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from profiles.models import Club, Country, Gender, Language, Profile, Timezone

User = get_user_model()


@pytest.mark.django_db
class TestModels:
    def test_profile_creation(self):
        user = User.objects.create_user(
            email="test@example.com",
            username="test",
            password="testpass123",
            first_name="Test",
            last_name="User",
        )
        profile = Profile.objects.create(user=user, display_name="Test User")
        assert profile.user == user
        assert str(profile) == f"Profile for {user}"

    def test_country_creation(self):
        country = Country.objects.create(name="Testland", iso_code="TL")
        assert country.name == "Testland"
        assert country.is_active is True

    def test_club_creation(self):
        club = Club.objects.create(name="FC Test", slug="fc-test")
        assert club.name == "FC Test"

    def test_gender_creation(self):
        gender = Gender.objects.create(name="Male", code="M")
        assert gender.code == "M"

    def test_language_creation(self):
        lang = Language.objects.create(name="English", code="en")
        assert lang.code == "en"

    def test_timezone_creation(self):
        tz = Timezone.objects.create(timezone_name="Africa/Kampala", utc_offset="+03:00")
        assert tz.utc_offset == "+03:00"

    def test_country_unique_name(self):
        Country.objects.create(name="Testland", iso_code="TL")
        with pytest.raises(IntegrityError):
            Country.objects.create(name="Testland", iso_code="XY")

    def test_club_unique_name(self):
        Club.objects.create(name="FC Test", slug="fc-test")
        with pytest.raises(IntegrityError):
            Club.objects.create(name="FC Test", slug="fc-test-2")

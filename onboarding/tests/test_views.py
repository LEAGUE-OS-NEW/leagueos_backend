"""Tests for onboarding views."""

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from onboarding.models import UserOnboarding
from onboarding.services.preference_service import PreferenceService
from onboarding.tests.factories import (
    ClubFactory,
    CompetitionFactory,
    CountryFactory,
    SportFactory,
    UserFactory,
)


class OnboardingViewsTests(TestCase):
    """Tests for onboarding views."""

    def setUp(self):
        self.client = APIClient()
        self.user = UserFactory()
        self.client.force_authenticate(user=self.user)

    def test_get_onboarding_status_creates_onboarding(self):
        url = reverse("onboarding:onboarding-status")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("data", response.data)
        self.assertEqual(response.data["data"]["current_step"], UserOnboarding.Step.COUNTRY)

    def test_post_country_selection(self):
        url = reverse("onboarding:onboarding-country")
        country = CountryFactory()
        response = self.client.post(url, {"country_id": str(country.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

    def test_post_sport_selection(self):
        url = reverse("onboarding:onboarding-sports")
        sport = SportFactory()
        response = self.client.post(url, {"sport_ids": [str(sport.id)]})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

    def test_post_competition_selection(self):
        url = reverse("onboarding:onboarding-competitions")
        sport = SportFactory()
        competition = CompetitionFactory(sport=sport)
        # First select the sport
        PreferenceService.select_sports(self.user, [sport])
        response = self.client.post(url, {"competition_ids": [str(competition.id)]})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

    def test_post_club_selection(self):
        url = reverse("onboarding:onboarding-clubs")
        club = ClubFactory()
        response = self.client.post(url, {"club_ids": [str(club.id)]})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

    def test_skip_step(self):
        url = reverse("onboarding:onboarding-skip")
        response = self.client.post(url, {"step": UserOnboarding.Step.COUNTRY})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn(UserOnboarding.Step.COUNTRY, self.user.onboarding.skipped_steps)

    def test_complete_onboarding(self):
        url = reverse("onboarding:onboarding-complete")
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.user.onboarding.refresh_from_db()
        self.assertTrue(self.user.onboarding.completed)

    def test_get_dashboard_configuration(self):
        url = reverse("onboarding:onboarding-dashboard")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

    def test_unauthenticated_access_denied(self):
        self.client.force_authenticate(user=None)
        url = reverse("onboarding:onboarding-status")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class PreferenceCataloguesTests(TestCase):
    """Tests for preference catalogue endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.user = UserFactory()
        self.client.force_authenticate(user=self.user)

    def test_countries_catalogue(self):
        url = reverse("onboarding:preference-countries")
        CountryFactory()
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(len(response.data["data"]), 1)

    def test_sports_catalogue(self):
        url = reverse("onboarding:preference-sports")
        SportFactory()
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])

    def test_competitions_catalogue_filtered_by_sport(self):
        url = reverse("onboarding:preference-competitions")
        sport1 = SportFactory()
        sport2 = SportFactory()
        CompetitionFactory(sport=sport1)
        CompetitionFactory(sport=sport2)
        response = self.client.get(url, {"sport": str(sport1.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 1)

    def test_clubs_catalogue_filtered_by_competition(self):
        url = reverse("onboarding:preference-clubs")
        competition = CompetitionFactory()
        ClubFactory()
        ClubFactory(competition=competition)
        response = self.client.get(url, {"competition": str(competition.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["data"]), 1)

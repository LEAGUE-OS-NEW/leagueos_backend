"""Tests for onboarding views."""

import uuid

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
        self.assertEqual(response.data["data"]["country"]["id"], str(country.id))
        self.assertFalse(response.data["data"]["completed"])

    def test_replaying_country_does_not_advance_unrelated_current_step(self):
        first_country = CountryFactory()
        second_country = CountryFactory()
        url = reverse("onboarding:onboarding-country")
        first = self.client.post(url, {"country_id": str(first_country.id)})
        self.assertEqual(first.data["data"]["current_step"], UserOnboarding.Step.SPORTS)
        replay = self.client.post(url, {"country_id": str(second_country.id)})
        self.assertEqual(replay.data["data"]["current_step"], UserOnboarding.Step.SPORTS)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.country, second_country)

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

    def test_replaying_earlier_skip_does_not_advance_current_step(self):
        url = reverse("onboarding:onboarding-skip")
        self.client.post(url, {"step": UserOnboarding.Step.COUNTRY})
        replay = self.client.post(url, {"step": UserOnboarding.Step.COUNTRY})
        self.assertEqual(replay.data["data"]["current_step"], UserOnboarding.Step.SPORTS)
        self.assertEqual(replay.data["data"]["skipped_steps"].count(UserOnboarding.Step.COUNTRY), 1)

    def test_complete_onboarding(self):
        url = reverse("onboarding:onboarding-complete")
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.user.onboarding.refresh_from_db()
        self.assertTrue(self.user.onboarding.completed)
        self.assertTrue(response.data["data"]["completed"])
        self.assertEqual(response.data["data"]["current_step"], UserOnboarding.Step.COMPLETED)

    def test_page_resume_returns_saved_selections(self):
        country = CountryFactory()
        self.client.post(reverse("onboarding:onboarding-country"), {"country_id": country.id})
        response = self.client.get(reverse("onboarding:onboarding-status"))
        self.assertEqual(response.data["data"]["preferred_country"]["id"], str(country.id))
        self.assertEqual(response.data["data"]["current_step"], UserOnboarding.Step.SPORTS)
        self.assertFalse(response.data["data"]["completed"])

    def test_invalid_and_inactive_catalogue_ids_are_rejected(self):
        inactive = CountryFactory(is_active=False)
        url = reverse("onboarding:onboarding-country")
        for catalogue_id in (inactive.id, uuid.uuid4()):
            with self.subTest(catalogue_id=catalogue_id):
                response = self.client.post(url, {"country_id": catalogue_id})
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_full_flow_and_dashboard_access_after_completion(self):
        country = CountryFactory()
        sport = SportFactory()
        competition = CompetitionFactory(sport=sport)
        club = ClubFactory(sport=sport, competition=competition)
        submissions = (
            ("onboarding:onboarding-country", {"country_id": country.id}),
            ("onboarding:onboarding-sports", {"sport_ids": [sport.id]}),
            ("onboarding:onboarding-competitions", {"competition_ids": [competition.id]}),
            ("onboarding:onboarding-clubs", {"club_ids": [club.id]}),
        )
        for url_name, payload in submissions:
            response = self.client.post(reverse(url_name), payload)
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        completed = self.client.post(reverse("onboarding:onboarding-complete"))
        self.assertTrue(completed.data["data"]["completed"])
        dashboard = self.client.get(reverse("onboarding:onboarding-dashboard"))
        self.assertEqual(dashboard.status_code, status.HTTP_200_OK)
        self.assertTrue(dashboard.data["data"]["completed"])
        self.assertIn("configuration", dashboard.data["data"])

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

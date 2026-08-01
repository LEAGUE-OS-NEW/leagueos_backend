"""Tests for onboarding services."""

from django.test import TestCase

from onboarding.models import OnboardingAnalyticsEvent, UserOnboarding
from onboarding.services.catalogue_service import CatalogueService
from onboarding.services.dashboard_configuration_service import (
    DashboardConfigurationService,
)
from onboarding.services.onboarding_service import OnboardingService
from onboarding.services.preference_service import PreferenceService
from onboarding.tests.factories import (
    ClubFactory,
    CompetitionFactory,
    CountryFactory,
    SportFactory,
    UserFactory,
)


class OnboardingServiceTests(TestCase):
    """Tests for OnboardingService."""

    def test_get_or_create_onboarding_creates_new(self):
        user = UserFactory()
        onboarding = OnboardingService.get_or_create_onboarding(user)
        self.assertEqual(onboarding.user, user)
        self.assertEqual(onboarding.current_step, UserOnboarding.Step.COUNTRY)
        self.assertFalse(onboarding.completed)

    def test_get_or_create_onboarding_returns_existing(self):
        user = UserFactory()
        onboarding1 = OnboardingService.get_or_create_onboarding(user)
        onboarding2 = OnboardingService.get_or_create_onboarding(user)
        self.assertEqual(onboarding1.id, onboarding2.id)

    def test_skip_step_advances_step(self):
        user = UserFactory()
        onboarding = OnboardingService.get_or_create_onboarding(user)
        self.assertEqual(onboarding.current_step, UserOnboarding.Step.COUNTRY)

        OnboardingService.skip_step(user, UserOnboarding.Step.COUNTRY)
        onboarding.refresh_from_db()
        self.assertEqual(onboarding.current_step, UserOnboarding.Step.SPORTS)
        self.assertIn(UserOnboarding.Step.COUNTRY, onboarding.skipped_steps)

    def test_complete_onboarding_marks_completed(self):
        user = UserFactory()
        onboarding = OnboardingService.get_or_create_onboarding(user)
        self.assertFalse(onboarding.completed)

        OnboardingService.complete_onboarding(user)
        onboarding.refresh_from_db()
        self.assertTrue(onboarding.completed)
        self.assertEqual(onboarding.current_step, UserOnboarding.Step.COMPLETED)
        self.assertIsNotNone(onboarding.completed_at)

    def test_resume_onboarding_resets_completed(self):
        user = UserFactory()
        onboarding = OnboardingService.get_or_create_onboarding(user)
        OnboardingService.complete_onboarding(user)
        onboarding.refresh_from_db()
        self.assertTrue(onboarding.completed)

        OnboardingService.resume_onboarding(user)
        onboarding.refresh_from_db()
        self.assertFalse(onboarding.completed)
        self.assertIsNone(onboarding.completed_at)
        self.assertEqual(onboarding.current_step, UserOnboarding.Step.COUNTRY)


class PreferenceServiceTests(TestCase):
    """Tests for PreferenceService."""

    def test_select_country_updates_profile(self):
        user = UserFactory()
        country = CountryFactory()
        PreferenceService.select_country(user, country)
        profile = user.profile
        self.assertEqual(profile.country, country)

    def test_select_sports_creates_preferences(self):
        user = UserFactory()
        sport1 = SportFactory()
        sport2 = SportFactory()
        PreferenceService.select_sports(user, [sport1, sport2])
        self.assertEqual(user.sport_preferences.count(), 2)
        self.assertIn(sport1.id, PreferenceService.get_user_sport_ids(user))

    def test_select_competitions_creates_preferences(self):
        user = UserFactory()
        sport = SportFactory()
        competition = CompetitionFactory(sport=sport)
        PreferenceService.select_sports(user, [sport])
        PreferenceService.select_competitions(user, [competition])
        self.assertEqual(user.competition_preferences.count(), 1)
        self.assertEqual(user.competition_preferences.first().competition, competition)

    def test_select_clubs_creates_preferences(self):
        user = UserFactory()
        club = ClubFactory()
        PreferenceService.select_clubs(user, [club])
        self.assertEqual(user.club_preferences.count(), 1)
        self.assertEqual(user.club_preferences.first().club, club)


class CatalogueServiceTests(TestCase):
    """Tests for CatalogueService."""

    def test_get_countries_returns_active_only(self):
        active_country = CountryFactory(is_active=True)
        CountryFactory(is_active=False)
        countries = list(CatalogueService.get_countries())
        self.assertIn(active_country, countries)
        self.assertEqual(len(countries), 1)

    def test_get_sports_returns_active_only(self):
        active_sport = SportFactory(is_active=True)
        SportFactory(is_active=False)
        sports = list(CatalogueService.get_sports())
        self.assertIn(active_sport, sports)
        self.assertEqual(len(sports), 1)

    def test_get_competitions_filters_by_sport(self):
        sport1 = SportFactory()
        comp1 = CompetitionFactory(sport=sport1)
        CatalogueService.get_competitions(sport_id=sport1.id)
        comps = list(CatalogueService.get_competitions(sport_id=sport1.id))
        self.assertIn(comp1, comps)
        self.assertEqual(len(comps), 1)


class DashboardConfigurationServiceTests(TestCase):
    """Tests for DashboardConfigurationService."""

    def test_generate_dashboard_configuration(self):
        user = UserFactory()
        country = CountryFactory()
        sport = SportFactory()
        competition = CompetitionFactory(sport=sport)
        club = ClubFactory()

        PreferenceService.select_country(user, country)
        PreferenceService.select_sports(user, [sport])
        PreferenceService.select_competitions(user, [competition])
        PreferenceService.select_clubs(user, [club])

        config = DashboardConfigurationService.generate_dashboard_configuration(user)
        self.assertEqual(config["preferred_country"], country)
        self.assertIn(sport, config["favourite_sports"])
        self.assertIn(competition, config["favourite_competitions"])
        self.assertIn(club, config["favourite_clubs"])

    def test_generate_dashboard_configuration_creates_analytics_event(self):
        user = UserFactory()
        DashboardConfigurationService.generate_dashboard_configuration(user)
        events = OnboardingAnalyticsEvent.objects.filter(
            user=user, event_type=OnboardingAnalyticsEvent.EventType.DASHBOARD_GENERATED
        )
        self.assertTrue(events.exists())

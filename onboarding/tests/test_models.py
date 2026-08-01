"""Tests for onboarding models."""

from django.db import IntegrityError
from django.test import TestCase

from onboarding.models import UserOnboarding
from onboarding.tests.factories import (
    OnboardingAnalyticsEventFactory,
    UserClubPreferenceFactory,
    UserCompetitionPreferenceFactory,
    UserFactory,
    UserOnboardingFactory,
    UserSportPreferenceFactory,
)


class UserOnboardingModelTests(TestCase):
    """Tests for the UserOnboarding model."""

    def test_str_representation(self):
        onboarding = UserOnboardingFactory()
        expected = f"Onboarding for {onboarding.user} ({onboarding.current_step})"
        self.assertEqual(str(onboarding), expected)

    def test_completion_percentage_when_completed(self):
        onboarding = UserOnboardingFactory(completed=True)
        self.assertEqual(onboarding.completion_percentage, 100)

    def test_completion_percentage_at_country_step(self):
        onboarding = UserOnboardingFactory(
            current_step=UserOnboarding.Step.COUNTRY, completed=False
        )
        self.assertEqual(onboarding.completion_percentage, 0)

    def test_completion_percentage_at_sports_step(self):
        onboarding = UserOnboardingFactory(current_step=UserOnboarding.Step.SPORTS, completed=False)
        self.assertEqual(onboarding.completion_percentage, 25)

    def test_completion_percentage_at_competitions_step(self):
        onboarding = UserOnboardingFactory(
            current_step=UserOnboarding.Step.COMPETITIONS, completed=False
        )
        self.assertEqual(onboarding.completion_percentage, 50)

    def test_completion_percentage_at_clubs_step(self):
        onboarding = UserOnboardingFactory(current_step=UserOnboarding.Step.CLUBS, completed=False)
        self.assertEqual(onboarding.completion_percentage, 75)

    def test_completed_steps_when_completed(self):
        onboarding = UserOnboardingFactory(completed=True)
        expected_steps = [
            UserOnboarding.Step.COUNTRY,
            UserOnboarding.Step.SPORTS,
            UserOnboarding.Step.COMPETITIONS,
            UserOnboarding.Step.CLUBS,
        ]
        self.assertEqual(onboarding.completed_steps, expected_steps)

    def test_completed_steps_at_sports_step(self):
        onboarding = UserOnboardingFactory(current_step=UserOnboarding.Step.SPORTS, completed=False)
        self.assertEqual(onboarding.completed_steps, [UserOnboarding.Step.COUNTRY])

    def test_unique_constraint(self):
        user = UserFactory()
        UserOnboardingFactory(user=user)
        with self.assertRaises(IntegrityError):
            UserOnboardingFactory(user=user)


class UserSportPreferenceModelTests(TestCase):
    """Tests for the UserSportPreference model."""

    def test_str_representation(self):
        pref = UserSportPreferenceFactory()
        expected = f"{pref.user} → {pref.sport}"
        self.assertEqual(str(pref), expected)


class UserCompetitionPreferenceModelTests(TestCase):
    """Tests for the UserCompetitionPreference model."""

    def test_str_representation(self):
        pref = UserCompetitionPreferenceFactory()
        expected = f"{pref.user} → {pref.competition}"
        self.assertEqual(str(pref), expected)


class UserClubPreferenceModelTests(TestCase):
    """Tests for the UserClubPreference model."""

    def test_str_representation(self):
        pref = UserClubPreferenceFactory()
        expected = f"{pref.user} → {pref.club}"
        self.assertEqual(str(pref), expected)


class OnboardingAnalyticsEventModelTests(TestCase):
    """Tests for the OnboardingAnalyticsEvent model."""

    def test_str_representation(self):
        event = OnboardingAnalyticsEventFactory()
        self.assertIn(event.event_type, str(event))
        self.assertIn(str(event.user), str(event))

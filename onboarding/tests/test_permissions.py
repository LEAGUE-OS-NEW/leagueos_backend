"""Tests for onboarding permissions."""

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from onboarding.tests.factories import UserFactory, UserOnboardingFactory


class IsOnboardingOwnerTests(TestCase):
    """Tests for the IsOnboardingOwner permission."""

    def setUp(self):
        self.client = APIClient()
        self.user = UserFactory()
        self.other_user = UserFactory()
        self.onboarding = UserOnboardingFactory(user=self.user)

    def test_owner_can_access(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("onboarding:onboarding-status")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_unauthenticated_cannot_access(self):
        url = reverse("onboarding:onboarding-status")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

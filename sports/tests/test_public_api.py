from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from sports.models import (
    Competition,
    EventParticipant,
    Participant,
    Sport,
    SportingEvent,
)


class PublicSportsCatalogueAPITests(APITestCase):
    def setUp(self):
        self.now = timezone.now()

        self.football = Sport.objects.create(
            name="Football",
            code="FOOTBALL",
        )
        self.inactive_rugby = Sport.objects.create(
            name="Rugby",
            code="RUGBY",
            is_active=False,
        )

        self.competition = Competition.objects.create(
            sport=self.football,
            name="Uganda Premier League",
            country_code="UG",
            is_verified=True,
        )
        self.unverified_competition = Competition.objects.create(
            sport=self.football,
            name="Unverified League",
            country_code="UG",
            is_verified=False,
        )

        self.kcca = Participant.objects.create(
            sport=self.football,
            kind=Participant.Kind.TEAM,
            name="KCCA FC",
            short_name="KCCA",
            country_code="UG",
            is_verified=True,
        )
        self.vipers = Participant.objects.create(
            sport=self.football,
            kind=Participant.Kind.TEAM,
            name="Vipers SC",
            short_name="Vipers",
            country_code="UG",
            is_verified=True,
        )
        self.unverified_team = Participant.objects.create(
            sport=self.football,
            kind=Participant.Kind.TEAM,
            name="Unverified FC",
            country_code="UG",
            is_verified=False,
        )

        self.event = SportingEvent.objects.create(
            sport=self.football,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="KCCA FC vs Vipers SC",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

        EventParticipant.objects.create(
            event=self.event,
            participant=self.kcca,
            role=EventParticipant.Role.HOME,
            position=1,
        )
        EventParticipant.objects.create(
            event=self.event,
            participant=self.vipers,
            role=EventParticipant.Role.AWAY,
            position=2,
        )

        self.external_event = SportingEvent.objects.create(
            sport=self.football,
            competition=None,
            event_type=(SportingEvent.EventType.MATCH),
            name="Arsenal FC vs Chelsea FC",
            starts_at=self.now + timedelta(days=3),
            status=SportingEvent.Status.SCHEDULED,
            source_name="sports-provider",
            source_reference="fixture-123",
            is_verified=True,
            verified_at=self.now,
        )

        self.unverified_event = SportingEvent.objects.create(
            sport=self.football,
            competition=self.competition,
            event_type=(SportingEvent.EventType.MATCH),
            name="Unverified match",
            starts_at=self.now + timedelta(days=4),
            status=SportingEvent.Status.SCHEDULED,
        )

    def test_sport_list_excludes_inactive_sports(self):
        response = self.client.get(
            reverse("sports:sport-list"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        sport_ids = {item["id"] for item in response.data["results"]}

        self.assertIn(
            str(self.football.id),
            sport_ids,
        )
        self.assertNotIn(
            str(self.inactive_rugby.id),
            sport_ids,
        )

    def test_competition_list_contains_verified_records(self):
        response = self.client.get(
            reverse("sports:competition-list"),
            {
                "sport": str(self.football.id),
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        competition_ids = {item["id"] for item in response.data["results"]}

        self.assertIn(
            str(self.competition.id),
            competition_ids,
        )
        self.assertNotIn(
            str(self.unverified_competition.id),
            competition_ids,
        )

    def test_participant_list_supports_sport_and_kind(self):
        response = self.client.get(
            reverse("sports:participant-list"),
            {
                "sport": str(self.football.id),
                "kind": Participant.Kind.TEAM,
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        participant_ids = {item["id"] for item in response.data["results"]}

        self.assertIn(
            str(self.kcca.id),
            participant_ids,
        )
        self.assertIn(
            str(self.vipers.id),
            participant_ids,
        )
        self.assertNotIn(
            str(self.unverified_team.id),
            participant_ids,
        )

    def test_event_list_excludes_unverified_events(self):
        response = self.client.get(
            reverse("sports:event-list"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        event_ids = {item["id"] for item in response.data["results"]}

        self.assertIn(
            str(self.event.id),
            event_ids,
        )
        self.assertIn(
            str(self.external_event.id),
            event_ids,
        )
        self.assertNotIn(
            str(self.unverified_event.id),
            event_ids,
        )

    def test_event_list_filters_by_participant(self):
        response = self.client.get(
            reverse("sports:event-list"),
            {
                "participant": str(self.kcca.id),
                "status": (SportingEvent.Status.SCHEDULED),
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["count"],
            1,
        )
        self.assertEqual(
            response.data["results"][0]["id"],
            str(self.event.id),
        )

    def test_external_event_can_have_no_competition(self):
        response = self.client.get(
            reverse("sports:event-list"),
            {
                "search": "Arsenal",
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["count"],
            1,
        )
        self.assertIsNone(response.data["results"][0]["competition"])

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from sports.models import (
    Competition,
    EventParticipant,
    Participant,
    Sport,
    SportingEvent,
)


class SportsCatalogueModelTests(TestCase):
    def setUp(self):
        self.football = Sport.objects.create(
            name="Football",
            code="football",
        )
        self.rugby = Sport.objects.create(
            name="Rugby",
            code="rugby",
        )

        self.upl = Competition.objects.create(
            sport=self.football,
            name="Uganda Premier League",
            country_code="ug",
        )

        self.kcca = Participant.objects.create(
            sport=self.football,
            kind=Participant.Kind.TEAM,
            name="KCCA FC",
            short_name="KCCA",
            country_code="ug",
        )
        self.vipers = Participant.objects.create(
            sport=self.football,
            kind=Participant.Kind.TEAM,
            name="Vipers SC",
            short_name="Vipers",
            country_code="ug",
        )

    def create_match(self, **overrides):
        values = {
            "sport": self.football,
            "competition": self.upl,
            "event_type": SportingEvent.EventType.MATCH,
            "name": "KCCA FC vs Vipers SC",
            "starts_at": timezone.now(),
            "status": SportingEvent.Status.SCHEDULED,
        }
        values.update(overrides)

        return SportingEvent.objects.create(**values)

    def test_sport_normalizes_code_and_slug(self):
        self.assertEqual(
            self.football.code,
            "FOOTBALL",
        )
        self.assertEqual(
            self.football.slug,
            "football",
        )

    def test_competition_normalizes_country_and_slug(self):
        self.assertEqual(
            self.upl.country_code,
            "UG",
        )
        self.assertEqual(
            self.upl.slug,
            "uganda-premier-league",
        )

    def test_participant_normalizes_country_and_slug(self):
        self.assertEqual(
            self.kcca.country_code,
            "UG",
        )
        self.assertEqual(
            self.kcca.slug,
            "kcca-fc",
        )

    def test_event_can_exist_without_competition(self):
        event = self.create_match(
            competition=None,
            name="Uganda vs Kenya Friendly",
        )

        self.assertIsNone(event.competition)

    def test_external_event_does_not_require_platform_club(self):
        arsenal = Participant.objects.create(
            sport=self.football,
            kind=Participant.Kind.TEAM,
            name="Arsenal FC",
            country_code="GB",
            source_name="sports-provider",
            source_reference="team-arsenal",
            is_verified=True,
        )
        chelsea = Participant.objects.create(
            sport=self.football,
            kind=Participant.Kind.TEAM,
            name="Chelsea FC",
            country_code="GB",
            source_name="sports-provider",
            source_reference="team-chelsea",
            is_verified=True,
        )

        event = self.create_match(
            competition=None,
            name="Arsenal FC vs Chelsea FC",
            source_name="sports-provider",
            source_reference="fixture-12345",
        )

        EventParticipant.objects.create(
            event=event,
            participant=arsenal,
            role=EventParticipant.Role.HOME,
            position=1,
        )
        EventParticipant.objects.create(
            event=event,
            participant=chelsea,
            role=EventParticipant.Role.AWAY,
            position=2,
        )

        self.assertEqual(
            event.event_participants.count(),
            2,
        )

    def test_event_rejects_competition_from_another_sport(self):
        rugby_competition = Competition.objects.create(
            sport=self.rugby,
            name="Uganda Rugby Premiership",
            country_code="UG",
        )

        event = SportingEvent(
            sport=self.football,
            competition=rugby_competition,
            event_type=SportingEvent.EventType.MATCH,
            name="Invalid event",
            starts_at=timezone.now(),
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        self.assertIn(
            "competition",
            context.exception.message_dict,
        )

    def test_event_participant_must_match_event_sport(self):
        rugby_team = Participant.objects.create(
            sport=self.rugby,
            kind=Participant.Kind.TEAM,
            name="KOBs Rugby Club",
            country_code="UG",
        )
        event = self.create_match()

        entry = EventParticipant(
            event=event,
            participant=rugby_team,
            role=EventParticipant.Role.AWAY,
            position=2,
        )

        with self.assertRaises(ValidationError) as context:
            entry.full_clean()

        self.assertIn(
            "participant",
            context.exception.message_dict,
        )

    def test_match_has_unique_home_and_away_roles(self):
        event = self.create_match()

        EventParticipant.objects.create(
            event=event,
            participant=self.kcca,
            role=EventParticipant.Role.HOME,
            position=1,
        )

        another_team = Participant.objects.create(
            sport=self.football,
            kind=Participant.Kind.TEAM,
            name="SC Villa",
            country_code="UG",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EventParticipant.objects.create(
                    event=event,
                    participant=another_team,
                    role=EventParticipant.Role.HOME,
                    position=2,
                )

    def test_tournament_supports_multiple_competitors(self):
        event = SportingEvent.objects.create(
            sport=self.rugby,
            competition=None,
            event_type=SportingEvent.EventType.TOURNAMENT,
            name="Kampala Rugby Sevens",
            starts_at=timezone.now(),
        )

        for position, name in enumerate(
            [
                "KOBs",
                "Heathens",
                "Pirates",
            ],
            start=1,
        ):
            participant = Participant.objects.create(
                sport=self.rugby,
                kind=Participant.Kind.TEAM,
                name=name,
                country_code="UG",
            )

            EventParticipant.objects.create(
                event=event,
                participant=participant,
                role=EventParticipant.Role.COMPETITOR,
                position=position,
            )

        self.assertEqual(
            event.participants.count(),
            3,
        )

    def test_verified_event_requires_timestamp(self):
        event = SportingEvent(
            sport=self.football,
            competition=self.upl,
            event_type=SportingEvent.EventType.MATCH,
            name="KCCA FC vs Vipers SC",
            starts_at=timezone.now(),
            is_verified=True,
            verified_at=None,
        )

        with self.assertRaises(ValidationError) as context:
            event.full_clean()

        self.assertIn(
            "verified_at",
            context.exception.message_dict,
        )


class SeedSportsCommandTests(TestCase):
    def test_command_creates_supported_sports(self):
        call_command(
            "seed_sports",
            verbosity=0,
        )

        self.assertEqual(
            set(
                Sport.objects.values_list(
                    "code",
                    flat=True,
                )
            ),
            {
                "FOOTBALL",
                "RUGBY",
                "BASKETBALL",
            },
        )

    def test_command_is_idempotent(self):
        call_command(
            "seed_sports",
            verbosity=0,
        )
        first_count = Sport.objects.count()

        call_command(
            "seed_sports",
            verbosity=0,
        )

        self.assertEqual(
            Sport.objects.count(),
            first_count,
        )

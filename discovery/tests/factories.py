"""Factory Boy factories for discovery module tests."""

from __future__ import annotations

import uuid

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory
from faker import Faker

from accounts.models import User
from discovery.models import (
    AuditLog,
    ClubProfile,
    MatchBroadcast,
    MatchCentre,
    MatchLineup,
    MatchOfficial,
    MatchPlayerStatistic,
    MatchTeamStatistic,
    MatchTimelineEvent,
    News,
    NewsCategory,
    PlayerProfile,
    SearchAnalytics,
    SearchSuggestion,
    Season,
    SportsFeedIngestion,
    SportsFeedProvider,
    Venue,
)
from onboarding.models import UserClubPreference
from profiles.models import Club
from sports.models import Competition, EventParticipant, Participant, Sport, SportingEvent

fake = Faker()


class UserFactory(DjangoModelFactory):
    """Factory for the User model."""

    class Meta:
        model = User
        django_get_or_create = ("email",)

    id = factory.LazyFunction(uuid.uuid4)
    email = factory.Sequence(lambda n: f"user{n}@leagueos.com")
    username = factory.Sequence(lambda n: f"user{n}")
    first_name = fake.first_name()
    last_name = fake.last_name()
    is_verified = True
    is_active = True


class SportFactory(DjangoModelFactory):
    """Factory for the Sport model."""

    class Meta:
        model = Sport
        django_get_or_create = ("name",)

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"Sport {n}")
    code = factory.Sequence(lambda n: f"SPORT{n}")
    slug = factory.Sequence(lambda n: f"sport-{n}")
    is_active = True


class CompetitionFactory(DjangoModelFactory):
    """Factory for the Competition model."""

    class Meta:
        model = Competition
        django_get_or_create = ("name",)

    id = factory.LazyFunction(uuid.uuid4)
    sport = factory.SubFactory(SportFactory)
    name = factory.Sequence(lambda n: f"Competition {n}")
    slug = factory.Sequence(lambda n: f"competition-{n}")
    country_code = "UG"
    is_active = True
    is_verified = True


class ClubFactory(DjangoModelFactory):
    """Factory for the Club model."""

    class Meta:
        model = Club
        django_get_or_create = ("name",)

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"Club {n}")
    slug = factory.Sequence(lambda n: f"club-{n}")
    sport = factory.SubFactory(SportFactory)
    competition = factory.SubFactory(CompetitionFactory)
    is_active = True


class ParticipantFactory(DjangoModelFactory):
    """Factory for the Participant model."""

    class Meta:
        model = Participant

    id = factory.LazyFunction(uuid.uuid4)
    sport = factory.SubFactory(SportFactory)
    kind = Participant.Kind.TEAM
    name = factory.Sequence(lambda n: f"Participant {n}")
    short_name = factory.Sequence(lambda n: f"P{n}")
    slug = factory.Sequence(lambda n: f"participant-{n}")
    country_code = "UG"
    is_active = True
    is_verified = True


class PlayerParticipantFactory(ParticipantFactory):
    """Factory for an athlete participant."""

    kind = Participant.Kind.ATHLETE
    name = factory.Sequence(lambda n: f"Athlete {n}")
    short_name = factory.Sequence(lambda n: f"A{n}")


class SportingEventFactory(DjangoModelFactory):
    """Factory for the canonical SportingEvent (fixture)."""

    class Meta:
        model = SportingEvent

    id = factory.LazyFunction(uuid.uuid4)
    sport = factory.SubFactory(SportFactory)
    competition = factory.SubFactory(CompetitionFactory)
    event_type = SportingEvent.EventType.MATCH
    name = factory.Sequence(lambda n: f"Fixture {n}")
    starts_at = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(days=7))
    status = SportingEvent.Status.SCHEDULED
    venue = factory.Sequence(lambda n: f"Stadium {n}")
    country_code = "UG"
    is_verified = True
    verified_at = factory.LazyFunction(lambda: timezone.now())


class EventParticipantFactory(DjangoModelFactory):
    """Factory for EventParticipant."""

    class Meta:
        model = EventParticipant

    id = factory.LazyFunction(uuid.uuid4)
    event = factory.SubFactory(SportingEventFactory)
    participant = factory.SubFactory(ParticipantFactory)
    role = EventParticipant.Role.HOME
    position = 1


class VenueFactory(DjangoModelFactory):
    """Factory for Venue."""

    class Meta:
        model = Venue
        django_get_or_create = ("name",)

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"Venue {n}")
    slug = factory.Sequence(lambda n: f"venue-{n}")
    country_code = "UG"
    city = fake.city()
    capacity = 50000
    is_active = True
    is_verified = True


class SeasonFactory(DjangoModelFactory):
    """Factory for Season."""

    class Meta:
        model = Season

    id = factory.LazyFunction(uuid.uuid4)
    sport = factory.SubFactory(SportFactory)
    competition = factory.SubFactory(CompetitionFactory)
    name = factory.Sequence(lambda n: f"Season {n}")
    slug = factory.Sequence(lambda n: f"season-{n}")
    is_active = True
    is_verified = True


class ClubProfileFactory(DjangoModelFactory):
    """Factory for ClubProfile."""

    class Meta:
        model = ClubProfile

    id = factory.LazyFunction(uuid.uuid4)
    club = factory.SubFactory(ClubFactory)
    stadium = fake.company()
    coach = fake.name()
    is_published = True
    is_verified = True


class PlayerProfileFactory(DjangoModelFactory):
    """Factory for PlayerProfile."""

    class Meta:
        model = PlayerProfile

    id = factory.LazyFunction(uuid.uuid4)
    participant = factory.SubFactory(PlayerParticipantFactory)
    club = factory.SubFactory(ClubFactory)
    position = "Forward"
    shirt_number = 9
    is_published = True
    is_verified = True


class NewsCategoryFactory(DjangoModelFactory):
    """Factory for NewsCategory."""

    class Meta:
        model = NewsCategory
        django_get_or_create = ("code",)

    id = factory.LazyFunction(uuid.uuid4)
    code = factory.Sequence(lambda n: f"CATEGORY{n}")
    name = factory.Sequence(lambda n: f"Category {n}")
    is_active = True


class NewsFactory(DjangoModelFactory):
    """Factory for News."""

    class Meta:
        model = News

    id = factory.LazyFunction(uuid.uuid4)
    title = factory.Sequence(lambda n: f"News {n}")
    summary = fake.text(max_nb_chars=200)
    body = fake.text()
    category = factory.SubFactory(NewsCategoryFactory)
    status = News.Status.PUBLISHED
    is_verified = True


class MatchCentreFactory(DjangoModelFactory):
    """Factory for MatchCentre."""

    class Meta:
        model = MatchCentre

    id = factory.LazyFunction(uuid.uuid4)
    fixture = factory.SubFactory(SportingEventFactory)
    result = "2-1"
    home_score = 2
    away_score = 1
    data_confidence = "0.95"
    feed_status = MatchCentre.FeedStatus.COMPLETED
    is_verified = True


class MatchLineupFactory(DjangoModelFactory):
    """Factory for MatchLineup."""

    class Meta:
        model = MatchLineup

    id = factory.LazyFunction(uuid.uuid4)
    match_centre = factory.SubFactory(MatchCentreFactory)
    participant = factory.SubFactory(PlayerParticipantFactory)
    player = factory.SubFactory(PlayerParticipantFactory)
    side = "HOME"
    position = "Forward"
    shirt_number = 9
    is_starter = True


class MatchPlayerStatisticFactory(DjangoModelFactory):
    """Factory for MatchPlayerStatistic."""

    class Meta:
        model = MatchPlayerStatistic

    id = factory.LazyFunction(uuid.uuid4)
    match_centre = factory.SubFactory(MatchCentreFactory)
    participant = factory.SubFactory(PlayerParticipantFactory)
    stat_type = "GOALS"
    value = 1


class MatchTeamStatisticFactory(DjangoModelFactory):
    """Factory for MatchTeamStatistic."""

    class Meta:
        model = MatchTeamStatistic

    id = factory.LazyFunction(uuid.uuid4)
    match_centre = factory.SubFactory(MatchCentreFactory)
    participant = factory.SubFactory(ParticipantFactory)
    stat_type = "POSSESSION"
    value = 55


class MatchTimelineEventFactory(DjangoModelFactory):
    """Factory for MatchTimelineEvent."""

    class Meta:
        model = MatchTimelineEvent

    id = factory.LazyFunction(uuid.uuid4)
    match_centre = factory.SubFactory(MatchCentreFactory)
    event_type = MatchTimelineEvent.EventType.GOAL
    minute = 23
    participant = factory.SubFactory(ParticipantFactory)
    player = factory.SubFactory(PlayerParticipantFactory)


class MatchOfficialFactory(DjangoModelFactory):
    """Factory for MatchOfficial."""

    class Meta:
        model = MatchOfficial

    id = factory.LazyFunction(uuid.uuid4)
    match_centre = factory.SubFactory(MatchCentreFactory)
    role = "REFEREE"
    name = fake.name()


class MatchBroadcastFactory(DjangoModelFactory):
    """Factory for MatchBroadcast."""

    class Meta:
        model = MatchBroadcast

    id = factory.LazyFunction(uuid.uuid4)
    match_centre = factory.SubFactory(MatchCentreFactory)
    provider = fake.company()
    country_code = "UG"


class SportsFeedProviderFactory(DjangoModelFactory):
    """Factory for SportsFeedProvider."""

    class Meta:
        model = SportsFeedProvider
        django_get_or_create = ("code",)

    id = factory.LazyFunction(uuid.uuid4)
    code = factory.Sequence(lambda n: f"PROVIDER{n}")
    name = factory.Sequence(lambda n: f"Provider {n}")
    is_active = True


class SportsFeedIngestionFactory(DjangoModelFactory):
    """Factory for SportsFeedIngestion."""

    class Meta:
        model = SportsFeedIngestion

    id = factory.LazyFunction(uuid.uuid4)
    provider = factory.SubFactory(SportsFeedProviderFactory)
    status = SportsFeedIngestion.Status.PENDING
    confidence = 0.0
    is_verified = False


class SearchAnalyticsFactory(DjangoModelFactory):
    """Factory for SearchAnalytics."""

    class Meta:
        model = SearchAnalytics

    id = factory.LazyFunction(uuid.uuid4)
    query = factory.Sequence(lambda n: f"query-{n}")
    duration_ms = 10
    result_count = 5
    applied_filters = {}


class SearchSuggestionFactory(DjangoModelFactory):
    """Factory for SearchSuggestion."""

    class Meta:
        model = SearchSuggestion

    id = factory.LazyFunction(uuid.uuid4)
    suggestion_type = SearchSuggestion.SuggestionType.POPULAR
    entity_type = "club"
    entity_id = factory.LazyFunction(uuid.uuid4)
    display_name = factory.Sequence(lambda n: f"Suggestion {n}")
    score = 10
    is_active = True


class AuditLogFactory(DjangoModelFactory):
    """Factory for AuditLog."""

    class Meta:
        model = AuditLog

    id = factory.LazyFunction(uuid.uuid4)
    action = AuditLog.ACTION_CHOICES[0][0]
    entity_type = "club"
    metadata = {}


class UserClubPreferenceFactory(DjangoModelFactory):
    """Factory for UserClubPreference (following)."""

    class Meta:
        model = UserClubPreference
        django_get_or_create = ("user", "club")

    id = factory.LazyFunction(uuid.uuid4)
    user = factory.SubFactory(UserFactory)
    club = factory.SubFactory(ClubFactory)

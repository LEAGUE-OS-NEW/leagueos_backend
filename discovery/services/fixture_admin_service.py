"""Fixture admin service — the write-side counterpart to fixture_service.py.
Lets Sports Data & Statistics Admin / Super Admin create a fixture, move it
through its lifecycle (scheduled -> live -> completed, or postponed/
cancelled), and enter/update its score and live clock."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from discovery.models import MatchCentre
from sports.models import EventParticipant, SportingEvent


class FixtureAdminService:
    """Service for fixture creation and moderation."""

    @staticmethod
    @transaction.atomic
    def create_fixture(
        *, sport, competition, home_participant, away_participant, starts_at, venue, actor
    ):
        """Create a fixture between two participants. Admin-authored
        fixtures are verified immediately (no separate review step),
        mirroring how admin-authored Sports/Competitions/Participants
        already work elsewhere in this app."""
        name = f"{home_participant.name} vs {away_participant.name}"
        fixture = SportingEvent.objects.create(
            sport=sport,
            competition=competition,
            name=name,
            starts_at=starts_at,
            venue=venue,
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=timezone.now(),
        )
        EventParticipant.objects.create(
            event=fixture,
            participant=home_participant,
            role=EventParticipant.Role.HOME,
            position=1,
        )
        EventParticipant.objects.create(
            event=fixture,
            participant=away_participant,
            role=EventParticipant.Role.AWAY,
            position=2,
        )
        return fixture

    @staticmethod
    def list_admin_fixtures():
        """All fixtures regardless of verification/status, newest kickoff
        first, for the admin table."""
        return (
            SportingEvent.objects.select_related(
                "sport", "competition", "competition__sport", "match_centre"
            )
            .prefetch_related("event_participants__participant")
            .order_by("-starts_at")
        )

    @staticmethod
    def set_status(*, fixture, status):
        fixture.status = status
        fixture.save(update_fields=["status", "updated_at"])
        return fixture

    @staticmethod
    def update_score(*, fixture, home_score, away_score, clock_display):
        match_centre, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        match_centre.home_score = home_score
        match_centre.away_score = away_score
        match_centre.clock_display = clock_display
        match_centre.feed_status = MatchCentre.FeedStatus.PROCESSING
        match_centre.is_verified = True
        match_centre.save(
            update_fields=[
                "home_score",
                "away_score",
                "clock_display",
                "feed_status",
                "is_verified",
            ]
        )
        return fixture

    @staticmethod
    @transaction.atomic
    def complete_fixture(*, fixture):
        fixture.status = SportingEvent.Status.COMPLETED
        if fixture.ends_at is None:
            fixture.ends_at = timezone.now()
        fixture.save(update_fields=["status", "ends_at", "updated_at"])

        match_centre, _ = MatchCentre.objects.get_or_create(fixture=fixture)
        match_centre.feed_status = MatchCentre.FeedStatus.COMPLETED
        match_centre.save(update_fields=["feed_status"])
        return fixture


fixture_admin_service = FixtureAdminService()

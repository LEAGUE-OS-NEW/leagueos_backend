"""Serializers for the discovery module."""

from __future__ import annotations

from rest_framework import serializers

from discovery.models import (
    MatchLineup,
    MatchOfficial,
    MatchPlayerStatistic,
    MatchTeamStatistic,
    MatchTimelineEvent,
    News,
)
from onboarding.models import UserClubPreference
from profiles.models import Club
from sports.models import Competition, Participant, SportingEvent

# =============================================================================
# Search
# =============================================================================


class SearchQuerySerializer(serializers.Serializer):
    """Query parameters for the search endpoint."""

    q = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
    )
    sport = serializers.UUIDField(required=False)
    competition = serializers.UUIDField(required=False)
    country = serializers.CharField(required=False, max_length=2)
    club = serializers.UUIDField(required=False)
    season = serializers.UUIDField(required=False)
    page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=100,
        default=20,
    )
    ordering = serializers.ChoiceField(
        choices=["relevance", "name", "-created_at"],
        required=False,
        default="relevance",
    )


class SearchResultSerializer(serializers.Serializer):
    """A single search result."""

    id = serializers.UUIDField()
    entity_type = serializers.CharField()
    display_name = serializers.CharField()
    slug = serializers.CharField(required=False, allow_blank=True)
    country_code = serializers.CharField(required=False, allow_blank=True)
    sport = serializers.UUIDField(required=False, allow_null=True)
    competition = serializers.UUIDField(required=False, allow_null=True)
    status = serializers.CharField(required=False, allow_blank=True)
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    logo = serializers.CharField(required=False, allow_blank=True)


class SearchResponseSerializer(serializers.Serializer):
    """Search response envelope."""

    results = SearchResultSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


class AutocompleteQuerySerializer(serializers.Serializer):
    """Query parameters for autocomplete."""

    q = serializers.CharField(required=False, allow_blank=True, max_length=200)
    entity_type = serializers.ChoiceField(
        choices=["club", "player", "competition", "venue", "all"],
        required=False,
        default="all",
    )
    limit = serializers.IntegerField(required=False, min_value=1, max_value=20, default=10)


class AutocompleteResultSerializer(serializers.Serializer):
    """A single autocomplete result."""

    uuid = serializers.UUIDField()
    display_name = serializers.CharField()
    entity_type = serializers.CharField()
    logo = serializers.CharField(required=False, allow_blank=True)


class SuggestionSerializer(serializers.Serializer):
    """A single search suggestion."""

    suggestion_type = serializers.CharField()
    entity_type = serializers.CharField()
    entity_id = serializers.UUIDField()
    display_name = serializers.CharField()


# =============================================================================
# Clubs
# =============================================================================


class ClubListQuerySerializer(serializers.Serializer):
    """Query parameters for the club list endpoint."""

    sport = serializers.UUIDField(required=False)
    country = serializers.CharField(required=False, max_length=2)
    search = serializers.CharField(required=False, allow_blank=True, max_length=180)
    ordering = serializers.ChoiceField(
        choices=["name", "-name", "founded", "-founded"],
        required=False,
        default="name",
    )


class DiscoveryClubSerializer(serializers.ModelSerializer):
    """Public club serializer."""

    sport = serializers.UUIDField(source="sport_id", read_only=True)
    competition = serializers.UUIDField(source="competition_id", read_only=True)

    class Meta:
        model = Club
        fields = [
            "id",
            "name",
            "slug",
            "sport",
            "competition",
            "founded",
        ]


class ClubProfileSerializer(serializers.Serializer):
    """Extended club profile data."""

    logo = serializers.CharField(required=False, allow_null=True)
    country = serializers.UUIDField(required=False, allow_null=True)
    stadium = serializers.CharField(required=False, allow_blank=True)
    coach = serializers.CharField(required=False, allow_blank=True)
    league = serializers.UUIDField(required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True)
    social_links = serializers.JSONField(required=False)
    current_season = serializers.UUIDField(required=False, allow_null=True)


class ClubDetailResponseSerializer(serializers.Serializer):
    """Full club profile response."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    sport = serializers.UUIDField(required=False, allow_null=True)
    competition = serializers.UUIDField(required=False, allow_null=True)
    founded = serializers.IntegerField(required=False, allow_null=True)
    profile = ClubProfileSerializer(required=False, allow_null=True)


# =============================================================================
# Players
# =============================================================================


class PlayerListQuerySerializer(serializers.Serializer):
    """Query parameters for the player list endpoint."""

    sport = serializers.UUIDField(required=False)
    club = serializers.UUIDField(required=False)
    search = serializers.CharField(required=False, allow_blank=True, max_length=180)
    ordering = serializers.ChoiceField(
        choices=["name", "created_at", "-created_at"],
        required=False,
        default="name",
    )


class PlayerSerializer(serializers.ModelSerializer):
    """Public player serializer."""

    sport = serializers.UUIDField(source="sport_id", read_only=True)

    class Meta:
        model = Participant
        fields = [
            "id",
            "name",
            "short_name",
            "slug",
            "sport",
            "country_code",
        ]


class PlayerProfileSerializer(serializers.Serializer):
    """Extended player profile data."""

    club = serializers.UUIDField(required=False, allow_null=True)
    position = serializers.CharField(required=False, allow_blank=True)
    shirt_number = serializers.IntegerField(required=False, allow_null=True)
    nationality = serializers.UUIDField(required=False, allow_null=True)
    biography = serializers.CharField(required=False, allow_blank=True)
    career_history = serializers.JSONField(required=False)
    statistics = serializers.JSONField(required=False)
    status = serializers.CharField(required=False)


class PlayerDetailResponseSerializer(serializers.Serializer):
    """Full player profile response."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    short_name = serializers.CharField(required=False, allow_blank=True)
    slug = serializers.CharField()
    sport = serializers.UUIDField(required=False, allow_null=True)
    country_code = serializers.CharField(required=False, allow_blank=True)
    profile = PlayerProfileSerializer(required=False, allow_null=True)


# =============================================================================
# Competitions
# =============================================================================


class CompetitionSerializer(serializers.ModelSerializer):
    """Public competition serializer."""

    sport = serializers.UUIDField(source="sport_id", read_only=True)

    class Meta:
        model = Competition
        fields = [
            "id",
            "name",
            "slug",
            "country_code",
            "sport",
        ]


# =============================================================================
# Fixtures & Results
# =============================================================================


class FixtureListQuerySerializer(serializers.Serializer):
    """Query parameters for the fixture list endpoint."""

    sport = serializers.UUIDField(required=False)
    competition = serializers.UUIDField(required=False)
    club = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(
        choices=SportingEvent.Status.choices,
        required=False,
    )
    date_from = serializers.DateTimeField(required=False)
    date_to = serializers.DateTimeField(required=False)
    ordering = serializers.ChoiceField(
        choices=["starts_at", "-starts_at", "name", "-name"],
        required=False,
        default="starts_at",
    )


class FixtureParticipantSerializer(serializers.Serializer):
    """A participant in a fixture."""

    role = serializers.CharField()
    position = serializers.IntegerField()
    participant = serializers.DictField()


class FixtureSerializer(serializers.Serializer):
    """Public fixture serializer."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    event_type = serializers.CharField()
    status = serializers.CharField()
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    venue = serializers.CharField(required=False, allow_blank=True)
    country_code = serializers.CharField(required=False, allow_blank=True)
    sport = serializers.UUIDField(required=False, allow_null=True)
    competition = serializers.UUIDField(required=False, allow_null=True)
    participants = FixtureParticipantSerializer(many=True, required=False)


# =============================================================================
# News
# =============================================================================


class NewsListQuerySerializer(serializers.Serializer):
    """Query parameters for the news list endpoint."""

    category = serializers.UUIDField(required=False)
    sport = serializers.UUIDField(required=False)
    competition = serializers.UUIDField(required=False)
    club = serializers.UUIDField(required=False)
    featured = serializers.BooleanField(required=False)
    search = serializers.CharField(required=False, allow_blank=True, max_length=180)
    ordering = serializers.ChoiceField(
        choices=["-published_at", "published_at", "-created_at"],
        required=False,
        default="-published_at",
    )


class NewsSerializer(serializers.ModelSerializer):
    """Public news serializer (published & verified only)."""

    category = serializers.UUIDField(source="category_id", read_only=True)
    sport = serializers.UUIDField(source="sport_id", read_only=True, allow_null=True)
    competition = serializers.UUIDField(
        source="competition_id",
        read_only=True,
        allow_null=True,
    )
    club = serializers.UUIDField(source="club_id", read_only=True, allow_null=True)

    class Meta:
        model = News
        fields = [
            "id",
            "title",
            "slug",
            "summary",
            "body",
            "category",
            "sport",
            "competition",
            "club",
            "is_featured",
            "published_at",
        ]


# =============================================================================
# Match Centre
# =============================================================================


class MatchCentreLineupSerializer(serializers.ModelSerializer):
    """Lineup entry serializer."""

    player = serializers.UUIDField(source="player_id", read_only=True, allow_null=True)

    class Meta:
        model = MatchLineup
        fields = [
            "id",
            "side",
            "position",
            "shirt_number",
            "is_starter",
            "player",
        ]


class MatchCentrePlayerStatSerializer(serializers.ModelSerializer):
    """Player statistic serializer."""

    participant = serializers.UUIDField(source="participant_id", read_only=True)

    class Meta:
        model = MatchPlayerStatistic
        fields = [
            "participant",
            "stat_type",
            "value",
        ]


class MatchCentreTeamStatSerializer(serializers.ModelSerializer):
    """Team statistic serializer."""

    participant = serializers.UUIDField(source="participant_id", read_only=True)

    class Meta:
        model = MatchTeamStatistic
        fields = [
            "participant",
            "stat_type",
            "value",
        ]


class MatchCentreTimelineSerializer(serializers.ModelSerializer):
    """Timeline event serializer."""

    participant = serializers.UUIDField(
        source="participant_id",
        read_only=True,
        allow_null=True,
    )
    player = serializers.UUIDField(source="player_id", read_only=True, allow_null=True)

    class Meta:
        model = MatchTimelineEvent
        fields = [
            "id",
            "event_type",
            "minute",
            "participant",
            "player",
            "description",
        ]


class MatchCentreOfficialSerializer(serializers.ModelSerializer):
    """Official serializer."""

    class Meta:
        model = MatchOfficial
        fields = [
            "id",
            "role",
            "name",
        ]


class MatchCentreVenueSerializer(serializers.Serializer):
    """Venue serializer for match centre."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    city = serializers.CharField(required=False, allow_blank=True)
    capacity = serializers.IntegerField(required=False, allow_null=True)


class MatchCentreFixtureSerializer(serializers.Serializer):
    """Fixture summary within match centre."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    status = serializers.CharField()
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    sport = serializers.UUIDField(required=False, allow_null=True)
    competition = serializers.UUIDField(required=False, allow_null=True)


class MatchCentreSerializer(serializers.Serializer):
    """Aggregated match centre response."""

    fixture = MatchCentreFixtureSerializer()
    result = serializers.CharField(required=False, allow_blank=True)
    home_score = serializers.IntegerField(required=False, allow_null=True)
    away_score = serializers.IntegerField(required=False, allow_null=True)
    attendance = serializers.IntegerField(required=False, allow_null=True)
    venue = MatchCentreVenueSerializer(required=False, allow_null=True)
    lineups = MatchCentreLineupSerializer(many=True, required=False)
    player_statistics = MatchCentrePlayerStatSerializer(many=True, required=False)
    team_statistics = MatchCentreTeamStatSerializer(many=True, required=False)
    timeline = MatchCentreTimelineSerializer(many=True, required=False)
    officials = MatchCentreOfficialSerializer(many=True, required=False)
    broadcasts = serializers.ListField(required=False, child=serializers.DictField())
    data_confidence = serializers.CharField(required=False)
    feed_status = serializers.CharField(required=False)
    last_updated = serializers.DateTimeField(required=False, allow_null=True)


# =============================================================================
# Following
# =============================================================================


class FollowSerializer(serializers.ModelSerializer):
    """Serializer for a followed club."""

    club = serializers.UUIDField(source="club_id", read_only=True)
    club_name = serializers.CharField(source="club.name", read_only=True)
    club_slug = serializers.CharField(source="club.slug", read_only=True)

    class Meta:
        model = UserClubPreference
        fields = [
            "id",
            "club",
            "club_name",
            "club_slug",
            "created_at",
        ]

"""Serializers for the discovery module."""

from __future__ import annotations

from django.utils import timezone
from rest_framework import serializers

from discovery.models import (
    MatchLineup,
    MatchOfficial,
    MatchPlayerStatistic,
    MatchTeamStatistic,
    MatchTimelineEvent,
    News,
    NewsCategory,
)
from onboarding.models import UserClubPreference
from profiles.models import Club
from sports.models import Competition, Participant, Sport, SportingEvent

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
    search = serializers.CharField(required=False, allow_blank=True, max_length=180)
    ordering = serializers.ChoiceField(
        choices=["name", "-name", "founded", "-founded", "created_at", "-created_at"],
        required=False,
        default="name",
    )
    has_admin = serializers.BooleanField(required=False)


class DiscoveryClubSerializer(serializers.ModelSerializer):
    """Public club serializer."""

    sport = serializers.UUIDField(source="sport_id", read_only=True)
    competition = serializers.UUIDField(source="competition_id", read_only=True)
    sport_name = serializers.CharField(
        source="sport.name", read_only=True, allow_null=True, default=None
    )
    competition_name = serializers.CharField(
        source="competition.name", read_only=True, allow_null=True, default=None
    )
    logo = serializers.SerializerMethodField()

    class Meta:
        model = Club
        fields = [
            "id",
            "name",
            "slug",
            "sport",
            "sport_name",
            "competition",
            "competition_name",
            "founded",
            "logo",
            "created_at",
        ]

    def get_logo(self, obj: Club) -> str | None:
        if not obj.logo:
            return None
        from profiles.services.storage_service import StorageService

        return StorageService.get_public_url(obj.logo.name)


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
    sport_name = serializers.CharField(required=False, allow_null=True)
    competition = serializers.UUIDField(required=False, allow_null=True)
    competition_name = serializers.CharField(required=False, allow_null=True)
    founded = serializers.IntegerField(required=False, allow_null=True)
    logo = serializers.CharField(required=False, allow_null=True)
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
    live_score_featured = serializers.BooleanField(required=False)
    ordering = serializers.ChoiceField(
        choices=["starts_at", "-starts_at", "name", "-name"],
        required=False,
        default="starts_at",
    )


class FixtureSerializer(serializers.Serializer):
    """Public fixture serializer. Used for both list and detail — both
    fixture_service.get_public_fixtures/get_public_fixture return real
    SportingEvent instances with the same select_related/prefetch, so the
    method fields below work identically for either."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    event_type = serializers.CharField()
    status = serializers.CharField()
    starts_at = serializers.DateTimeField(required=False, allow_null=True)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    venue = serializers.CharField(required=False, allow_blank=True)
    match_type = serializers.CharField(required=False, allow_blank=True)
    show_in_markets = serializers.BooleanField(required=False)
    is_live_score_featured = serializers.BooleanField(required=False)
    verification_status = serializers.SerializerMethodField()
    country_code = serializers.CharField(required=False, allow_blank=True)
    # source="*_id" — obj.sport/obj.competition are the related model
    # instances (this serializer is fed real SportingEvent rows, not
    # dicts), so a plain UUIDField without a source would render the
    # instance's __str__ (its name) instead of its id.
    sport = serializers.UUIDField(source="sport_id", required=False, allow_null=True)
    sport_name = serializers.CharField(
        source="sport.name", read_only=True, allow_null=True, default=None
    )
    competition = serializers.UUIDField(source="competition_id", required=False, allow_null=True)
    competition_name = serializers.CharField(
        source="competition.name", read_only=True, allow_null=True, default=None
    )
    participants = serializers.SerializerMethodField()
    home_score = serializers.SerializerMethodField()
    away_score = serializers.SerializerMethodField()
    clock_display = serializers.SerializerMethodField()

    def get_participants(self, obj: SportingEvent) -> list[dict]:
        return [
            {
                "role": ep.role,
                "position": ep.position,
                "participant": {
                    "id": str(ep.participant.id),
                    "name": ep.participant.name,
                    "short_name": ep.participant.short_name,
                    "kind": ep.participant.kind,
                },
            }
            for ep in obj.event_participants.all()
        ]

    def _match_centre(self, obj: SportingEvent):
        from discovery.models import MatchCentre

        try:
            return obj.match_centre
        except MatchCentre.DoesNotExist:
            return None

    def get_home_score(self, obj: SportingEvent) -> int | None:
        match_centre = self._match_centre(obj)
        return match_centre.home_score if match_centre else None

    def get_away_score(self, obj: SportingEvent) -> int | None:
        match_centre = self._match_centre(obj)
        return match_centre.away_score if match_centre else None

    def get_clock_display(self, obj: SportingEvent) -> str:
        match_centre = self._match_centre(obj)
        return match_centre.clock_display if match_centre else ""

    def get_verification_status(self, obj: SportingEvent) -> str:
        from discovery.models import FixtureResultVerification

        try:
            return obj.result_verification.status
        except FixtureResultVerification.DoesNotExist:
            return "NONE"


class FixtureCreateSerializer(serializers.Serializer):
    """Sports Data Admin creating a fixture between two participants."""

    sport = serializers.PrimaryKeyRelatedField(queryset=Sport.objects.filter(is_active=True))
    competition = serializers.PrimaryKeyRelatedField(
        queryset=Competition.objects.all(), required=False, allow_null=True, default=None
    )
    home_participant = serializers.PrimaryKeyRelatedField(queryset=Participant.objects.all())
    away_participant = serializers.PrimaryKeyRelatedField(queryset=Participant.objects.all())
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField(required=False, allow_null=True)
    venue = serializers.CharField(required=False, allow_blank=True, default="")
    match_type = serializers.CharField(required=False, allow_blank=True, default="")
    show_in_markets = serializers.BooleanField(required=False, default=False)
    is_live_score_featured = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        errors = {}
        sport = attrs["sport"]
        competition = attrs.get("competition")
        home = attrs["home_participant"]
        away = attrs["away_participant"]
        starts_at = attrs["starts_at"]
        ends_at = attrs.get("ends_at")

        if competition and competition.sport_id != sport.id:
            errors["competition"] = "Competition must belong to the selected sport."
        if home.sport_id != sport.id:
            errors["home_participant"] = "Home participant must belong to the selected sport."
        if away.sport_id != sport.id:
            errors["away_participant"] = "Away participant must belong to the selected sport."
        if home.id == away.id:
            errors["away_participant"] = "Home and away participants must be different."
        if starts_at < timezone.now():
            errors["starts_at"] = "Kickoff time cannot be in the past."
        if ends_at and ends_at < starts_at:
            errors["ends_at"] = "Anticipated end time cannot be earlier than kickoff."

        if errors:
            raise serializers.ValidationError(errors)
        return attrs


class FixtureRescheduleSerializer(serializers.Serializer):
    """Sports Data Admin editing a fixture's kickoff time, venue, and/or
    anticipated end time — typically after postponing it. Partial: any
    subset of these fields may be sent."""

    starts_at = serializers.DateTimeField(required=False)
    venue = serializers.CharField(required=False, allow_blank=True)
    ends_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate_starts_at(self, value):
        if value < timezone.now():
            raise serializers.ValidationError("Kickoff time cannot be in the past.")
        return value


class FixtureStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[
            SportingEvent.Status.SCHEDULED,
            SportingEvent.Status.LIVE,
            SportingEvent.Status.POSTPONED,
            SportingEvent.Status.CANCELLED,
            SportingEvent.Status.ABANDONED,
        ]
    )


class FixtureScoreSerializer(serializers.Serializer):
    home_score = serializers.IntegerField(min_value=0)
    away_score = serializers.IntegerField(min_value=0)
    clock_display = serializers.CharField(
        required=False, allow_blank=True, max_length=24, default=""
    )


class FixtureResultVerificationSerializer(serializers.Serializer):
    """Read shape for the Result Verification admin's 'Fixture Results'
    queue — a completed fixture's score, submitted for QA review. Distinct
    from MarketResultVerificationSerializer, which describes a market
    outcome, not a raw score."""

    id = serializers.UUIDField()
    fixture_id = serializers.UUIDField(source="fixture.id")
    fixture_name = serializers.CharField(source="fixture.name")
    sport_name = serializers.CharField(source="fixture.sport.name")
    competition_name = serializers.CharField(
        source="fixture.competition.name", allow_null=True, default=None
    )
    starts_at = serializers.DateTimeField(source="fixture.starts_at")
    home_score = serializers.SerializerMethodField()
    away_score = serializers.SerializerMethodField()
    status = serializers.CharField()
    submitted_by_email = serializers.CharField(
        source="submitted_by.email", allow_null=True, default=None
    )
    submitted_at = serializers.DateTimeField()
    reviewed_by_email = serializers.CharField(
        source="reviewed_by.email", allow_null=True, default=None
    )
    reviewed_at = serializers.DateTimeField(allow_null=True)
    review_note = serializers.CharField(allow_blank=True)

    def get_home_score(self, obj) -> int | None:
        match_centre = getattr(obj.fixture, "match_centre", None)
        return match_centre.home_score if match_centre else None

    def get_away_score(self, obj) -> int | None:
        match_centre = getattr(obj.fixture, "match_centre", None)
        return match_centre.away_score if match_centre else None


class FixtureResultVerificationDecisionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


# =============================================================================
# News
# =============================================================================


class NewsListQuerySerializer(serializers.Serializer):
    """Query parameters for the news list endpoint."""

    category = serializers.UUIDField(required=False)
    sport = serializers.UUIDField(required=False)
    competition = serializers.UUIDField(required=False)
    club = serializers.UUIDField(required=False)
    featured = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
    )
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
            "is_trending",
            "published_at",
        ]


class NewsCategorySerializer(serializers.ModelSerializer):
    """Public list of selectable news categories — used by the club
    submission form and the admin Compose News form."""

    class Meta:
        model = NewsCategory
        fields = ["id", "code", "name"]


# =============================================================================
# News moderation (club submission + platform admin review)
# =============================================================================


class NewsSubmissionSerializer(serializers.ModelSerializer):
    """Club-side submission — creates a PENDING_APPROVAL article. `club` and
    `status` are set server-side by the view, never taken from the client."""

    class Meta:
        model = News
        fields = ["title", "summary", "body", "category", "sport", "competition"]


class NewsComposeSerializer(serializers.ModelSerializer):
    """Staff Compose News — create-and-publish directly, no club, no review."""

    class Meta:
        model = News
        fields = ["title", "summary", "body", "category", "sport", "competition"]


class NewsModerationSerializer(serializers.ModelSerializer):
    """Full detail for the review queue, published list, and Edit Story —
    exposes fields the public NewsSerializer intentionally omits."""

    created_by = serializers.SerializerMethodField()

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
            "status",
            "is_featured",
            "is_trending",
            "is_verified",
            "rejection_reason",
            "published_at",
            "created_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "slug",
            "club",
            "status",
            "is_featured",
            "is_trending",
            "is_verified",
            "rejection_reason",
            "published_at",
            "created_at",
            "created_by",
        ]

    def get_created_by(self, obj: News) -> dict | None:
        if not obj.created_by_id:
            return None
        return {
            "id": obj.created_by_id,
            "name": (
                f"{obj.created_by.first_name} {obj.created_by.last_name}".strip()
                or obj.created_by.email
            ),
        }


class NewsModerationUpdateSerializer(serializers.ModelSerializer):
    """Edit Story — partial update of an article's content/classification."""

    class Meta:
        model = News
        fields = ["title", "summary", "body", "category", "sport", "competition"]
        extra_kwargs = {field: {"required": False} for field in fields}


class NewsApproveSerializer(serializers.Serializer):
    is_top_story = serializers.BooleanField(required=False, default=False)
    is_trending = serializers.BooleanField(required=False, default=False)


class NewsRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=False, max_length=2000)


class NewsFeaturedSerializer(serializers.Serializer):
    is_featured = serializers.BooleanField()


class NewsTrendingSerializer(serializers.Serializer):
    is_trending = serializers.BooleanField()


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

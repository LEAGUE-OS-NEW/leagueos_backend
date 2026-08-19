from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Sum
from rest_framework import serializers

from django.utils import timezone
from profiles.models import Club, Country
from sports.models import Competition, Participant, Sport, SportingEvent

from .models import (
    FantasyCompetition,
    FantasyGameweek,
    FantasyLeague,
    FantasyPlayer,
    FantasyPlayerGameweekPoints,
    FantasyScoringCorrection,
    FantasyScoringRule,
    FantasyTeam,
    FantasyTeamGameweekScore,
    FantasyTeamGameweekState,
    FantasyTeamPlayer,
)
from .services import replace_lineup, validate_selections
from .statistics import statistic_catalogue


class CleanModelSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        instance = self.instance or self.Meta.model()
        for field, value in attrs.items():
            if field != "fixtures":
                setattr(instance, field, value)
        try:
            instance.full_clean(
                exclude=[
                    "fixtures"] if self.Meta.model is FantasyGameweek else None
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(
                    exc, "message_dict") else exc.messages
            ) from exc
        return attrs


class FantasyPlayerSerializer(CleanModelSerializer):
    player_name = serializers.CharField(source="player.name", read_only=True)
    club = serializers.SerializerMethodField()
    ownership = serializers.SerializerMethodField()
    total_points = serializers.SerializerMethodField()
    current_gameweek_points = serializers.SerializerMethodField()
    form = serializers.SerializerMethodField()

    class Meta:
        model = FantasyPlayer
        fields = [
            "id",
            "fantasy_competition",
            "player",
            "player_name",
            "club",
            "position",
            "price",
            "starting_points",
            "eligible",
            "availability",
            "ownership",
            "total_points",
            "current_gameweek_points",
            "form",
        ]

    def get_club(self, obj) -> dict | None:
        team = obj.real_team
        return {"id": str(team.id), "name": team.name} if team else None

    def get_ownership(self, obj) -> float | None:
        total = obj.fantasy_competition.teams.count()
        if not total:
            return None
        selected = obj.team_selections.values("team_id").distinct().count()
        return round(selected * 100 / total, 2)

    def get_total_points(self, obj) -> float | None:
        value = obj.gameweek_points.aggregate(
            value=Sum("total_points"))["value"]
        return float(value) if value is not None else None

    def get_current_gameweek_points(self, obj) -> float | None:
        gameweek = (
            obj.fantasy_competition.gameweeks.exclude(
                status="DRAFT").order_by("number").last()
        )
        if not gameweek:
            return None
        record = obj.gameweek_points.filter(gameweek=gameweek).first()
        return float(record.total_points) if record else None

    def get_form(self, obj) -> float | None:
        # Return admin-configured starting_points as the form value.
        # Once match statistics exist, the scoring engine will produce real
        # per-gameweek points — until then starting_points gives fans a
        # meaningful pre-season value configured by the admin.
        sp = getattr(obj, "starting_points", None)
        if sp is not None and sp != 0:
            return float(sp)
        return None


class ScoringRuleSerializer(CleanModelSerializer):
    class Meta:
        model = FantasyScoringRule
        fields = "__all__"

    def validate_conditions(self, value):
        if value:
            raise serializers.ValidationError(
                "Conditional scoring rules are not supported; "
                "create an unconditional statistic rule."
            )
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        competition = attrs.get(
            "fantasy_competition", getattr(
                self.instance, "fantasy_competition", None)
        )
        statistic_type = (
            attrs.get("statistic_type", getattr(
                self.instance, "statistic_type", ""))
            .strip()
            .upper()
        )
        if statistic_type not in statistic_catalogue(competition.competition.sport):
            raise serializers.ValidationError(
                {"statistic_type": "Select an approved statistic type for this sport."}
            )
        attrs["statistic_type"] = statistic_type
        return attrs


class GameweekSerializer(CleanModelSerializer):
    fixtures = serializers.PrimaryKeyRelatedField(
        many=True, queryset=SportingEvent.objects.all(), required=False
    )
    fixture_details = serializers.SerializerMethodField()

    class Meta:
        model = FantasyGameweek
        fields = "__all__"

    def get_fixture_details(self, obj) -> list[dict]:
        return [
            {
                "id": str(fixture.id),
                "name": fixture.name,
                "starts_at": fixture.starts_at,
                "status": fixture.status,
            }
            for fixture in obj.fixtures.all()
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        competition = attrs.get(
            "fantasy_competition", getattr(
                self.instance, "fantasy_competition", None)
        )
        fixtures = attrs.get("fixtures", [])
        invalid = [
            fixture.id
            for fixture in fixtures
            if fixture.competition_id != competition.competition_id
            or fixture.sport_id != competition.competition.sport_id
        ]
        if invalid:
            raise serializers.ValidationError(
                {"fixtures": "Fixtures must belong to the selected real competition and sport."}
            )
        return attrs


class CompetitionSerializer(CleanModelSerializer):
    sport = serializers.CharField(
        source="competition.sport.slug", read_only=True)
    season_name = serializers.CharField(source="season.name", read_only=True)
    scoring_rules = ScoringRuleSerializer(many=True, read_only=True)
    current_gameweek = serializers.SerializerMethodField()
    entries = serializers.SerializerMethodField()
    total_gameweeks = serializers.SerializerMethodField()

    class Meta:
        model = FantasyCompetition
        fields = "__all__"
        ref_name = "FantasyCompetition"

    def get_current_gameweek(self, obj) -> dict | None:
        gw = obj.gameweeks.exclude(status="DRAFT").order_by("number").last()
        return GameweekSerializer(gw).data if gw else None

    def get_entries(self, obj) -> int:
        return obj.teams.count()

    def get_total_gameweeks(self, obj) -> int:
        return obj.gameweeks.count()

    def validate_tie_break_rules(self, value):
        supported = {"total_points",
                     "fewer_transfer_penalties", "earlier_registration"}
        if not isinstance(value, list) or any(rule not in supported for rule in value):
            raise serializers.ValidationError(
                f"Supported tie breaks are: {', '.join(sorted(supported))}."
            )
        return value


class TeamSelectionSerializer(serializers.ModelSerializer):
    fantasy_player_detail = FantasyPlayerSerializer(
        source="fantasy_player", read_only=True)

    class Meta:
        model = FantasyTeamPlayer
        exclude = ["team"]
        read_only_fields = ["id", "purchase_price", "created_at", "updated_at"]


class TeamSerializer(serializers.ModelSerializer):
    selections = TeamSelectionSerializer(many=True, required=False)

    class Meta:
        model = FantasyTeam
        fields = "__all__"
        read_only_fields = ["owner", "budget_remaining", "free_transfers"]

    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop("selections", None)
        raw = self.initial_data.get("selections", [])
        competition = validated_data["fantasy_competition"]
        selections = []
        for item in raw:
            try:
                player = FantasyPlayer.objects.get(
                    pk=item.get("fantasy_player"))
            except FantasyPlayer.DoesNotExist:
                raise serializers.ValidationError(
                    "Unknown Fantasy player.") from None
            selections.append({**item, "fantasy_player": player})
        if (
            not competition.enabled
            or competition.registration_state != competition.RegistrationState.OPEN
        ):
            raise serializers.ValidationError(
                {"fantasy_competition": "Fantasy competition registration is not open."}
            )
        if (
            competition.registration_deadline
            and timezone.now() >= competition.registration_deadline
        ):
            raise serializers.ValidationError(
                {"fantasy_competition": "Fantasy competition registration deadline has passed."}
            )
        try:
            validate_selections(competition, selections)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        team = FantasyTeam.objects.create(
            owner=self.context["request"].user,
            budget_remaining=competition.initial_budget
            - sum(x["fantasy_player"].price for x in selections),
            free_transfers=competition.free_transfers_per_gameweek,
            **validated_data,
        )
        for item in selections:
            FantasyTeamPlayer.objects.create(
                team=team, purchase_price=item["fantasy_player"].price, **item
            )
        return team


class LineupSerializer(serializers.Serializer):
    selections = TeamSelectionSerializer(many=True)

    def save(self, **kwargs):
        team = self.context["team"]
        resolved = []
        for item in self.validated_data["selections"]:
            player = item["fantasy_player"]
            resolved.append({**item, "fantasy_player": player})
        try:
            return replace_lineup(team, resolved)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc


class TransferSerializer(serializers.Serializer):
    gameweek = serializers.PrimaryKeyRelatedField(
        queryset=FantasyGameweek.objects.all())
    player_out = serializers.PrimaryKeyRelatedField(
        queryset=FantasyPlayer.objects.all())
    player_in = serializers.PrimaryKeyRelatedField(
        queryset=FantasyPlayer.objects.all())


class LeagueSerializer(serializers.ModelSerializer):
    member_count = serializers.IntegerField(
        source="memberships.count", read_only=True)

    class Meta:
        model = FantasyLeague
        fields = "__all__"
        read_only_fields = ["owner", "join_code"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        is_owner = bool(
            request and request.user.is_authenticated and instance.owner_id == request.user.id
        )
        if instance.visibility == FantasyLeague.Visibility.PRIVATE and not is_owner:
            data.pop("join_code", None)
        return data

    def validate(self, attrs):
        capacity = attrs.get("capacity", getattr(
            self.instance, "capacity", None))
        if capacity is not None and capacity < 2:
            raise serializers.ValidationError(
                {"capacity": "League capacity must be at least two."})
        return attrs


class PlayerPointsSerializer(serializers.ModelSerializer):
    player = FantasyPlayerSerializer(source="fantasy_player", read_only=True)

    class Meta:
        model = FantasyPlayerGameweekPoints
        fields = "__all__"


class MatchPlayerStatisticCreateSerializer(serializers.Serializer):
    """
    Serializer for admin-initiated test match statistics.

    Accepts a fixture (SportingEvent UUID) and a participant (Participant UUID)
    rather than requiring the caller to know the MatchCentre ID.  The view
    handles the get_or_create of MatchCentre internally.
    """

    fixture = serializers.PrimaryKeyRelatedField(
        queryset=SportingEvent.objects.all(),
        help_text="UUID of the SportingEvent (fixture) this statistic belongs to.",
    )
    participant = serializers.PrimaryKeyRelatedField(
        queryset=Participant.objects.filter(kind="ATHLETE"),
        help_text="UUID of the Participant (athlete) who recorded the statistic.",
    )
    stat_type = serializers.CharField(
        max_length=100,
        help_text="Statistic type code, e.g. GOALS, ASSISTS. Must be valid for the sport.",
    )
    value = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Numeric value for the statistic (must be >= 0).",
    )

    # ── validation ────────────────────────────────────────────────────────────

    def validate_stat_type(self, value):
        return value.strip().upper()

    def validate_value(self, value):
        from decimal import Decimal

        if value < Decimal("0"):
            raise serializers.ValidationError("Value must be zero or greater.")
        return value

    def validate(self, attrs):
        fixture = attrs["fixture"]
        stat_type = attrs["stat_type"]
        participant = attrs["participant"]

        # Determine sport via the fixture — prefer direct FK, fall back to competition
        sport = getattr(fixture, "sport", None) or (
            fixture.competition.sport if fixture.competition_id else None
        )
        if sport is None:
            raise serializers.ValidationError(
                {"fixture": "Cannot determine sport for this fixture."}
            )

        catalogue = statistic_catalogue(sport)
        if not catalogue:
            raise serializers.ValidationError(
                {"fixture": f"No statistic catalogue defined for sport '{sport}'."}
            )
        if stat_type not in catalogue:
            raise serializers.ValidationError(
                {
                    "stat_type": (
                        f"'{stat_type}' is not a valid statistic type for {sport}. "
                        f"Allowed: {', '.join(sorted(catalogue.keys()))}."
                    )
                }
            )

        # Participant must belong to the same sport as the fixture
        if participant.sport_id != sport.id:
            raise serializers.ValidationError(
                {"participant": "Participant sport does not match the fixture sport."}
            )

        return attrs


class CorrectionSerializer(serializers.ModelSerializer):
    player_name = serializers.CharField(
        source="player_points.fantasy_player.player.name", read_only=True
    )
    gameweek = serializers.UUIDField(
        source="player_points.gameweek_id", read_only=True)

    class Meta:
        model = FantasyScoringCorrection
        fields = [
            "id",
            "player_points",
            "player_name",
            "gameweek",
            "previous_value",
            "new_value",
            "reason",
            "actor",
            "created_at",
        ]
        read_only_fields = ["previous_value", "actor"]

    def validate_reason(self, value):
        if not value.strip():
            raise serializers.ValidationError(
                "A correction reason is required.")
        return value.strip()


class TeamGameweekStateSerializer(serializers.ModelSerializer):
    free_transfers_remaining = serializers.IntegerField(read_only=True)

    class Meta:
        model = FantasyTeamGameweekState
        fields = [
            "gameweek",
            "free_transfers_allocated",
            "free_transfers_used",
            "free_transfers_remaining",
            "transfer_penalty",
        ]


class TeamScoreSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source="team.name", read_only=True)
    manager = serializers.SerializerMethodField()

    class Meta:
        model = FantasyTeamGameweekScore
        fields = "__all__"

    def get_manager(self, obj):
        return obj.team.owner.get_full_name().strip() or obj.team.owner.get_username()


class FantasyPlayerFullCreateSerializer(serializers.Serializer):
    """
    Admin-only: Create a brand-new player (Participant + PlayerProfile) and
    immediately add them to the Fantasy competition player pool.

    Used when a club fails to submit a player who should be available in
    Fantasy — the Super Admin manually adds them via this single action.
    The Participant is tagged with source_name='ADMIN_MANUAL' so the origin
    is auditable without requiring a new model field.
    """

    # ── Participant identity ──────────────────────────────────────────────
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    sport = serializers.PrimaryKeyRelatedField(
        queryset=Sport.objects.filter(is_active=True),
        help_text="UUID of the canonical Sport (must match the competition).",
    )

    # ── PlayerProfile fields ──────────────────────────────────────────────
    club = serializers.PrimaryKeyRelatedField(
        queryset=Club.objects.filter(is_active=True),
        help_text="UUID of the profiles.Club this player belongs to.",
    )
    profile_position = serializers.CharField(
        max_length=100,
        help_text="Canonical position label stored on PlayerProfile (e.g. 'GK', 'DEF').",
    )
    shirt_number = serializers.IntegerField(
        required=False, allow_null=True, min_value=1)
    nationality = serializers.PrimaryKeyRelatedField(
        queryset=Country.objects.all(),
        required=False,
        allow_null=True,
    )
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    photo_url = serializers.URLField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional player photo URL.",
    )

    # ── FantasyPlayer pool fields ─────────────────────────────────────────
    fantasy_competition = serializers.PrimaryKeyRelatedField(
        queryset=FantasyCompetition.objects.all(),
        help_text="UUID of the FantasyCompetition to add this player to.",
    )
    fantasy_position = serializers.CharField(
        max_length=50,
        help_text="Fantasy position key (must be in the competition's position_rules).",
    )
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    starting_points = serializers.DecimalField(
        max_digits=8, decimal_places=2, required=False, default=0
    )
    eligible = serializers.BooleanField(default=True)
    availability = serializers.ChoiceField(
        choices=FantasyPlayer.Availability.choices,
        default=FantasyPlayer.Availability.AVAILABLE,
    )

    # ── Validation ────────────────────────────────────────────────────────

    def validate(self, attrs):
        errors = {}

        sport = attrs["sport"]
        fc = attrs["fantasy_competition"]

        # Sport must match the competition's sport.
        if sport.id != fc.competition.sport_id:
            errors["sport"] = (
                f"Sport '{sport.name}' does not match the competition's sport "
                f"'{fc.competition.sport.name}'."
            )

        # Fantasy position must exist in the competition's position_rules.
        fantasy_position = attrs["fantasy_position"]
        if fantasy_position not in fc.position_rules:
            errors["fantasy_position"] = (
                f"'{fantasy_position}' is not a valid position for this competition. "
                f"Allowed: {', '.join(fc.position_rules.keys())}."
            )

        # Price must be positive.
        if attrs.get("price") is not None and attrs["price"] <= 0:
            errors["price"] = "Price must be greater than zero."

        if attrs.get("starting_points") is not None and attrs["starting_points"] < 0:
            errors["starting_points"] = "Starting points cannot be negative."

        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        from django.utils.text import slugify
        from discovery.models import PlayerProfile

        first_name = validated_data["first_name"].strip()
        last_name = validated_data["last_name"].strip()
        full_name = f"{first_name} {last_name}"
        sport = validated_data["sport"]
        club = validated_data["club"]
        fc = validated_data["fantasy_competition"]
        fantasy_position = validated_data["fantasy_position"]
        profile_position = validated_data["profile_position"]

        # ── Duplicate detection ───────────────────────────────────────────
        # Check if a Participant with this name+sport+ATHLETE already exists.
        base_slug = slugify(full_name)
        existing_participant = Participant.objects.filter(
            sport=sport,
            kind=Participant.Kind.ATHLETE,
            slug=base_slug,
        ).first()

        if existing_participant:
            # Reuse the existing Participant rather than creating a duplicate.
            participant = existing_participant
        else:
            # Ensure slug uniqueness within (sport, kind, country_code, slug).
            slug = base_slug
            counter = 1
            country_code = club.sport.name[:2].upper() if club.sport else "UG"
            while Participant.objects.filter(
                sport=sport, kind=Participant.Kind.ATHLETE,
                country_code=country_code, slug=slug
            ).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1

            participant = Participant.objects.create(
                sport=sport,
                kind=Participant.Kind.ATHLETE,
                name=full_name,
                short_name=last_name,
                slug=slug,
                country_code=country_code,
                source_name="ADMIN_MANUAL",
                source_reference="",
                is_active=True,
                is_verified=True,
            )

        # ── PlayerProfile: get-or-create ──────────────────────────────────
        profile, _ = PlayerProfile.objects.get_or_create(
            participant=participant,
            defaults={
                "club": club,
                "position": profile_position,
                "shirt_number": validated_data.get("shirt_number"),
                "nationality": validated_data.get("nationality"),
                "status": PlayerProfile.Status.ACTIVE,
                "is_published": True,
                "is_verified": True,
                "biography": "",
            },
        )
        # Always update club + position in case the profile already exists.
        profile.club = club
        profile.position = profile_position
        if validated_data.get("shirt_number") is not None:
            profile.shirt_number = validated_data["shirt_number"]
        if validated_data.get("nationality") is not None:
            profile.nationality = validated_data["nationality"]
        profile.save(
            update_fields=[
                "club",
                "position",
                "shirt_number",
                "nationality",
                "updated_at",
            ]
        )

        # ── Duplicate FantasyPlayer detection ────────────────────────────
        existing_fp = FantasyPlayer.objects.filter(
            fantasy_competition=fc, player=participant
        ).first()
        if existing_fp:
            raise serializers.ValidationError(
                {
                    "player": (
                        f"'{full_name}' is already in the '{fc.name}' player pool "
                        f"(Fantasy Player ID: {existing_fp.id})."
                    )
                }
            )

        # ── Create FantasyPlayer ──────────────────────────────────────────
        fantasy_player = FantasyPlayer.objects.create(
            fantasy_competition=fc,
            player=participant,
            position=fantasy_position,
            price=validated_data["price"],
            starting_points=validated_data.get("starting_points", 0),
            eligible=validated_data.get("eligible", True),
            availability=validated_data.get(
                "availability", FantasyPlayer.Availability.AVAILABLE),
        )
        return fantasy_player

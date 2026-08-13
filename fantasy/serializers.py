from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from django.utils import timezone
from sports.models import SportingEvent

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
                exclude=["fixtures"] if self.Meta.model is FantasyGameweek else None
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            ) from exc
        return attrs


class FantasyPlayerSerializer(CleanModelSerializer):
    player_name = serializers.CharField(source="player.name", read_only=True)
    club = serializers.SerializerMethodField()

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
            "eligible",
            "availability",
        ]

    def get_club(self, obj) -> dict | None:
        team = obj.real_team
        return {"id": str(team.id), "name": team.name} if team else None


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
            "fantasy_competition", getattr(self.instance, "fantasy_competition", None)
        )
        statistic_type = (
            attrs.get("statistic_type", getattr(self.instance, "statistic_type", ""))
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
            "fantasy_competition", getattr(self.instance, "fantasy_competition", None)
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
    sport = serializers.CharField(source="competition.sport.slug", read_only=True)
    scoring_rules = ScoringRuleSerializer(many=True, read_only=True)
    current_gameweek = serializers.SerializerMethodField()

    class Meta:
        model = FantasyCompetition
        fields = "__all__"
        ref_name = "FantasyCompetition"

    def get_current_gameweek(self, obj) -> dict | None:
        gw = obj.gameweeks.exclude(status="DRAFT").order_by("number").last()
        return GameweekSerializer(gw).data if gw else None

    def validate_tie_break_rules(self, value):
        supported = {"total_points", "fewer_transfer_penalties", "earlier_registration"}
        if not isinstance(value, list) or any(rule not in supported for rule in value):
            raise serializers.ValidationError(
                f"Supported tie breaks are: {', '.join(sorted(supported))}."
            )
        return value


class TeamSelectionSerializer(serializers.ModelSerializer):
    fantasy_player_detail = FantasyPlayerSerializer(source="fantasy_player", read_only=True)

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
                player = FantasyPlayer.objects.get(pk=item.get("fantasy_player"))
            except FantasyPlayer.DoesNotExist:
                raise serializers.ValidationError("Unknown Fantasy player.") from None
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
    gameweek = serializers.PrimaryKeyRelatedField(queryset=FantasyGameweek.objects.all())
    player_out = serializers.PrimaryKeyRelatedField(queryset=FantasyPlayer.objects.all())
    player_in = serializers.PrimaryKeyRelatedField(queryset=FantasyPlayer.objects.all())


class LeagueSerializer(serializers.ModelSerializer):
    member_count = serializers.IntegerField(source="memberships.count", read_only=True)

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
        capacity = attrs.get("capacity", getattr(self.instance, "capacity", None))
        if capacity is not None and capacity < 2:
            raise serializers.ValidationError({"capacity": "League capacity must be at least two."})
        return attrs


class PlayerPointsSerializer(serializers.ModelSerializer):
    player = FantasyPlayerSerializer(source="fantasy_player", read_only=True)

    class Meta:
        model = FantasyPlayerGameweekPoints
        fields = "__all__"


class CorrectionSerializer(serializers.ModelSerializer):
    player_name = serializers.CharField(
        source="player_points.fantasy_player.player.name", read_only=True
    )
    gameweek = serializers.UUIDField(source="player_points.gameweek_id", read_only=True)

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
            raise serializers.ValidationError("A correction reason is required.")
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

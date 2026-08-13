from django.db import transaction
from django.db.models import Count, Q, Sum
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from discovery.models import MatchPlayerStatistic, Season
from sports.models import Competition, Participant, SportingEvent

from .models import (
    FantasyCompetition,
    FantasyGameweek,
    FantasyLeague,
    FantasyLeagueMembership,
    FantasyPlayer,
    FantasyScoringCorrection,
    FantasyScoringRule,
    FantasyTeam,
    FantasyTeamGameweekScore,
    FantasyTransfer,
)
from .permissions import CanManageFantasy
from .serializers import (
    CompetitionSerializer,
    CorrectionSerializer,
    FantasyPlayerSerializer,
    GameweekSerializer,
    LeagueSerializer,
    LineupSerializer,
    PlayerPointsSerializer,
    ScoringRuleSerializer,
    TeamGameweekStateSerializer,
    TeamScoreSerializer,
    TeamSerializer,
    TransferSerializer,
)
from .services import (
    deadline_locked,
    gameweek_state,
    notify_fantasy,
    rank_rows,
    score_gameweek,
    validate_selections,
)
from .statistics import statistic_catalogue


def safe_user_name(user):
    return user.get_full_name().strip() or user.get_username()


class CompetitionViewSet(viewsets.ModelViewSet):
    serializer_class = CompetitionSerializer
    fantasy_permission = "platform.fantasy.competitions.manage"

    def get_queryset(self):
        qs = FantasyCompetition.objects.select_related("competition__sport", "season")
        if self.action in {"list", "retrieve", "rules", "leaderboard"}:
            qs = qs.filter(enabled=True, visibility=FantasyCompetition.Visibility.PUBLIC)
        return qs

    def get_permissions(self):
        return (
            [AllowAny()]
            if self.action in {"list", "retrieve", "rules", "leaderboard"}
            else [CanManageFantasy()]
        )

    @action(detail=False, methods=["get"], url_path="admin-list")
    def admin_list(self, request):
        queryset = FantasyCompetition.objects.select_related(
            "competition__sport", "season"
        ).prefetch_related("scoring_rules", "gameweeks__fixtures")
        return Response(self.get_serializer(queryset, many=True).data)

    @action(detail=False, methods=["get"], url_path="canonical-options")
    def canonical_options(self, request):
        competitions = Competition.objects.select_related("sport").order_by("sport__name", "name")
        seasons = (
            Season.objects.select_related("competition", "sport")
            .filter(competition__isnull=False)
            .order_by("competition__name", "-starts_on", "name")
        )
        return Response(
            {
                "competitions": [
                    {
                        "id": str(row.id),
                        "name": row.name,
                        "sport": row.sport.name,
                        "sport_slug": row.sport.slug,
                    }
                    for row in competitions
                ],
                "seasons": [
                    {
                        "id": str(row.id),
                        "name": row.name,
                        "competition": str(row.competition_id),
                        "is_active": row.is_active,
                    }
                    for row in seasons
                ],
            }
        )

    @action(detail=True, methods=["get"])
    def rules(self, request, pk=None):
        competition = self.get_object()
        return Response(
            {
                "competition": CompetitionSerializer(competition).data,
                "scoring_rules": ScoringRuleSerializer(
                    competition.scoring_rules.filter(enabled=True), many=True
                ).data,
            }
        )

    @action(detail=True, methods=["get"])
    def leaderboard(self, request, pk=None):
        competition = self.get_object()
        scores = (
            FantasyTeamGameweekScore.objects.filter(team__fantasy_competition=competition)
            .values(
                "team_id",
                "team__name",
                "team__owner__username",
                "team__owner__first_name",
                "team__owner__last_name",
                "team__created_at",
            )
            .annotate(total_points=Sum("total_points"), transfer_penalties=Sum("transfer_penalty"))
        )
        rows = list(scores)
        for row in rows:
            first_name = row.pop("team__owner__first_name")
            last_name = row.pop("team__owner__last_name")
            row["manager"] = f"{first_name} {last_name}".strip() or row.pop("team__owner__username")
        return Response(rank_rows(rows, competition.tie_break_rules))

    @action(detail=True, methods=["get"], url_path="statistic-types")
    def statistic_types(self, request, pk=None):
        competition = self.get_object()
        observed = set(
            MatchPlayerStatistic.objects.filter(
                match_centre__fixture__competition=competition.competition,
            )
            .values_list("stat_type", flat=True)
            .distinct()
        )
        catalogue = statistic_catalogue(competition.competition.sport)
        return Response(
            [
                {
                    "code": code,
                    "label": label,
                    "observed": code in {value.upper() for value in observed},
                }
                for code, label in catalogue.items()
            ]
        )


class GameweekViewSet(viewsets.ModelViewSet):
    queryset = FantasyGameweek.objects.select_related("fantasy_competition").prefetch_related(
        "fixtures"
    )
    serializer_class = GameweekSerializer

    def fantasy_permission(self):
        return (
            "platform.fantasy.gameweeks.finalize"
            if self.action in {"transition", "finalize"}
            else "platform.fantasy.scoring.manage"
        )

    def get_queryset(self):
        qs = FantasyGameweek.objects.select_related("fantasy_competition").prefetch_related(
            "fixtures"
        )
        if self.action in {"list", "retrieve", "points", "leaderboard"}:
            qs = qs.filter(
                fantasy_competition__enabled=True,
                fantasy_competition__visibility=FantasyCompetition.Visibility.PUBLIC,
            )
        competition = self.request.query_params.get("competition")
        return qs.filter(fantasy_competition_id=competition) if competition else qs

    def get_permissions(self):
        return (
            [AllowAny()]
            if self.action in {"list", "retrieve", "points", "leaderboard"}
            else [CanManageFantasy()]
        )

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        gameweek = self.get_object()
        target = request.data.get("status")
        allowed = {
            "DRAFT": {"OPEN"},
            "OPEN": {"LOCKED"},
            "LOCKED": {"LIVE", "SCORING"},
            "LIVE": {"SCORING"},
            "SCORING": {"FINALIZED", "LIVE"},
            "FINALIZED": {"SCORING"},
        }
        if target not in allowed.get(gameweek.status, set()):
            return Response({"detail": "Invalid gameweek transition."}, status=400)
        gameweek.status = target
        gameweek.save(update_fields=["status", "updated_at"])
        if target == FantasyGameweek.Status.LOCKED:
            for team in gameweek.fantasy_competition.teams.select_related("owner"):
                notify_fantasy(
                    recipient=team.owner,
                    event_type="FANTASY_GAMEWEEK_LOCKED",
                    title=f"{gameweek.name} locked",
                    message="Lineups and transfers are now locked.",
                    deduplication_key=f"fantasy:locked:{gameweek.id}:{team.owner_id}",
                    data={"gameweek_id": str(gameweek.id)},
                )
        return Response(self.get_serializer(gameweek).data)

    @action(detail=True, methods=["post"])
    def recalculate(self, request, pk=None):
        gameweek = score_gameweek(self.get_object())
        if gameweek.status in {"LOCKED", "LIVE"}:
            gameweek.status = "SCORING"
            gameweek.save(update_fields=["status", "updated_at"])
        return Response({"status": gameweek.status, "detail": "Scoring recalculated idempotently."})

    @action(detail=True, methods=["post"])
    def finalize(self, request, pk=None):
        gameweek = self.get_object()
        if gameweek.status != FantasyGameweek.Status.SCORING:
            return Response({"detail": "Only a scoring gameweek can be finalized."}, status=400)
        if (
            gameweek.fixtures.exists()
            and gameweek.fixtures.exclude(
                status__in=["COMPLETED", "CANCELLED", "ABANDONED"]
            ).exists()
        ):
            return Response(
                {"detail": "All assigned fixtures must be complete before finalization."},
                status=400,
            )
        score_gameweek(gameweek)
        gameweek.status = FantasyGameweek.Status.FINALIZED
        gameweek.save(update_fields=["status", "updated_at"])
        for owner in gameweek.fantasy_competition.teams.values_list("owner", flat=True).distinct():
            from django.contrib.auth import get_user_model

            recipient = get_user_model().objects.get(pk=owner)
            notify_fantasy(
                recipient=recipient,
                event_type="FANTASY_GAMEWEEK_FINALIZED",
                title=f"{gameweek.name} finalized",
                message="Your verified Fantasy score and ranking are ready.",
                deduplication_key=f"fantasy:finalized:{gameweek.id}:{owner}",
                data={"gameweek_id": str(gameweek.id)},
            )
        return Response(self.get_serializer(gameweek).data)

    @action(detail=True, methods=["get"])
    def points(self, request, pk=None):
        return Response(
            PlayerPointsSerializer(
                self.get_object().player_points.select_related("fantasy_player__player"), many=True
            ).data
        )

    @action(detail=True, methods=["get"])
    def leaderboard(self, request, pk=None):
        gameweek = self.get_object()
        scores = gameweek.team_scores.select_related("team", "team__owner")
        data = TeamScoreSerializer(scores, many=True).data
        rows = []
        for score, item in zip(scores, data, strict=True):
            rows.append(
                {
                    **item,
                    "team_id": str(score.team_id),
                    "created_at": score.team.created_at,
                    "transfer_penalties": score.transfer_penalty,
                }
            )
        return Response(rank_rows(rows, gameweek.fantasy_competition.tie_break_rules))

    @action(detail=False, methods=["get"], url_path="fixture-candidates")
    def fixture_candidates(self, request):
        try:
            competition = FantasyCompetition.objects.get(pk=request.query_params.get("competition"))
        except (FantasyCompetition.DoesNotExist, ValueError, TypeError):
            return Response({"competition": ["Select a valid Fantasy competition."]}, status=400)
        fixtures = SportingEvent.objects.filter(
            competition=competition.competition, sport=competition.competition.sport
        ).order_by("starts_at")
        return Response(
            [
                {
                    "id": str(row.id),
                    "name": row.name,
                    "starts_at": row.starts_at,
                    "status": row.status,
                }
                for row in fixtures
            ]
        )


class PlayerViewSet(viewsets.ModelViewSet):
    serializer_class = FantasyPlayerSerializer
    fantasy_permission = "platform.fantasy.players.manage"

    def get_queryset(self):
        qs = FantasyPlayer.objects.select_related(
            "fantasy_competition", "player", "player__player_profile__club"
        )
        if self.action in {"list", "retrieve"}:
            qs = qs.filter(
                fantasy_competition__enabled=True,
                fantasy_competition__visibility=FantasyCompetition.Visibility.PUBLIC,
            )
        competition = self.request.query_params.get("competition")
        return qs.filter(fantasy_competition_id=competition) if competition else qs

    def get_permissions(self):
        return [AllowAny()] if self.action in {"list", "retrieve"} else [CanManageFantasy()]

    @action(detail=False, methods=["get"])
    def candidates(self, request):
        try:
            competition = FantasyCompetition.objects.get(pk=request.query_params.get("competition"))
        except (FantasyCompetition.DoesNotExist, ValueError, TypeError):
            return Response({"competition": ["Select a valid Fantasy competition."]}, status=400)
        athletes = (
            Participant.objects.filter(
                kind=Participant.Kind.ATHLETE, sport=competition.competition.sport
            )
            .select_related("player_profile__club")
            .order_by("name")
        )
        data = []
        for player in athletes:
            profile = getattr(player, "player_profile", None)
            data.append(
                {
                    "id": str(player.id),
                    "name": player.name,
                    "club": profile.club.name if profile and profile.club else None,
                    "profile_position": profile.position if profile else "",
                }
            )
        return Response(data)


class TeamViewSet(viewsets.ModelViewSet):
    queryset = FantasyTeam.objects.none()
    serializer_class = TeamSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            FantasyTeam.objects.filter(owner=self.request.user)
            .select_related("fantasy_competition")
            .prefetch_related("selections__fantasy_player__player")
        )

    @action(detail=True, methods=["put", "patch"])
    @transaction.atomic
    def lineup(self, request, pk=None):
        team = self.get_object()
        gameweek = (
            team.fantasy_competition.gameweeks.filter(status__in=["DRAFT", "OPEN"])
            .order_by("number")
            .first()
        )
        if not gameweek or deadline_locked(gameweek):
            return Response({"detail": "Lineup changes are locked."}, status=400)
        serializer = LineupSerializer(data=request.data, context={"team": team})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        team.refresh_from_db()
        return Response(self.get_serializer(team).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def transfer(self, request, pk=None):
        team = self.get_object()
        data = TransferSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        gw, outgoing, incoming = (
            data.validated_data[k] for k in ("gameweek", "player_out", "player_in")
        )
        if gw.fantasy_competition_id != team.fantasy_competition_id or deadline_locked(gw):
            return Response({"detail": "Transfers are locked for this gameweek."}, status=400)
        selection = team.selections.filter(fantasy_player=outgoing).first()
        if (
            not selection
            or incoming.fantasy_competition_id != team.fantasy_competition_id
            or not incoming.eligible
            or incoming.availability in {"INJURED", "SUSPENDED", "UNAVAILABLE"}
        ):
            return Response({"detail": "Invalid transfer players."}, status=400)
        new_budget = team.budget_remaining + selection.purchase_price - incoming.price
        prospective = []
        for current in team.selections.select_related("fantasy_player"):
            prospective.append(
                {
                    "fantasy_player": (
                        incoming if current.id == selection.id else current.fantasy_player
                    ),
                    "is_starter": current.is_starter,
                    "bench_order": current.bench_order,
                    "is_captain": current.is_captain,
                    "is_vice_captain": current.is_vice_captain,
                }
            )
        try:
            validate_selections(
                team.fantasy_competition,
                prospective,
                budget=team.fantasy_competition.initial_budget,
            )
        except Exception as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)}, status=400
            )
        state = gameweek_state(team, gw, lock=True)
        penalty = 0 if state.free_transfers_remaining else team.fantasy_competition.transfer_penalty
        FantasyTransfer.objects.create(
            team=team,
            gameweek=gw,
            player_out=outgoing,
            player_in=incoming,
            price_out=selection.purchase_price,
            price_in=incoming.price,
            penalty_points=penalty,
        )
        selection.fantasy_player = incoming
        selection.purchase_price = incoming.price
        selection.save()
        team.budget_remaining = new_budget
        state.free_transfers_used += 1
        state.transfer_penalty += penalty
        state.save(update_fields=["free_transfers_used", "transfer_penalty", "updated_at"])
        team.save(update_fields=["budget_remaining", "updated_at"])
        notify_fantasy(
            recipient=request.user,
            event_type="FANTASY_TRANSFER_SAVED",
            title="Fantasy transfer saved",
            message=f"{outgoing.player.name} was replaced by {incoming.player.name}.",
            deduplication_key=f"fantasy:transfer:{team.id}:{gw.id}:{state.free_transfers_used}",
            data={"team_id": str(team.id), "gameweek_id": str(gw.id), "penalty": penalty},
        )
        return Response(TeamSerializer(team, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def transfer_preview(self, request, pk=None):
        team = self.get_object()
        data = TransferSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        gw, outgoing, incoming = (
            data.validated_data[k] for k in ("gameweek", "player_out", "player_in")
        )
        if gw.fantasy_competition_id != team.fantasy_competition_id or deadline_locked(gw):
            return Response({"detail": "Transfers are locked for this gameweek."}, status=400)
        selection = team.selections.filter(fantasy_player=outgoing).first()
        if (
            not selection
            or incoming.fantasy_competition_id != team.fantasy_competition_id
            or not incoming.eligible
            or incoming.availability in {"INJURED", "SUSPENDED", "UNAVAILABLE"}
        ):
            return Response({"detail": "Invalid or unavailable transfer players."}, status=400)
        prospective = [
            {
                "fantasy_player": (
                    incoming if current.id == selection.id else current.fantasy_player
                ),
                "is_starter": current.is_starter,
                "bench_order": current.bench_order,
                "is_captain": current.is_captain,
                "is_vice_captain": current.is_vice_captain,
            }
            for current in team.selections.select_related("fantasy_player")
        ]
        try:
            validate_selections(
                team.fantasy_competition,
                prospective,
                budget=team.fantasy_competition.initial_budget,
            )
        except Exception as exc:
            return Response(
                {"detail": exc.messages if hasattr(exc, "messages") else str(exc)}, status=400
            )
        state = gameweek_state(team, gw)
        penalty = 0 if state.free_transfers_remaining else team.fantasy_competition.transfer_penalty
        new_budget = team.budget_remaining + selection.purchase_price - incoming.price
        return Response(
            {
                "gameweek": str(gw.id),
                "player_out": str(outgoing.id),
                "player_in": str(incoming.id),
                "price_out": selection.purchase_price,
                "price_in": incoming.price,
                "price_difference": incoming.price - selection.purchase_price,
                "current_budget": team.budget_remaining,
                "new_budget": new_budget,
                "free_transfers_allocated": state.free_transfers_allocated,
                "free_transfers_used": state.free_transfers_used,
                "free_transfers_remaining": state.free_transfers_remaining,
                "penalty_if_confirmed": penalty,
            }
        )

    @action(detail=True, methods=["get"])
    def transfers(self, request, pk=None):
        return Response(list(self.get_object().transfers.values().order_by("created_at")))

    @action(detail=True, methods=["get"])
    def transfer_balance(self, request, pk=None):
        team = self.get_object()
        gameweek_id = request.query_params.get("gameweek")
        gameweek = (
            team.fantasy_competition.gameweeks.get(pk=gameweek_id)
            if gameweek_id
            else team.fantasy_competition.gameweeks.filter(status__in=["DRAFT", "OPEN"])
            .order_by("number")
            .first()
        )
        if not gameweek:
            return Response({"detail": "No current gameweek."}, status=404)
        return Response(TeamGameweekStateSerializer(gameweek_state(team, gameweek)).data)

    @action(detail=True, methods=["get"])
    def points(self, request, pk=None):
        return Response(
            TeamScoreSerializer(
                self.get_object().gameweek_scores.order_by("gameweek__number"), many=True
            ).data
        )


class LeagueViewSet(viewsets.ModelViewSet):
    serializer_class = LeagueSerializer

    def get_queryset(self):
        qs = FantasyLeague.objects.select_related("fantasy_competition", "owner").filter(
            fantasy_competition__enabled=True
        )
        if not self.request.user.is_authenticated:
            return qs.filter(visibility="PUBLIC", fantasy_competition__visibility="PUBLIC")
        if self.action == "mine":
            return qs.filter(memberships__team__owner=self.request.user)
        return qs.filter(
            Q(visibility="PUBLIC", fantasy_competition__visibility="PUBLIC")
            | Q(memberships__team__owner=self.request.user)
            | Q(owner=self.request.user)
        ).distinct()

    def get_permissions(self):
        if self.action == "admin_overview":
            return [CanManageFantasy()]
        return (
            [AllowAny()]
            if self.action in {"list", "retrieve", "standings"}
            else [IsAuthenticated()]
        )

    @action(detail=False, methods=["get"], url_path="admin-overview")
    def admin_overview(self, request):
        leagues = (
            FantasyLeague.objects.select_related("fantasy_competition", "owner")
            .annotate(member_count_value=Count("memberships"))
            .order_by("fantasy_competition__name", "name")
        )
        return Response(
            [
                {
                    "id": str(row.id),
                    "name": row.name,
                    "competition": row.fantasy_competition.name,
                    "fantasy_competition": str(row.fantasy_competition_id),
                    "visibility": row.visibility,
                    "owner": safe_user_name(row.owner),
                    "member_count": row.member_count_value,
                    "capacity": row.capacity,
                    "status": (
                        "FULL"
                        if row.capacity and row.member_count_value >= row.capacity
                        else "OPEN"
                    ),
                }
                for row in leagues
            ]
        )

    def perform_create(self, serializer):
        league = serializer.save(owner=self.request.user)
        team = FantasyTeam.objects.get(
            owner=self.request.user, fantasy_competition=league.fantasy_competition
        )
        FantasyLeagueMembership.objects.get_or_create(league=league, team=team)

    def perform_update(self, serializer):
        if serializer.instance.owner_id != self.request.user.id:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Only the league owner may edit this league.")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.owner_id != self.request.user.id:
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("Only the league owner may delete this league.")
        instance.delete()

    @action(detail=False, methods=["get"])
    def mine(self, request):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    @action(detail=False, methods=["post"])
    @transaction.atomic
    def join_by_code(self, request):
        try:
            league = FantasyLeague.objects.get(
                join_code=str(request.data.get("code", "")).upper(), visibility="PRIVATE"
            )
            team = FantasyTeam.objects.get(
                owner=request.user, fantasy_competition=league.fantasy_competition
            )
        except (FantasyLeague.DoesNotExist, FantasyTeam.DoesNotExist):
            return Response(
                {"detail": "Invalid invite code or no team for this competition."}, status=400
            )
        return self._join(league, team)

    @action(detail=True, methods=["post"])
    def join(self, request, pk=None):
        league = self.get_object()
        if league.visibility != "PUBLIC":
            return Response({"detail": "Use the private league invite code."}, status=400)
        try:
            team = FantasyTeam.objects.get(
                owner=request.user, fantasy_competition=league.fantasy_competition
            )
        except FantasyTeam.DoesNotExist:
            return Response({"detail": "Create a team for this competition first."}, status=400)
        return self._join(league, team)

    def _join(self, league, team):
        if league.capacity and league.memberships.count() >= league.capacity:
            return Response({"detail": "League capacity has been reached."}, status=400)
        membership, created = FantasyLeagueMembership.objects.get_or_create(
            league=league, team=team
        )
        if created:
            notify_fantasy(
                recipient=team.owner,
                event_type="FANTASY_LEAGUE_JOINED",
                title=f"Joined {league.name}",
                message="Your Fantasy team is now in the league.",
                deduplication_key=f"fantasy:league-joined:{membership.id}",
                data={"league_id": str(league.id)},
            )
        return Response(LeagueSerializer(league).data)

    @action(detail=True, methods=["post"])
    def leave(self, request, pk=None):
        league = self.get_object()
        if league.owner_id == request.user.id:
            return Response({"detail": "The league owner cannot leave."}, status=400)
        league.memberships.filter(team__owner=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"])
    def members(self, request, pk=None):
        league = self.get_object()
        if (
            league.visibility == FantasyLeague.Visibility.PRIVATE
            and not league.memberships.filter(team__owner=request.user).exists()
        ):
            return Response(
                {"detail": "Private league membership is visible to members only."}, status=403
            )
        memberships = league.memberships.select_related("team__owner")
        totals = {
            row["team_id"]: row["total"] or 0
            for row in FantasyTeamGameweekScore.objects.filter(
                team__league_memberships__league=league
            )
            .values("team_id")
            .annotate(total=Sum("total_points"))
        }
        rows = [
            {
                "team_id": str(item.team_id),
                "fantasy_team": item.team.name,
                "manager": safe_user_name(item.team.owner),
                "total_points": totals.get(item.team_id, 0),
                "joined_at": item.created_at,
            }
            for item in memberships
        ]
        return Response(rank_rows(rows, league.fantasy_competition.tie_break_rules))

    @action(detail=True, methods=["get"])
    def standings(self, request, pk=None):
        league = self.get_object()
        scores = (
            FantasyTeamGameweekScore.objects.filter(team__league_memberships__league=league)
            .values(
                "team_id",
                "team__name",
                "team__owner__username",
                "team__owner__first_name",
                "team__owner__last_name",
                "team__created_at",
            )
            .annotate(total_points=Sum("total_points"), transfer_penalties=Sum("transfer_penalty"))
        )
        rows = list(scores)
        for row in rows:
            first_name = row.pop("team__owner__first_name")
            last_name = row.pop("team__owner__last_name")
            row["manager"] = f"{first_name} {last_name}".strip() or row.pop("team__owner__username")
        return Response(rank_rows(rows, league.fantasy_competition.tie_break_rules))


class ScoringRuleViewSet(viewsets.ModelViewSet):
    queryset = FantasyScoringRule.objects.all()
    serializer_class = ScoringRuleSerializer
    permission_classes = [CanManageFantasy]
    fantasy_permission = "platform.fantasy.scoring.manage"


class CorrectionViewSet(viewsets.ModelViewSet):
    queryset = FantasyScoringCorrection.objects.select_related("player_points")
    serializer_class = CorrectionSerializer
    permission_classes = [CanManageFantasy]
    fantasy_permission = "platform.fantasy.scoring.manage"
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related(
                "player_points__gameweek", "player_points__fantasy_player__player", "actor"
            )
        )
        gameweek = self.request.query_params.get("gameweek")
        return queryset.filter(player_points__gameweek_id=gameweek) if gameweek else queryset

    @transaction.atomic
    def perform_create(self, serializer):
        player_points = serializer.validated_data["player_points"]
        correction = serializer.save(
            actor=self.request.user, previous_value=player_points.total_points
        )
        player_points.correction_points = correction.new_value - player_points.base_points
        player_points.total_points = correction.new_value
        player_points.save(update_fields=["correction_points", "total_points", "updated_at"])
        score_gameweek(player_points.gameweek)
        for team in (
            player_points.gameweek.fantasy_competition.teams.filter(
                selections__fantasy_player=player_points.fantasy_player
            )
            .select_related("owner")
            .distinct()
        ):
            notify_fantasy(
                recipient=team.owner,
                event_type="FANTASY_SCORING_CORRECTION",
                title="Fantasy score corrected",
                message=(
                    f"{player_points.fantasy_player.player.name}'s points were corrected: "
                    f"{correction.reason}"
                ),
                deduplication_key=f"fantasy:correction:{correction.id}:{team.owner_id}",
                data={
                    "gameweek_id": str(player_points.gameweek_id),
                    "player_id": str(player_points.fantasy_player_id),
                },
            )

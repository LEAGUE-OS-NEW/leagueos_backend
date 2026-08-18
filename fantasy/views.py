from django.db import transaction
from django.db.models import Count, Q, Sum
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from discovery.models import MatchCentre, MatchPlayerStatistic, Season
from sports.models import Competition, Participant, SportingEvent

from .models import (
    FantasyCompetition,
    FantasyGameweek,
    FantasyLeague,
    FantasyLeagueMembership,
    FantasyPlayer,
    FantasyPlayerGameweekPoints,
    FantasyScoringCorrection,
    FantasyScoringRule,
    FantasyStatisticReview,
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
    MatchPlayerStatisticCreateSerializer,
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
            if self.action
            in {
                "list",
                "retrieve",
                "rules",
                "leaderboard",
                # --- Local testing: admin endpoints temporarily open ---
                "admin_list",
                "canonical_options",
                "statistic_types",
            }
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
        # Fetch all existing FantasyCompetition (competition, season) pairs so the
        # frontend can warn the admin before they attempt a duplicate submission.
        taken = FantasyCompetition.objects.values(
            "competition_id", "season_id", "id", "name"
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
                "taken_pairs": [
                    {
                        "competition": str(row["competition_id"]),
                        "season": str(row["season_id"]),
                        "fantasy_competition_id": str(row["id"]),
                        "fantasy_competition_name": row["name"],
                    }
                    for row in taken
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
            if self.action
            in {
                "list",
                "retrieve",
                "points",
                "leaderboard",
                # --- Local testing: admin endpoints temporarily open ---
                "transition",
                "recalculate",
                "finalize",
                "fixture_candidates",
            }
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
        return (
            [AllowAny()]
            if self.action
            in {
                "list",
                "retrieve",
                # --- Local testing: admin endpoints temporarily open ---
                "candidates",
                "create",
                "update",
                "partial_update",
                "destroy",
            }
            else [CanManageFantasy()]
        )

    @action(detail=False, methods=["get"])
    def candidates(self, request):
        try:
            competition = FantasyCompetition.objects.get(pk=request.query_params.get("competition"))
        except (FantasyCompetition.DoesNotExist, ValueError, TypeError):
            return Response({"competition": ["Select a valid Fantasy competition."]}, status=400)
        # Exclude athletes already present in this competition's player pool
        # so the dropdown only ever shows athletes that haven't been added yet.
        # This is competition-specific: an athlete excluded from Competition A
        # will still appear for Competition B if they haven't been added there.
        already_pooled = FantasyPlayer.objects.filter(
            fantasy_competition=competition
        ).values_list("player_id", flat=True)

        athletes = (
            Participant.objects.filter(
                kind=Participant.Kind.ATHLETE, sport=competition.competition.sport
            )
            .exclude(id__in=already_pooled)
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
            # --- Local testing: admin endpoint temporarily open ---
            return [AllowAny()]
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
    # --- Local testing: admin endpoint temporarily open ---
    permission_classes = [AllowAny]
    fantasy_permission = "platform.fantasy.scoring.manage"


class CorrectionViewSet(viewsets.ModelViewSet):
    queryset = FantasyScoringCorrection.objects.select_related("player_points")
    serializer_class = CorrectionSerializer
    # --- Local testing: admin endpoint temporarily open ---
    permission_classes = [AllowAny]
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
        # --- Local testing: fall back to first user when unauthenticated ---
        actor = self.request.user
        if not actor.is_authenticated:
            from django.contrib.auth import get_user_model

            actor = get_user_model().objects.order_by("pk").first()
        correction = serializer.save(
            actor=actor, previous_value=player_points.total_points
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


class MatchStatisticViewSet(viewsets.ViewSet):
    """
    Admin viewset for MatchPlayerStatistic management.

    Provides two distinct surfaces:

    1. REVIEW surface (primary Admin workflow):
       GET  /fantasy/admin/match-statistics/review/
            — Grouped player+fixture rows with fantasy points breakdown.
            Filter by: competition, gameweek, fixture, participant, review_status.
       GET  /fantasy/admin/match-statistics/review/<fixture_id>/<participant_id>/
            — Full detail for one player+fixture: all stats + fantasy points breakdown.
       POST /fantasy/admin/match-statistics/correct/
            — Correct a single MatchPlayerStatistic value and re-run scoring.
       POST /fantasy/admin/match-statistics/approve/
            — Approve a player+fixture review record.

    2. TEST DATA ENTRY surface (secondary, kept for dev/test workflows):
       POST /fantasy/admin/match-statistics/   — create a single stat
       GET  /fantasy/admin/match-statistics/   — list all stats (raw)
    """

    # --- Local testing: admin endpoint temporarily open ---
    permission_classes = [AllowAny]
    fantasy_permission = "platform.fantasy.scoring.manage"

    # ── helpers ────────────────────────────────────────────────────────────

    def _build_player_fixture_row(self, participant, fixture, fantasy_competition):
        """
        Build a single grouped row for the review list.

        Returns a dict with player info, all stats for this fixture, fantasy
        points breakdown from FantasyPlayerGameweekPoints (if scored), and
        the review status from FantasyStatisticReview.
        """
        from decimal import Decimal

        # Gather all MatchPlayerStatistic records for this player+fixture.
        match_centre = getattr(fixture, "match_centre", None)
        stats = []
        if match_centre:
            stats = list(
                MatchPlayerStatistic.objects.filter(
                    match_centre=match_centre,
                    participant=participant,
                ).values("id", "stat_type", "value")
            )

        # Find the gameweek(s) that include this fixture.
        gameweeks = list(
            FantasyGameweek.objects.filter(
                fantasy_competition=fantasy_competition,
                fixtures=fixture,
            ).values("id", "name", "number", "status")
        )
        gameweek = gameweeks[0] if gameweeks else None

        # Fantasy points breakdown from FantasyPlayerGameweekPoints.
        fantasy_points = None
        breakdown = []
        if gameweek:
            try:
                fp_player = FantasyPlayer.objects.get(
                    fantasy_competition=fantasy_competition,
                    player=participant,
                )
                gw = FantasyGameweek.objects.get(pk=gameweek["id"])
                pts_record = FantasyPlayerGameweekPoints.objects.filter(
                    gameweek=gw, fantasy_player=fp_player
                ).first()
                if pts_record:
                    fantasy_points = str(pts_record.total_points)
                    breakdown = pts_record.breakdown or []
            except (FantasyPlayer.DoesNotExist, FantasyGameweek.DoesNotExist):
                pass

        # Review status — get_or_create so it always exists for observable stats.
        review = None
        review_status = "PENDING"
        review_id = None
        if stats:
            review, _ = FantasyStatisticReview.objects.get_or_create(
                fantasy_competition=fantasy_competition,
                fixture=fixture,
                participant=participant,
                defaults={"status": FantasyStatisticReview.Status.PENDING},
            )
            review_status = review.status
            review_id = str(review.id)

        # Player profile info.
        profile = getattr(participant, "player_profile", None)
        club_name = profile.club.name if profile and profile.club else None
        club_id = str(profile.club.id) if profile and profile.club else None

        return {
            "participant_id": str(participant.id),
            "participant_name": participant.name,
            "club": club_name,
            "club_id": club_id,
            "fixture_id": str(fixture.id),
            "fixture_name": fixture.name,
            "fixture_status": fixture.status,
            "gameweek": gameweek,
            "stats": [
                {
                    "id": str(s["id"]),
                    "stat_type": s["stat_type"],
                    "value": str(s["value"]),
                }
                for s in stats
            ],
            "fantasy_points": fantasy_points,
            "breakdown": breakdown,
            "review_status": review_status,
            "review_id": review_id,
        }

    # ── review list ────────────────────────────────────────────────────────

    @action(detail=False, methods=["get"], url_path="review")
    def review_list(self, request):
        """
        GET /fantasy/admin/match-statistics/review/

        Returns one row per (participant, fixture) pair where at least one
        MatchPlayerStatistic exists.

        Query params:
          competition  — FantasyCompetition UUID (required)
          gameweek     — FantasyGameweek UUID (optional)
          fixture      — SportingEvent UUID (optional)
          participant  — Participant UUID (optional, player search)
          review_status — PENDING | APPROVED (optional)
        """
        competition_id = request.query_params.get("competition")
        if not competition_id:
            return Response(
                {"detail": "competition query parameter is required."}, status=400
            )
        try:
            fantasy_comp = FantasyCompetition.objects.select_related(
                "competition"
            ).get(pk=competition_id)
        except (FantasyCompetition.DoesNotExist, ValueError):
            return Response({"detail": "Fantasy competition not found."}, status=404)

        # Build the base queryset of fixtures for this competition.
        fixture_qs = SportingEvent.objects.filter(
            competition=fantasy_comp.competition
        ).prefetch_related("match_centre")

        # Optional filters.
        gameweek_id = request.query_params.get("gameweek")
        if gameweek_id:
            try:
                gw = FantasyGameweek.objects.get(
                    pk=gameweek_id, fantasy_competition=fantasy_comp
                )
                fixture_qs = fixture_qs.filter(id__in=gw.fixtures.values_list("id", flat=True))
            except (FantasyGameweek.DoesNotExist, ValueError):
                return Response({"detail": "Gameweek not found."}, status=404)

        fixture_filter = request.query_params.get("fixture")
        if fixture_filter:
            fixture_qs = fixture_qs.filter(id=fixture_filter)

        # Find all (participant, fixture) pairs that have at least one stat.
        stat_qs = MatchPlayerStatistic.objects.filter(
            match_centre__fixture__in=fixture_qs
        ).select_related(
            "match_centre__fixture",
            "participant__player_profile__club",
        ).values(
            "participant_id", "match_centre__fixture_id"
        ).distinct()

        participant_filter = request.query_params.get("participant")
        if participant_filter:
            stat_qs = stat_qs.filter(participant_id=participant_filter)

        review_status_filter = request.query_params.get("review_status")

        # Collect unique (participant_id, fixture_id) pairs.
        pairs = list(stat_qs)

        # Pre-fetch participants and fixtures.
        participant_ids = {p["participant_id"] for p in pairs}
        fixture_ids = {p["match_centre__fixture_id"] for p in pairs}

        participants = {
            str(p.id): p
            for p in Participant.objects.filter(
                id__in=participant_ids
            ).select_related("player_profile__club")
        }
        fixtures = {
            str(f.id): f
            for f in SportingEvent.objects.filter(
                id__in=fixture_ids
            ).select_related("match_centre")
        }

        # Pre-fetch review statuses.
        reviews = {
            (str(r.fixture_id), str(r.participant_id)): r
            for r in FantasyStatisticReview.objects.filter(
                fantasy_competition=fantasy_comp,
                fixture_id__in=fixture_ids,
                participant_id__in=participant_ids,
            )
        }

        # Pre-fetch fantasy points for all player+gameweek combos.
        fp_players = {
            str(fp.player_id): fp
            for fp in FantasyPlayer.objects.filter(
                fantasy_competition=fantasy_comp,
                player_id__in=participant_ids,
            )
        }
        # Gameweeks for fixture→gameweek mapping.
        fixture_to_gameweek = {}
        for gw in FantasyGameweek.objects.filter(
            fantasy_competition=fantasy_comp
        ).prefetch_related("fixtures"):
            for f in gw.fixtures.all():
                fixture_to_gameweek[str(f.id)] = gw

        # Pre-fetch points records.
        fp_player_ids = [fp.id for fp in fp_players.values()]
        points_map = {
            (str(pts.gameweek_id), str(pts.fantasy_player_id)): pts
            for pts in FantasyPlayerGameweekPoints.objects.filter(
                fantasy_player_id__in=fp_player_ids
            )
        }

        rows = []
        for pair in pairs:
            pid = str(pair["participant_id"])
            fid = str(pair["match_centre__fixture_id"])
            participant = participants.get(pid)
            fixture = fixtures.get(fid)
            if not participant or not fixture:
                continue

            # Stats for this pair.
            stat_list = list(
                MatchPlayerStatistic.objects.filter(
                    match_centre__fixture_id=fid,
                    participant_id=pid,
                ).values("id", "stat_type", "value")
            )

            # Review.
            review = reviews.get((fid, pid))
            review_status = review.status if review else "PENDING"
            review_id = str(review.id) if review else None

            # Apply review_status filter now that we have the value.
            if review_status_filter and review_status != review_status_filter:
                continue

            # Fantasy points.
            fp_player = fp_players.get(pid)
            fantasy_points = None
            breakdown = []
            gameweek = fixture_to_gameweek.get(fid)
            if fp_player and gameweek:
                pts_record = points_map.get((str(gameweek.id), str(fp_player.id)))
                if pts_record:
                    fantasy_points = str(pts_record.total_points)
                    breakdown = pts_record.breakdown or []

            profile = getattr(participant, "player_profile", None)
            rows.append({
                "participant_id": pid,
                "participant_name": participant.name,
                "club": profile.club.name if profile and profile.club else None,
                "club_id": str(profile.club.id) if profile and profile.club else None,
                "fixture_id": fid,
                "fixture_name": fixture.name,
                "fixture_status": fixture.status,
                "gameweek": {
                    "id": str(gameweek.id),
                    "name": gameweek.name,
                    "number": gameweek.number,
                    "status": gameweek.status,
                } if gameweek else None,
                "stats": [
                    {"id": str(s["id"]), "stat_type": s["stat_type"], "value": str(s["value"])}
                    for s in stat_list
                ],
                "fantasy_points": fantasy_points,
                "breakdown": breakdown,
                "review_status": review_status,
                "review_id": review_id,
            })

        return Response(rows)

    # ── review detail ──────────────────────────────────────────────────────

    @action(
        detail=False,
        methods=["get"],
        url_path=r"review/(?P<fixture_id>[^/.]+)/(?P<participant_id>[^/.]+)",
    )
    def review_detail(self, request, fixture_id=None, participant_id=None):
        """
        GET /fantasy/admin/match-statistics/review/<fixture_id>/<participant_id>/

        Full detail for one player in one fixture: all stats + full fantasy
        points breakdown from the existing scoring engine.

        Query params:
          competition — FantasyCompetition UUID (required)
        """
        competition_id = request.query_params.get("competition")
        if not competition_id:
            return Response(
                {"detail": "competition query parameter is required."}, status=400
            )
        try:
            fantasy_comp = FantasyCompetition.objects.select_related("competition").get(
                pk=competition_id
            )
        except (FantasyCompetition.DoesNotExist, ValueError):
            return Response({"detail": "Fantasy competition not found."}, status=404)

        try:
            fixture = SportingEvent.objects.select_related("match_centre").get(pk=fixture_id)
        except (SportingEvent.DoesNotExist, ValueError):
            return Response({"detail": "Fixture not found."}, status=404)

        try:
            participant = Participant.objects.select_related(
                "player_profile__club"
            ).get(pk=participant_id)
        except (Participant.DoesNotExist, ValueError):
            return Response({"detail": "Participant not found."}, status=404)

        # All stats for this player+fixture.
        stats = list(
            MatchPlayerStatistic.objects.filter(
                match_centre__fixture=fixture,
                participant=participant,
            ).values("id", "stat_type", "value")
        )

        # Gameweek lookup.
        gameweek = None
        try:
            gameweek = FantasyGameweek.objects.filter(
                fantasy_competition=fantasy_comp,
                fixtures=fixture,
            ).first()
        except Exception:
            pass

        # Fantasy points + breakdown.
        fantasy_points = None
        base_points = None
        correction_points = None
        breakdown = []
        scoring_rules = []
        try:
            fp_player = FantasyPlayer.objects.get(
                fantasy_competition=fantasy_comp,
                player=participant,
            )
            if gameweek:
                pts_record = FantasyPlayerGameweekPoints.objects.filter(
                    gameweek=gameweek, fantasy_player=fp_player
                ).first()
                if pts_record:
                    fantasy_points = str(pts_record.total_points)
                    base_points = str(pts_record.base_points)
                    correction_points = str(pts_record.correction_points)
                    breakdown = pts_record.breakdown or []

            # Include the scoring rules so the UI can show points-per-unit.
            scoring_rules = list(
                FantasyScoringRule.objects.filter(
                    fantasy_competition=fantasy_comp, enabled=True, conditions={}
                ).values("statistic_type", "points")
            )
        except FantasyPlayer.DoesNotExist:
            pass

        # Review record.
        review = FantasyStatisticReview.objects.filter(
            fantasy_competition=fantasy_comp,
            fixture=fixture,
            participant=participant,
        ).first()

        profile = getattr(participant, "player_profile", None)

        # Competition info.
        competition_data = {
            "id": str(fantasy_comp.id),
            "name": fantasy_comp.name,
        }

        return Response({
            "participant_id": str(participant.id),
            "participant_name": participant.name,
            "club": profile.club.name if profile and profile.club else None,
            "club_id": str(profile.club.id) if profile and profile.club else None,
            "fixture_id": str(fixture.id),
            "fixture_name": fixture.name,
            "fixture_status": fixture.status,
            "competition": competition_data,
            "gameweek": {
                "id": str(gameweek.id),
                "name": gameweek.name,
                "number": gameweek.number,
                "status": gameweek.status,
            } if gameweek else None,
            "stats": [
                {"id": str(s["id"]), "stat_type": s["stat_type"], "value": str(s["value"])}
                for s in stats
            ],
            "fantasy_points": fantasy_points,
            "base_points": base_points,
            "correction_points": correction_points,
            "breakdown": breakdown,
            "scoring_rules": [
                {"statistic_type": r["statistic_type"], "points": str(r["points"])}
                for r in scoring_rules
            ],
            "review_status": review.status if review else "PENDING",
            "review_id": str(review.id) if review else None,
            "approved_at": review.approved_at.isoformat() if review and review.approved_at else None,
        })

    # ── correct ────────────────────────────────────────────────────────────

    @action(detail=False, methods=["post"], url_path="correct")
    @transaction.atomic
    def correct(self, request):
        """
        POST /fantasy/admin/match-statistics/correct/

        Correct the value of a single MatchPlayerStatistic identified by its
        ID, then re-run score_gameweek() for all gameweeks that include the
        affected fixture.

        Body:
          stat_id   — MatchPlayerStatistic UUID
          value     — new numeric value (must be >= 0)
          reason    — audit reason (optional but encouraged)
        """
        stat_id = request.data.get("stat_id")
        new_value = request.data.get("value")
        reason = request.data.get("reason", "")

        if not stat_id:
            return Response({"detail": "stat_id is required."}, status=400)
        if new_value is None:
            return Response({"detail": "value is required."}, status=400)

        from decimal import Decimal, InvalidOperation

        try:
            new_decimal = Decimal(str(new_value))
        except InvalidOperation:
            return Response({"detail": "value must be a valid number."}, status=400)
        if new_decimal < Decimal("0"):
            return Response({"detail": "value must be zero or greater."}, status=400)

        try:
            stat = MatchPlayerStatistic.objects.select_related(
                "match_centre__fixture"
            ).get(pk=stat_id)
        except (MatchPlayerStatistic.DoesNotExist, ValueError):
            return Response({"detail": "Statistic not found."}, status=404)

        old_value = stat.value
        stat.value = new_decimal
        stat.save(update_fields=["value", "updated_at"])

        # Re-run scoring for every Fantasy gameweek that includes this fixture.
        fixture = stat.match_centre.fixture
        affected_gameweeks = list(
            FantasyGameweek.objects.filter(fixtures=fixture)
        )
        for gameweek in affected_gameweeks:
            score_gameweek(gameweek)

        return Response({
            "stat_id": str(stat.id),
            "stat_type": stat.stat_type,
            "participant_id": str(stat.participant_id),
            "fixture_id": str(fixture.id),
            "fixture_name": fixture.name,
            "old_value": str(old_value),
            "new_value": str(stat.value),
            "reason": reason,
            "gameweeks_rescored": [str(gw.id) for gw in affected_gameweeks],
        })

    # ── approve ────────────────────────────────────────────────────────────

    @action(detail=False, methods=["post"], url_path="approve")
    def approve(self, request):
        """
        POST /fantasy/admin/match-statistics/approve/

        Approve a FantasyStatisticReview record (player+fixture combination).
        Creates the review record if it doesn't exist yet.

        Body:
          competition  — FantasyCompetition UUID (required)
          fixture      — SportingEvent UUID (required)
          participant  — Participant UUID (required)
          notes        — optional admin notes
        """
        competition_id = request.data.get("competition")
        fixture_id = request.data.get("fixture")
        participant_id = request.data.get("participant")

        if not all([competition_id, fixture_id, participant_id]):
            return Response(
                {"detail": "competition, fixture, and participant are required."}, status=400
            )

        try:
            fantasy_comp = FantasyCompetition.objects.get(pk=competition_id)
        except (FantasyCompetition.DoesNotExist, ValueError):
            return Response({"detail": "Fantasy competition not found."}, status=404)
        try:
            fixture = SportingEvent.objects.get(pk=fixture_id)
        except (SportingEvent.DoesNotExist, ValueError):
            return Response({"detail": "Fixture not found."}, status=404)
        try:
            participant = Participant.objects.get(pk=participant_id)
        except (Participant.DoesNotExist, ValueError):
            return Response({"detail": "Participant not found."}, status=404)

        from django.utils import timezone as tz

        # Determine the actor.
        actor = request.user if request.user.is_authenticated else None
        if actor is None:
            from django.contrib.auth import get_user_model
            actor = get_user_model().objects.order_by("pk").first()

        review, _ = FantasyStatisticReview.objects.get_or_create(
            fantasy_competition=fantasy_comp,
            fixture=fixture,
            participant=participant,
            defaults={"status": FantasyStatisticReview.Status.PENDING},
        )
        review.status = FantasyStatisticReview.Status.APPROVED
        review.approved_at = tz.now()
        review.approved_by = actor
        review.notes = request.data.get("notes", review.notes)
        review.save(update_fields=["status", "approved_at", "approved_by", "notes", "updated_at"])

        return Response({
            "review_id": str(review.id),
            "status": review.status,
            "approved_at": review.approved_at.isoformat(),
            "approved_by": actor.get_full_name().strip() or actor.get_username() if actor else None,
        })

    # ── test data entry (kept for dev / secondary use) ─────────────────────

    def create(self, request):
        serializer = MatchPlayerStatisticCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        fixture = serializer.validated_data["fixture"]
        participant = serializer.validated_data["participant"]
        stat_type = serializer.validated_data["stat_type"]
        value = serializer.validated_data["value"]

        # Safely get or create the MatchCentre for this fixture.
        match_centre, mc_created = MatchCentre.objects.get_or_create(fixture=fixture)

        # Guard against duplicate (match_centre, participant, stat_type).
        if MatchPlayerStatistic.objects.filter(
            match_centre=match_centre,
            participant=participant,
            stat_type=stat_type,
        ).exists():
            return Response(
                {
                    "detail": (
                        f"A statistic of type '{stat_type}' already exists for this participant "
                        f"in fixture '{fixture.name}'. Delete or correct the existing record."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        stat = MatchPlayerStatistic.objects.create(
            match_centre=match_centre,
            participant=participant,
            stat_type=stat_type,
            value=value,
        )

        return Response(
            {
                "id": str(stat.id),
                "fixture": str(fixture.id),
                "fixture_name": fixture.name,
                "participant": str(participant.id),
                "participant_name": participant.name,
                "stat_type": stat.stat_type,
                "value": str(stat.value),
                "match_centre_created": mc_created,
            },
            status=status.HTTP_201_CREATED,
        )

    def list(self, request):
        """
        Return all MatchPlayerStatistic records, optionally filtered by
        fixture (?fixture=<uuid>) or participant (?participant=<uuid>).
        Useful for verifying test data before running recalculate.
        """
        qs = MatchPlayerStatistic.objects.select_related(
            "match_centre__fixture", "participant"
        ).order_by("-created_at")

        fixture_id = request.query_params.get("fixture")
        if fixture_id:
            qs = qs.filter(match_centre__fixture_id=fixture_id)

        participant_id = request.query_params.get("participant")
        if participant_id:
            qs = qs.filter(participant_id=participant_id)

        return Response(
            [
                {
                    "id": str(s.id),
                    "fixture": str(s.match_centre.fixture_id),
                    "fixture_name": s.match_centre.fixture.name,
                    "participant": str(s.participant_id),
                    "participant_name": s.participant.name,
                    "stat_type": s.stat_type,
                    "value": str(s.value),
                }
                for s in qs
            ]
        )

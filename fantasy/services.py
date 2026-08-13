from collections import Counter
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from discovery.models import MatchLineup, MatchPlayerStatistic

from .models import (
    FantasyPlayerGameweekPoints,
    FantasyTeamGameweekScore,
    FantasyTeamGameweekState,
    FantasyTeamPlayer,
)

SUPPORTED_TIE_BREAK_RULES = {
    "total_points",
    "fewer_transfer_penalties",
    "earlier_registration",
}


def rank_rows(rows, configured_rules, *, points_key="total_points"):
    """Apply configured Fantasy tie breaks and a deterministic UUID fallback."""
    rules = [rule for rule in configured_rules if rule in SUPPORTED_TIE_BREAK_RULES]
    if not rules:
        rules = ["total_points", "earlier_registration"]

    def key(row):
        values = []
        for rule in rules:
            if rule == "total_points":
                values.append(-Decimal(str(row.get(points_key, 0) or 0)))
            elif rule == "fewer_transfer_penalties":
                values.append(Decimal(str(row.get("transfer_penalties", 0) or 0)))
            elif rule == "earlier_registration":
                values.append(row.get("created_at"))
        values.append(str(row.get("team_id", "")))
        return tuple(values)

    ranked = sorted(rows, key=key)
    return [{"rank": index, **row} for index, row in enumerate(ranked, 1)]


def notify_fantasy(*, recipient, event_type, title, message, deduplication_key, data=None):
    """Use the shared notification domain when its seeded Fantasy category exists."""
    from notifications.models import NotificationCategory
    from notifications.services.notification_service import NotificationService

    if not NotificationCategory.objects.filter(
        code="FANTASY_TEAM_UPDATES", is_active=True
    ).exists():
        return None
    return NotificationService.create(
        recipient=recipient,
        category_code="FANTASY_TEAM_UPDATES",
        event_type=event_type,
        title=title,
        message=message,
        deduplication_key=deduplication_key,
        data=data or {},
        deep_link_path="/fan/fantasy",
    )


UNSELECTABLE_AVAILABILITY = {"INJURED", "SUSPENDED", "UNAVAILABLE"}


def validate_selections(competition, selections, *, budget=None):
    if len(selections) != competition.squad_size:
        raise ValidationError(f"Exactly {competition.squad_size} players are required.")
    players = [item["fantasy_player"] for item in selections]
    ids = [str(player.id) for player in players]
    if len(ids) != len(set(ids)):
        raise ValidationError("A player may only be selected once.")
    if any(player.fantasy_competition_id != competition.id for player in players):
        raise ValidationError("Every player must belong to this Fantasy competition.")
    if any(
        not player.eligible or player.availability in UNSELECTABLE_AVAILABILITY
        for player in players
    ):
        raise ValidationError(
            "Ineligible, injured, suspended, or unavailable players cannot be selected."
        )
    allowed_budget = competition.initial_budget if budget is None else budget
    if sum(player.price for player in players) > allowed_budget:
        raise ValidationError("Squad exceeds the available budget.")
    if Counter(player.position for player in players) != Counter(
        {key: int(value) for key, value in competition.position_rules.items()}
    ):
        raise ValidationError("Squad does not meet positional composition rules.")
    club_counts = Counter(str(player.real_team.pk) for player in players if player.real_team)
    if club_counts and max(club_counts.values()) > competition.max_players_per_team:
        raise ValidationError("Squad exceeds the maximum players from one real team/club.")

    starters = [item for item in selections if item.get("is_starter")]
    bench = [item for item in selections if not item.get("is_starter")]
    if len(starters) != competition.starting_lineup_size:
        raise ValidationError(f"Exactly {competition.starting_lineup_size} starters are required.")
    if len(bench) != competition.bench_size:
        raise ValidationError(f"Exactly {competition.bench_size} bench players are required.")
    captains = [item for item in starters if item.get("is_captain")]
    vice_captains = [item for item in starters if item.get("is_vice_captain")]
    if len(vice_captains) != 1:
        raise ValidationError("Vice captain must be exactly one starting player.")
    if len(captains) != 1:
        raise ValidationError("Captain must be exactly one starting player.")
    if captains[0]["fantasy_player"].id == vice_captains[0]["fantasy_player"].id:
        raise ValidationError("Captain and vice captain must be different players.")
    bench_orders = [item.get("bench_order") for item in bench]
    if sorted(bench_orders) != list(range(1, competition.bench_size + 1)):
        raise ValidationError(
            "Bench order must contain each position from 1 through the bench size."
        )
    if any(item.get("bench_order") is not None for item in starters):
        raise ValidationError("Starting players cannot have a bench order.")

    formation = Counter(item["fantasy_player"].position for item in starters)
    for position, limits in competition.formation_rules.items():
        count = formation.get(position, 0)
        if count < int(limits.get("min", 0)) or count > int(
            limits.get("max", competition.starting_lineup_size)
        ):
            raise ValidationError(f"Starting lineup violates formation rules for {position}.")


def deadline_locked(gameweek):
    return (
        gameweek.status not in {gameweek.Status.DRAFT, gameweek.Status.OPEN}
        or timezone.now() >= gameweek.deadline_at
    )


def gameweek_state(team, gameweek, *, lock=False):
    queryset = FantasyTeamGameweekState.objects
    if lock:
        queryset = queryset.select_for_update()
    state, _ = queryset.get_or_create(
        team=team,
        gameweek=gameweek,
        defaults={"free_transfers_allocated": team.fantasy_competition.free_transfers_per_gameweek},
    )
    return state


@transaction.atomic
def replace_lineup(team, selections):
    competition = team.fantasy_competition
    validate_selections(competition, selections, budget=competition.initial_budget)
    current = {
        selection.fantasy_player_id: selection for selection in team.selections.select_for_update()
    }
    if set(current) != {item["fantasy_player"].id for item in selections}:
        raise ValidationError("Lineup updates cannot change squad membership; use transfers.")
    for item in selections:
        selection = current[item["fantasy_player"].id]
        selection.is_starter = bool(item.get("is_starter"))
        selection.bench_order = item.get("bench_order")
        selection.is_captain = bool(item.get("is_captain"))
        selection.is_vice_captain = bool(item.get("is_vice_captain"))
    # Avoid transient conditional-unique violations when captaincy changes.
    team.selections.update(is_captain=False, is_vice_captain=False)
    FantasyTeamPlayer.objects.bulk_update(
        current.values(),
        ["is_starter", "bench_order", "is_captain", "is_vice_captain", "updated_at"],
    )
    return team


def _participated(gameweek, fantasy_player):
    fixture_ids = gameweek.fixtures.values_list("id", flat=True)
    participant_id = fantasy_player.player_id
    if MatchPlayerStatistic.objects.filter(
        match_centre__fixture_id__in=fixture_ids, participant_id=participant_id
    ).exists():
        return True
    return MatchLineup.objects.filter(
        match_centre__fixture_id__in=fixture_ids, participant_id=participant_id
    ).exists()


@transaction.atomic
def score_gameweek(gameweek):
    fixture_ids = list(gameweek.fixtures.values_list("id", flat=True))
    rules = {
        rule.statistic_type.upper(): rule
        for rule in gameweek.fantasy_competition.scoring_rules.filter(enabled=True, conditions={})
    }
    for player in gameweek.fantasy_competition.player_pool.all():
        stats = MatchPlayerStatistic.objects.filter(
            match_centre__fixture_id__in=fixture_ids, participant=player.player
        )
        breakdown, base = [], Decimal("0")
        for stat in stats:
            rule = rules.get(stat.stat_type.upper())
            if rule:
                points = stat.value * rule.points
                base += points
                breakdown.append(
                    {
                        "statistic_type": stat.stat_type,
                        "value": str(stat.value),
                        "points": str(points),
                    }
                )
        record, _ = FantasyPlayerGameweekPoints.objects.get_or_create(
            gameweek=gameweek, fantasy_player=player
        )
        latest = record.corrections.order_by("created_at", "id").last()
        correction = (latest.new_value - base) if latest else Decimal("0")
        record.base_points = base
        record.correction_points = correction
        record.total_points = base + correction
        record.breakdown = breakdown
        record.statistics_available = stats.exists()
        record.save()

    for team in gameweek.fantasy_competition.teams.all():
        selections = list(team.selections.select_related("fantasy_player").order_by("bench_order"))
        starters = [selection for selection in selections if selection.is_starter]
        total = Decimal("0")
        captain_bonus = Decimal("0")
        detail = []
        captain = next((selection for selection in starters if selection.is_captain), None)
        vice = next((selection for selection in starters if selection.is_vice_captain), None)
        effective_captain = captain
        fallback = False
        if (
            captain
            and vice
            and gameweek.fantasy_competition.vice_captain_fallback
            and not _participated(gameweek, captain.fantasy_player)
            and _participated(gameweek, vice.fantasy_player)
        ):
            effective_captain, fallback = vice, True
        for selection in starters:
            point_record = FantasyPlayerGameweekPoints.objects.filter(
                gameweek=gameweek, fantasy_player=selection.fantasy_player
            ).first()
            points = point_record.total_points if point_record else Decimal("0")
            total += points
            player_captain_bonus = Decimal("0")
            if effective_captain and selection.id == effective_captain.id:
                captain_bonus = points * (gameweek.fantasy_competition.captain_multiplier - 1)
                player_captain_bonus = captain_bonus
            detail.append(
                {
                    "player_id": str(selection.fantasy_player_id),
                    "player_name": selection.fantasy_player.player.name,
                    "position": selection.fantasy_player.position,
                    "base_points": str(point_record.base_points if point_record else Decimal("0")),
                    "correction_points": str(
                        point_record.correction_points if point_record else Decimal("0")
                    ),
                    "captain_bonus": str(player_captain_bonus),
                    "final_points": str(points + player_captain_bonus),
                    "statistics_available": bool(
                        point_record and point_record.statistics_available
                    ),
                    "captain": bool(effective_captain and selection.id == effective_captain.id),
                }
            )
        state = gameweek_state(team, gameweek)
        penalty = Decimal(state.transfer_penalty)
        FantasyTeamGameweekScore.objects.update_or_create(
            team=team,
            gameweek=gameweek,
            defaults={
                "player_points": total,
                "captain_bonus": captain_bonus,
                "transfer_penalty": penalty,
                "total_points": total + captain_bonus - penalty,
                "breakdown": {
                    "players": detail,
                    "vice_captain_fallback": fallback,
                    "effective_captain_id": (
                        str(effective_captain.fantasy_player_id) if effective_captain else None
                    ),
                },
            },
        )
    return gameweek

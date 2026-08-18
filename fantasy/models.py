import secrets
import string
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from discovery.models import Season
from sports.models import Competition, Participant, SportingEvent


class UUIDTimeStampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class FantasyCompetition(UUIDTimeStampedModel):
    class RegistrationState(models.TextChoices):
        CLOSED = "CLOSED", "Closed"
        OPEN = "OPEN", "Open"

    class Visibility(models.TextChoices):
        PUBLIC = "PUBLIC", "Public"
        PRIVATE = "PRIVATE", "Private"

    competition = models.ForeignKey(
        Competition, on_delete=models.PROTECT, related_name="fantasy_competitions"
    )
    season = models.ForeignKey(
        Season, on_delete=models.PROTECT, related_name="fantasy_competitions"
    )
    name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=True, db_index=True)
    registration_state = models.CharField(
        max_length=12, choices=RegistrationState.choices, default=RegistrationState.CLOSED
    )
    visibility = models.CharField(
        max_length=12, choices=Visibility.choices, default=Visibility.PUBLIC
    )
    squad_size = models.PositiveSmallIntegerField()
    starting_lineup_size = models.PositiveSmallIntegerField()
    bench_size = models.PositiveSmallIntegerField()
    initial_budget = models.DecimalField(max_digits=12, decimal_places=2)
    max_players_per_team = models.PositiveSmallIntegerField(default=3)
    captain_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=2)
    vice_captain_fallback = models.BooleanField(default=True)
    free_transfers_per_gameweek = models.PositiveSmallIntegerField(default=1)
    transfer_penalty = models.IntegerField(default=4)
    position_rules = models.JSONField(default=dict)
    formation_rules = models.JSONField(default=dict)
    tie_break_rules = models.JSONField(default=list)
    gameweek_rules = models.JSONField(default=dict)
    registration_deadline = models.DateTimeField(null=True, blank=True)
    prize_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["competition", "season"], name="unique_fantasy_competition_season"
            )
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}
        if (
            self.season_id
            and self.competition_id
            and self.season.competition_id != self.competition_id
        ):
            errors["season"] = "Season must belong to the selected competition."
        if any(
            value <= 0
            for value in (
                self.squad_size,
                self.starting_lineup_size,
                self.initial_budget,
                self.max_players_per_team,
                self.captain_multiplier,
            )
        ):
            errors["squad_size"] = (
                "Squad, lineup, budget, quota, and captain multiplier values must be positive."
            )
        if self.starting_lineup_size + self.bench_size != self.squad_size:
            errors["squad_size"] = "Squad size must equal starters plus bench."
        try:
            position_total = sum(int(v) for v in self.position_rules.values())
        except (TypeError, ValueError):
            position_total = -1
        if position_total != self.squad_size:
            errors["position_rules"] = "Position requirements must total squad size."
        if (
            self.season_id
            and self.competition_id
            and self.season.sport_id != self.competition.sport_id
        ):
            errors["competition"] = "Competition and season sports must match."
        if errors:
            raise ValidationError(errors)


class FantasyGameweek(UUIDTimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        OPEN = "OPEN", "Open"
        LOCKED = "LOCKED", "Locked"
        LIVE = "LIVE", "Live"
        SCORING = "SCORING", "Scoring"
        FINALIZED = "FINALIZED", "Finalized"

    fantasy_competition = models.ForeignKey(
        FantasyCompetition, on_delete=models.CASCADE, related_name="gameweeks"
    )
    number = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=100)
    starts_at = models.DateTimeField()
    deadline_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    fixtures = models.ManyToManyField(SportingEvent, related_name="fantasy_gameweeks", blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["fantasy_competition", "number"], name="unique_fantasy_gameweek_number"
            )
        ]
        ordering = ["fantasy_competition", "number"]

    def __str__(self):
        return f"{self.fantasy_competition} - {self.name}"

    def clean(self):
        errors = {}
        if not (self.starts_at <= self.deadline_at <= self.ends_at):
            errors["deadline_at"] = "Dates must satisfy starts_at <= deadline_at <= ends_at."
        if self.pk:
            bad = self.fixtures.exclude(competition_id=self.fantasy_competition.competition_id)
            if bad.exists():
                errors["fixtures"] = (
                    "Every fixture must belong to the Fantasy competition's real competition."
                )
        if errors:
            raise ValidationError(errors)


class FantasyPlayer(UUIDTimeStampedModel):
    class Availability(models.TextChoices):
        AVAILABLE = "AVAILABLE", "Available"
        DOUBTFUL = "DOUBTFUL", "Doubtful"
        INJURED = "INJURED", "Injured"
        SUSPENDED = "SUSPENDED", "Suspended"
        UNAVAILABLE = "UNAVAILABLE", "Unavailable"

    fantasy_competition = models.ForeignKey(
        FantasyCompetition, on_delete=models.CASCADE, related_name="player_pool"
    )
    player = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name="fantasy_entries",
        limit_choices_to={"kind": "ATHLETE"},
    )
    position = models.CharField(max_length=50)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    eligible = models.BooleanField(default=True)
    availability = models.CharField(
        max_length=16, choices=Availability.choices, default=Availability.AVAILABLE
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["fantasy_competition", "player"], name="unique_fantasy_player_entry"
            )
        ]
        ordering = ["position", "player__name"]

    def __str__(self):
        return f"{self.player} ({self.fantasy_competition})"

    @property
    def real_team(self):
        profile = getattr(self.player, "player_profile", None)
        return profile.club if profile else None

    def clean(self):
        errors = {}
        if self.player_id and self.player.kind != Participant.Kind.ATHLETE:
            errors["player"] = "Fantasy players must reference a canonical ATHLETE participant."
        if (
            self.player_id
            and self.fantasy_competition_id
            and self.player.sport_id != self.fantasy_competition.competition.sport_id
        ):
            errors["player"] = "Player sport must match the Fantasy competition sport."
        if self.price is not None and self.price <= 0:
            errors["price"] = "Price must be greater than zero."
        if (
            self.fantasy_competition_id
            and self.position
            and self.position not in self.fantasy_competition.position_rules
        ):
            errors["position"] = (
                "Position must be configured in the Fantasy competition position rules."
            )
        if errors:
            raise ValidationError(errors)


class FantasyTeam(UUIDTimeStampedModel):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fantasy_teams"
    )
    fantasy_competition = models.ForeignKey(
        FantasyCompetition, on_delete=models.CASCADE, related_name="teams"
    )
    name = models.CharField(max_length=100)
    budget_remaining = models.DecimalField(max_digits=12, decimal_places=2)
    free_transfers = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "fantasy_competition"],
                name="one_fantasy_team_per_owner_competition",
            )
        ]

    def __str__(self):
        return self.name

    def registration_open(self):
        competition = self.fantasy_competition
        return (
            competition.enabled
            and competition.registration_state == competition.RegistrationState.OPEN
            and (
                not competition.registration_deadline
                or timezone.now() < competition.registration_deadline
            )
        )


class FantasyTeamPlayer(UUIDTimeStampedModel):
    team = models.ForeignKey(FantasyTeam, on_delete=models.CASCADE, related_name="selections")
    fantasy_player = models.ForeignKey(
        FantasyPlayer, on_delete=models.PROTECT, related_name="team_selections"
    )
    is_starter = models.BooleanField(default=False)
    bench_order = models.PositiveSmallIntegerField(null=True, blank=True)
    is_captain = models.BooleanField(default=False)
    is_vice_captain = models.BooleanField(default=False)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "fantasy_player"], name="unique_player_per_fantasy_team"
            ),
            models.UniqueConstraint(
                fields=["team"],
                condition=models.Q(is_captain=True),
                name="one_captain_per_fantasy_team",
            ),
            models.UniqueConstraint(
                fields=["team"],
                condition=models.Q(is_vice_captain=True),
                name="one_vice_captain_per_fantasy_team",
            ),
        ]

    def __str__(self):
        return f"{self.fantasy_player} in {self.team}"


class FantasyTransfer(UUIDTimeStampedModel):
    team = models.ForeignKey(FantasyTeam, on_delete=models.CASCADE, related_name="transfers")
    gameweek = models.ForeignKey(
        FantasyGameweek, on_delete=models.PROTECT, related_name="transfers"
    )
    player_out = models.ForeignKey(
        FantasyPlayer, on_delete=models.PROTECT, related_name="transfers_out"
    )
    player_in = models.ForeignKey(
        FantasyPlayer, on_delete=models.PROTECT, related_name="transfers_in"
    )
    price_out = models.DecimalField(max_digits=10, decimal_places=2)
    price_in = models.DecimalField(max_digits=10, decimal_places=2)
    penalty_points = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.team}: {self.player_out} to {self.player_in}"


class FantasyTeamGameweekState(UUIDTimeStampedModel):
    """Immutable-per-gameweek transfer accounting snapshot for a team."""

    team = models.ForeignKey(FantasyTeam, on_delete=models.CASCADE, related_name="gameweek_states")
    gameweek = models.ForeignKey(
        FantasyGameweek, on_delete=models.CASCADE, related_name="team_states"
    )
    free_transfers_allocated = models.PositiveSmallIntegerField(default=0)
    free_transfers_used = models.PositiveSmallIntegerField(default=0)
    transfer_penalty = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "gameweek"], name="unique_fantasy_team_gameweek_state"
            )
        ]

    def __str__(self):
        return f"{self.team} - {self.gameweek} transfer state"

    @property
    def free_transfers_remaining(self):
        return max(self.free_transfers_allocated - self.free_transfers_used, 0)


class FantasyLeague(UUIDTimeStampedModel):
    class Visibility(models.TextChoices):
        PUBLIC = "PUBLIC", "Public"
        PRIVATE = "PRIVATE", "Private"

    fantasy_competition = models.ForeignKey(
        FantasyCompetition, on_delete=models.CASCADE, related_name="leagues"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_fantasy_leagues"
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    visibility = models.CharField(
        max_length=12, choices=Visibility.choices, default=Visibility.PRIVATE
    )
    join_code = models.CharField(max_length=12, unique=True, null=True, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.visibility == self.Visibility.PRIVATE and not self.join_code:
            alphabet = string.ascii_uppercase + string.digits
            while True:
                code = "".join(secrets.choice(alphabet) for _ in range(8))
                if not type(self).objects.filter(join_code=code).exists():
                    self.join_code = code
                    break
        if self.visibility == self.Visibility.PUBLIC:
            self.join_code = None
        super().save(*args, **kwargs)


class FantasyLeagueMembership(UUIDTimeStampedModel):
    league = models.ForeignKey(FantasyLeague, on_delete=models.CASCADE, related_name="memberships")
    team = models.ForeignKey(
        FantasyTeam, on_delete=models.CASCADE, related_name="league_memberships"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["league", "team"], name="unique_fantasy_league_membership"
            )
        ]

    def __str__(self):
        return f"{self.team} in {self.league}"


class FantasyScoringRule(UUIDTimeStampedModel):
    fantasy_competition = models.ForeignKey(
        FantasyCompetition, on_delete=models.CASCADE, related_name="scoring_rules"
    )
    statistic_type = models.CharField(max_length=50)
    points = models.DecimalField(max_digits=8, decimal_places=2)
    conditions = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["fantasy_competition", "statistic_type", "conditions"],
                name="unique_fantasy_scoring_rule",
            )
        ]

    def __str__(self):
        return f"{self.statistic_type}: {self.points}"


class FantasyPlayerGameweekPoints(UUIDTimeStampedModel):
    gameweek = models.ForeignKey(
        FantasyGameweek, on_delete=models.CASCADE, related_name="player_points"
    )
    fantasy_player = models.ForeignKey(
        FantasyPlayer, on_delete=models.PROTECT, related_name="gameweek_points"
    )
    base_points = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    correction_points = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_points = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    breakdown = models.JSONField(default=list)
    statistics_available = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["gameweek", "fantasy_player"], name="unique_fantasy_player_gameweek_points"
            )
        ]

    def __str__(self):
        return f"{self.fantasy_player} - {self.gameweek}: {self.total_points}"


class FantasyScoringCorrection(UUIDTimeStampedModel):
    player_points = models.ForeignKey(
        FantasyPlayerGameweekPoints, on_delete=models.CASCADE, related_name="corrections"
    )
    previous_value = models.DecimalField(max_digits=10, decimal_places=2)
    new_value = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="fantasy_scoring_corrections",
    )

    def __str__(self):
        return f"Correction for {self.player_points}: {self.new_value}"


class FantasyTeamGameweekScore(UUIDTimeStampedModel):
    team = models.ForeignKey(FantasyTeam, on_delete=models.CASCADE, related_name="gameweek_scores")
    gameweek = models.ForeignKey(
        FantasyGameweek, on_delete=models.CASCADE, related_name="team_scores"
    )
    player_points = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    captain_bonus = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    transfer_penalty = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_points = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    breakdown = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "gameweek"], name="unique_fantasy_team_gameweek_score"
            )
        ]

    def __str__(self):
        return f"{self.team} - {self.gameweek}: {self.total_points}"


class FantasyStatisticReview(UUIDTimeStampedModel):
    """
    Fantasy-side lightweight approval record for a player's statistics in a fixture.

    Created automatically the first time match statistics are viewed/processed
    for a given (fantasy_competition, fixture, participant) combination.
    Admin can approve after reviewing and optionally correcting the raw stats.

    This model lives entirely in the Fantasy app and does NOT modify
    MatchPlayerStatistic or the discovery/clubs pipeline.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending Review"
        APPROVED = "APPROVED", "Approved"

    fantasy_competition = models.ForeignKey(
        FantasyCompetition,
        on_delete=models.CASCADE,
        related_name="statistic_reviews",
    )
    fixture = models.ForeignKey(
        SportingEvent,
        on_delete=models.CASCADE,
        related_name="fantasy_statistic_reviews",
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name="fantasy_statistic_reviews",
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fantasy_statistic_approvals",
    )
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["fantasy_competition", "fixture", "participant"],
                name="unique_fantasy_statistic_review",
            )
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.participant} @ {self.fixture} "
            f"[{self.fantasy_competition}] — {self.status}"
        )

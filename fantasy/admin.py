from django.contrib import admin

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
    FantasyTeamPlayer,
    FantasyTransfer,
)

for model in [
    FantasyCompetition,
    FantasyGameweek,
    FantasyPlayer,
    FantasyTeam,
    FantasyTeamPlayer,
    FantasyTransfer,
    FantasyLeague,
    FantasyLeagueMembership,
    FantasyScoringRule,
    FantasyPlayerGameweekPoints,
    FantasyScoringCorrection,
    FantasyTeamGameweekScore,
    FantasyStatisticReview,
]:
    admin.site.register(model)

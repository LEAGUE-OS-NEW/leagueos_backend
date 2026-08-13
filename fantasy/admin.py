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
]:
    admin.site.register(model)

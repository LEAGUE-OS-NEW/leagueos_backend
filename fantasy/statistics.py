"""Approved Fantasy scoring statistics mapped to Sports Data provider keys.

Discovery currently stores provider player-stat keys as free text and has no
definition catalogue.  Keep the deliberately small supported set here so an
administrator can configure a new season before imported match history exists.
"""

FANTASY_STATISTICS = {
    "football": {
        "GOALS": "Goals",
        "ASSISTS": "Assists",
        "MINUTES_PLAYED": "Minutes played",
        "CLEAN_SHEETS": "Clean sheets",
        "SAVES": "Goalkeeper saves",
        "PENALTIES_SAVED": "Penalties saved",
        "YELLOW_CARDS": "Yellow cards",
        "RED_CARDS": "Red cards",
        "OWN_GOALS": "Own goals",
        "PENALTIES_MISSED": "Penalties missed",
        "GOALS_CONCEDED": "Goals conceded",
    },
    "rugby": {
        "TRIES": "Tries",
        "TRY_ASSISTS": "Try assists",
        "CONVERSIONS": "Conversions",
        "PENALTY_GOALS": "Penalty goals",
        "DROP_GOALS": "Drop goals",
        "TACKLES": "Tackles",
        "TURNOVERS_WON": "Turnovers won",
        "YELLOW_CARDS": "Yellow cards",
        "RED_CARDS": "Red cards",
        "MINUTES_PLAYED": "Minutes played",
    },
    "basketball": {
        "POINTS": "Points",
        "REBOUNDS": "Rebounds",
        "ASSISTS": "Assists",
        "STEALS": "Steals",
        "BLOCKS": "Blocks",
        "TURNOVERS": "Turnovers",
        "THREE_POINTERS_MADE": "Three-pointers made",
        "FREE_THROWS_MADE": "Free throws made",
        "MINUTES_PLAYED": "Minutes played",
    },
}


def statistic_catalogue(sport) -> dict[str, str]:
    """Return definitions for a canonical Sport without trusting arbitrary data."""
    candidates = {str(getattr(sport, "slug", "")).lower(), str(getattr(sport, "name", "")).lower()}
    for candidate in candidates:
        if candidate in FANTASY_STATISTICS:
            return FANTASY_STATISTICS[candidate]
    return {}

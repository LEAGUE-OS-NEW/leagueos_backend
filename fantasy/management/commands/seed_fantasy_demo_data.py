from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from discovery.models import PlayerProfile, Season
from fantasy.models import FantasyCompetition, FantasyGameweek, FantasyPlayer, FantasyScoringRule
from fantasy.statistics import statistic_catalogue
from profiles.models import Club
from sports.models import Competition, Participant, SportingEvent

DEMO_SOURCE = "LEAGUE_OS_FANTASY_DEMO"
CONFIG = {
    "football": {
        "positions": ["GK", "DEF", "MID", "FWD"],
        "rules": {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3},
        "starters": 11,
    },
    "rugby": {
        "positions": ["FR", "LK", "BR", "HB", "CT", "B3"],
        "rules": {"FR": 3, "LK": 2, "BR": 3, "HB": 2, "CT": 2, "B3": 3},
        "starters": 15,
    },
    "basketball": {
        "positions": ["PG", "SG", "SF", "PF", "C"],
        "rules": {"PG": 2, "SG": 2, "SF": 2, "PF": 2, "C": 2},
        "starters": 5,
    },
}


def demo_price(team_index, position_index):
    """Return deterministic local-demo configuration prices."""
    return (Decimal("4.00"), Decimal("8.00"), Decimal("12.00"))[(team_index + position_index) % 3]


def resolve_club(team, competition):
    """Reuse an exact canonical Club or create a clearly demo-owned one."""
    exact = Club.objects.filter(
        name=team.name, sport=competition.sport, competition=competition
    ).first()
    if exact:
        return exact, False

    demo_slug = slugify(f"fantasy-demo-{competition.sport.slug}-{team.slug}")
    demo_name = f"Fantasy Demo {team.name} ({competition.sport.name})"
    existing = Club.objects.filter(slug=demo_slug).first()
    if existing:
        if (
            existing.name != demo_name
            or existing.sport_id != competition.sport_id
            or existing.competition_id != competition.id
        ):
            raise CommandError(
                f"Refusing to overwrite unrelated Club with demo slug '{demo_slug}'."
            )
        return existing, False
    return (
        Club.objects.create(
            slug=demo_slug,
            name=demo_name,
            sport=competition.sport,
            competition=competition,
        ),
        True,
    )


class Command(BaseCommand):
    help = "Prepare idempotent local Fantasy data using the canonical sports dataset."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "Refusing to seed Fantasy demo data when DEBUG is False; "
                "this command is for local development only."
            )
        if not options["confirm"]:
            raise CommandError("Refusing to seed without --confirm.")

        counts = Counter()
        for slug, config in CONFIG.items():
            competition = (
                Competition.objects.select_related("sport")
                .filter(sport__slug__iexact=slug, is_active=True)
                .order_by("created_at")
                .first()
            )
            if not competition:
                counts["skipped_competitions"] += 1
                self.stdout.write(self.style.WARNING(f"Skipping {slug}: no canonical competition."))
                continue

            teams = list(
                Participant.objects.filter(
                    sport=competition.sport, kind=Participant.Kind.TEAM, is_active=True
                ).order_by("name")
            )
            events = list(
                SportingEvent.objects.filter(competition=competition).order_by("starts_at")
            )
            if len(teams) < 6 or not events:
                counts["skipped_competitions"] += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping {slug}: six canonical teams and fixtures required."
                    )
                )
                continue

            first_date = events[0].starts_at.date()
            last_date = max((event.ends_at or event.starts_at).date() for event in events)
            season, made = Season.objects.update_or_create(
                sport=competition.sport,
                competition=competition,
                slug="fantasy-demo-season",
                defaults={
                    "name": "Fantasy Demo Season (Local Development)",
                    "starts_on": first_date - timedelta(days=30),
                    "ends_on": last_date + timedelta(days=30),
                    "is_active": True,
                    "is_verified": False,
                },
            )
            counts["seasons_created" if made else "seasons_reused"] += 1

            athletes = []
            positions = config["positions"]
            for team_index, team in enumerate(teams):
                club, club_made = resolve_club(team, competition)
                counts["clubs_created" if club_made else "clubs_reused"] += 1
                for position_index, position in enumerate(positions):
                    reference = f"athlete:{slug}:{team.slug}:{position.lower()}"
                    athlete, athlete_made = Participant.objects.update_or_create(
                        source_name=DEMO_SOURCE,
                        source_reference=reference,
                        defaults={
                            "sport": competition.sport,
                            "kind": Participant.Kind.ATHLETE,
                            "name": f"Demo {team.short_name or team.name} {position}",
                            "short_name": f"Demo {position} {team_index + 1}",
                            "country_code": "UG",
                            "is_active": True,
                            "is_verified": False,
                        },
                    )
                    counts["athletes_created" if athlete_made else "athletes_reused"] += 1
                    profile, profile_made = PlayerProfile.objects.update_or_create(
                        participant=athlete,
                        defaults={
                            "club": club,
                            "position": position,
                            "shirt_number": position_index + 1,
                            "status": PlayerProfile.Status.ACTIVE,
                            "is_published": True,
                            "is_verified": False,
                            "biography": "Deterministic local-development Fantasy athlete.",
                        },
                    )
                    counts["profiles_created" if profile_made else "profiles_reused"] += 1
                    athletes.append((athlete, profile, team_index, position_index))

            rules = config["rules"]
            squad_size = sum(rules.values())
            fantasy, fantasy_made = FantasyCompetition.objects.update_or_create(
                competition=competition,
                season=season,
                defaults={
                    "name": f"{competition.name} Fantasy (Local Demo)",
                    "description": (
                        "Local development competition backed by canonical sports records. "
                        "Its 1-point statistic rules are LOCAL DEMO scoring defaults, not "
                        "approved production scoring policy."
                    ),
                    "enabled": True,
                    "registration_state": FantasyCompetition.RegistrationState.OPEN,
                    "visibility": FantasyCompetition.Visibility.PUBLIC,
                    "squad_size": squad_size,
                    "starting_lineup_size": config["starters"],
                    "bench_size": squad_size - config["starters"],
                    "initial_budget": Decimal("100.00"),
                    "max_players_per_team": 3,
                    "position_rules": rules,
                    "formation_rules": {
                        key: {"min": 0, "max": count} for key, count in rules.items()
                    },
                    "tie_break_rules": ["total_points", "fewer_transfer_penalties"],
                    "prize_metadata": {},
                },
            )
            counts[
                "fantasy_competitions_created" if fantasy_made else "fantasy_competitions_reused"
            ] += 1

            for athlete, profile, team_index, position_index in athletes:
                _, player_made = FantasyPlayer.objects.update_or_create(
                    fantasy_competition=fantasy,
                    player=athlete,
                    defaults={
                        "position": profile.position,
                        "price": demo_price(team_index, position_index),
                        "eligible": True,
                        "availability": FantasyPlayer.Availability.AVAILABLE,
                    },
                )
                counts["fantasy_players_created" if player_made else "fantasy_players_reused"] += 1

            gameweek_defaults = {
                "name": "Gameweek 1",
                "starts_at": events[0].starts_at,
                "deadline_at": events[0].starts_at,
                "ends_at": max(
                    event.ends_at or event.starts_at + timedelta(hours=3) for event in events
                ),
                "status": FantasyGameweek.Status.OPEN,
            }
            gameweek, gameweek_made = FantasyGameweek.objects.get_or_create(
                fantasy_competition=fantasy,
                number=1,
                defaults=gameweek_defaults,
            )
            if gameweek_made or gameweek.status in {
                FantasyGameweek.Status.DRAFT,
                FantasyGameweek.Status.OPEN,
            }:
                for field in ("name", "starts_at", "deadline_at", "ends_at"):
                    setattr(gameweek, field, gameweek_defaults[field])
                if not gameweek_made:
                    gameweek.save(update_fields=["name", "starts_at", "deadline_at", "ends_at"])
                gameweek.fixtures.set(events)
            counts["gameweeks_created" if gameweek_made else "gameweeks_reused"] += 1

            for statistic in statistic_catalogue(competition.sport):
                _, rule_made = FantasyScoringRule.objects.update_or_create(
                    fantasy_competition=fantasy,
                    statistic_type=statistic.upper(),
                    conditions={},
                    defaults={"points": Decimal("1.00"), "enabled": True},
                )
                counts["scoring_rules_created" if rule_made else "scoring_rules_reused"] += 1

        for key in sorted(counts):
            self.stdout.write(f"{key}: {counts[key]}")
        self.stdout.write(
            self.style.SUCCESS("Fantasy local demo data is ready; no statistics created.")
        )

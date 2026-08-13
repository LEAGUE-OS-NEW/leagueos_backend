from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from discovery.models import PlayerProfile, Season
from fantasy.models import FantasyCompetition, FantasyGameweek, FantasyPlayer, FantasyScoringRule
from sports.models import Competition, Participant, SportingEvent
from fantasy.statistics import statistic_catalogue

CONFIG = {
    "football": ({"Goalkeepers": 2, "Defenders": 5, "Midfielders": 5, "Forwards": 3}, 11),
    "rugby": (
        {
            "Front Row": 3,
            "Second Row": 2,
            "Back Row": 3,
            "Half Backs": 2,
            "Centres": 2,
            "Back Three": 3,
        },
        15,
    ),
    "basketball": (
        {
            "Point Guards": 2,
            "Shooting Guards": 2,
            "Small Forwards": 2,
            "Power Forwards": 2,
            "Centers": 2,
        },
        5,
    ),
}


class Command(BaseCommand):
    help = "Idempotently seed Fantasy configuration by reusing canonical demo sports records."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", action="store_true")

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("Refusing to seed without --confirm.")
        created = 0
        for slug, (position_rules, starters) in CONFIG.items():
            competition = Competition.objects.filter(sport__slug__iexact=slug).first()
            if not competition:
                self.stdout.write(self.style.WARNING(f"Skipping {slug}: no canonical competition."))
                continue
            season = Season.objects.filter(competition=competition).first()
            athletes = Participant.objects.filter(
                sport=competition.sport, kind=Participant.Kind.ATHLETE, player_profile__isnull=False
            )
            events = SportingEvent.objects.filter(competition=competition).order_by("starts_at")[
                :10
            ]
            if not season or not athletes.exists() or not events.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping {slug}: season, athletes, or fixtures unavailable."
                    )
                )
                continue
            squad = sum(position_rules.values())
            fantasy, was_created = FantasyCompetition.objects.update_or_create(
                competition=competition,
                season=season,
                defaults={
                    "name": f"{competition.name} Fantasy",
                    "enabled": True,
                    "registration_state": "OPEN",
                    "visibility": "PUBLIC",
                    "squad_size": squad,
                    "starting_lineup_size": starters,
                    "bench_size": squad - starters,
                    "initial_budget": Decimal("100"),
                    "max_players_per_team": 3,
                    "position_rules": position_rules,
                    "formation_rules": {
                        key: {"min": 0, "max": count} for key, count in position_rules.items()
                    },
                    "tie_break_rules": ["total_points", "fewer_transfer_penalties"],
                },
            )
            created += int(was_created)
            for athlete in athletes:
                profile = athlete.player_profile
                position = (
                    profile.position
                    if profile.position in position_rules
                    else next(iter(position_rules))
                )
                FantasyPlayer.objects.update_or_create(
                    fantasy_competition=fantasy,
                    player=athlete,
                    defaults={
                        "position": position,
                        "price": Decimal("5.00"),
                        "eligible": profile.status == PlayerProfile.Status.ACTIVE,
                        "availability": (
                            "AVAILABLE"
                            if profile.status == PlayerProfile.Status.ACTIVE
                            else (
                                profile.status
                                if profile.status in {"INJURED", "SUSPENDED"}
                                else "UNAVAILABLE"
                            )
                        ),
                    },
                )
            gameweek, _ = FantasyGameweek.objects.update_or_create(
                fantasy_competition=fantasy,
                number=1,
                defaults={
                    "name": "Gameweek 1",
                    "starts_at": events[0].starts_at,
                    "deadline_at": events[0].starts_at,
                    "ends_at": max(
                        (event.ends_at or event.starts_at + timedelta(hours=3)) for event in events
                    ),
                    "status": "DRAFT",
                },
            )
            gameweek.fixtures.set(events)
            for statistic in statistic_catalogue(competition.sport):
                FantasyScoringRule.objects.get_or_create(
                    fantasy_competition=fantasy,
                    statistic_type=statistic.upper(),
                    conditions={},
                    defaults={"points": Decimal("1"), "enabled": True},
                )
        self.stdout.write(
            self.style.SUCCESS(
                f"Fantasy demo configuration ready; {created} competition(s) created."
            )
        )

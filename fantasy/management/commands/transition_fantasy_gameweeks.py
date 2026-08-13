from django.core.management.base import BaseCommand
from django.utils import timezone

from fantasy.models import FantasyGameweek
from fantasy.services import notify_fantasy


class Command(BaseCommand):
    help = "Idempotently advance time/event-driven Fantasy gameweek states without finalizing."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        now = timezone.now()
        transitions = []
        for gameweek in FantasyGameweek.objects.prefetch_related("fixtures").order_by("starts_at"):
            target = None
            if (
                gameweek.status == FantasyGameweek.Status.DRAFT
                and gameweek.starts_at <= now < gameweek.deadline_at
            ):
                target = FantasyGameweek.Status.OPEN
            elif gameweek.status == FantasyGameweek.Status.OPEN and now >= gameweek.deadline_at:
                target = FantasyGameweek.Status.LOCKED
            elif gameweek.status == FantasyGameweek.Status.LOCKED and (
                now >= gameweek.starts_at or gameweek.fixtures.filter(status="LIVE").exists()
            ):
                target = FantasyGameweek.Status.LIVE
            elif (
                gameweek.status == FantasyGameweek.Status.LIVE
                and gameweek.fixtures.exists()
                and not gameweek.fixtures.exclude(
                    status__in=["COMPLETED", "CANCELLED", "ABANDONED"]
                ).exists()
            ):
                target = FantasyGameweek.Status.SCORING
            if target:
                transitions.append((gameweek, target))
        for gameweek, target in transitions:
            self.stdout.write(f"{gameweek.id}: {gameweek.status} -> {target}")
            if not options["dry_run"]:
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
        suffix = " (dry run)" if options["dry_run"] else ""
        self.stdout.write(
            self.style.SUCCESS(f"Transitioned {len(transitions)} Fantasy gameweek(s){suffix}.")
        )

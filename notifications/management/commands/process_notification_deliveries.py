from django.core.management.base import BaseCommand, CommandError

from notifications.models import NotificationChannel
from notifications.services.notification_delivery_service import NotificationDeliveryService


class Command(BaseCommand):
    help = "Process persisted notification deliveries."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--channel", choices=["EMAIL", "IN_APP", "PUSH"])
        parser.add_argument("--max-attempts", type=int, default=5)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 1000:
            raise CommandError("--limit must be between 1 and 1000")
        if not 1 <= options["max_attempts"] <= 20:
            raise CommandError("--max-attempts must be between 1 and 20")
        if (
            options["channel"]
            and not NotificationChannel.objects.filter(code=options["channel"]).exists()
        ):
            raise CommandError("The selected channel has not been seeded")
        rows = NotificationDeliveryService.process(
            limit=options["limit"],
            channel=options["channel"],
            max_attempts=options["max_attempts"],
            dry_run=options["dry_run"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"{'Would process' if options['dry_run'] else 'Processed'} {len(rows)} deliveries"
            )
        )

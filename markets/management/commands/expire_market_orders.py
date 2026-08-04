from django.core.management.base import BaseCommand, CommandError

from markets.services.order_expiry_service import MarketOrderExpiryService


class Command(BaseCommand):
    help = "Expire due good-till-date market orders."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        try:
            audits = MarketOrderExpiryService.expire_due_orders(limit=options["limit"])
        except Exception as error:
            if hasattr(error, "message_dict"):
                detail = "; ".join(
                    f"{field}: {', '.join(messages)}"
                    for field, messages in error.message_dict.items()
                )
                raise CommandError(detail) from error
            raise
        self.stdout.write(self.style.SUCCESS(f"Expired {len(audits)} market order(s)."))

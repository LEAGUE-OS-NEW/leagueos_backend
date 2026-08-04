from datetime import date

from django.core.management.base import BaseCommand, CommandError

from markets.models import Market
from markets.services.reconciliation_service import MarketReconciliationService
from wallets.models import Wallet


class Command(BaseCommand):
    help = "Run immutable market financial reconciliation."

    def add_arguments(self, parser):
        parser.add_argument("--market-id")
        parser.add_argument("--date", type=date.fromisoformat)
        parser.add_argument("--wallet-id")
        parser.add_argument("--limit", type=int, default=1000)

    def handle(self, *args, **options):
        if options["limit"] < 1 or options["limit"] > 10000:
            raise CommandError("limit must be between 1 and 10000")
        market = None
        if options["market_id"]:
            market = Market.objects.get(id=options["market_id"])
        wallet = None
        if options["wallet_id"]:
            wallet = Wallet.objects.get(id=options["wallet_id"])
        run = MarketReconciliationService.run(
            run_date=options["date"],
            market=market,
            wallet=wallet,
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Reconciliation {run.id} completed with {run.mismatch_count} mismatch(es)."
            )
        )

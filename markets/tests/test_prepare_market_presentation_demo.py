from datetime import timedelta
from io import StringIO
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from authentication.tests.factories import UserFactory
from markets.management.commands.prepare_market_presentation_demo import DEMO_MARKETS
from markets.models import (
    Market,
    MarketCategory,
    MarketCompleteSetIssuance,
    MarketLiquidityConfiguration,
    MarketLiquidityProvider,
    MarketOrder,
    MarketScope,
)
from markets.services.catalog_service import MarketCatalogService
from sports.models import Sport
from wallets.models import LedgerEntry
from wallets.services.wallet_service import WalletService


@override_settings(DEBUG=True)
class PrepareMarketPresentationDemoTests(TestCase):
    def setUp(self):
        self.admin = UserFactory(is_superuser=True, is_staff=True)
        self.sport = Sport.objects.create(name="Presentation Sport", code="PRESENTATION")
        self.category = MarketCategory.objects.create(name="Presentation Winner")
        now = timezone.now()
        self.curated = [
            self._market(
                question, Market.Status.OPEN, now - timedelta(days=1), now + timedelta(days=1)
            )
            for question in DEMO_MARKETS
        ]
        self.stale = self._market(
            "Will this stale presentation record remain live?",
            Market.Status.OPEN,
            now - timedelta(days=10),
            now - timedelta(days=5),
        )
        self.resolved = self._market(
            "LOCAL QA: Will City Oilers beat Namuwongo Blazers?",
            Market.Status.OPEN,
            now - timedelta(days=20),
            now - timedelta(days=10),
        )
        winning_outcome = self.resolved.outcomes.get(side="YES")
        Market.objects.filter(pk=self.resolved.pk).update(
            status=Market.Status.RESOLVED,
            winning_outcome=winning_outcome,
            resolved_by=self.admin,
            resolved_at=now - timedelta(days=9),
            resolution_notes="Local QA result.",
            resolution_evidence="Local QA evidence.",
        )
        history_user = UserFactory()
        self.history_entry = WalletService.credit(
            user=history_user,
            currency="UGX",
            amount="1000",
            idempotency_reference=uuid4(),
            market=self.stale,
        )

    def _market(self, question, status, opens_at, closes_at):
        return MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.CUSTOM,
            custom_subject=question,
            question=question,
            status=status,
            opens_at=opens_at,
            closes_at=closes_at,
            yes_label="Yes",
            no_label="No",
        )

    def test_requires_explicit_confirmation(self):
        with self.assertRaisesMessage(CommandError, "--confirm"):
            call_command("prepare_market_presentation_demo")

    def test_prepares_tradeable_markets_and_archives_stale_without_deleting_history(self):
        output = StringIO()
        call_command("prepare_market_presentation_demo", "--confirm", stdout=output)

        for market in self.curated:
            market.refresh_from_db()
            prices = dict(market.outcomes.values_list("side", "opening_price"))
            self.assertEqual(market.status, Market.Status.OPEN)
            self.assertGreater(market.closes_at, timezone.now())
            self.assertLessEqual(market.opens_at, timezone.now())
            self.assertTrue(market.is_catalog_visible)
            self.assertTrue(market.is_featured)
            self.assertIsNotNone(prices["YES"])
            self.assertIsNotNone(prices["NO"])
            self.assertEqual(prices["YES"] + prices["NO"], 1)
            config = market.liquidity_configuration
            self.assertEqual(config.status, MarketLiquidityConfiguration.Status.ACTIVE)
            self.assertEqual(config.initial_liquidity_ugx, 400000)
            self.assertEqual(market.complete_set_issuances.count(), 1)
            self.assertEqual(market.orders.filter(status=MarketOrder.Status.OPEN).count(), 2)

        self.stale.refresh_from_db()
        self.assertEqual(self.stale.status, Market.Status.OPEN)
        self.assertFalse(self.stale.is_catalog_visible)
        self.assertTrue(LedgerEntry.objects.filter(pk=self.history_entry.pk).exists())
        self.resolved.refresh_from_db()
        self.assertEqual(self.resolved.status, Market.Status.RESOLVED)
        self.assertTrue(self.resolved.is_catalog_visible)
        self.assertIn("ACTIVE PRESENTATION MARKETS", output.getvalue())
        self.assertIn("ARCHIVED / HIDDEN", output.getvalue())

    def test_repeated_run_is_idempotent_and_wallet_changes_are_ledger_backed(self):
        call_command("prepare_market_presentation_demo", "--confirm", stdout=StringIO())
        counts = (
            MarketLiquidityProvider.objects.count(),
            MarketCompleteSetIssuance.objects.count(),
            MarketOrder.objects.count(),
            LedgerEntry.objects.count(),
        )

        call_command("prepare_market_presentation_demo", "--confirm", stdout=StringIO())

        self.assertEqual(
            counts,
            (
                MarketLiquidityProvider.objects.count(),
                MarketCompleteSetIssuance.objects.count(),
                MarketOrder.objects.count(),
                LedgerEntry.objects.count(),
            ),
        )
        self.assertEqual(
            LedgerEntry.objects.filter(
                wallet__user__email="presentation.liquidity@leagueos.test"
            ).count(),
            5,
        )

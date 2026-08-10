from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from markets.models import MarketCategory


class SeedMarketCatalogCommandTests(TestCase):
    def test_seed_creates_match_result_category(self):
        output = StringIO()

        call_command(
            "seed_market_catalog",
            stdout=output,
        )

        category = MarketCategory.objects.get(
            name="Match Result",
        )

        self.assertTrue(
            category.is_active,
        )
        self.assertEqual(
            category.slug,
            "match-result",
        )
        self.assertEqual(
            category.display_order,
            10,
        )

        self.assertIn(
            "Successfully seeded market catalogue.",
            output.getvalue(),
        )

    def test_seed_is_idempotent(self):
        call_command(
            "seed_market_catalog",
            stdout=StringIO(),
        )

        call_command(
            "seed_market_catalog",
            stdout=StringIO(),
        )

        self.assertEqual(
            MarketCategory.objects.filter(
                name="Match Result",
            ).count(),
            1,
        )

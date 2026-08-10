from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from markets.models import MarketCategory

EXPECTED_CATEGORIES = [
    "Match Result",
    "Totals",
    "Handicap / Spread",
    "Correct Score / Margin",
    "Player / Team Prop",
    "Tournament / Season",
    "Event / Occurrence",
]


class SeedMarketCatalogCommandTests(TestCase):
    def test_seed_creates_required_market_categories(self):
        output = StringIO()

        call_command(
            "seed_market_catalog",
            stdout=output,
        )

        categories = list(
            MarketCategory.objects.filter(
                is_active=True,
            )
            .order_by("display_order")
            .values_list(
                "name",
                flat=True,
            )
        )

        self.assertEqual(
            categories,
            EXPECTED_CATEGORIES,
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
            MarketCategory.objects.count(),
            len(EXPECTED_CATEGORIES),
        )

from io import StringIO

from django.core.management import (
    call_command,
)
from django.test import TestCase

from authentication.tests.factories import (
    UserFactory,
)
from markets.models import (
    Market,
    MarketTemplate,
)
from sports.models import (
    Competition,
    Participant,
    Sport,
    SportingEvent,
)


class SeedMarketDemoDataTests(TestCase):
    def setUp(self):
        self.admin = UserFactory(
            email="admin@leagueos.com",
            is_superuser=True,
            is_staff=True,
        )

        Sport.objects.create(
            name="Football",
            code="FOOTBALL",
        )
        Sport.objects.create(
            name="Rugby",
            code="RUGBY",
        )
        Sport.objects.create(
            name="Basketball",
            code="BASKETBALL",
        )

        call_command(
            "seed_market_catalog",
            stdout=StringIO(),
        )

    def run_seed(self):
        output = StringIO()

        call_command(
            "seed_market_demo_data",
            "--confirm",
            "--creator-email",
            self.admin.email,
            stdout=output,
        )

        return output.getvalue()

    def test_seed_creates_real_demo_catalogue(self):
        output = self.run_seed()

        self.assertEqual(
            Competition.objects.filter(source_name=("LEAGUE_OS_DEMO")).count(),
            3,
        )

        self.assertEqual(
            SportingEvent.objects.filter(source_name=("LEAGUE_OS_DEMO")).count(),
            9,
        )

        self.assertGreaterEqual(
            Participant.objects.filter(source_name=("LEAGUE_OS_DEMO")).count(),
            18,
        )

        self.assertEqual(
            MarketTemplate.objects.count(),
            7,
        )

        self.assertEqual(
            Market.objects.filter(
                status=Market.Status.OPEN,
            ).count(),
            16,
        )

        self.assertIn(
            "Market demo seed complete",
            output,
        )

    def test_seed_is_idempotent(self):
        self.run_seed()

        before = {
            "competitions": (Competition.objects.count()),
            "participants": (Participant.objects.count()),
            "events": (SportingEvent.objects.count()),
            "templates": (MarketTemplate.objects.count()),
            "markets": (Market.objects.count()),
        }

        self.run_seed()

        after = {
            "competitions": (Competition.objects.count()),
            "participants": (Participant.objects.count()),
            "events": (SportingEvent.objects.count()),
            "templates": (MarketTemplate.objects.count()),
            "markets": (Market.objects.count()),
        }

        self.assertEqual(
            before,
            after,
        )

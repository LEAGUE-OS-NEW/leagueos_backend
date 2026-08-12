from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from markets.models import (
    Market,
    MarketCategory,
    MarketScope,
)
from markets.services.catalog_service import (
    MarketCatalogService,
)
from sports.models import (
    Competition,
    Sport,
    SportingEvent,
)


class MarketStatsAPITests(APITestCase):
    def setUp(self):
        now = timezone.now()

        self.sport = Sport.objects.create(
            name="Rugby",
            code="RUGBY",
        )

        self.category = MarketCategory.objects.create(
            name="Match Result",
        )

        self.competition = Competition.objects.create(
            sport=self.sport,
            name="Test Rugby League",
            country_code="UG",
            is_verified=True,
        )

        self.event = SportingEvent.objects.create(
            sport=self.sport,
            competition=(self.competition),
            name="KOBS vs Heathens",
            starts_at=(
                now
                + timedelta(
                    days=2,
                )
            ),
            status=(SportingEvent.Status.SCHEDULED),
            is_verified=True,
            verified_at=now,
        )

        MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question=("Will KOBS beat Heathens?"),
            rules="Official result.",
            resolution_source=("Official result"),
            resolution_criteria=("Verified final score."),
            status=Market.Status.OPEN,
            opens_at=(
                now
                - timedelta(
                    hours=1,
                )
            ),
            closes_at=(
                now
                + timedelta(
                    days=1,
                )
            ),
        )

    def test_public_stats_use_real_markets(self):
        response = self.client.get(reverse("markets:market-stats"))

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        self.assertEqual(
            response.data["total_markets"],
            1,
        )
        self.assertEqual(
            response.data["open_markets"],
            1,
        )
        self.assertEqual(
            response.data["trader_count"],
            0,
        )
        self.assertEqual(
            Decimal(response.data["total_volume_ugx"]),
            Decimal("0.00"),
        )

        rugby = next(item for item in response.data["sports"] if item["code"] == "RUGBY")

        self.assertEqual(
            rugby["total_markets"],
            1,
        )
        self.assertEqual(
            rugby["open_markets"],
            1,
        )

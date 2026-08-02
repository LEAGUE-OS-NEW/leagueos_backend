from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from authentication.tests.factories import UserFactory
from markets.models import Market, MarketCategory, MarketOrder, MarketOutcome, MarketScope
from sports.models import Sport


class MarketOrderBookAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        sport = Sport.objects.create(name="Football", code="FOOTBALL")
        category = MarketCategory.objects.create(name="Results")
        self.market = Market.objects.create(
            sport=sport,
            category=category,
            scope_type=MarketScope.CUSTOM,
            custom_subject="Cup",
            question="Win?",
            status=Market.Status.OPEN,
            closes_at=timezone.now(),
        )
        self.outcome = MarketOutcome.objects.create(
            market=self.market, side="YES", position=1, label="Yes"
        )
        MarketOutcome.objects.create(market=self.market, side="NO", position=2, label="No")
        self.user = UserFactory()
        self.url = reverse(
            "markets:market-order-book",
            kwargs={"market_id": self.market.id, "outcome_id": self.outcome.id},
        )

    def test_public_response_contract_precision_and_privacy(self):
        MarketOrder.objects.create(
            user=self.user,
            market=self.market,
            outcome=self.outcome,
            side="BUY",
            quantity=Decimal("2.0000"),
            limit_price=Decimal("0.62000"),
            status="OPEN",
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["market_id"], str(self.market.id))
        self.assertEqual(
            response.data["outcome"], {"id": str(self.outcome.id), "side": "YES", "label": "Yes"}
        )
        self.assertEqual(response.data["best_bid"], "0.62000")
        self.assertIsNone(response.data["best_ask"])
        self.assertIsNone(response.data["spread"])
        self.assertEqual(response.data["total_bid_quantity"], "2.0000")
        self.assertEqual(response.data["total_ask_quantity"], "0.0000")
        self.assertEqual(
            response.data["bids"], [{"price": "0.62000", "quantity": "2.0000", "order_count": 1}]
        )
        rendered = str(response.data).lower()
        for private in ("user", "buyer", "seller", "wallet", "order_id"):
            self.assertNotIn(private, rendered)

    def test_empty_book_contract(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["best_bid"], None)
        self.assertEqual(response.data["best_ask"], None)
        self.assertEqual(response.data["spread"], None)
        self.assertEqual(response.data["bids"], [])
        self.assertEqual(response.data["asks"], [])
        self.assertEqual(response.data["recent_trades"], [])

    def test_invalid_query_parameters_are_field_specific(self):
        for field, values in {
            "levels": ("0", "101", "abc"),
            "trades": ("-1", "101", "abc"),
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    response = self.client.get(self.url, {field: value})
                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertIn(field, response.data)

    def test_missing_market_and_outcome_outside_market_return_404(self):
        missing = self.client.get(
            reverse(
                "markets:market-order-book",
                kwargs={
                    "market_id": "00000000-0000-0000-0000-000000000001",
                    "outcome_id": self.outcome.id,
                },
            )
        )
        other = Market.objects.create(
            sport=self.market.sport,
            category=self.market.category,
            scope_type=MarketScope.CUSTOM,
            custom_subject="Other",
            question="Other?",
            status=Market.Status.OPEN,
        )
        outside = self.client.get(
            reverse(
                "markets:market-order-book",
                kwargs={"market_id": other.id, "outcome_id": self.outcome.id},
            )
        )
        self.assertEqual(missing.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(outside.status_code, status.HTTP_404_NOT_FOUND)

    def test_query_count_is_bounded_with_many_orders(self):
        MarketOrder.objects.bulk_create(
            [
                MarketOrder(
                    user=self.user,
                    market=self.market,
                    outcome=self.outcome,
                    side="BUY",
                    quantity=Decimal("1.0000"),
                    limit_price=Decimal(f"0.{50000 + i:05d}"),
                    status="OPEN",
                )
                for i in range(30)
            ]
        )
        with self.assertNumQueries(4):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

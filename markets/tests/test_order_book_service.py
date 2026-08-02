from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.test import TestCase
from django.utils import timezone

from authentication.tests.factories import UserFactory
from markets.models import (
    Market,
    MarketCategory,
    MarketFill,
    MarketOrder,
    MarketOutcome,
    MarketScope,
)
from markets.services.order_book_service import MarketOrderBookService
from sports.models import Sport


class MarketOrderBookServiceTests(TestCase):
    def setUp(self):
        sport = Sport.objects.create(name="Football", code="FOOTBALL")
        category = MarketCategory.objects.create(name="Match Result")
        self.market = Market.objects.create(
            sport=sport,
            category=category,
            scope_type=MarketScope.CUSTOM,
            custom_subject="Final",
            question="Who wins?",
            status=Market.Status.OPEN,
            closes_at=timezone.now() + timedelta(days=1),
        )
        self.outcome = MarketOutcome.objects.create(
            market=self.market, side=MarketOutcome.Side.YES, position=1, label="Yes"
        )
        self.other_outcome = MarketOutcome.objects.create(
            market=self.market, side=MarketOutcome.Side.NO, position=2, label="No"
        )
        self.user = UserFactory()

    def order(
        self,
        side,
        quantity,
        price,
        *,
        filled="0.0000",
        status=MarketOrder.Status.OPEN,
        market=None,
        outcome=None,
    ):
        return MarketOrder.objects.create(
            user=self.user,
            market=market or self.market,
            outcome=outcome or self.outcome,
            side=side,
            quantity=Decimal(quantity),
            limit_price=Decimal(price),
            filled_quantity=Decimal(filled),
            status=status,
        )

    def test_aggregates_remaining_quantity_orders_levels_and_metrics(self):
        self.order("BUY", "4.0000", "0.62000", filled="1.0000", status="PARTIALLY_FILLED")
        self.order("BUY", "2.0000", "0.62000")
        self.order("BUY", "3.0000", "0.60000")
        self.order("BUY", "1.0000", "0.64000")
        self.order("SELL", "2.5000", "0.65000")
        self.order("SELL", "1.0000", "0.67000")
        self.order("SELL", "2.0000", "0.67000")

        book = MarketOrderBookService.get_order_book(
            market_id=self.market.id, outcome_id=self.outcome.id
        )

        self.assertEqual(
            book["bids"],
            [
                {"price": Decimal("0.64000"), "quantity": Decimal("1.0000"), "order_count": 1},
                {"price": Decimal("0.62000"), "quantity": Decimal("5.0000"), "order_count": 2},
                {"price": Decimal("0.60000"), "quantity": Decimal("3.0000"), "order_count": 1},
            ],
        )
        self.assertEqual(
            book["asks"],
            [
                {"price": Decimal("0.65000"), "quantity": Decimal("2.5000"), "order_count": 1},
                {"price": Decimal("0.67000"), "quantity": Decimal("3.0000"), "order_count": 2},
            ],
        )
        self.assertEqual(book["best_bid"], Decimal("0.64000"))
        self.assertEqual(book["best_ask"], Decimal("0.65000"))
        self.assertEqual(book["spread"], Decimal("0.01000"))
        self.assertEqual(book["total_bid_quantity"], Decimal("9.0000"))
        self.assertEqual(book["total_ask_quantity"], Decimal("5.5000"))

    def test_excludes_ineligible_and_unrelated_orders(self):
        self.order("BUY", "1.0000", "0.50000")
        for excluded_status in ("FILLED", "CANCELLED", "REJECTED"):
            self.order(
                "BUY",
                "9.0000",
                "0.90000",
                status=excluded_status,
                filled="9.0000" if excluded_status == "FILLED" else "0.0000",
            )
        self.order("BUY", "2.0000", "0.80000", filled="2.0000")
        self.order("BUY", "4.0000", "0.70000", outcome=self.other_outcome)
        other_market = Market.objects.create(
            sport=self.market.sport,
            category=self.market.category,
            scope_type=MarketScope.CUSTOM,
            custom_subject="Other",
            question="Other?",
            status=Market.Status.OPEN,
        )
        other = MarketOutcome.objects.create(
            market=other_market, side="YES", position=1, label="Yes"
        )
        self.order("BUY", "5.0000", "0.75000", market=other_market, outcome=other)

        book = MarketOrderBookService.get_order_book(
            market_id=self.market.id, outcome_id=self.outcome.id
        )
        self.assertEqual(len(book["bids"]), 1)
        self.assertEqual(book["total_bid_quantity"], Decimal("1.0000"))

    def test_empty_book_and_limits(self):
        for price in ("0.50000", "0.51000", "0.52000"):
            self.order("BUY", "1.0000", price)
            self.order("SELL", "1.0000", str(Decimal(price) + Decimal("0.20000")))
        book = MarketOrderBookService.get_order_book(
            market_id=self.market.id, outcome_id=self.outcome.id, level_limit=2, trade_limit=0
        )
        self.assertEqual(
            [x["price"] for x in book["bids"]], [Decimal("0.52000"), Decimal("0.51000")]
        )
        self.assertEqual(
            [x["price"] for x in book["asks"]], [Decimal("0.70000"), Decimal("0.71000")]
        )
        self.assertEqual(book["recent_trades"], [])

    def test_recent_trades_are_newest_first_and_limited(self):
        buy = self.order("BUY", "3.0000", "0.70000", status="FILLED", filled="3.0000")
        sell = self.order("SELL", "3.0000", "0.40000", status="FILLED", filled="3.0000")
        old = MarketFill.objects.create(
            execution_reference=uuid4(),
            market=self.market,
            outcome=self.outcome,
            buy_order=buy,
            sell_order=sell,
            maker_order=sell,
            taker_order=buy,
            quantity=Decimal("1.0000"),
            price=Decimal("0.60000"),
        )
        new = MarketFill.objects.create(
            execution_reference=uuid4(),
            market=self.market,
            outcome=self.outcome,
            buy_order=buy,
            sell_order=sell,
            maker_order=sell,
            taker_order=buy,
            quantity=Decimal("2.0000"),
            price=Decimal("0.61000"),
        )
        MarketFill.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(hours=1))
        book = MarketOrderBookService.get_order_book(
            market_id=self.market.id, outcome_id=self.outcome.id, trade_limit=1
        )
        self.assertEqual([trade["id"] for trade in book["recent_trades"]], [new.id])

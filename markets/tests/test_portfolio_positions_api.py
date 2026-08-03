from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from markets.models import MarketFill, MarketOrder, MarketPosition
from markets.portfolio_position_serializers import MarketPortfolioPositionSerializer
from markets.tests.test_order_history_api import MarketOrderHistoryFixtureMixin
from wallets.models import LedgerEntry, Wallet


class MarketPortfolioPositionFixtureMixin:
    def portfolio_positions_url(self):
        return reverse("markets:market-portfolio-position-list")

    def position(self, **overrides):
        values = {
            "user": self.owner,
            "market": self.market,
            "outcome": self.outcome,
            "quantity": Decimal("4.0000"),
            "reserved_quantity": Decimal("1.0000"),
            "average_entry_price": Decimal("0.40000"),
            "total_cost": Decimal("1.6000"),
            "realized_pnl": Decimal("0.2500"),
        }
        values.update(overrides)
        return MarketPosition.objects.create(**values)

    def order(self, **overrides):
        values = {
            "user": self.other_participant,
            "market": self.market,
            "outcome": self.outcome,
            "side": MarketOrder.Side.BUY,
            "quantity": Decimal("3.0000"),
            "filled_quantity": Decimal("0.0000"),
            "limit_price": Decimal("0.60000"),
            "average_fill_price": None,
            "status": MarketOrder.Status.OPEN,
        }
        values.update(overrides)
        return MarketOrder.objects.create(**values)

    def get_positions(self, user=None, **params):
        self.authenticate(user or self.owner)
        response = self.client.get(self.portfolio_positions_url(), params)
        return response


class MarketPortfolioPositionAPITests(
    MarketPortfolioPositionFixtureMixin,
    MarketOrderHistoryFixtureMixin,
    APITestCase,
):
    def test_authentication_empty_pagination_and_positive_current_scope(self):
        self.assertEqual(self.client.get(self.portfolio_positions_url()).status_code, 401)
        empty = self.get_positions(self.empty_user)
        self.assertEqual(empty.status_code, status.HTTP_200_OK, empty.data)
        self.assertEqual(
            empty.data,
            {"count": 0, "next": None, "previous": None, "results": []},
        )

        included = self.position()
        self.position(
            outcome=self.market.outcomes.exclude(id=self.outcome.id).get(),
            quantity=Decimal("0.0000"),
            reserved_quantity=Decimal("0.0000"),
            average_entry_price=Decimal("0.00000"),
            total_cost=Decimal("0.0000"),
        )
        other = self.position(user=self.other_participant)
        response = self.get_positions()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], str(included.id))
        self.assertNotIn(str(other.id), str(response.data))

    def test_response_contract_formatting_calculations_and_privacy(self):
        position = self.position(realized_pnl=Decimal("-0.1250"))
        self.order(limit_price=Decimal("0.65000"))
        response = self.get_positions()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        item = response.data["results"][0]
        self.assertEqual(
            set(item),
            {
                "id",
                "market_id",
                "outcome_id",
                "market_question",
                "outcome_label",
                "market_status",
                "quantity",
                "reserved_quantity",
                "available_quantity",
                "average_entry_price",
                "total_cost_basis",
                "realized_pnl",
                "mark_price",
                "mark_source",
                "market_value",
                "unrealized_pnl",
                "total_position_pnl",
                "valuation_complete",
                "open_sell_order_count",
                "reserved_sell_order_quantity",
                "created_at",
                "updated_at",
            },
        )
        self.assertEqual(item["market_id"], str(self.market.id))
        self.assertEqual(item["outcome_id"], str(self.outcome.id))
        self.assertEqual(item["market_question"], self.market.question)
        self.assertEqual(item["outcome_label"], self.outcome.label)
        self.assertEqual(item["market_status"], self.market.status)
        self.assertEqual(item["quantity"], "4.0000")
        self.assertEqual(item["reserved_quantity"], "1.0000")
        self.assertEqual(item["available_quantity"], "3.0000")
        self.assertEqual(item["average_entry_price"], "0.40000")
        self.assertEqual(item["total_cost_basis"], "1.6000")
        self.assertEqual(item["realized_pnl"], "-0.1250")
        self.assertEqual(item["mark_price"], "0.65000")
        self.assertEqual(item["market_value"], "2.6000")
        self.assertEqual(item["unrealized_pnl"], "1.0000")
        self.assertEqual(item["total_position_pnl"], "0.8750")
        self.assertTrue(item["valuation_complete"])
        payload = str(item).lower()
        for forbidden in ("email", "phone", "username", "display_name", "wallet", "ledger"):
            self.assertNotIn(forbidden, payload)
        position.refresh_from_db()

    def test_resolution_winner_loser_and_void_cost_basis_marks(self):
        winner = self.position()
        loser = self.position(
            outcome=self.market.outcomes.exclude(id=self.outcome.id).get(),
            quantity=Decimal("2.0000"),
            reserved_quantity=Decimal("0.0000"),
            total_cost=Decimal("1.5000"),
        )
        self.market.status = self.market.Status.RESOLVED
        self.market.winning_outcome = self.outcome
        self.market.save(update_fields=["status", "winning_outcome", "updated_at"])
        resolved = self.get_positions().data["results"]
        by_id = {item["id"]: item for item in resolved}
        self.assertEqual(
            (by_id[str(winner.id)]["mark_price"], by_id[str(winner.id)]["mark_source"]),
            ("1.00000", "resolution"),
        )
        self.assertEqual(
            (by_id[str(loser.id)]["mark_price"], by_id[str(loser.id)]["mark_source"]),
            ("0.00000", "resolution"),
        )

        self.market.status = self.market.Status.VOIDED
        self.market.winning_outcome = None
        self.market.save(update_fields=["status", "winning_outcome", "updated_at"])
        voided = {item["id"]: item for item in self.get_positions().data["results"]}
        self.assertEqual(voided[str(winner.id)]["mark_price"], "0.40000")
        self.assertEqual(voided[str(winner.id)]["mark_source"], "void_cost_basis")
        self.assertEqual(voided[str(winner.id)]["market_value"], "1.6000")
        self.assertEqual(voided[str(winner.id)]["unrealized_pnl"], "0.0000")

    def test_best_bid_eligibility_self_exclusion_and_last_trade_tie_break(self):
        self.position()
        self.order(user=self.owner, limit_price=Decimal("0.99000"))
        self.order(status=MarketOrder.Status.CANCELLED, limit_price=Decimal("0.90000"))
        self.order(limit_price=Decimal("0.70000"))
        best_bid = self.get_positions().data["results"][0]
        self.assertEqual((best_bid["mark_price"], best_bid["mark_source"]), ("0.70000", "best_bid"))

        MarketOrder.objects.filter(user=self.other_participant).update(
            status=MarketOrder.Status.CANCELLED
        )
        buy = self.order(status=MarketOrder.Status.FILLED, filled_quantity=Decimal("3.0000"))
        sell = self.order(
            user=self.owner,
            side=MarketOrder.Side.SELL,
            status=MarketOrder.Status.FILLED,
            filled_quantity=Decimal("3.0000"),
        )
        timestamp = timezone.now() - timedelta(minutes=1)
        for fill_id, price in ((UUID(int=1), "0.45000"), (UUID(int=2), "0.55000")):
            fill = MarketFill.objects.create(
                id=fill_id,
                execution_reference=uuid4(),
                market=self.market,
                outcome=self.outcome,
                buy_order=buy,
                sell_order=sell,
                maker_order=buy,
                taker_order=sell,
                quantity=Decimal("1.0000"),
                price=Decimal(price),
            )
            MarketFill.objects.filter(id=fill.id).update(created_at=timestamp)
        trade = self.get_positions().data["results"][0]
        self.assertEqual((trade["mark_price"], trade["mark_source"]), ("0.55000", "last_trade"))

        self.market.closes_at = timezone.now() - timedelta(seconds=1)
        self.market.save(update_fields=["closes_at", "updated_at"])
        self.order(limit_price=Decimal("0.80000"))
        expired = self.get_positions().data["results"][0]
        self.assertEqual(expired["mark_source"], "last_trade")

    def test_unpriced_nulls_and_sell_reservation_reconciliation(self):
        self.position(reserved_quantity=Decimal("1.5000"))
        self.order(
            user=self.owner,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("2.0000"),
            filled_quantity=Decimal("0.5000"),
            status=MarketOrder.Status.PARTIALLY_FILLED,
        )
        self.order(
            user=self.owner,
            side=MarketOrder.Side.SELL,
            status=MarketOrder.Status.CANCELLED,
        )
        item = self.get_positions().data["results"][0]
        self.assertEqual(item["mark_source"], "unpriced")
        self.assertIsNone(item["mark_price"])
        self.assertIsNone(item["market_value"])
        self.assertIsNone(item["unrealized_pnl"])
        self.assertIsNone(item["total_position_pnl"])
        self.assertFalse(item["valuation_complete"])
        self.assertEqual(item["reserved_quantity"], "1.5000")
        self.assertEqual(item["open_sell_order_count"], 1)
        self.assertEqual(item["reserved_sell_order_quantity"], "1.5000")

    def test_filters_validation_and_scope(self):
        priced = self.position()
        self.order()
        self.position(user=self.other_participant)
        cases = (
            ({"market_id": self.market.id}, {str(priced.id)}),
            ({"outcome_id": self.outcome.id}, {str(priced.id)}),
            ({"market_status": self.market.status}, {str(priced.id)}),
            ({"mark_source": "best_bid"}, {str(priced.id)}),
            ({"valuation_complete": "true"}, {str(priced.id)}),
            ({"mark_source": "unpriced"}, set()),
            ({"valuation_complete": "false"}, set()),
        )
        for params, expected in cases:
            with self.subTest(params=params):
                response = self.get_positions(**params)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["count"], len(expected))
                self.assertEqual({row["id"] for row in response.data["results"]}, expected)
        for params in (
            {"market_id": "invalid"},
            {"outcome_id": "invalid"},
            {"market_status": "invalid"},
            {"mark_source": "invalid"},
            {"valuation_complete": "invalid"},
        ):
            with self.subTest(params=params):
                self.assertEqual(self.get_positions(**params).status_code, 400)

    def test_calculated_filters_are_applied_before_pagination(self):
        priced = []
        unpriced = []
        for index in range(5):
            market = self.open_market(self.create_market())
            outcome = market.outcomes.get(side=self.outcome.Side.YES)
            position = self.position(market=market, outcome=outcome)
            if index < 3:
                self.order(market=market, outcome=outcome)
                priced.append(str(position.id))
            else:
                unpriced.append(str(position.id))
        self.position(user=self.other_participant)

        for params, expected_ids in (
            ({"mark_source": "unpriced", "page_size": 1}, unpriced),
            ({"valuation_complete": "true", "page_size": 1}, priced),
        ):
            with self.subTest(params=params):
                first = self.get_positions(**params)
                self.assertEqual(first.data["count"], len(expected_ids))
                self.assertIsNotNone(first.data["next"])
                seen = []
                response = first
                while response is not None:
                    rows = response.data["results"]
                    self.assertEqual(len(rows), 1)
                    seen.extend(row["id"] for row in rows)
                    next_url = response.data["next"]
                    response = self.client.get(next_url) if next_url else None
                self.assertEqual(set(seen), set(expected_ids))

    def test_ordering_uses_close_question_outcome_and_position_id(self):
        early = self.open_market(self.create_market())
        later_a = self.open_market(self.create_market())
        later_b = self.open_market(self.create_market())
        no_close = self.open_market(self.create_market())
        early.question = "Zulu"
        early.closes_at = self.now + timedelta(minutes=10)
        later_a.question = "Alpha"
        later_a.closes_at = self.now + timedelta(minutes=20)
        later_b.question = "Beta"
        later_b.closes_at = later_a.closes_at
        no_close.question = "Aardvark"
        no_close.closes_at = None
        for market in (early, later_a, later_b, no_close):
            market.save(update_fields=["question", "closes_at", "updated_at"])

        early_outcomes = sorted(early.outcomes.all(), key=lambda outcome: outcome.label)
        expected = [
            self.position(market=early, outcome=early_outcomes[0]),
            self.position(market=early, outcome=early_outcomes[1]),
            self.position(
                id=UUID(int=2),
                market=later_a,
                outcome=later_a.outcomes.get(side=self.outcome.Side.YES),
            ),
            self.position(
                id=UUID(int=1),
                market=later_a,
                outcome=later_a.outcomes.get(side=self.outcome.Side.YES),
                user=self.other_participant,
            ),
            self.position(
                market=later_b,
                outcome=later_b.outcomes.get(side=self.outcome.Side.YES),
            ),
            self.position(
                market=no_close,
                outcome=no_close.outcomes.get(side=self.outcome.Side.YES),
            ),
        ]
        expected = [position for position in expected if position.user_id == self.owner.id]
        response = self.get_positions()
        self.assertEqual(
            [row["id"] for row in response.data["results"]],
            [str(position.id) for position in expected],
        )

    def test_query_count_and_read_only_behavior(self):
        first = self.position()
        wallet = Wallet.objects.get(user=self.owner, currency="UGX")
        before_wallet = (wallet.available_balance, wallet.reserved_balance, wallet.updated_at)
        before_position = (
            first.quantity,
            first.reserved_quantity,
            first.total_cost,
            first.realized_pnl,
            first.updated_at,
        )
        before_ledgers = LedgerEntry.objects.count()
        before_orders = MarketOrder.objects.count()
        self.authenticate(self.owner)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.portfolio_positions_url())
            list(response.data["results"])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertLessEqual(len(queries), 3)
        wallet.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(
            (wallet.available_balance, wallet.reserved_balance, wallet.updated_at), before_wallet
        )
        self.assertEqual(
            (
                first.quantity,
                first.reserved_quantity,
                first.total_cost,
                first.realized_pnl,
                first.updated_at,
            ),
            before_position,
        )
        self.assertEqual(LedgerEntry.objects.count(), before_ledgers)
        self.assertEqual(MarketOrder.objects.count(), before_orders)

    def test_invalid_available_quantity_fails_explicitly(self):
        position = SimpleNamespace(quantity=Decimal("1.0000"), reserved_quantity=Decimal("1.0001"))
        with self.assertRaisesMessage(
            ValidationError, "Position contains invalid historical reservation data."
        ):
            MarketPortfolioPositionSerializer().get_available_quantity(position)

    def test_empty_and_populated_multi_market_query_counts_are_bounded(self):
        self.authenticate(self.empty_user)
        with CaptureQueriesContext(connection) as empty_queries:
            empty = self.client.get(self.portfolio_positions_url())
            self.assertEqual(empty.data["count"], 0)
        self.assertLessEqual(len(empty_queries), 1)

        markets = [self.market]
        for index in range(2):
            market = self.open_market(self.create_market())
            market.question = f"Market question {index}"
            market.closes_at = self.now + timedelta(hours=index + 2)
            market.save(update_fields=["question", "closes_at", "updated_at"])
            markets.append(market)
        expected_ids = []
        for market in markets:
            for outcome in market.outcomes.all():
                position = self.position(
                    market=market,
                    outcome=outcome,
                    reserved_quantity=Decimal("0.5000"),
                )
                expected_ids.append(str(position.id))
                self.order(market=market, outcome=outcome)
                self.order(
                    user=self.owner,
                    market=market,
                    outcome=outcome,
                    side=MarketOrder.Side.SELL,
                    quantity=Decimal("1.5000"),
                    filled_quantity=Decimal("0.5000"),
                    status=MarketOrder.Status.PARTIALLY_FILLED,
                )

        self.authenticate(self.owner)
        with CaptureQueriesContext(connection) as populated_queries:
            response = self.client.get(self.portfolio_positions_url())
            self.assertEqual(response.data["count"], 6)
            self.assertEqual({item["id"] for item in response.data["results"]}, set(expected_ids))
        self.assertLessEqual(len(populated_queries), 1)

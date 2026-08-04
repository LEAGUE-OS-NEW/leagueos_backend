from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from markets.models import MarketOrder, MarketPosition
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.open_order_service import ParticipantOpenOrderService
from markets.services.participation_service import MarketParticipationService
from markets.services.resolution_service import MarketResolutionService
from markets.services.void_refund_service import MarketVoidRefundService
from markets.tests.test_order_history_api import MarketOrderHistoryFixtureMixin


class ParticipantOpenOrdersAPITests(
    MarketOrderHistoryFixtureMixin,
    APITestCase,
):
    def open_orders_url(self):
        return reverse("markets:participant-open-orders")

    def test_open_orders_requires_authentication(self):
        response = self.client.get(self.open_orders_url())

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_open_orders_returns_only_active_orders_owned_by_user(self):
        open_order = self.create_order(quantity=Decimal("10.0000"))
        partial_order = self.create_order(quantity=Decimal("3.0000"))
        MarketOrder.objects.filter(id=partial_order.id).update(
            filled_quantity=Decimal("1.0000"),
            average_fill_price=Decimal("0.45678"),
            status=MarketOrder.Status.PARTIALLY_FILLED,
        )
        other_order = self.create_order(user=self.other_participant)
        for terminal_status in (
            MarketOrder.Status.FILLED,
            MarketOrder.Status.CANCELLED,
            MarketOrder.Status.REJECTED,
        ):
            order = self.create_order()
            updates = {"status": terminal_status}
            if terminal_status == MarketOrder.Status.FILLED:
                updates.update(
                    filled_quantity=order.quantity,
                    average_fill_price=Decimal("0.55000"),
                )
            MarketOrder.objects.filter(id=order.id).update(**updates)
        self.authenticate(self.owner)

        response = self.client.get(self.open_orders_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["count"], 2)
        returned_ids = {item["id"] for item in response.data["results"]}
        self.assertEqual(returned_ids, {str(open_order.id), str(partial_order.id)})
        self.assertNotIn(str(other_order.id), returned_ids)

    def test_open_order_response_calculations_formatting_and_privacy(self):
        buy = self.create_order(
            quantity=Decimal("3.0000"),
            limit_price=Decimal("0.33333"),
        )
        MarketOrder.objects.filter(id=buy.id).update(
            filled_quantity=Decimal("1.0000"),
            average_fill_price=Decimal("0.30000"),
            status=MarketOrder.Status.PARTIALLY_FILLED,
        )
        MarketPosition.objects.create(
            user=self.owner,
            market=self.market,
            outcome=self.outcome,
            quantity=Decimal("5.0000"),
            reserved_quantity=Decimal("0.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("2.0000"),
        )
        sell = self.create_order(
            side=MarketOrder.Side.SELL,
            quantity=Decimal("2.5000"),
            limit_price=Decimal("0.60000"),
        )
        self.authenticate(self.owner)

        response = self.client.get(self.open_orders_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        items = {item["id"]: item for item in response.data["results"]}
        buy_data = items[str(buy.id)]
        sell_data = items[str(sell.id)]
        self.assertEqual(buy_data["remaining_quantity"], "2.0000")
        self.assertEqual(buy_data["fill_percentage"], "33.33")
        self.assertEqual(buy_data["reserved_wallet_amount"], "0.6667")
        self.assertEqual(buy_data["reserved_position_quantity"], "0.0000")
        self.assertEqual(buy_data["average_fill_price"], "0.30000")
        self.assertTrue(buy_data["is_cancellable"])
        self.assertEqual(sell_data["remaining_quantity"], "2.5000")
        self.assertEqual(sell_data["fill_percentage"], "0.00")
        self.assertEqual(sell_data["reserved_wallet_amount"], "0.0000")
        self.assertEqual(sell_data["reserved_position_quantity"], "2.5000")
        self.assertIsNone(sell_data["average_fill_price"])
        self.assertEqual(buy_data["market_question"], self.market.question)
        self.assertEqual(buy_data["outcome_label"], self.outcome.label)
        self.assertEqual(
            set(buy_data),
            {
                "id",
                "market_id",
                "outcome_id",
                "market_question",
                "outcome_label",
                "side",
                "status",
                "time_in_force",
                "expires_at",
                "expired_at",
                "quantity",
                "filled_quantity",
                "remaining_quantity",
                "fill_percentage",
                "limit_price",
                "average_fill_price",
                "reserved_wallet_amount",
                "reserved_position_quantity",
                "is_cancellable",
                "created_at",
                "updated_at",
            },
        )

    def test_open_orders_filters_validate_and_preserve_user_scope(self):
        buy = self.create_order()
        MarketPosition.objects.create(
            user=self.owner,
            market=self.market,
            outcome=self.outcome,
            quantity=Decimal("2.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("0.8000"),
        )
        sell = MarketOrder.objects.create(
            user=self.owner,
            market=self.market,
            outcome=self.outcome,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("2.0000"),
            limit_price=Decimal("0.90000"),
            status=MarketOrder.Status.OPEN,
        )
        self.create_order(user=self.other_participant)
        self.authenticate(self.owner)

        cases = (
            ({"market_id": self.market.id}, {str(buy.id), str(sell.id)}),
            ({"outcome_id": self.outcome.id}, {str(buy.id), str(sell.id)}),
            ({"side": "BUY"}, {str(buy.id)}),
            ({"side": "SELL"}, {str(sell.id)}),
            ({"status": "OPEN"}, {str(buy.id), str(sell.id)}),
        )
        for params, expected_ids in cases:
            with self.subTest(params=params):
                response = self.client.get(self.open_orders_url(), params)
                self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
                self.assertEqual({item["id"] for item in response.data["results"]}, expected_ids)

        for params in (
            {"status": "FILLED"},
            {"status": "invalid"},
            {"side": "invalid"},
            {"market_id": "invalid"},
            {"outcome_id": "invalid"},
        ):
            with self.subTest(params=params):
                response = self.client.get(self.open_orders_url(), params)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_open_orders_pagination_empty_result_and_deterministic_ordering(self):
        self.authenticate(self.empty_user)
        empty_response = self.client.get(self.open_orders_url())
        self.assertEqual(set(empty_response.data), {"count", "next", "previous", "results"})
        self.assertEqual(empty_response.data["count"], 0)
        self.assertEqual(empty_response.data["results"], [])

        first = self.create_order()
        second = self.create_order()
        same_time = first.created_at
        MarketOrder.objects.filter(id__in=(first.id, second.id)).update(created_at=same_time)
        self.authenticate(self.owner)
        response = self.client.get(self.open_orders_url(), {"page_size": 1})
        expected_first = max(str(first.id), str(second.id))
        self.assertEqual(response.data["count"], 2)
        self.assertIsNotNone(response.data["next"])
        self.assertEqual(response.data["results"][0]["id"], expected_first)

    def test_open_orders_read_has_no_financial_or_order_side_effects(self):
        order = self.create_order()
        wallet = self.owner.wallets.get(currency="UGX")
        before_wallet = (wallet.available_balance, wallet.reserved_balance)
        before_order = (order.status, order.updated_at)
        before_entries = wallet.ledger_entries.count()
        self.authenticate(self.owner)

        response = self.client.get(self.open_orders_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        wallet.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual((wallet.available_balance, wallet.reserved_balance), before_wallet)
        self.assertEqual((order.status, order.updated_at), before_order)
        self.assertEqual(wallet.ledger_entries.count(), before_entries)

    def test_open_order_service_scopes_filters_and_orders(self):
        first = self.create_order()
        partial = self.create_order()
        MarketOrder.objects.filter(id=partial.id).update(
            status=MarketOrder.Status.PARTIALLY_FILLED,
            filled_quantity=Decimal("1.0000"),
        )
        self.create_order(user=self.other_participant)

        orders = list(
            ParticipantOpenOrderService.list_open_orders(
                user=self.owner,
                filters={"status": MarketOrder.Status.PARTIALLY_FILLED},
            )
        )

        self.assertEqual([order.id for order in orders], [partial.id])
        self.assertNotEqual(first.id, partial.id)

    def test_open_orders_query_count_is_bounded(self):
        self.authenticate(self.empty_user)
        with CaptureQueriesContext(connection) as empty_queries:
            response = self.client.get(self.open_orders_url())
            self.assertEqual(response.data["count"], 0)
        self.assertLessEqual(len(empty_queries), 2)

        second_market = self.open_market(self.create_market())
        second_outcome = second_market.outcomes.get(side="YES")
        for index in range(8):
            market, outcome = (
                (self.market, self.outcome) if index % 2 == 0 else (second_market, second_outcome)
            )
            MarketOrder.objects.create(
                user=self.owner,
                market=market,
                outcome=outcome,
                side="BUY" if index % 2 == 0 else "SELL",
                quantity=Decimal("1.0000"),
                limit_price=Decimal("0.50000"),
                status=MarketOrder.Status.OPEN,
            )
        self.authenticate(self.owner)
        with CaptureQueriesContext(connection) as populated_queries:
            response = self.client.get(self.open_orders_url())
            self.assertEqual(response.data["count"], 8)
            list(response.data["results"])
        self.assertLessEqual(len(populated_queries), 2)

    def test_cancellation_close_and_void_refund_remove_active_orders(self):
        manual = self.create_order()
        MarketParticipationService.cancel_order(user=self.owner, order_id=manual.id)
        self.authenticate(self.owner)
        self.assertEqual(self.client.get(self.open_orders_url()).data["count"], 0)

        close_order = self.create_order()
        before_close = self.client.get(self.open_orders_url())
        self.assertEqual(before_close.data["results"][0]["id"], str(close_order.id))
        MarketLifecycleService.close(
            market_id=self.market.id,
            actor=self.approver_user,
            notes="Trading closed.",
        )
        self.assertEqual(self.client.get(self.open_orders_url()).data["count"], 0)

        void_market = self.open_market(self.create_market())
        void_outcome = void_market.outcomes.get(side="YES")
        MarketPosition.objects.create(
            user=self.owner,
            market=void_market,
            outcome=void_outcome,
            quantity=Decimal("1.0000"),
            reserved_quantity=Decimal("1.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("0.4000"),
        )
        MarketOrder.objects.create(
            user=self.owner,
            market=void_market,
            outcome=void_outcome,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("1.0000"),
            limit_price=Decimal("0.90000"),
            status=MarketOrder.Status.OPEN,
        )
        MarketResolutionService.void(
            market_id=void_market.id,
            actor=self.approver_user,
            notes="Fixture abandoned.",
            evidence="Official notice.",
        )
        MarketVoidRefundService.refund_void_market(
            market_id=void_market.id,
            actor=self.approver_user,
        )
        self.assertEqual(self.client.get(self.open_orders_url()).data["count"], 0)

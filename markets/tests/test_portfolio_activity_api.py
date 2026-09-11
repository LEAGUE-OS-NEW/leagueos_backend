from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from authentication.tests.factories import UserFactory
from markets.models import (
    MarketCloseCleanup,
    MarketCloseOrderCancellation,
    MarketFill,
    MarketOrder,
    MarketPosition,
    MarketPositionSettlement,
    MarketPositionVoidRefund,
    MarketSettlement,
    MarketVoidOrderCancellation,
    MarketVoidRefund,
)
from markets.services.fill_service import MarketFillService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.participation_service import MarketParticipationService
from markets.services.portfolio_activity_service import MarketPortfolioActivityService
from markets.services.resolution_service import MarketResolutionService
from markets.services.settlement_service import MarketSettlementService
from markets.services.void_refund_service import MarketVoidRefundService
from markets.tests.test_market_close_cleanup import MarketCloseCleanupFixtureMixin
from markets.tests.test_market_settlement import SettlementFixtureMixin
from markets.tests.test_order_history_api import MarketOrderHistoryFixtureMixin
from markets.tests.test_void_refund import VoidRefundFixtureMixin
from wallets.models import LedgerEntry, Wallet


class MarketPortfolioActivityRouteTests(TestCase):
    def test_activity_endpoint_requires_authentication(self):
        response = self.client.get(reverse("markets:market-portfolio-activity-list"))

        self.assertEqual(response.status_code, 401)


class MarketPortfolioActivityFixtureMixin(MarketOrderHistoryFixtureMixin):
    def activity_url(self):
        return reverse("markets:market-portfolio-activity-list")

    def raw_order(
        self, *, user=None, side="BUY", status="OPEN", quantity="3.0000", price="0.33333"
    ):
        return MarketOrder.objects.create(
            user=user or self.owner,
            market=self.market,
            outcome=self.outcome,
            side=side,
            quantity=Decimal(quantity),
            limit_price=Decimal(price),
            filled_quantity=Decimal("0.0000"),
            status=status,
        )

    def fill(self, *, buyer=None, seller=None, quantity="2.5000", price="0.43210"):
        buy = self.raw_order(user=buyer or self.owner, side="BUY", status="FILLED")
        sell = self.raw_order(user=seller or self.other_participant, side="SELL", status="FILLED")
        return MarketFill.objects.create(
            execution_reference=uuid4(),
            market=self.market,
            outcome=self.outcome,
            buy_order=buy,
            sell_order=sell,
            maker_order=buy,
            taker_order=sell,
            quantity=Decimal(quantity),
            price=Decimal(price),
        )

    def settlement(
        self,
        *,
        user=None,
        outcome=None,
        winner=True,
        payout="4.0000",
        net_payout=None,
        pnl="1.5000",
    ):
        parent, _ = MarketSettlement.objects.get_or_create(
            market=self.market,
            defaults={
                "winning_outcome": self.outcome,
                "payout_per_unit": Decimal("1.0000"),
                "settlement_currency": "UGX",
                "executed_by": self.approver_user,
            },
        )
        position = MarketPosition.objects.create(
            user=user or self.owner,
            market=self.market,
            outcome=outcome or self.outcome,
            quantity=Decimal("0.0000"),
            reserved_quantity=Decimal("0.0000"),
            average_entry_price=Decimal("0.00000"),
            total_cost=Decimal("0.0000"),
            realized_pnl=Decimal(pnl),
        )
        return MarketPositionSettlement.objects.create(
            market_settlement=parent,
            market_position=position,
            participant=user or self.owner,
            outcome=outcome or self.outcome,
            was_winner=winner,
            settled_quantity=Decimal("4.0000"),
            payout_per_unit=Decimal("1.0000"),
            payout_amount=Decimal(payout),
            net_payout_amount=Decimal(net_payout) if net_payout is not None else Decimal(payout),
            cost_basis=Decimal("2.5000"),
            realized_pnl_delta=Decimal(pnl),
        )

    def refund(self, *, user=None, outcome=None, position=None, net_refund=None):
        parent, _ = MarketVoidRefund.objects.get_or_create(
            market=self.market,
            defaults={"refund_currency": "UGX", "executed_by": self.approver_user},
        )
        position = position or MarketPosition.objects.create(
            user=user or self.owner,
            market=self.market,
            outcome=outcome or self.outcome,
            quantity=Decimal("0.0000"),
            reserved_quantity=Decimal("0.0000"),
            average_entry_price=Decimal("0.00000"),
            total_cost=Decimal("0.0000"),
            realized_pnl=Decimal("0.0000"),
        )
        return MarketPositionVoidRefund.objects.create(
            market_void_refund=parent,
            market_position=position,
            participant=position.user,
            outcome=position.outcome,
            refunded_quantity=Decimal("5.0000"),
            cost_basis=Decimal("2.7500"),
            refund_amount=Decimal("2.7500"),
            net_refund_amount=(
                Decimal(net_refund) if net_refund is not None else Decimal("2.7500")
            ),
            realized_pnl_delta=Decimal("0.0000"),
        )


class MarketPortfolioActivityAPITests(MarketPortfolioActivityFixtureMixin, APITestCase):
    def setUp(self):
        super().setUp()
        self.authenticate(self.owner)

    def results(self, **params):
        response = self.client.get(self.activity_url(), params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def mixed_activity(self):
        fill = self.fill()
        manual = self.raw_order(status="CANCELLED")
        close_order = self.raw_order(status="CANCELLED")
        close = MarketCloseCleanup.objects.create(
            market=self.market, executed_by=self.approver_user
        )
        close_row = MarketCloseOrderCancellation.objects.create(
            market_close_cleanup=close,
            market_order=close_order,
            order_side="BUY",
            remaining_quantity_cancelled=Decimal("1.2500"),
            released_wallet_reservation_amount=Decimal("0.4167"),
        )
        settlement = self.settlement()
        refund = self.refund(position=settlement.market_position)
        void_order = self.raw_order(side="SELL", status="CANCELLED")
        void_row = MarketVoidOrderCancellation.objects.create(
            market_void_refund=refund.market_void_refund,
            market_order=void_order,
            order_side="SELL",
            remaining_quantity_cancelled=Decimal("1.5000"),
            released_position_reservation_quantity=Decimal("1.5000"),
        )
        return fill, manual, close_row, void_row, settlement, refund

    def test_empty_activity_is_paginated(self):
        self.assertEqual(
            self.results(),
            {"count": 0, "next": None, "previous": None, "results": []},
        )

    def test_buy_and_sell_fills_have_participant_semantics_and_formatting(self):
        fill = self.fill()
        buy = self.results()["results"][0]
        self.assertEqual(buy["id"], f"market-fill:{fill.id}:buy")
        self.assertEqual(buy["event_type"], "BUY_FILL")
        self.assertEqual(buy["side"], "BUY")
        self.assertEqual(buy["order_id"], str(fill.buy_order_id))
        self.assertEqual(buy["fill_id"], str(fill.id))
        self.assertEqual(buy["quantity"], "2.5000")
        self.assertEqual(buy["price"], "0.43210")
        self.assertEqual(buy["notional_amount"], "1.0803")
        self.assertIsNone(buy["wallet_amount"])
        self.assertIsNone(buy["realized_pnl_delta"])

        self.authenticate(self.other_participant)
        sell = self.results()["results"][0]
        self.assertEqual(sell["id"], f"market-fill:{fill.id}:sell")
        self.assertEqual(sell["event_type"], "SELL_FILL")
        self.assertEqual(sell["side"], "SELL")
        self.assertEqual(sell["order_id"], str(fill.sell_order_id))

    def test_manual_buy_and_sell_cancellations_use_exact_release_semantics(self):
        buy = self.raw_order(status="CANCELLED", quantity="3.0000", price="0.33333")
        sell = self.raw_order(side="SELL", status="CANCELLED", quantity="2.0000")
        events = {event["order_id"]: event for event in self.results()["results"]}
        buy_event = events[str(buy.id)]
        self.assertEqual(buy_event["cancellation_reason"], "MANUAL")
        self.assertEqual(
            buy_event["released_wallet_amount"],
            format(MarketParticipationService.calculate_buy_cancellation_release(buy), ".4f"),
        )
        self.assertIsNone(buy_event["released_position_quantity"])
        sell_event = events[str(sell.id)]
        self.assertEqual(sell_event["released_position_quantity"], "2.0000")
        self.assertIsNone(sell_event["released_wallet_amount"])

    def test_close_and_void_cleanup_are_snapshotted_and_deduplicated(self):
        close_order = self.raw_order(status="CANCELLED")
        close = MarketCloseCleanup.objects.create(
            market=self.market, executed_by=self.approver_user
        )
        close_row = MarketCloseOrderCancellation.objects.create(
            market_close_cleanup=close,
            market_order=close_order,
            order_side="BUY",
            remaining_quantity_cancelled=Decimal("1.2500"),
            released_wallet_reservation_amount=Decimal("0.4167"),
        )
        events = self.results()["results"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["id"], f"market-close-cancellation:{close_row.id}:cancel")
        self.assertEqual(events[0]["cancellation_reason"], "MARKET_CLOSE")
        self.assertEqual(events[0]["quantity"], "1.2500")
        self.assertEqual(events[0]["released_wallet_amount"], "0.4167")

    def test_void_cleanup_reason_and_sell_release(self):
        order = self.raw_order(side="SELL", status="CANCELLED")
        parent = MarketVoidRefund.objects.create(
            market=self.market, refund_currency="UGX", executed_by=self.approver_user
        )
        row = MarketVoidOrderCancellation.objects.create(
            market_void_refund=parent,
            market_order=order,
            order_side="SELL",
            remaining_quantity_cancelled=Decimal("2.0000"),
            released_position_reservation_quantity=Decimal("2.0000"),
        )
        event = self.results()["results"][0]
        self.assertEqual(event["id"], f"market-void-cancellation:{row.id}:cancel")
        self.assertEqual(event["cancellation_reason"], "MARKET_VOID")
        self.assertEqual(event["released_position_quantity"], "2.0000")

    def test_winning_and_losing_settlements_use_immutable_values_once(self):
        win = self.settlement(winner=True, payout="4.0000", pnl="1.5000")
        loser_user = UserFactory()
        loss = self.settlement(user=loser_user, winner=False, payout="0.0000", pnl="-2.5000")
        event = self.results()["results"][0]
        self.assertEqual(event["id"], f"position-settlement:{win.id}:win")
        self.assertEqual(event["event_type"], "SETTLEMENT_WIN")
        self.assertEqual(event["wallet_amount"], "4.0000")
        self.assertEqual(event["realized_pnl_delta"], "1.5000")
        self.authenticate(loser_user)
        event = self.results()["results"][0]
        self.assertEqual(event["id"], f"position-settlement:{loss.id}:loss")
        self.assertEqual(event["wallet_amount"], "0.0000")
        self.assertEqual(event["realized_pnl_delta"], "-2.5000")

    def test_void_refund_is_not_profit_or_duplicated_ledger_activity(self):
        row = self.refund()
        data = self.results()
        self.assertEqual(data["count"], 1)
        event = data["results"][0]
        self.assertEqual(event["id"], f"position-void-refund:{row.id}:refund")
        self.assertEqual(event["wallet_amount"], "2.7500")
        self.assertEqual(event["realized_pnl_delta"], "0.0000")

    def test_settlement_and_refund_wallet_amount_is_net_not_gross(self):
        win = self.settlement(winner=True, payout="4.0000", net_payout="3.8000")
        event = self.results()["results"][0]
        self.assertEqual(event["id"], f"position-settlement:{win.id}:win")
        self.assertEqual(event["wallet_amount"], "3.8000")

        refund_user = UserFactory()
        row = self.refund(user=refund_user, net_refund="2.6000")
        self.authenticate(refund_user)
        event = self.results()["results"][0]
        self.assertEqual(event["id"], f"position-void-refund:{row.id}:refund")
        self.assertEqual(event["wallet_amount"], "2.6000")

    def test_every_event_type_filter_is_exact_and_participant_scoped(self):
        self.fill()
        self.fill(buyer=self.other_participant, seller=self.owner)
        self.raw_order(status="CANCELLED")
        self.raw_order(user=self.other_participant, status="CANCELLED")
        self.settlement(winner=True)
        other_outcome = self.market.outcomes.exclude(pk=self.outcome.pk).first()
        self.settlement(user=self.other_participant, winner=False)
        self.settlement(outcome=other_outcome, winner=False)
        owner_position = MarketPosition.objects.get(user=self.owner, outcome=other_outcome)
        self.refund(position=owner_position)
        self.refund(user=self.other_participant, outcome=other_outcome)
        expected_counts = {
            "BUY_FILL": 1,
            "SELL_FILL": 1,
            "ORDER_CANCELLED": 1,
            "SETTLEMENT_WIN": 1,
            "SETTLEMENT_LOSS": 1,
            "VOID_REFUND": 1,
        }
        for event_type, count in expected_counts.items():
            data = self.results(event_type=event_type)
            self.assertEqual(data["count"], count)
            self.assertTrue(all(event["event_type"] == event_type for event in data["results"]))

    def test_self_trade_historical_fill_has_two_stable_events(self):
        fill = self.fill(buyer=self.owner, seller=self.owner)
        expected = {f"market-fill:{fill.id}:buy", f"market-fill:{fill.id}:sell"}
        for _ in range(2):
            events = self.results()["results"]
            self.assertEqual({event["id"] for event in events}, expected)
            self.assertEqual(len(events), 2)
            by_side = {event["side"]: event for event in events}
            self.assertEqual(by_side["BUY"]["order_id"], str(fill.buy_order_id))
            self.assertEqual(by_side["SELL"]["order_id"], str(fill.sell_order_id))
            for event in events:
                self.assertEqual(event["fill_id"], str(fill.id))
                self.assertEqual(event["quantity"], "2.5000")
                self.assertEqual(event["price"], "0.43210")
                self.assertEqual(event["notional_amount"], "1.0803")

    def test_timestamp_filters_are_inclusive_for_every_source(self):
        fill, _, close, _, settlement, refund = self.mixed_activity()
        stamp = timezone.now() - timedelta(days=2)
        for model, pk in (
            (MarketFill, fill.pk),
            (MarketCloseOrderCancellation, close.pk),
            (MarketPositionSettlement, settlement.pk),
            (MarketPositionVoidRefund, refund.pk),
        ):
            model.objects.filter(pk=pk).update(created_at=stamp)
        data = self.results(occurred_from=stamp.isoformat(), occurred_to=stamp.isoformat())
        self.assertEqual(data["count"], 4)
        self.assertEqual(
            {event["event_type"] for event in data["results"]},
            {"BUY_FILL", "ORDER_CANCELLED", "SETTLEMENT_WIN", "VOID_REFUND"},
        )

    def test_scope_filters_validation_and_inclusive_dates(self):
        fill = self.fill()
        self.fill(buyer=self.other_participant)
        exact = fill.created_at.isoformat()
        for params in (
            {"market_id": self.market.id},
            {"outcome_id": self.outcome.id},
            {"event_type": "BUY_FILL"},
            {"occurred_from": exact},
            {"occurred_to": exact},
            {"occurred_from": exact, "occurred_to": exact},
        ):
            self.assertEqual(self.results(**params)["count"], 1)
        invalid = (
            {"market_id": "x"},
            {"outcome_id": "x"},
            {"event_type": "ORDER_PLACED"},
            {"occurred_from": "x"},
            {"occurred_from": timezone.now(), "occurred_to": timezone.now() - timedelta(days=1)},
        )
        for params in invalid:
            self.assertEqual(self.client.get(self.activity_url(), params).status_code, 400)

    def test_global_mixed_source_ordering_and_pagination(self):
        fill, manual, close, void, settlement, refund = self.mixed_activity()
        base = timezone.now() - timedelta(days=1)
        updates = (
            (MarketFill, fill.pk, base),
            (MarketOrder, manual.pk, base + timedelta(seconds=1)),
            (MarketCloseOrderCancellation, close.pk, base + timedelta(seconds=2)),
            (MarketVoidOrderCancellation, void.pk, base + timedelta(seconds=2)),
            (MarketPositionSettlement, settlement.pk, base + timedelta(seconds=3)),
            (MarketPositionVoidRefund, refund.pk, base + timedelta(seconds=4)),
        )
        for model, pk, stamp in updates:
            field = "updated_at" if model is MarketOrder else "created_at"
            model.objects.filter(pk=pk).update(**{field: stamp})

        complete = self.results(page_size=100)
        expected = [event["id"] for event in complete["results"]]
        self.assertEqual(complete["count"], 6)
        self.assertEqual(
            expected,
            [
                event["id"]
                for event in sorted(
                    complete["results"],
                    key=lambda event: (event["occurred_at"], event["id"]),
                    reverse=True,
                )
            ],
        )
        page = self.results(page_size=2)
        seen = []
        page_number = 1
        while True:
            seen.extend(event["id"] for event in page["results"])
            if page_number > 1:
                self.assertIsNotNone(page["previous"])
            if page["next"] is None:
                break
            response = self.client.get(page["next"])
            self.assertEqual(response.status_code, 200)
            page = response.data
            page_number += 1
        self.assertEqual(seen, expected)
        self.assertEqual(len(seen), len(set(seen)))

    def test_response_privacy_and_read_only_guarantees(self):
        self.mixed_activity()
        before = {
            "wallets": list(
                Wallet.objects.values_list("id", "available_balance", "reserved_balance")
            ),
            "ledger": LedgerEntry.objects.count(),
            "orders": list(MarketOrder.objects.values_list("id", "status", "updated_at")),
            "positions": list(MarketPosition.objects.values_list("id", "quantity", "updated_at")),
            "fills": list(MarketFill.objects.values_list("id", "quantity", "price")),
            "close": list(MarketCloseCleanup.objects.values_list("id", "executed_at")),
            "close_rows": list(
                MarketCloseOrderCancellation.objects.values_list(
                    "id", "remaining_quantity_cancelled"
                )
            ),
            "settlements": list(MarketSettlement.objects.values_list("id", "total_payout_amount")),
            "settlement_rows": list(
                MarketPositionSettlement.objects.values_list("id", "payout_amount")
            ),
            "voids": list(
                MarketVoidRefund.objects.values_list("id", "total_position_refund_amount")
            ),
            "void_rows": list(
                MarketVoidOrderCancellation.objects.values_list(
                    "id", "remaining_quantity_cancelled"
                )
            ),
            "refund_rows": list(
                MarketPositionVoidRefund.objects.values_list("id", "refund_amount")
            ),
        }
        serialized = str(self.results()["results"]).lower()
        for forbidden in (
            "email",
            "phone",
            "username",
            "display_name",
            "roles",
            "permissions",
            "ledger",
        ):
            self.assertNotIn(forbidden, serialized)
        after = {
            "wallets": list(
                Wallet.objects.values_list("id", "available_balance", "reserved_balance")
            ),
            "ledger": LedgerEntry.objects.count(),
            "orders": list(MarketOrder.objects.values_list("id", "status", "updated_at")),
            "positions": list(MarketPosition.objects.values_list("id", "quantity", "updated_at")),
            "fills": list(MarketFill.objects.values_list("id", "quantity", "price")),
            "close": list(MarketCloseCleanup.objects.values_list("id", "executed_at")),
            "close_rows": list(
                MarketCloseOrderCancellation.objects.values_list(
                    "id", "remaining_quantity_cancelled"
                )
            ),
            "settlements": list(MarketSettlement.objects.values_list("id", "total_payout_amount")),
            "settlement_rows": list(
                MarketPositionSettlement.objects.values_list("id", "payout_amount")
            ),
            "voids": list(
                MarketVoidRefund.objects.values_list("id", "total_position_refund_amount")
            ),
            "void_rows": list(
                MarketVoidOrderCancellation.objects.values_list(
                    "id", "remaining_quantity_cancelled"
                )
            ),
            "refund_rows": list(
                MarketPositionVoidRefund.objects.values_list("id", "refund_amount")
            ),
        }
        self.assertEqual(after, before)

    def test_source_query_count_is_constant(self):
        self.fill()
        self.raw_order(status="CANCELLED")
        self.settlement()
        with self.assertNumQueries(6):
            events = MarketPortfolioActivityService.list_activity(user=self.owner, filters={})
        self.assertEqual(len(events), 3)
        for _ in range(4):
            self.fill()
        with self.assertNumQueries(6):
            MarketPortfolioActivityService.list_activity(user=self.owner, filters={})


class MarketPortfolioActivityCloseWorkflowTests(MarketCloseCleanupFixtureMixin, APITestCase):
    def test_production_fill_manual_cancel_and_market_close_emit_activity(self):
        market = self.create_open_market()
        buy = self.reserve_buy(market, quantity="1.0000", price="0.60000")
        sell, _ = self.reserve_sell(market, quantity="1.0000")
        fill = MarketFillService.execute_fill(
            execution_reference=uuid4(),
            buy_order_id=buy.id,
            sell_order_id=sell.id,
            maker_order_id=buy.id,
            taker_order_id=sell.id,
            quantity=Decimal("1.0000"),
            price=Decimal("0.60000"),
        )
        manual = self.reserve_buy(market, quantity="1.0000")
        MarketParticipationService.cancel_order(user=self.buyer, order_id=manual.id)
        close_order = self.reserve_buy(market, quantity="1.0000")
        MarketLifecycleService.close(market_id=market.id, actor=self.actor, notes="Closed")

        events = MarketPortfolioActivityService.list_activity(user=self.buyer, filters={})
        ids = {event["id"] for event in events}
        self.assertIn(f"market-fill:{fill.id}:buy", ids)
        self.assertIn(f"market-order:{manual.id}:cancel", ids)
        cleanup = MarketCloseOrderCancellation.objects.get(market_order=close_order)
        self.assertIn(f"market-close-cancellation:{cleanup.id}:cancel", ids)
        self.assertNotIn(f"market-order:{close_order.id}:cancel", ids)


class MarketPortfolioActivitySettlementWorkflowTests(SettlementFixtureMixin, APITestCase):
    def test_production_resolution_and_settlement_emit_activity(self):
        market = self.resolve_market()
        position = self.create_position(market=market)
        MarketSettlementService.settle_market(market_id=market.id, actor=self.actor)
        events = MarketPortfolioActivityService.list_activity(user=position.user, filters={})
        self.assertEqual([event["event_type"] for event in events], ["SETTLEMENT_WIN"])


class MarketPortfolioActivityVoidWorkflowTests(VoidRefundFixtureMixin, APITestCase):
    def test_production_void_and_refund_emit_refund_and_cleanup_activity(self):
        market = self.open_market(self.create_market())
        position = self.position(market)
        with patch(
            "markets.services.participation_service.MarketMatchingService.match_order",
            return_value=[],
        ):
            order = MarketParticipationService.place_order(
                user=self.trader,
                market_id=market.id,
                outcome_id=position.outcome_id,
                side=MarketOrder.Side.SELL,
                quantity=Decimal("1.0000"),
                limit_price=Decimal("0.60000"),
            )
        MarketResolutionService.void(
            market_id=market.id,
            actor=self.actor,
            notes="Abandoned",
            evidence="Official notice",
        )
        MarketVoidRefundService.refund_void_market(market_id=market.id, actor=self.actor)
        events = MarketPortfolioActivityService.list_activity(user=self.trader, filters={})
        types = {event["event_type"] for event in events}
        self.assertEqual(types, {"ORDER_CANCELLED", "VOID_REFUND"})
        cleanup = MarketVoidOrderCancellation.objects.get(market_order=order)
        self.assertIn(f"market-void-cancellation:{cleanup.id}:cancel", {e["id"] for e in events})
        self.assertNotIn(f"market-order:{order.id}:cancel", {e["id"] for e in events})

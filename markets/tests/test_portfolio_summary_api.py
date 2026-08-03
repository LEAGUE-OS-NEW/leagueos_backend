from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from markets.models import (
    MarketFill,
    MarketOrder,
    MarketPosition,
    MarketPositionSettlement,
    MarketPositionVoidRefund,
)
from markets.services.fill_service import MarketFillService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.participation_service import MarketParticipationService
from markets.services.resolution_service import MarketResolutionService
from markets.services.settlement_service import MarketSettlementService
from markets.services.void_refund_service import MarketVoidRefundService
from markets.tests.test_order_history_api import MarketOrderHistoryFixtureMixin
from wallets.models import LedgerEntry, Wallet


class MarketPortfolioSummaryAPITests(MarketOrderHistoryFixtureMixin, APITestCase):
    def portfolio_url(self):
        return reverse("markets:market-portfolio-summary")

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
            "user": self.owner,
            "market": self.market,
            "outcome": self.outcome,
            "side": MarketOrder.Side.BUY,
            "quantity": Decimal("3.0000"),
            "filled_quantity": Decimal("1.0000"),
            "limit_price": Decimal("0.33333"),
            "average_fill_price": Decimal("0.30000"),
            "status": MarketOrder.Status.PARTIALLY_FILLED,
        }
        values.update(overrides)
        return MarketOrder.objects.create(**values)

    def summary(self, **params):
        self.authenticate(self.owner)
        response = self.client.get(self.portfolio_url(), params)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data

    def close_market(self, market):
        return MarketLifecycleService.close(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading closed.",
        )

    def test_authentication_empty_missing_wallet_and_schema_contract(self):
        self.assertEqual(self.client.get(self.portfolio_url()).status_code, 401)
        wallet_count = Wallet.objects.count()
        self.authenticate(self.empty_user)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.portfolio_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertLessEqual(len(queries), 8)
        self.assertEqual(Wallet.objects.count(), wallet_count)
        self.assertEqual(response.data["currency"], "UGX")
        self.assertEqual(response.data["scope"], {"market_id": None})
        self.assertEqual(
            response.data["wallet"],
            {
                "exists": False,
                "available_balance": "0.0000",
                "reserved_balance": "0.0000",
                "total_balance": "0.0000",
            },
        )
        self.assertEqual(response.data["positions"]["total_pnl"], "0.0000")
        self.assertTrue(response.data["positions"]["valuation_complete"])
        self.assertEqual(response.data["orders"]["open_order_count"], 0)
        self.assertIsNotNone(response.data["as_of"])

    def test_exposure_realized_pnl_unpriced_and_privacy(self):
        self.position()
        self.position(
            outcome=self.market.outcomes.exclude(id=self.outcome.id).get(),
            quantity=Decimal("0.0000"),
            reserved_quantity=Decimal("0.0000"),
            average_entry_price=Decimal("0.00000"),
            total_cost=Decimal("0.0000"),
            realized_pnl=Decimal("-0.5000"),
        )
        self.position(user=self.other_participant, realized_pnl=Decimal("99.0000"))
        self.authenticate(self.owner)
        response = self.client.get(self.portfolio_url())
        self.assertEqual(response.status_code, 200, response.data)
        positions = response.data["positions"]
        self.assertEqual(positions["open_position_count"], 1)
        self.assertEqual(positions["market_count"], 1)
        self.assertEqual(positions["total_quantity"], "4.0000")
        self.assertEqual(positions["reserved_quantity"], "1.0000")
        self.assertEqual(positions["available_quantity"], "3.0000")
        self.assertEqual(positions["total_cost_basis"], "1.6000")
        self.assertEqual(positions["realized_pnl"], "-0.2500")
        self.assertEqual(positions["unpriced_position_count"], 1)
        self.assertEqual(positions["unpriced_cost_basis"], "1.6000")
        self.assertFalse(positions["valuation_complete"])
        self.assertIsNone(positions["total_pnl"])
        payload = str(response.data).lower()
        for forbidden in ("email", "phone", "username", "display_name", "ledger", "permission"):
            self.assertNotIn(forbidden, payload)

    def test_external_best_bid_marks_position_and_self_bid_is_excluded(self):
        self.position(total_cost=Decimal("1.6000"))
        self.order(
            limit_price=Decimal("0.90000"),
            filled_quantity=Decimal("0.0000"),
            status=MarketOrder.Status.OPEN,
        )
        self.order(
            user=self.other_participant,
            quantity=Decimal("2.0000"),
            filled_quantity=Decimal("0.0000"),
            limit_price=Decimal("0.60000"),
            average_fill_price=None,
            status=MarketOrder.Status.OPEN,
        )
        self.authenticate(self.owner)
        positions = self.client.get(self.portfolio_url()).data["positions"]
        self.assertEqual(positions["marked_market_value"], "2.4000")
        self.assertEqual(positions["marked_unrealized_pnl"], "0.8000")
        self.assertEqual(positions["total_pnl"], "1.0500")
        self.assertEqual(positions["mark_sources"]["best_bid"], 1)

    def test_expired_and_inactive_bids_are_excluded(self):
        self.position()
        self.order(
            user=self.other_participant,
            filled_quantity=Decimal("0.0000"),
            average_fill_price=None,
            status=MarketOrder.Status.CANCELLED,
            limit_price=Decimal("0.80000"),
        )
        self.order(
            user=self.other_participant,
            filled_quantity=Decimal("0.0000"),
            average_fill_price=None,
            status=MarketOrder.Status.OPEN,
            limit_price=Decimal("0.70000"),
        )
        self.market.closes_at = timezone.now() - timedelta(seconds=1)
        self.market.save(update_fields=["closes_at", "updated_at"])
        self.authenticate(self.owner)
        positions = self.client.get(self.portfolio_url()).data["positions"]
        self.assertEqual(positions["unpriced_position_count"], 1)
        self.assertEqual(positions["mark_sources"]["best_bid"], 0)

    def test_latest_trade_uses_created_at_then_uuid_descending(self):
        self.position()
        buy = self.order(
            user=self.other_participant,
            filled_quantity=Decimal("1.0000"),
            status=MarketOrder.Status.FILLED,
        )
        sell = self.order(
            side=MarketOrder.Side.SELL,
            filled_quantity=Decimal("1.0000"),
            status=MarketOrder.Status.FILLED,
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
        self.authenticate(self.owner)
        positions = self.client.get(self.portfolio_url()).data["positions"]
        self.assertEqual(positions["marked_market_value"], "2.2000")
        self.assertEqual(positions["mark_sources"]["last_trade"], 1)

    def test_resolved_winner_and_void_cost_basis_priority(self):
        position = self.position()
        self.market.status = self.market.Status.RESOLVED
        self.market.winning_outcome = self.outcome
        self.market.save(update_fields=["status", "winning_outcome", "updated_at"])
        self.authenticate(self.owner)
        resolved = self.client.get(self.portfolio_url()).data["positions"]
        self.assertEqual(resolved["marked_market_value"], "4.0000")
        self.assertEqual(resolved["mark_sources"]["resolution"], 1)

        self.market.status = self.market.Status.VOIDED
        self.market.winning_outcome = None
        self.market.save(update_fields=["status", "winning_outcome", "updated_at"])
        voided = self.client.get(self.portfolio_url()).data["positions"]
        self.assertEqual(voided["marked_market_value"], f"{position.total_cost:.4f}")
        self.assertEqual(voided["marked_unrealized_pnl"], "0.0000")
        self.assertEqual(voided["mark_sources"]["void_cost_basis"], 1)

    def test_order_exposure_uses_active_remaining_quantities_and_exact_buy_rounding(self):
        self.order()
        self.order(
            side=MarketOrder.Side.SELL,
            quantity=Decimal("5.0000"),
            filled_quantity=Decimal("2.0000"),
            limit_price=Decimal("0.70000"),
        )
        self.order(status=MarketOrder.Status.CANCELLED)
        self.order(user=self.other_participant)
        self.authenticate(self.owner)
        orders = self.client.get(self.portfolio_url()).data["orders"]
        self.assertEqual(orders["open_order_count"], 2)
        self.assertEqual(orders["open_buy_order_count"], 1)
        self.assertEqual(orders["open_sell_order_count"], 1)
        self.assertEqual(orders["remaining_order_quantity"], "5.0000")
        self.assertEqual(orders["reserved_buy_amount"], "0.6667")
        self.assertEqual(orders["reserved_sell_quantity"], "3.0000")

    def test_market_filter_preserves_user_scope_and_full_wallet(self):
        self.position()
        self.order()
        wallet = Wallet.objects.get(user=self.owner, currency="UGX")
        expected_wallet = wallet.available_balance + wallet.reserved_balance
        self.authenticate(self.owner)
        included = self.client.get(self.portfolio_url(), {"market_id": self.market.id})
        excluded = self.client.get(self.portfolio_url(), {"market_id": uuid4()})
        invalid = self.client.get(self.portfolio_url(), {"market_id": "invalid"})
        self.assertEqual(included.data["positions"]["open_position_count"], 1)
        self.assertEqual(included.data["orders"]["open_order_count"], 1)
        self.assertEqual(excluded.data["positions"]["open_position_count"], 0)
        self.assertEqual(excluded.data["orders"]["open_order_count"], 0)
        self.assertEqual(included.data["wallet"]["total_balance"], f"{expected_wallet:.4f}")
        self.assertEqual(excluded.data["wallet"], included.data["wallet"])
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)

    def test_read_is_non_mutating_and_query_count_is_bounded(self):
        self.position()
        self.order()
        self.authenticate(self.owner)
        before = {
            "wallets": list(Wallet.objects.values()),
            "ledger": list(LedgerEntry.objects.values()),
            "positions": list(MarketPosition.objects.values()),
            "orders": list(MarketOrder.objects.values()),
        }
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.portfolio_url())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertLessEqual(len(queries), 8)
        self.assertEqual(before["wallets"], list(Wallet.objects.values()))
        self.assertEqual(before["ledger"], list(LedgerEntry.objects.values()))
        self.assertEqual(before["positions"], list(MarketPosition.objects.values()))
        self.assertEqual(before["orders"], list(MarketOrder.objects.values()))

    def test_openapi_contains_complete_portfolio_endpoint(self):
        response = self.client.get(reverse("api-schema"), {"format": "json"})
        self.assertEqual(response.status_code, 200)
        operation = response.json()["paths"]["/api/v1/markets/portfolio/summary/"]["get"]
        self.assertIn("market_id", {parameter["name"] for parameter in operation["parameters"]})
        self.assertIn("200", operation["responses"])

    def test_resolved_winner_and_loser_marks_before_settlement(self):
        loser = self.market.outcomes.exclude(id=self.outcome.id).get()
        self.position(quantity=Decimal("3.0000"), total_cost=Decimal("1.2000"))
        self.position(
            outcome=loser,
            quantity=Decimal("2.0000"),
            reserved_quantity=Decimal("0.0000"),
            total_cost=Decimal("1.4000"),
            realized_pnl=Decimal("0.0000"),
        )
        closed = self.close_market(self.market)
        MarketResolutionService.resolve(
            market_id=closed.id,
            actor=self.approver_user,
            winning_outcome_id=self.outcome.id,
            notes="Final result.",
            evidence="Official report.",
        )

        positions = self.summary()["positions"]

        self.assertEqual(positions["mark_sources"]["resolution"], 2)
        self.assertEqual(positions["marked_position_count"], 2)
        self.assertEqual(positions["marked_market_value"], "3.0000")
        self.assertEqual(positions["marked_unrealized_pnl"], "0.4000")
        self.assertEqual(positions["total_pnl"], "0.6500")

    def test_completed_normal_settlement_is_counted_exactly_once(self):
        loser = self.market.outcomes.exclude(id=self.outcome.id).get()
        winner_position = self.position(
            quantity=Decimal("3.0000"),
            reserved_quantity=Decimal("0.0000"),
            total_cost=Decimal("1.2000"),
            realized_pnl=Decimal("0.3000"),
        )
        loser_position = self.position(
            outcome=loser,
            quantity=Decimal("2.0000"),
            reserved_quantity=Decimal("0.0000"),
            total_cost=Decimal("1.4000"),
            realized_pnl=Decimal("-0.1000"),
        )
        closed = self.close_market(self.market)
        resolved = MarketResolutionService.resolve(
            market_id=closed.id,
            actor=self.approver_user,
            winning_outcome_id=self.outcome.id,
            notes="Final result.",
            evidence="Official report.",
        )
        wallet_before = Wallet.objects.get(user=self.owner, currency="UGX").available_balance
        settlement = MarketSettlementService.settle_market(
            market_id=resolved.id, actor=self.approver_user
        )
        winner_position.refresh_from_db()
        loser_position.refresh_from_db()
        records = MarketPositionSettlement.objects.filter(market_settlement=settlement)

        self.assertEqual(winner_position.quantity, Decimal("0.0000"))
        self.assertEqual(loser_position.quantity, Decimal("0.0000"))
        self.assertEqual(winner_position.realized_pnl, Decimal("2.1000"))
        self.assertEqual(loser_position.realized_pnl, Decimal("-1.5000"))
        self.assertEqual(
            sum((row.realized_pnl_delta for row in records), Decimal()), Decimal("0.4000")
        )
        self.assertEqual(settlement.total_payout_amount, Decimal("3.0000"))
        self.assertEqual(
            Wallet.objects.get(user=self.owner, currency="UGX").available_balance,
            wallet_before + Decimal("3.0000"),
        )
        positions = self.summary()["positions"]
        self.assertEqual(positions["open_position_count"], 0)
        self.assertEqual(positions["total_cost_basis"], "0.0000")
        self.assertEqual(positions["realized_pnl"], "0.6000")
        self.assertEqual(positions["total_pnl"], "0.6000")

    def test_completed_void_refund_is_not_profit(self):
        position = self.position(
            quantity=Decimal("5.0000"),
            reserved_quantity=Decimal("0.0000"),
            total_cost=Decimal("2.2500"),
            realized_pnl=Decimal("-0.3500"),
        )
        wallet_before = Wallet.objects.get(user=self.owner, currency="UGX").available_balance
        voided = MarketResolutionService.void(
            market_id=self.market.id,
            actor=self.approver_user,
            notes="Event abandoned.",
            evidence="Official notice.",
        )
        refund = MarketVoidRefundService.refund_void_market(
            market_id=voided.id, actor=self.approver_user
        )
        position.refresh_from_db()
        record = MarketPositionVoidRefund.objects.get(market_void_refund=refund)

        self.assertEqual(position.quantity, Decimal("0.0000"))
        self.assertEqual(position.realized_pnl, Decimal("-0.3500"))
        self.assertEqual(record.refund_amount, Decimal("2.2500"))
        self.assertEqual(record.realized_pnl_delta, Decimal("0.0000"))
        self.assertEqual(
            Wallet.objects.get(user=self.owner, currency="UGX").available_balance,
            wallet_before + Decimal("2.2500"),
        )
        positions = self.summary()["positions"]
        self.assertEqual(positions["open_position_count"], 0)
        self.assertEqual(positions["total_cost_basis"], "0.0000")
        self.assertEqual(positions["realized_pnl"], "-0.3500")
        self.assertEqual(positions["total_pnl"], "-0.3500")

    @patch(
        "markets.services.participation_service.MarketMatchingService.match_order", return_value=[]
    )
    def test_partial_sale_uses_remaining_cost_and_stored_realized_pnl(self, _match):
        self.position(
            user=self.other_participant,
            quantity=Decimal("10.0000"),
            reserved_quantity=Decimal("0.0000"),
            total_cost=Decimal("2.0000"),
            realized_pnl=Decimal("0.0000"),
        )
        buy = MarketParticipationService.place_order(
            user=self.owner,
            market_id=self.market.id,
            outcome_id=self.outcome.id,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("10.0000"),
            limit_price=Decimal("0.40000"),
        )
        sell = MarketParticipationService.place_order(
            user=self.other_participant,
            market_id=self.market.id,
            outcome_id=self.outcome.id,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("10.0000"),
            limit_price=Decimal("0.40000"),
        )
        MarketFillService.execute_fill(
            execution_reference=uuid4(),
            buy_order_id=buy.id,
            sell_order_id=sell.id,
            maker_order_id=sell.id,
            taker_order_id=buy.id,
            quantity=Decimal("10.0000"),
            price=Decimal("0.40000"),
        )
        owner_sell = MarketParticipationService.place_order(
            user=self.owner,
            market_id=self.market.id,
            outcome_id=self.outcome.id,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("4.0000"),
            limit_price=Decimal("0.70000"),
        )
        other_buy = MarketParticipationService.place_order(
            user=self.other_participant,
            market_id=self.market.id,
            outcome_id=self.outcome.id,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("4.0000"),
            limit_price=Decimal("0.70000"),
        )
        MarketFillService.execute_fill(
            execution_reference=uuid4(),
            buy_order_id=other_buy.id,
            sell_order_id=owner_sell.id,
            maker_order_id=owner_sell.id,
            taker_order_id=other_buy.id,
            quantity=Decimal("4.0000"),
            price=Decimal("0.70000"),
        )
        MarketParticipationService.place_order(
            user=self.owner,
            market_id=self.market.id,
            outcome_id=self.outcome.id,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("2.0000"),
            limit_price=Decimal("0.80000"),
        )
        MarketParticipationService.place_order(
            user=self.other_participant,
            market_id=self.market.id,
            outcome_id=self.outcome.id,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("1.0000"),
            limit_price=Decimal("0.60000"),
        )

        positions = self.summary()["positions"]
        self.assertEqual(positions["total_quantity"], "6.0000")
        self.assertEqual(positions["reserved_quantity"], "2.0000")
        self.assertEqual(positions["available_quantity"], "4.0000")
        self.assertEqual(positions["total_cost_basis"], "2.4000")
        self.assertEqual(positions["realized_pnl"], "1.2000")
        self.assertEqual(positions["marked_market_value"], "3.6000")
        self.assertEqual(positions["marked_unrealized_pnl"], "1.2000")
        self.assertEqual(positions["mark_sources"]["best_bid"], 1)

    def test_closed_portfolio_includes_positive_and_negative_realized_pnl(self):
        loser = self.market.outcomes.exclude(id=self.outcome.id).get()
        self.position(
            quantity=Decimal("0"),
            reserved_quantity=Decimal("0"),
            total_cost=Decimal("0"),
            realized_pnl=Decimal("2.1250"),
        )
        self.position(
            outcome=loser,
            quantity=Decimal("0"),
            reserved_quantity=Decimal("0"),
            total_cost=Decimal("0"),
            realized_pnl=Decimal("-0.8750"),
        )
        positions = self.summary()["positions"]
        self.assertEqual(positions["open_position_count"], 0)
        self.assertTrue(positions["valuation_complete"])
        self.assertEqual(positions["marked_unrealized_pnl"], "0.0000")
        self.assertEqual(positions["realized_pnl"], "1.2500")
        self.assertEqual(positions["total_pnl"], "1.2500")

    def test_terminal_orders_are_excluded_from_exposure(self):
        self.order(status=MarketOrder.Status.OPEN, filled_quantity=Decimal("0"))
        self.order(status=MarketOrder.Status.PARTIALLY_FILLED)
        for terminal in (
            MarketOrder.Status.FILLED,
            MarketOrder.Status.CANCELLED,
            MarketOrder.Status.REJECTED,
        ):
            self.order(
                status=terminal,
                filled_quantity=(
                    Decimal("3.0000") if terminal == MarketOrder.Status.FILLED else Decimal("0")
                ),
            )
        orders = self.summary()["orders"]
        self.assertEqual(orders["open_order_count"], 2)
        self.assertEqual(orders["remaining_order_quantity"], "5.0000")

    def test_market_filter_restricts_all_accounting_but_not_wallet(self):
        second = self.open_market(self.create_market())
        second_outcome = second.outcomes.get(side=self.outcome.Side.YES)
        self.position(
            quantity=Decimal("0"),
            reserved_quantity=Decimal("0"),
            total_cost=Decimal("0"),
            realized_pnl=Decimal("1.5000"),
        )
        self.position(
            market=second,
            outcome=second_outcome,
            quantity=Decimal("0"),
            reserved_quantity=Decimal("0"),
            total_cost=Decimal("0"),
            realized_pnl=Decimal("-0.4000"),
        )
        self.position(
            user=self.other_participant,
            quantity=Decimal("0"),
            reserved_quantity=Decimal("0"),
            total_cost=Decimal("0"),
            realized_pnl=Decimal("99.0000"),
        )
        self.position(
            outcome=self.market.outcomes.exclude(id=self.outcome.id).get(),
            quantity=Decimal("2"),
            reserved_quantity=Decimal("0"),
            total_cost=Decimal("1"),
            realized_pnl=Decimal("0"),
        )
        self.order()
        self.order(market=second, outcome=second_outcome)
        full = self.summary()
        filtered = self.summary(market_id=self.market.id)
        self.assertEqual(filtered["positions"]["realized_pnl"], "1.5000")
        self.assertEqual(filtered["positions"]["open_position_count"], 1)
        self.assertEqual(filtered["orders"]["open_order_count"], 1)
        self.assertEqual(filtered["wallet"], full["wallet"])

    def test_multi_market_portfolio_query_count_and_aggregates_are_bounded(self):
        second = self.open_market(self.create_market())
        third = self.open_market(self.create_market())
        markets = (self.market, second, third)
        for index, market in enumerate(markets, start=1):
            outcomes = list(market.outcomes.all())
            self.position(
                market=market,
                outcome=outcomes[0],
                quantity=Decimal(index),
                reserved_quantity=Decimal("0"),
                total_cost=Decimal(index) / 2,
                realized_pnl=Decimal("0.1000"),
            )
            self.position(
                market=market,
                outcome=outcomes[1],
                quantity=Decimal("1"),
                reserved_quantity=Decimal("0"),
                total_cost=Decimal("0.2500"),
                realized_pnl=Decimal("0"),
            )
            self.order(
                market=market,
                outcome=outcomes[0],
                filled_quantity=Decimal("0"),
                status=MarketOrder.Status.OPEN,
            )
            self.order(
                market=market,
                outcome=outcomes[1],
                side=MarketOrder.Side.SELL,
                quantity=Decimal("1"),
                filled_quantity=Decimal("0"),
                status=MarketOrder.Status.OPEN,
            )
            self.order(market=market, outcome=outcomes[0], status=MarketOrder.Status.CANCELLED)
            self.order(
                user=self.other_participant,
                market=market,
                outcome=outcomes[0],
                limit_price=Decimal("0.60000"),
                filled_quantity=Decimal("0"),
                status=MarketOrder.Status.OPEN,
            )
        self.position(
            user=self.other_participant,
            quantity=Decimal("50"),
            reserved_quantity=Decimal("0"),
            total_cost=Decimal("1"),
            realized_pnl=Decimal("90"),
        )
        self.authenticate(self.owner)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.portfolio_url())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertLessEqual(len(queries), 8)
        positions = response.data["positions"]
        self.assertEqual(positions["market_count"], 3)
        self.assertEqual(positions["open_position_count"], 6)
        self.assertEqual(positions["total_quantity"], "9.0000")
        self.assertEqual(positions["total_cost_basis"], "3.7500")
        self.assertEqual(positions["marked_position_count"], 3)
        self.assertEqual(positions["unpriced_position_count"], 3)
        self.assertEqual(positions["marked_market_value"], "3.6000")
        self.assertEqual(positions["realized_pnl"], "0.3000")
        self.assertEqual(response.data["orders"]["open_order_count"], 6)

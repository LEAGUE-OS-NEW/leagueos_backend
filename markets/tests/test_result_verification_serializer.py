from datetime import timedelta
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from markets.models import Market
from markets.result_verification_serializers import MarketResultVerificationSerializer


class RelatedRows(list):
    def all(self):
        return self


class ResultVerificationStateTests(SimpleTestCase):
    def setUp(self):
        self.serializer = MarketResultVerificationSerializer()

    def market(self, status=Market.Status.CLOSED, provisional=None, settles_by=None):
        market = SimpleNamespace(
            status=status,
            Status=Market.Status,
            winning_outcome_id="outcome-1" if status == Market.Status.RESOLVED else None,
            winning_outcome=SimpleNamespace(market_id="market-1"),
            id="market-1",
            settles_by=settles_by,
        )
        if provisional is not None:
            market.provisional_result = provisional
        return market

    def provisional(self, *, deadline, disputes=(), decisions=()):
        return SimpleNamespace(
            dispute_deadline=deadline,
            disputes=RelatedRows(disputes),
            decisions=RelatedRows(decisions),
        )

    def test_closed_without_provisional_is_awaiting_result(self):
        self.assertEqual(self.serializer.get_workflow_state(self.market()), "AWAITING_RESULT")

    def test_open_window_and_dispute_are_distinct(self):
        future = timezone.now() + timedelta(hours=1)
        self.assertEqual(
            self.serializer.get_workflow_state(
                self.market(provisional=self.provisional(deadline=future))
            ),
            "DISPUTE_WINDOW",
        )
        disputed = self.provisional(deadline=future, disputes=[SimpleNamespace()])
        self.assertEqual(
            self.serializer.get_workflow_state(self.market(provisional=disputed)), "DISPUTED"
        )

    def test_expired_window_is_ready_to_resolve(self):
        past = timezone.now() - timedelta(seconds=1)
        state = self.serializer.get_workflow_state(
            self.market(provisional=self.provisional(deadline=past))
        )
        self.assertEqual(state, "READY_TO_RESOLVE")

    def test_resolved_and_settled_are_distinct(self):
        market = self.market(status=Market.Status.RESOLVED)
        self.assertEqual(self.serializer.get_workflow_state(market), "READY_TO_SETTLE")
        self.assertTrue(self.serializer.get_can_settle(market))
        market.settlement = SimpleNamespace()
        self.assertEqual(self.serializer.get_workflow_state(market), "SETTLED")
        self.assertFalse(self.serializer.get_can_settle(market))

    def test_resolved_before_settlement_target_is_pending(self):
        target = timezone.now() + timedelta(hours=1)
        market = self.market(status=Market.Status.RESOLVED, settles_by=target)

        self.assertEqual(self.serializer.get_workflow_state(market), "SETTLEMENT_PENDING")
        self.assertFalse(self.serializer.get_can_settle(market))
        self.assertEqual(
            self.serializer.get_settlement_block_reason(market),
            f"Settlement becomes available at {target.isoformat()}.",
        )

    def test_resolved_at_settlement_target_is_ready(self):
        target = timezone.now()
        market = self.market(status=Market.Status.RESOLVED, settles_by=target)

        self.assertEqual(self.serializer.get_workflow_state(market), "READY_TO_SETTLE")
        self.assertTrue(self.serializer.get_can_settle(market))

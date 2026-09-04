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

    def market(self, status=Market.Status.CLOSED, provisional=None, closes_at=None):
        market = SimpleNamespace(status=status, Status=Market.Status, closes_at=closes_at)
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
        market.settlement = SimpleNamespace()
        self.assertEqual(self.serializer.get_workflow_state(market), "SETTLED")

    def test_overdue_open_market_is_ready_to_close(self):
        past = timezone.now() - timedelta(minutes=5)
        for status in (Market.Status.OPEN, Market.Status.SUSPENDED):
            market = self.market(status=status, closes_at=past)
            self.assertEqual(self.serializer.get_workflow_state(market), "READY_TO_CLOSE")
            self.assertTrue(self.serializer.get_can_close(market))

    def test_not_yet_due_open_market_falls_through_to_awaiting_result(self):
        # This state is never actually queried in production (the view's
        # queryset only includes OPEN/SUSPENDED markets past closes_at), but
        # the method itself should still degrade sanely rather than crash.
        future = timezone.now() + timedelta(hours=1)
        market = self.market(status=Market.Status.OPEN, closes_at=future)
        self.assertNotEqual(self.serializer.get_workflow_state(market), "READY_TO_CLOSE")
        self.assertFalse(self.serializer.get_can_close(market))

    def test_can_void_covers_every_pre_resolution_status_only(self):
        voidable = (
            Market.Status.APPROVED,
            Market.Status.OPEN,
            Market.Status.SUSPENDED,
            Market.Status.CLOSED,
        )
        for status in voidable:
            self.assertTrue(self.serializer.get_can_void(self.market(status=status)))
        for status in (Market.Status.RESOLVED, Market.Status.VOIDED, Market.Status.DRAFT):
            self.assertFalse(self.serializer.get_can_void(self.market(status=status)))

    def test_voided_and_refunded_are_distinct_and_only_voided_can_refund(self):
        market = self.market(status=Market.Status.VOIDED)
        self.assertEqual(self.serializer.get_workflow_state(market), "VOIDED")
        self.assertTrue(self.serializer.get_can_refund(market))
        self.assertIsNone(self.serializer.get_void_refund(market))

        market.void_refund = SimpleNamespace(
            id="11111111-1111-1111-1111-111111111111",
            executed_at=timezone.now(),
        )
        self.assertEqual(self.serializer.get_workflow_state(market), "REFUNDED")
        self.assertFalse(self.serializer.get_can_refund(market))
        self.assertEqual(self.serializer.get_void_refund(market)["status"], "REFUNDED")

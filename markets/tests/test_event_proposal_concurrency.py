from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from django.db import close_old_connections, connection
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from authentication.tests.factories import UserFactory
from markets.models import Market, MarketCategory, MarketEventGroup, MarketProposalReview
from markets.services.proposal_service import MarketProposalDuplicateConflict, MarketProposalService
from sports.models import Sport, SportingEvent


class ProposalApprovalCollisionTests(TransactionTestCase):
    """Deterministic collision simulation against the same locked context."""

    def test_two_exact_proposals_create_only_one_market_and_review(self):
        actor = UserFactory()
        proposer = UserFactory()
        sport = Sport.objects.create(name="Football", code="FOOTBALL")
        category = MarketCategory.objects.create(name="Result")
        event = SportingEvent.objects.create(
            sport=sport,
            name="KCCA v Vipers",
            starts_at=timezone.now() + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
        )
        values = {
            "proposer": proposer,
            "question": "Will KCCA win?",
            "category": category,
            "sporting_event": event,
            "proposed_closes_at": timezone.now() + timedelta(days=1),
        }
        first = MarketProposalService.submit(**values)
        second = MarketProposalService.submit(**values)
        MarketProposalService.review(proposal_id=first.id, actor=actor, action="APPROVE")
        with self.assertRaises(MarketProposalDuplicateConflict):
            MarketProposalService.review(proposal_id=second.id, actor=actor, action="APPROVE")
        self.assertEqual(Market.objects.count(), 1)
        self.assertEqual(MarketProposalReview.objects.filter(action="APPROVE").count(), 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_real_postgresql_simultaneous_exact_approvals_serialize(self):
        if connection.vendor != "postgresql":
            self.skipTest("Requires PostgreSQL row locking and separate connections.")
        actor = UserFactory()
        proposer = UserFactory()
        sport = Sport.objects.create(name="Rugby", code="RUGBY")
        category = MarketCategory.objects.create(name="Winner")
        event = SportingEvent.objects.create(
            sport=sport,
            name="Heathens v Pirates",
            starts_at=timezone.now() + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
        )
        values = {
            "proposer": proposer,
            "question": "Will Heathens win?",
            "category": category,
            "sporting_event": event,
            "proposed_closes_at": timezone.now() + timedelta(days=1),
        }
        proposals = [MarketProposalService.submit(**values) for _ in range(2)]
        barrier = Barrier(2)

        def approve(proposal_id):
            close_old_connections()
            barrier.wait()
            try:
                MarketProposalService.review(proposal_id=proposal_id, actor=actor, action="APPROVE")
                return "approved"
            except MarketProposalDuplicateConflict:
                return "conflict"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(approve, [proposal.id for proposal in proposals]))
        self.assertCountEqual(results, ["approved", "conflict"])
        self.assertEqual(Market.objects.count(), 1)
        self.assertEqual(MarketProposalReview.objects.filter(action="APPROVE").count(), 1)
        self.assertEqual(MarketEventGroup.objects.filter(sporting_event=event).count(), 1)

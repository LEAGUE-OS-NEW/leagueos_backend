from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Sum
from django.test import TestCase
from django.utils import timezone

from authentication.tests.factories import UserFactory
from markets.models import (
    Market,
    MarketCategory,
    MarketEventGroup,
    MarketFill,
    MarketOrder,
    MarketPosition,
    MarketProposal,
    MarketProposalReview,
    MarketScope,
    MarketSettlement,
    MarketVoidRefund,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.event_service import MarketEventService
from markets.services.proposal_service import (
    MarketProposalDuplicateConflict,
    MarketProposalService,
    build_duplicate_fingerprint,
    build_market_duplicate_fingerprint,
    normalize_market_question,
)
from sports.models import Sport, SportingEvent
from wallets.models import LedgerEntry, Wallet


class EventProposalServiceTests(TestCase):
    def setUp(self):
        self.actor = UserFactory()
        self.user = UserFactory()
        self.sport = Sport.objects.create(name="Football", code="FOOTBALL")
        self.category = MarketCategory.objects.create(name="Result")
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            name="KCCA v Vipers",
            starts_at=timezone.now() + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=timezone.now(),
        )
        self.closes_at = timezone.now() + timedelta(days=1)

    def submit(self, question="Will KCCA win?", **overrides):
        data = {
            "question": question,
            "category": self.category,
            "sporting_event": self.event,
            "proposed_closes_at": self.closes_at,
        }
        data.update(overrides)
        return MarketProposalService.submit(proposer=self.user, **data)

    def test_unsupported_scope_and_missing_context_are_rejected_before_save(self):
        with self.assertRaises(ValidationError):
            self.submit(scope_type=MarketScope.COMPETITION)
        with self.assertRaises(ValidationError):
            MarketProposalService.submit(
                proposer=self.user,
                question="Question?",
                category=self.category,
                proposed_closes_at=self.closes_at,
            )
        self.assertEqual(MarketProposal.objects.count(), 0)

    def test_equivalent_direct_and_group_event_contexts_have_same_fingerprint(self):
        group = MarketEventService.create(
            actor=self.actor,
            title="Match",
            slug="match",
            event_type=MarketEventGroup.EventType.SPORTING_EVENT,
            sporting_event=self.event,
        )
        direct = build_duplicate_fingerprint(
            question="Will KCCA win?",
            category_id=self.category.id,
            sporting_event_id=self.event.id,
        )
        grouped = build_duplicate_fingerprint(
            question=" will kcca win ",
            category_id=self.category.id,
            event_group=group,
        )
        self.assertEqual(direct, grouped)

    def test_edit_recalculates_duplicate_both_directions_and_clears_targets(self):
        first = self.submit()
        second = self.submit(question="Different question?")
        self.assertEqual(second.duplicate_status, MarketProposal.DuplicateStatus.CLEAR)
        second = MarketProposalService.update(
            proposal_id=second.id, proposer=self.user, question="Will KCCA win?"
        )
        self.assertEqual(second.duplicate_status, MarketProposal.DuplicateStatus.POSSIBLE_DUPLICATE)
        second = MarketProposalService.update(
            proposal_id=second.id, proposer=self.user, question="No longer the same?"
        )
        self.assertEqual(second.duplicate_status, MarketProposal.DuplicateStatus.CLEAR)
        self.assertIsNone(second.duplicate_of_market_id)
        self.assertIsNone(second.duplicate_of_proposal_id)
        self.assertNotEqual(first.duplicate_fingerprint, second.duplicate_fingerprint)

    def test_canonical_group_is_unique_and_approval_reuses_it(self):
        existing = MarketEventService.create(
            actor=self.actor,
            title="Match",
            slug="match",
            event_type=MarketEventGroup.EventType.SPORTING_EVENT,
            sporting_event=self.event,
        )
        with self.assertRaises((ValidationError, IntegrityError)):
            MarketEventService.create(
                actor=self.actor,
                title="Duplicate",
                slug="duplicate",
                event_type=MarketEventGroup.EventType.SPORTING_EVENT,
                sporting_event=self.event,
            )
        proposal = self.submit(question="Will there be a draw?")
        approved = MarketProposalService.review(
            proposal_id=proposal.id, actor=self.actor, action="APPROVE"
        )
        self.assertEqual(approved.approved_market.event_group_id, existing.id)
        self.assertEqual(MarketEventGroup.objects.filter(sporting_event=self.event).count(), 1)

    def test_group_edit_and_attachment_context_are_guarded(self):
        group = MarketEventService.create(
            actor=self.actor,
            title="Match",
            slug="match",
            event_type=MarketEventGroup.EventType.SPORTING_EVENT,
            sporting_event=self.event,
        )
        market = MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            event_group=group,
            question="Will KCCA win?",
            status=Market.Status.DRAFT,
        )
        with self.assertRaises(ValidationError):
            MarketEventService.update(
                event_id=group.id, event_type=MarketEventGroup.EventType.GENERAL_EVENT
            )
        MarketEventService.publish(event_id=group.id, actor=self.actor)
        with self.assertRaises(ValidationError):
            MarketEventService.update(event_id=group.id, sporting_event=None)
        original_status = market.status
        MarketEventService.detach_market(event_id=group.id, market_id=market.id)
        MarketEventService.detach_market(event_id=group.id, market_id=market.id)
        market.refresh_from_db()
        self.assertEqual(market.status, original_status)

    def test_duplicate_lookup_has_fixed_query_shape_for_multiple_rows(self):
        proposal = self.submit()
        for number in range(5):
            MarketCatalogService.create_market(
                sport=self.sport,
                category=self.category,
                scope_type=MarketScope.EVENT,
                sporting_event=self.event,
                question=f"Different {number}?",
                status=Market.Status.DRAFT,
            )
        with self.assertNumQueries(3):
            MarketProposalService.duplicate_candidates(proposal)

    def make_market(self, question="Will KCCA win?", **overrides):
        data = {
            "sport": self.sport,
            "category": self.category,
            "scope_type": MarketScope.EVENT,
            "sporting_event": self.event,
            "question": question,
            "status": Market.Status.DRAFT,
        }
        data.update(overrides)
        return MarketCatalogService.create_market(**data)

    def test_event_creation_validation_derivation_update_and_lifecycle(self):
        general = MarketEventService.create(
            actor=self.actor,
            title=" General ",
            slug="general",
            event_type=MarketEventGroup.EventType.GENERAL_EVENT,
        )
        self.assertEqual(general.title, "General")
        with self.assertRaises(ValidationError):
            MarketEventService.create(
                actor=self.actor,
                title="Bad sporting",
                event_type=MarketEventGroup.EventType.SPORTING_EVENT,
            )
        with self.assertRaises(ValidationError):
            MarketEventService.create(
                actor=self.actor,
                title="Bad general",
                event_type=MarketEventGroup.EventType.GENERAL_EVENT,
                sporting_event=self.event,
            )
        sporting = MarketEventService.create(
            actor=self.actor,
            title="Sporting",
            slug="sporting-lifecycle",
            event_type=MarketEventGroup.EventType.SPORTING_EVENT,
            sporting_event=self.event,
        )
        self.assertEqual(sporting.scheduled_at, self.event.starts_at)
        scheduled = self.closes_at
        updated = MarketEventService.update(
            event_id=general.id,
            title="Updated",
            description="Description",
            category=self.category,
            scheduled_at=scheduled,
        )
        self.assertEqual(
            (updated.title, updated.description, updated.category, updated.scheduled_at),
            ("Updated", "Description", self.category, scheduled),
        )
        MarketEventService.publish(event_id=general.id, actor=self.actor)
        with self.assertRaises(ValidationError):
            MarketEventService.publish(event_id=general.id, actor=self.actor)
        with self.assertRaises(ValidationError):
            MarketEventService.update(
                event_id=general.id,
                event_type=MarketEventGroup.EventType.LEAGUE_EVENT,
            )
        MarketEventService.archive(event_id=general.id, actor=self.actor)
        with self.assertRaises(ValidationError):
            MarketEventService.archive(event_id=general.id, actor=self.actor)

    def test_blank_title_publish_and_attachment_validation_matrix(self):
        group = MarketEventService.create(
            actor=self.actor,
            title="Temporary",
            slug="blank-later",
            event_type=MarketEventGroup.EventType.GENERAL_EVENT,
        )
        MarketEventGroup.objects.filter(pk=group.pk).update(title=" ")
        with self.assertRaises(ValidationError):
            MarketEventService.publish(event_id=group.id, actor=self.actor)

        sporting = MarketEventService.create(
            actor=self.actor,
            title="Sporting",
            slug="sporting-attach",
            event_type=MarketEventGroup.EventType.SPORTING_EVENT,
            sporting_event=self.event,
        )
        other_event = SportingEvent.objects.create(
            sport=self.sport,
            name="Other",
            starts_at=self.event.starts_at,
            status=SportingEvent.Status.SCHEDULED,
        )
        mismatch = self.make_market(sporting_event=other_event, question="Mismatch?")
        with self.assertRaises(ValidationError):
            MarketEventService.attach_market(event_id=sporting.id, market_id=mismatch.id)
        general = MarketEventService.create(
            actor=self.actor,
            title="General attach",
            slug="general-attach",
            event_type=MarketEventGroup.EventType.GENERAL_EVENT,
        )
        with self.assertRaises(ValidationError):
            MarketEventService.attach_market(event_id=general.id, market_id=mismatch.id)
        attached = self.make_market(question="Attached identity?")
        MarketEventService.attach_market(event_id=sporting.id, market_id=attached.id)
        with self.assertRaises(ValidationError):
            MarketEventService.update(event_id=sporting.id, sporting_event=other_event)
        occupied = self.make_market(question="Occupied?", event_group=sporting)
        with self.assertRaises(ValidationError):
            MarketEventService.attach_market(event_id=general.id, market_id=occupied.id)
        MarketEventService.publish(event_id=general.id, actor=self.actor)
        MarketEventService.archive(event_id=general.id, actor=self.actor)
        custom = self.make_market(
            question="Custom?",
            scope_type=MarketScope.CUSTOM,
            sporting_event=None,
            custom_subject="Topic",
        )
        with self.assertRaises(ValidationError):
            MarketEventService.attach_market(event_id=general.id, market_id=custom.id)

    def test_attach_detach_persists_context_fingerprint_without_state_change(self):
        group = MarketEventService.create(
            actor=self.actor,
            title="General fingerprint",
            slug="general-fingerprint",
            event_type=MarketEventGroup.EventType.GENERAL_EVENT,
        )
        market = self.make_market(
            question="General question?",
            scope_type=MarketScope.CUSTOM,
            sporting_event=None,
            custom_subject="Topic",
        )
        original = market.duplicate_fingerprint
        original_status = market.status
        MarketEventService.attach_market(event_id=group.id, market_id=market.id)
        market.refresh_from_db()
        self.assertNotEqual(market.duplicate_fingerprint, original)
        self.assertEqual(market.duplicate_fingerprint, build_market_duplicate_fingerprint(market))
        MarketEventService.detach_market(event_id=group.id, market_id=market.id)
        market.refresh_from_db()
        self.assertEqual(market.duplicate_fingerprint, original)
        self.assertEqual(market.status, original_status)

        sporting = MarketEventService.create(
            actor=self.actor,
            title="Canonical",
            slug="canonical-fingerprint",
            event_type=MarketEventGroup.EventType.SPORTING_EVENT,
            sporting_event=self.event,
        )
        sporting_market = self.make_market(question="Canonical question?")
        canonical = sporting_market.duplicate_fingerprint
        MarketEventService.attach_market(event_id=sporting.id, market_id=sporting_market.id)
        sporting_market.refresh_from_db()
        self.assertEqual(sporting_market.duplicate_fingerprint, canonical)
        self.assertEqual(
            MarketEventService.attach_market(event_id=sporting.id, market_id=sporting_market.id).id,
            sporting_market.id,
        )

    def test_proposal_validation_normalization_edit_and_withdraw_transitions(self):
        self.assertEqual(normalize_market_question(" KＣＣＡ... "), "kcca")
        with self.assertRaises(ValidationError):
            self.submit(question="...!!!")
        group = MarketEventService.create(
            actor=self.actor,
            title="Group only",
            slug="group-only",
            event_type=MarketEventGroup.EventType.SPORTING_EVENT,
            sporting_event=self.event,
        )
        group_only = self.submit(sporting_event=None, proposed_event_group=group)
        self.assertEqual(group_only.proposed_event_group, group)
        with self.assertRaises(ValidationError):
            self.submit(proposed_closes_at=None)
        other_event = SportingEvent.objects.create(
            sport=self.sport,
            name="Other proposal event",
            starts_at=self.event.starts_at,
            status=SportingEvent.Status.SCHEDULED,
        )
        with self.assertRaises(ValidationError):
            self.submit(sporting_event=other_event, proposed_event_group=group)
        proposal = self.submit(question="Editable?")
        MarketProposalService.review(
            proposal_id=proposal.id, actor=self.actor, action="START_REVIEW"
        )
        with self.assertRaises(ValidationError):
            MarketProposalService.update(proposal_id=proposal.id, proposer=self.user, question="No")
        withdrawable = self.submit(question="Withdraw me?")
        MarketProposalService.withdraw(proposal_id=withdrawable.id, proposer=self.user)
        with self.assertRaises(ValidationError):
            MarketProposalService.withdraw(proposal_id=withdrawable.id, proposer=self.user)

    def test_duplicate_candidates_status_context_and_legacy_matrix(self):
        proposal = self.submit(question="Duplicate 42?")
        active = self.submit(question=" duplicate 42 ")
        rejected = self.submit(question="Duplicate 42?")
        rejected.status = MarketProposal.Status.REJECTED
        rejected.save(update_fields=["status"])
        withdrawn = self.submit(question="Duplicate 42?")
        withdrawn.status = MarketProposal.Status.WITHDRAWN
        withdrawn.save(update_fields=["status"])
        indexed = self.make_market(question="Duplicate 42?")
        ignored = self.make_market(question="Duplicate 42?", status=Market.Status.REJECTED)
        legacy = self.make_market(question="Duplicate 42?")
        Market.objects.filter(pk=legacy.pk).update(duplicate_fingerprint=None)
        candidates = MarketProposalService.duplicate_candidates(proposal)
        proposal_ids = {pk for pk, _ in candidates["proposals"]}
        market_ids = {pk for pk, _ in candidates["markets"]}
        self.assertIn(active.id, proposal_ids)
        self.assertNotIn(rejected.id, proposal_ids)
        self.assertNotIn(withdrawn.id, proposal_ids)
        self.assertIn(indexed.id, market_ids)
        self.assertIn(legacy.id, market_ids)
        self.assertNotIn(ignored.id, market_ids)

    def test_review_action_and_duplicate_target_validation_matrix(self):
        proposal = self.submit(question="Review target?")
        started = MarketProposalService.review(
            proposal_id=proposal.id, actor=self.actor, action="START_REVIEW"
        )
        self.assertEqual(started.status, MarketProposal.Status.UNDER_REVIEW)
        self.assertEqual(
            MarketProposalService.review(
                proposal_id=proposal.id, actor=self.actor, action="START_REVIEW"
            ).status,
            MarketProposal.Status.UNDER_REVIEW,
        )
        with self.assertRaises(ValidationError):
            MarketProposalService.review(proposal_id=proposal.id, actor=self.actor, action="REJECT")
        rejected = MarketProposalService.review(
            proposal_id=proposal.id, actor=self.actor, action="REJECT", reason="Invalid"
        )
        self.assertEqual(rejected.status, MarketProposal.Status.REJECTED)

        source = self.submit(question="Same duplicate?")
        other = self.submit(question="Same duplicate?")
        with self.assertRaises(ValidationError):
            MarketProposalService.review(
                proposal_id=source.id,
                actor=self.actor,
                action="MARK_DUPLICATE",
                reason="Duplicate",
            )
        with self.assertRaises(ValidationError):
            MarketProposalService.review(
                proposal_id=source.id,
                actor=self.actor,
                action="MARK_DUPLICATE",
                reason="Duplicate",
                duplicate_of_proposal=source,
            )
        with self.assertRaises(ValidationError):
            MarketProposalService.review(
                proposal_id=source.id,
                actor=self.actor,
                action="MARK_DUPLICATE",
                reason="Duplicate",
                duplicate_of_market=self.make_market(question="Same duplicate?"),
                duplicate_of_proposal=other,
            )
        duplicate = MarketProposalService.review(
            proposal_id=source.id,
            actor=self.actor,
            action="MARK_DUPLICATE",
            reason="Duplicate",
            duplicate_of_proposal=other,
        )
        self.assertEqual(duplicate.status, MarketProposal.Status.DUPLICATE)
        with self.assertRaises(MarketProposalDuplicateConflict):
            MarketProposalService.review(
                proposal_id=duplicate.id, actor=self.actor, action="APPROVE"
            )

        unsupported = self.submit(question="Unsupported?")
        with self.assertRaises(ValidationError):
            MarketProposalService.review(
                proposal_id=unsupported.id, actor=self.actor, action="UNKNOWN"
            )

    def test_mark_duplicate_market_and_incompatible_targets(self):
        proposal = self.submit(question="Market duplicate?")
        market = self.make_market(question="Market duplicate?")
        result = MarketProposalService.review(
            proposal_id=proposal.id,
            actor=self.actor,
            action="MARK_DUPLICATE",
            reason="same",
            duplicate_of_market=market,
        )
        self.assertEqual(result.duplicate_of_market, market)
        incompatible = self.submit(question="Different source?")
        with self.assertRaises(ValidationError):
            MarketProposalService.review(
                proposal_id=incompatible.id,
                actor=self.actor,
                action="MARK_DUPLICATE",
                reason="same",
                duplicate_of_market=market,
            )
        ineligible = self.submit(question="Market duplicate?")
        ineligible.status = MarketProposal.Status.WITHDRAWN
        ineligible.save(update_fields=["status"])
        another = self.submit(question="Market duplicate?")
        with self.assertRaises(ValidationError):
            MarketProposalService.review(
                proposal_id=another.id,
                actor=self.actor,
                action="MARK_DUPLICATE",
                reason="same",
                duplicate_of_proposal=ineligible,
            )

    def financial_snapshot(self):
        return {
            "wallet": (
                Wallet.objects.count(),
                Wallet.objects.aggregate(
                    available=Sum("available_balance"), reserved=Sum("reserved_balance")
                ),
            ),
            "ledger": (
                LedgerEntry.objects.count(),
                LedgerEntry.objects.aggregate(total=Sum("amount")),
            ),
            "orders": (
                MarketOrder.objects.count(),
                MarketOrder.objects.aggregate(
                    quantity=Sum("quantity"), filled=Sum("filled_quantity")
                ),
            ),
            "positions": (
                MarketPosition.objects.count(),
                MarketPosition.objects.aggregate(quantity=Sum("quantity"), cost=Sum("total_cost")),
            ),
            "fills": (
                MarketFill.objects.count(),
                MarketFill.objects.aggregate(quantity=Sum("quantity")),
            ),
            "settlements": (MarketSettlement.objects.count(), {}),
            "refunds": (MarketVoidRefund.objects.count(), {}),
        }

    def assert_financially_inert(self, operation):
        before = self.financial_snapshot()
        result = operation()
        self.assertEqual(self.financial_snapshot(), before)
        return result

    def test_event_and_proposal_workflows_are_financially_inert(self):
        group = self.assert_financially_inert(
            lambda: MarketEventService.create(
                actor=self.actor,
                title="Financial matrix",
                slug="financial-matrix",
                event_type=MarketEventGroup.EventType.GENERAL_EVENT,
            )
        )
        self.assert_financially_inert(
            lambda: MarketEventService.update(event_id=group.id, description="Edited")
        )
        market = self.make_market(
            question="Financial custom?",
            scope_type=MarketScope.CUSTOM,
            sporting_event=None,
            custom_subject="Finance-free",
        )
        self.assert_financially_inert(
            lambda: MarketEventService.attach_market(event_id=group.id, market_id=market.id)
        )
        self.assert_financially_inert(
            lambda: MarketEventService.detach_market(event_id=group.id, market_id=market.id)
        )
        self.assert_financially_inert(
            lambda: MarketEventService.publish(event_id=group.id, actor=self.actor)
        )
        self.assert_financially_inert(
            lambda: MarketEventService.archive(event_id=group.id, actor=self.actor)
        )

        editable = self.assert_financially_inert(lambda: self.submit(question="Financial edit?"))
        self.assert_financially_inert(
            lambda: MarketProposalService.update(
                proposal_id=editable.id, proposer=self.user, question="Financial edited?"
            )
        )
        self.assert_financially_inert(
            lambda: MarketProposalService.withdraw(proposal_id=editable.id, proposer=self.user)
        )
        started = self.assert_financially_inert(lambda: self.submit(question="Start review?"))
        self.assert_financially_inert(
            lambda: MarketProposalService.review(
                proposal_id=started.id, actor=self.actor, action="START_REVIEW"
            )
        )
        self.assert_financially_inert(
            lambda: MarketProposalService.review(
                proposal_id=started.id,
                actor=self.actor,
                action="REJECT",
                reason="Rejected",
            )
        )
        duplicate = self.assert_financially_inert(lambda: self.submit(question="Duplicate inert?"))
        target = self.submit(question="Duplicate inert?")
        self.assert_financially_inert(
            lambda: MarketProposalService.review(
                proposal_id=duplicate.id,
                actor=self.actor,
                action="MARK_DUPLICATE",
                reason="Duplicate",
                duplicate_of_proposal=target,
            )
        )

    def test_approval_creates_only_catalog_records_and_review(self):
        proposal = self.submit(question="Approval financial matrix?")
        before_financial = self.financial_snapshot()
        before = {
            "markets": Market.objects.count(),
            "groups": MarketEventGroup.objects.count(),
            "reviews": MarketProposalReview.objects.count(),
        }
        approved = MarketProposalService.review(
            proposal_id=proposal.id, actor=self.actor, action="APPROVE"
        )
        self.assertEqual(self.financial_snapshot(), before_financial)
        self.assertEqual(Market.objects.count(), before["markets"] + 1)
        self.assertEqual(MarketEventGroup.objects.count(), before["groups"] + 1)
        self.assertEqual(MarketProposalReview.objects.count(), before["reviews"] + 1)
        self.assertEqual(approved.approved_market.status, Market.Status.DRAFT)
        self.assertEqual(approved.approved_market.outcomes.count(), 2)

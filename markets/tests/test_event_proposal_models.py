from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from authentication.tests.factories import UserFactory
from markets.models import (
    MarketCategory,
    MarketEventGroup,
    MarketProposal,
    MarketProposalReview,
)
from markets.services.proposal_service import normalize_market_question
from sports.models import Sport, SportingEvent


class EventProposalModelTests(TestCase):
    def setUp(self):
        self.user = UserFactory()
        self.category = MarketCategory.objects.create(name="Match result")
        self.sport = Sport.objects.create(name="Football", code="FOOTBALL")
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            name="KCCA v Vipers",
            starts_at=timezone.now() + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
        )

    def test_event_group_defaults_to_draft_and_sport_time_is_derived(self):
        group = MarketEventGroup.objects.create(
            title="KCCA v Vipers markets",
            slug="kcca-v-vipers",
            event_type=MarketEventGroup.EventType.SPORTING_EVENT,
            sporting_event=self.event,
            created_by=self.user,
        )
        self.assertEqual(group.status, MarketEventGroup.Status.DRAFT)
        self.assertEqual(group.scheduled_at, self.event.starts_at)

    def test_question_normalization_is_deterministic_and_preserves_numbers(self):
        self.assertEqual(
            normalize_market_question("  ¿WILL   KCCA win 2-0?!  "),
            normalize_market_question("will kcca WIN 2-0"),
        )
        self.assertNotEqual(
            normalize_market_question("Will KCCA win 2-0?"),
            normalize_market_question("Will KCCA win 3-0?"),
        )

    def test_proposal_defaults_and_question_are_normalized_without_rewriting(self):
        proposal = MarketProposal.objects.create(
            proposer=self.user,
            question="  Will KCCA win?  ",
            category=self.category,
            sporting_event=self.event,
            proposed_closes_at=timezone.now() + timedelta(days=1),
            proposed_resolution_source="Official result",
        )
        self.assertEqual(proposal.question, "Will KCCA win?")
        self.assertEqual(proposal.status, MarketProposal.Status.SUBMITTED)
        self.assertEqual(proposal.duplicate_status, MarketProposal.DuplicateStatus.CLEAR)
        self.assertTrue(proposal.duplicate_fingerprint)

    def test_review_is_immutable_at_instance_and_queryset_level(self):
        proposal = MarketProposal.objects.create(
            proposer=self.user,
            question="Will KCCA win?",
            category=self.category,
            sporting_event=self.event,
            proposed_closes_at=timezone.now() + timedelta(days=1),
        )
        review = MarketProposalReview.objects.create(
            proposal=proposal,
            actor=self.user,
            action=MarketProposalReview.Action.START_REVIEW,
            previous_status=MarketProposal.Status.SUBMITTED,
            new_status=MarketProposal.Status.UNDER_REVIEW,
        )
        review.reason = "changed"
        with self.assertRaises(ValidationError):
            review.save()
        with self.assertRaises(ValidationError):
            review.delete()
        with self.assertRaises(ValidationError):
            MarketProposalReview.objects.filter(pk=review.pk).update(reason="changed")
        with self.assertRaises(ValidationError):
            MarketProposalReview.objects.filter(pk=review.pk).delete()

    def test_event_proposal_migrations_are_schema_only(self):
        migration_dir = Path(__file__).resolve().parents[1] / "migrations"
        for name in (
            "0012_marketeventgroup_market_event_group_marketproposal_and_more.py",
            "0013_market_duplicate_fingerprint_and_more.py",
        ):
            text = (migration_dir / name).read_text(encoding="utf-8")
            self.assertNotIn("RunPython", text)
            self.assertNotIn("RunSQL", text)

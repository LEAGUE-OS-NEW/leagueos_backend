from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from authentication.tests.factories import (
    PermissionFactory,
    RoleFactory,
    RolePermissionFactory,
    UserFactory,
    UserRoleFactory,
)
from markets.models import (
    Market,
    MarketCategory,
    MarketOutcome,
    MarketPosition,
    MarketProvisionalEvidence,
    MarketResultDispute,
    MarketResultDisputeDecision,
    MarketScope,
    MarketSettlement,
    MarketVoidRefund,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.provisional_result_service import (
    MarketProvisionalResultService,
)
from markets.services.result_dispute_decision_service import (
    MarketResultDisputeDecisionService,
)
from markets.services.result_dispute_service import (
    MarketResultDisputeService,
)
from markets.services.settlement_service import MarketSettlementService
from markets.services.void_refund_service import (
    MarketVoidRefundService,
)
from sports.models import Competition, Sport, SportingEvent


class MarketResultDisputeDecisionTests(TestCase):
    def setUp(self):
        self.now = timezone.now()

        self.manage_permission = PermissionFactory(
            name="manage_market",
            resource="market",
            action="manage",
        )
        self.approve_permission = PermissionFactory(
            name="approve_market",
            resource="market",
            action="approve",
        )

        self.operations_role = RoleFactory(
            name="Decision Operations Admin",
            display_name="Decision Operations Admin",
        )
        self.approval_role = RoleFactory(
            name="Decision Independent Approver",
            display_name="Decision Independent Approver",
        )

        RolePermissionFactory(
            role=self.operations_role,
            permission=self.manage_permission,
        )
        RolePermissionFactory(
            role=self.approval_role,
            permission=self.approve_permission,
        )

        self.creator_user = UserFactory()
        self.publisher_user = UserFactory()
        self.decision_user = UserFactory()
        self.participant_user = UserFactory()
        self.outsider_user = UserFactory()

        UserRoleFactory(
            user=self.creator_user,
            role=self.operations_role,
        )

        # These additional assignments let the tests verify independence,
        # rather than failing only because permission is absent.
        UserRoleFactory(
            user=self.creator_user,
            role=self.approval_role,
        )
        UserRoleFactory(
            user=self.publisher_user,
            role=self.approval_role,
        )
        UserRoleFactory(
            user=self.decision_user,
            role=self.approval_role,
        )
        UserRoleFactory(
            user=self.participant_user,
            role=self.approval_role,
        )

        self.sport = Sport.objects.create(
            name="Dispute Decision Football",
            code="DISPUTE_DECISION_FOOTBALL",
        )
        self.category = MarketCategory.objects.create(
            name="Dispute Decision Result",
        )
        self.competition = Competition.objects.create(
            sport=self.sport,
            name="Dispute Decision League",
            country_code="UG",
            is_verified=True,
        )
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="Decision United v Final City",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

    def create_market(self, **overrides):
        values = {
            "sport": self.sport,
            "category": self.category,
            "scope_type": MarketScope.EVENT,
            "sporting_event": self.event,
            "question": "Will Decision United win?",
            "description": "Independent dispute decision contract.",
            "rules": "Resolve YES if Decision United wins.",
            "resolution_source": "Official competition result",
            "resolution_criteria": "Use the verified final score.",
            "status": Market.Status.DRAFT,
            "opens_at": self.now - timedelta(minutes=5),
            "closes_at": self.now + timedelta(days=1),
            "created_by": self.creator_user,
            "yes_label": "Decision United wins",
            "no_label": "Decision United does not win",
        }
        values.update(overrides)

        return MarketCatalogService.create_market(**values)

    def close_market(self, market):
        MarketLifecycleService.submit(
            market_id=market.id,
            actor=self.creator_user,
            notes="Ready for approval.",
        )
        MarketLifecycleService.approve(
            market_id=market.id,
            actor=self.publisher_user,
            notes="Approved.",
        )
        MarketLifecycleService.open(
            market_id=market.id,
            actor=self.publisher_user,
            notes="Trading opened.",
        )
        return MarketLifecycleService.close(
            market_id=market.id,
            actor=self.publisher_user,
            notes="Trading closed.",
        )

    def create_position(self, market, user=None):
        outcome = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        return MarketPosition.objects.create(
            user=user or self.participant_user,
            market=market,
            outcome=outcome,
            quantity=Decimal("5.0000"),
            reserved_quantity=Decimal("0.0000"),
            average_entry_price=Decimal("0.50000"),
            total_cost=Decimal("2.5000"),
            realized_pnl=Decimal("0.0000"),
        )

    def publish(
        self,
        market,
        *,
        published_at=None,
        dispute_window_hours=48,
    ):
        provisional_winner = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        values = {
            "market_id": market.id,
            "actor": self.publisher_user,
            "winning_outcome_id": provisional_winner.id,
            "notes": "Official result published provisionally.",
            "dispute_window_hours": dispute_window_hours,
            "evidence_items": [
                {
                    "evidence_type": (MarketProvisionalEvidence.EvidenceType.OFFICIAL_RESULT),
                    "label": "Official provisional score",
                    "reference": "PROVISIONAL-DECISION-0042",
                }
            ],
        }

        if published_at is None:
            return MarketProvisionalResultService.publish(**values)

        with patch(
            "markets.services.provisional_result_service.timezone.now",
            return_value=published_at,
        ):
            return MarketProvisionalResultService.publish(**values)

    def submit_dispute(
        self,
        market,
        *,
        submitted_at=None,
        actor=None,
    ):
        values = {
            "market_id": market.id,
            "actor": actor or self.participant_user,
            "category": (MarketResultDispute.Category.INCORRECT_OUTCOME),
            "explanation": (
                "The provisional winner conflicts with a corrected " "official competition report."
            ),
            "evidence_items": [
                {
                    "label": "Corrected competition report",
                    "reference": "CORRECTED-DECISION-0099",
                }
            ],
        }

        if submitted_at is None:
            return MarketResultDisputeService.submit(**values)

        with patch(
            "markets.services.result_dispute_service.timezone.now",
            return_value=submitted_at,
        ):
            return MarketResultDisputeService.submit(**values)

    def create_disputed_market(self, **market_overrides):
        market = self.close_market(self.create_market(**market_overrides))
        self.create_position(market)

        published_at = self.now - timedelta(hours=72)
        provisional = self.publish(
            market,
            published_at=published_at,
            dispute_window_hours=48,
        )
        dispute = self.submit_dispute(
            market,
            submitted_at=published_at + timedelta(hours=1),
        )

        return market, provisional, dispute

    def decide(
        self,
        market,
        *,
        decision_type=(MarketResultDisputeDecision.DecisionType.CONFIRM),
        actor=None,
        winning_outcome_id=None,
        review_extension_hours=None,
        notes="Independent review completed.",
        evidence="Reviewed provisional and dispute evidence.",
    ):
        return MarketResultDisputeDecisionService.decide(
            market_id=market.id,
            actor=actor or self.decision_user,
            decision_type=decision_type,
            winning_outcome_id=winning_outcome_id,
            review_extension_hours=review_extension_hours,
            notes=notes,
            evidence=evidence,
        )

    def test_confirm_decision_resolves_to_provisional_winner(self):
        market, provisional, dispute = self.create_disputed_market()
        transition_count = market.status_transitions.count()

        before = timezone.now()
        decision = self.decide(market)
        after = timezone.now()

        market.refresh_from_db()

        self.assertEqual(
            decision.provisional_result,
            provisional,
        )
        self.assertEqual(
            decision.decision_type,
            MarketResultDisputeDecision.DecisionType.CONFIRM,
        )
        self.assertEqual(
            decision.winning_outcome,
            provisional.winning_outcome,
        )
        self.assertEqual(
            decision.sequence,
            1,
        )
        self.assertEqual(
            decision.covered_dispute_count,
            1,
        )
        self.assertEqual(
            decision.decided_by,
            self.decision_user,
        )
        self.assertEqual(
            decision.decision_maker_email,
            self.decision_user.email,
        )
        self.assertGreaterEqual(
            decision.decided_at,
            before,
        )
        self.assertLessEqual(
            decision.decided_at,
            after,
        )

        self.assertEqual(
            market.status,
            Market.Status.RESOLVED,
        )
        self.assertEqual(
            market.winning_outcome,
            provisional.winning_outcome,
        )
        self.assertEqual(
            market.status_transitions.count(),
            transition_count + 1,
        )
        self.assertTrue(
            MarketResultDispute.objects.filter(
                pk=dispute.pk,
            ).exists()
        )

    def test_correct_decision_resolves_to_different_market_outcome(self):
        market, provisional, _dispute = self.create_disputed_market(
            question=("Will the corrected decision market resolve YES?")
        )
        corrected_winner = market.outcomes.get(
            side=MarketOutcome.Side.NO,
        )

        decision = self.decide(
            market,
            decision_type=(MarketResultDisputeDecision.DecisionType.CORRECT),
            winning_outcome_id=corrected_winner.id,
        )

        market.refresh_from_db()

        self.assertNotEqual(
            corrected_winner,
            provisional.winning_outcome,
        )
        self.assertEqual(
            decision.winning_outcome,
            corrected_winner,
        )
        self.assertEqual(
            market.status,
            Market.Status.RESOLVED,
        )
        self.assertEqual(
            market.winning_outcome,
            corrected_winner,
        )

    def test_void_decision_voids_market_without_winner(self):
        market, _provisional, _dispute = self.create_disputed_market(
            question="Should the disputed market be voided?",
        )

        decision = self.decide(
            market,
            decision_type=(MarketResultDisputeDecision.DecisionType.VOID),
        )

        market.refresh_from_db()

        self.assertEqual(
            decision.decision_type,
            MarketResultDisputeDecision.DecisionType.VOID,
        )
        self.assertIsNone(
            decision.winning_outcome,
        )
        self.assertEqual(
            market.status,
            Market.Status.VOIDED,
        )
        self.assertIsNone(
            market.winning_outcome,
        )

    def test_extension_preserves_market_and_blocks_early_final_decision(
        self,
    ):
        market, provisional, _dispute = self.create_disputed_market(
            question="Should review time be extended?",
        )
        transition_count = market.status_transitions.count()

        extension = self.decide(
            market,
            decision_type=(MarketResultDisputeDecision.DecisionType.EXTEND_REVIEW),
            review_extension_hours=24,
        )

        market.refresh_from_db()

        self.assertEqual(
            extension.sequence,
            1,
        )
        self.assertIsNotNone(
            extension.review_extended_until,
        )
        self.assertGreater(
            extension.review_extended_until,
            extension.decided_at,
        )
        self.assertEqual(
            market.status,
            Market.Status.CLOSED,
        )
        self.assertEqual(
            market.status_transitions.count(),
            transition_count,
        )

        with self.assertRaises(ValidationError) as error:
            self.decide(market)

        self.assertIn(
            "review_window",
            error.exception.message_dict,
        )

        with self.assertRaises(ValidationError):
            MarketResultDisputeService.require_no_open_disputes(market)

        final_time = extension.review_extended_until + timedelta(seconds=1)

        with patch(
            ("markets.services." "result_dispute_decision_service.timezone.now"),
            return_value=final_time,
        ):
            final_decision = self.decide(market)

        market.refresh_from_db()

        self.assertEqual(
            final_decision.sequence,
            2,
        )
        self.assertEqual(
            final_decision.provisional_result,
            provisional,
        )
        self.assertEqual(
            market.status,
            Market.Status.RESOLVED,
        )

    def test_decision_requires_permission_and_independent_actor(self):
        market, _provisional, _dispute = self.create_disputed_market()

        with self.assertRaises(PermissionDenied):
            self.decide(
                market,
                actor=self.outsider_user,
            )

        for conflicted_actor in [
            self.creator_user,
            self.publisher_user,
            self.participant_user,
        ]:
            with self.subTest(actor=conflicted_actor.id):
                with self.assertRaises(PermissionDenied):
                    self.decide(
                        market,
                        actor=conflicted_actor,
                    )

        self.assertFalse(
            MarketResultDisputeDecision.objects.filter(
                provisional_result__market=market,
            ).exists()
        )

    def test_decision_requires_dispute_and_closed_submission_window(
        self,
    ):
        market = self.close_market(
            self.create_market(
                question="Will a decision require a dispute?",
            )
        )
        self.create_position(market)

        historical_time = self.now - timedelta(hours=72)
        self.publish(
            market,
            published_at=historical_time,
        )

        with self.assertRaises(ValidationError) as error:
            self.decide(market)

        self.assertIn(
            "disputes",
            error.exception.message_dict,
        )

        open_market = self.close_market(
            self.create_market(question=("Can a decision occur during the dispute window?"))
        )
        self.create_position(open_market)
        self.publish(open_market)
        self.submit_dispute(open_market)

        with self.assertRaises(ValidationError) as error:
            self.decide(open_market)

        self.assertIn(
            "dispute_window",
            error.exception.message_dict,
        )

    def test_decision_validates_action_specific_payload(self):
        market, provisional, _dispute = self.create_disputed_market()

        invalid_cases = [
            (
                {
                    "decision_type": "NOT_A_DECISION",
                },
                "decision_type",
            ),
            (
                {
                    "notes": " ",
                },
                "notes",
            ),
            (
                {
                    "evidence": "",
                },
                "evidence",
            ),
            (
                {
                    "decision_type": (MarketResultDisputeDecision.DecisionType.CORRECT),
                },
                "winning_outcome",
            ),
            (
                {
                    "decision_type": (MarketResultDisputeDecision.DecisionType.CONFIRM),
                    "winning_outcome_id": (provisional.winning_outcome_id),
                },
                "winning_outcome",
            ),
            (
                {
                    "decision_type": (MarketResultDisputeDecision.DecisionType.VOID),
                    "winning_outcome_id": (provisional.winning_outcome_id),
                },
                "winning_outcome",
            ),
            (
                {
                    "decision_type": (MarketResultDisputeDecision.DecisionType.EXTEND_REVIEW),
                },
                "review_extension_hours",
            ),
            (
                {
                    "decision_type": (MarketResultDisputeDecision.DecisionType.EXTEND_REVIEW),
                    "review_extension_hours": 0,
                },
                "review_extension_hours",
            ),
            (
                {
                    "decision_type": (MarketResultDisputeDecision.DecisionType.EXTEND_REVIEW),
                    "review_extension_hours": 169,
                },
                "review_extension_hours",
            ),
        ]

        for overrides, expected_field in invalid_cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValidationError) as error:
                    self.decide(
                        market,
                        **overrides,
                    )

                self.assertIn(
                    expected_field,
                    error.exception.message_dict,
                )

        self.assertFalse(
            MarketResultDisputeDecision.objects.filter(
                provisional_result=provisional,
            ).exists()
        )

    def test_correct_rejects_provisional_and_cross_market_winner(self):
        market, provisional, _dispute = self.create_disputed_market()

        with self.assertRaises(ValidationError) as error:
            self.decide(
                market,
                decision_type=(MarketResultDisputeDecision.DecisionType.CORRECT),
                winning_outcome_id=(provisional.winning_outcome_id),
            )

        self.assertIn(
            "winning_outcome",
            error.exception.message_dict,
        )

        other_market = self.create_market(
            question="Will the unrelated market resolve YES?",
        )
        other_winner = other_market.outcomes.get(
            side=MarketOutcome.Side.NO,
        )

        with self.assertRaises(ValidationError) as error:
            self.decide(
                market,
                decision_type=(MarketResultDisputeDecision.DecisionType.CORRECT),
                winning_outcome_id=other_winner.id,
            )

        self.assertIn(
            "winning_outcome",
            error.exception.message_dict,
        )

    def test_decision_is_immutable_and_only_one_final_is_allowed(self):
        market, provisional, _dispute = self.create_disputed_market()
        decision = self.decide(market)

        decision.notes = "Changed decision."

        with self.assertRaises(ValidationError):
            decision.save()

        with self.assertRaises(ValidationError):
            decision.delete()

        with self.assertRaises(ValidationError):
            MarketResultDisputeDecision.objects.filter(
                pk=decision.pk,
            ).update(
                notes="Changed through queryset.",
            )

        with self.assertRaises(ValidationError):
            MarketResultDisputeDecision.objects.filter(
                pk=decision.pk,
            ).delete()

        with self.assertRaises(ValidationError) as error:
            self.decide(
                market,
                decision_type=(MarketResultDisputeDecision.DecisionType.VOID),
            )

        self.assertIn(
            "decision",
            error.exception.message_dict,
        )
        self.assertEqual(
            MarketResultDisputeDecision.objects.filter(
                provisional_result=provisional,
            ).count(),
            1,
        )

    def test_final_decisions_release_financial_gates(self):
        confirmed_market, _provisional, _dispute = self.create_disputed_market(
            question=("Will the confirmed market release settlement?")
        )
        self.decide(confirmed_market)

        settlement = MarketSettlementService.settle_market(
            market_id=confirmed_market.id,
            actor=self.decision_user,
        )

        self.assertEqual(
            settlement.market_id,
            confirmed_market.id,
        )
        self.assertTrue(
            MarketSettlement.objects.filter(
                market=confirmed_market,
            ).exists()
        )

        void_market, _provisional, _dispute = self.create_disputed_market(
            question=("Will the void decision release refunds?")
        )
        self.decide(
            void_market,
            decision_type=(MarketResultDisputeDecision.DecisionType.VOID),
        )

        refund = MarketVoidRefundService.refund_void_market(
            market_id=void_market.id,
            actor=self.decision_user,
        )

        self.assertEqual(
            refund.market_id,
            void_market.id,
        )
        self.assertTrue(
            MarketVoidRefund.objects.filter(
                market=void_market,
            ).exists()
        )

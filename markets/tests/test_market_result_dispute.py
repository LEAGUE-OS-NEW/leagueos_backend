from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

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
    MarketFill,
    MarketOrder,
    MarketOutcome,
    MarketPosition,
    MarketProvisionalEvidence,
    MarketResultDispute,
    MarketResultDisputeEvidence,
    MarketScope,
    MarketSettlement,
    MarketVoidRefund,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.provisional_result_service import (
    MarketProvisionalResultService,
)
from markets.services.resolution_service import MarketResolutionService
from markets.services.result_dispute_service import (
    MarketResultDisputeService,
)
from markets.services.settlement_service import MarketSettlementService
from markets.services.void_refund_service import MarketVoidRefundService
from sports.models import Competition, Sport, SportingEvent
from wallets.models import LedgerEntry, Wallet


class MarketResultDisputeTests(TestCase):
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
            name="Dispute Operations Admin",
            display_name="Dispute Operations Admin",
        )
        self.approval_role = RoleFactory(
            name="Dispute Approval Admin",
            display_name="Dispute Approval Admin",
        )

        RolePermissionFactory(
            role=self.operations_role,
            permission=self.manage_permission,
        )
        RolePermissionFactory(
            role=self.approval_role,
            permission=self.approve_permission,
        )

        self.operations_user = UserFactory()
        self.approver_user = UserFactory()
        self.participant_user = UserFactory()
        self.outsider_user = UserFactory()

        UserRoleFactory(
            user=self.operations_user,
            role=self.operations_role,
        )
        UserRoleFactory(
            user=self.approver_user,
            role=self.approval_role,
        )

        self.sport = Sport.objects.create(
            name="Dispute Contract Football",
            code="DISPUTE_CONTRACT_FOOTBALL",
        )
        self.category = MarketCategory.objects.create(
            name="Dispute Match Result",
        )
        self.competition = Competition.objects.create(
            sport=self.sport,
            name="Dispute Contract League",
            country_code="UG",
            is_verified=True,
        )
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="Dispute United v Review City",
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
            "question": "Will Dispute United win?",
            "description": "Participant dispute contract market.",
            "rules": "Resolve YES if Dispute United wins.",
            "resolution_source": "Official competition result",
            "resolution_criteria": "Use the verified final score.",
            "status": Market.Status.DRAFT,
            "opens_at": self.now - timedelta(minutes=5),
            "closes_at": self.now + timedelta(days=1),
            "created_by": self.operations_user,
            "yes_label": "Dispute United wins",
            "no_label": "Dispute United does not win",
        }
        values.update(overrides)

        return MarketCatalogService.create_market(**values)

    def close_market(self, market):
        MarketLifecycleService.submit(
            market_id=market.id,
            actor=self.operations_user,
            notes="Ready for approval.",
        )
        MarketLifecycleService.approve(
            market_id=market.id,
            actor=self.approver_user,
            notes="Approved.",
        )
        MarketLifecycleService.open(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading opened.",
        )
        return MarketLifecycleService.close(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading closed.",
        )

    def create_position(
        self,
        market,
        *,
        user=None,
        quantity="5.0000",
    ):
        outcome = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        return MarketPosition.objects.create(
            user=user or self.participant_user,
            market=market,
            outcome=outcome,
            quantity=Decimal(quantity),
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
        winner = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        values = {
            "market_id": market.id,
            "actor": self.approver_user,
            "winning_outcome_id": winner.id,
            "notes": "Official result published provisionally.",
            "dispute_window_hours": dispute_window_hours,
            "evidence_items": [
                {
                    "evidence_type": (MarketProvisionalEvidence.EvidenceType.OFFICIAL_RESULT),
                    "label": "Official final score",
                    "reference": "OFFICIAL-RESULT-DISPUTE-0042",
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

    def evidence_items(self):
        return [
            {
                "label": "Alternative official report",
                "reference": "ALTERNATIVE-REPORT-2026-0099",
            },
            {
                "label": "Competition correction notice",
                "reference": ("https://league.example/corrections/" "dispute-united-review-city"),
            },
        ]

    def submit(self, market, **overrides):
        values = {
            "market_id": market.id,
            "actor": self.participant_user,
            "category": (MarketResultDispute.Category.INCORRECT_OUTCOME),
            "explanation": (
                "The published winner conflicts with the corrected " "official competition report."
            ),
            "evidence_items": self.evidence_items(),
        }
        values.update(overrides)

        return MarketResultDisputeService.submit(**values)

    @staticmethod
    def financial_snapshot():
        return {
            "wallets": Wallet.objects.count(),
            "ledger_entries": LedgerEntry.objects.count(),
            "orders": MarketOrder.objects.count(),
            "positions": MarketPosition.objects.count(),
            "fills": MarketFill.objects.count(),
            "settlements": MarketSettlement.objects.count(),
            "void_refunds": MarketVoidRefund.objects.count(),
        }

    def test_participant_can_submit_immutable_dispute_and_evidence(self):
        market = self.close_market(self.create_market())
        position = self.create_position(market)
        provisional = self.publish(market)

        market_before = {
            "status": market.status,
            "winning_outcome_id": market.winning_outcome_id,
            "resolved_at": market.resolved_at,
            "transition_count": market.status_transitions.count(),
        }
        financial_before = self.financial_snapshot()

        before = timezone.now()
        dispute = self.submit(market)
        after = timezone.now()

        market.refresh_from_db()
        position.refresh_from_db()
        provisional.refresh_from_db()

        self.assertEqual(dispute.provisional_result, provisional)
        self.assertEqual(
            dispute.participant,
            self.participant_user,
        )
        self.assertEqual(
            dispute.participant_email,
            self.participant_user.email,
        )
        self.assertEqual(
            dispute.category,
            MarketResultDispute.Category.INCORRECT_OUTCOME,
        )
        self.assertGreaterEqual(dispute.submitted_at, before)
        self.assertLessEqual(dispute.submitted_at, after)

        self.assertEqual(
            dispute.explanation,
            ("The published winner conflicts with the corrected " "official competition report."),
        )

        evidence = list(
            dispute.evidence_items.order_by(
                "created_at",
                "id",
            )
        )
        self.assertEqual(len(evidence), 2)
        self.assertEqual(
            evidence[0].label,
            "Alternative official report",
        )

        self.assertEqual(
            {
                "status": market.status,
                "winning_outcome_id": market.winning_outcome_id,
                "resolved_at": market.resolved_at,
                "transition_count": (market.status_transitions.count()),
            },
            market_before,
        )
        self.assertEqual(
            self.financial_snapshot(),
            financial_before,
        )
        self.assertEqual(
            position.quantity,
            Decimal("5.0000"),
        )

    def test_non_participant_cannot_submit_dispute(self):
        market = self.close_market(self.create_market())
        self.publish(market)

        with self.assertRaises(ValidationError) as error:
            self.submit(
                market,
                actor=self.outsider_user,
            )

        self.assertIn(
            "participant",
            error.exception.message_dict,
        )
        self.assertFalse(
            MarketResultDispute.objects.filter(
                provisional_result__market=market,
            ).exists()
        )

    def test_position_on_another_market_does_not_qualify(self):
        market = self.close_market(self.create_market())
        self.publish(market)

        other_market = self.create_market(
            question="Will the other market resolve YES?",
        )
        self.create_position(
            other_market,
            user=self.outsider_user,
        )

        with self.assertRaises(ValidationError) as error:
            self.submit(
                market,
                actor=self.outsider_user,
            )

        self.assertIn(
            "participant",
            error.exception.message_dict,
        )

    def test_dispute_requires_provisional_result(self):
        market = self.close_market(self.create_market())
        self.create_position(market)

        with self.assertRaises(ValidationError) as error:
            self.submit(market)

        self.assertIn(
            "provisional_result",
            error.exception.message_dict,
        )

    def test_dispute_requires_open_window(self):
        market = self.close_market(self.create_market())
        self.create_position(market)

        historical_time = self.now - timedelta(hours=72)

        self.publish(
            market,
            published_at=historical_time,
            dispute_window_hours=48,
        )

        with self.assertRaises(ValidationError) as error:
            self.submit(market)

        self.assertIn(
            "dispute_window",
            error.exception.message_dict,
        )

    def test_dispute_validates_category_explanation_and_evidence(self):
        market = self.close_market(self.create_market())
        self.create_position(market)
        self.publish(market)

        invalid_cases = [
            (
                {"category": "NOT_A_CATEGORY"},
                "category",
            ),
            (
                {"explanation": "   "},
                "explanation",
            ),
            (
                {"evidence_items": []},
                "evidence_items",
            ),
            (
                {
                    "evidence_items": [
                        {
                            "label": "",
                            "reference": "REFERENCE-1",
                        }
                    ]
                },
                "evidence_items",
            ),
            (
                {
                    "evidence_items": [
                        {
                            "label": "Evidence",
                            "reference": "",
                        }
                    ]
                },
                "evidence_items",
            ),
        ]

        for overrides, expected_field in invalid_cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValidationError) as error:
                    self.submit(
                        market,
                        **overrides,
                    )

                self.assertIn(
                    expected_field,
                    error.exception.message_dict,
                )

        self.assertFalse(
            MarketResultDispute.objects.filter(
                provisional_result__market=market,
            ).exists()
        )

    def test_participant_can_submit_only_one_dispute_per_result(self):
        market = self.close_market(self.create_market())
        self.create_position(market)
        first = self.publish(market)
        first_dispute = self.submit(market)

        with self.assertRaises(ValidationError) as error:
            self.submit(
                market,
                explanation="Attempted duplicate dispute.",
            )

        self.assertIn(
            "dispute",
            error.exception.message_dict,
        )
        self.assertEqual(
            MarketResultDispute.objects.filter(
                provisional_result=first,
                participant=self.participant_user,
            ).count(),
            1,
        )
        self.assertEqual(
            MarketResultDispute.objects.get(
                provisional_result=first,
                participant=self.participant_user,
            ).id,
            first_dispute.id,
        )

    def test_dispute_submission_and_evidence_are_immutable(self):
        market = self.close_market(self.create_market())
        self.create_position(market)
        self.publish(market)

        dispute = self.submit(market)
        evidence = dispute.evidence_items.first()

        dispute.explanation = "Changed explanation."

        with self.assertRaises(ValidationError):
            dispute.save()

        with self.assertRaises(ValidationError):
            dispute.delete()

        with self.assertRaises(ValidationError):
            MarketResultDispute.objects.filter(
                pk=dispute.pk,
            ).update(
                explanation="Changed through queryset.",
            )

        evidence.reference = "CHANGED"

        with self.assertRaises(ValidationError):
            evidence.save()

        with self.assertRaises(ValidationError):
            evidence.delete()

        with self.assertRaises(ValidationError):
            MarketResultDisputeEvidence.objects.filter(
                pk=evidence.pk,
            ).delete()

    def test_open_dispute_blocks_settlement_after_window_closes(self):
        market = self.close_market(self.create_market())
        self.create_position(market)

        historical_time = self.now - timedelta(hours=72)
        dispute_time = historical_time + timedelta(hours=1)

        self.publish(
            market,
            published_at=historical_time,
            dispute_window_hours=48,
        )

        with patch(
            "markets.services.result_dispute_service.timezone.now",
            return_value=dispute_time,
        ):
            self.submit(market)

        winner = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )
        MarketResolutionService.resolve(
            market_id=market.id,
            actor=self.approver_user,
            winning_outcome_id=winner.id,
            notes="Final result confirmed.",
            evidence="Approved provisional evidence.",
        )

        financial_before = self.financial_snapshot()

        with self.assertRaises(ValidationError) as error:
            MarketSettlementService.settle_market(
                market_id=market.id,
                actor=self.approver_user,
            )

        self.assertIn(
            "disputes",
            error.exception.message_dict,
        )
        self.assertEqual(
            self.financial_snapshot(),
            financial_before,
        )

    def test_open_dispute_blocks_void_refund_after_window_closes(self):
        market = self.close_market(
            self.create_market(
                question="Will the disputed void market resolve YES?",
            )
        )
        self.create_position(market)

        historical_time = self.now - timedelta(hours=72)
        dispute_time = historical_time + timedelta(hours=1)

        self.publish(
            market,
            published_at=historical_time,
            dispute_window_hours=48,
        )

        with patch(
            "markets.services.result_dispute_service.timezone.now",
            return_value=dispute_time,
        ):
            self.submit(market)

        MarketResolutionService.void(
            market_id=market.id,
            actor=self.approver_user,
            notes="Final review requires a void.",
            evidence="Approved provisional evidence.",
        )

        financial_before = self.financial_snapshot()

        with self.assertRaises(ValidationError) as error:
            MarketVoidRefundService.refund_void_market(
                market_id=market.id,
                actor=self.approver_user,
            )

        self.assertIn(
            "disputes",
            error.exception.message_dict,
        )
        self.assertEqual(
            self.financial_snapshot(),
            financial_before,
        )

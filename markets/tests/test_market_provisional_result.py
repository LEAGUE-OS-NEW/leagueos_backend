from datetime import timedelta
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
    MarketProvisionalEvidence,
    MarketProvisionalResult,
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
from markets.services.settlement_service import MarketSettlementService
from markets.services.void_refund_service import MarketVoidRefundService
from sports.models import Competition, Sport, SportingEvent
from wallets.models import LedgerEntry, Wallet


class MarketProvisionalResultTests(TestCase):
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
            name="Provisional Result Operations Admin",
            display_name="Provisional Result Operations Admin",
        )
        self.approval_role = RoleFactory(
            name="Provisional Result Approval Admin",
            display_name="Provisional Result Approval Admin",
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
            name="Provisional Result Football",
            code="PROVISIONAL_RESULT_FOOTBALL",
        )
        self.category = MarketCategory.objects.create(
            name="Provisional Match Result",
        )
        self.competition = Competition.objects.create(
            sport=self.sport,
            name="Provisional Result League",
            country_code="UG",
            is_verified=True,
        )
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="Provisional United v Evidence City",
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
            "question": "Will Provisional United win?",
            "description": "Provisional-result contract market.",
            "rules": "Resolve YES if Provisional United wins.",
            "resolution_source": "Official competition result",
            "resolution_criteria": "Use the verified final score.",
            "status": Market.Status.DRAFT,
            "opens_at": self.now - timedelta(minutes=5),
            "closes_at": self.now + timedelta(days=1),
            "created_by": self.operations_user,
            "yes_label": "Provisional United wins",
            "no_label": "Provisional United does not win",
        }
        values.update(overrides)

        return MarketCatalogService.create_market(**values)

    def approve_market(self, market):
        MarketLifecycleService.submit(
            market_id=market.id,
            actor=self.operations_user,
            notes="Ready for independent approval.",
        )
        return MarketLifecycleService.approve(
            market_id=market.id,
            actor=self.approver_user,
            notes="Market approved.",
        )

    def close_market(self, market):
        self.approve_market(market)
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

    def evidence_items(self):
        return [
            {
                "evidence_type": (MarketProvisionalEvidence.EvidenceType.OFFICIAL_RESULT),
                "label": "Official final score",
                "reference": ("https://league.example/results/" "provisional-united-evidence-city"),
            },
            {
                "evidence_type": (MarketProvisionalEvidence.EvidenceType.DOCUMENT_REFERENCE),
                "label": "Signed match report",
                "reference": "MATCH-REPORT-2026-0042",
            },
        ]

    def publish(self, market, **overrides):
        winner = market.outcomes.get(side=MarketOutcome.Side.YES)
        values = {
            "market_id": market.id,
            "actor": self.approver_user,
            "winning_outcome_id": winner.id,
            "notes": "Official result published provisionally.",
            "evidence_items": self.evidence_items(),
            "dispute_window_hours": 48,
        }
        values.update(overrides)

        return MarketProvisionalResultService.publish(**values)

    def resolve(self, market):
        winner = market.outcomes.get(side=MarketOutcome.Side.YES)
        return MarketResolutionService.resolve(
            market_id=market.id,
            actor=self.approver_user,
            winning_outcome_id=winner.id,
            notes="Final result confirmed.",
            evidence="Approved provisional evidence.",
        )

    def void(self, market):
        return MarketResolutionService.void(
            market_id=market.id,
            actor=self.approver_user,
            notes="Final review requires voiding the market.",
            evidence="Approved provisional evidence.",
        )

    @staticmethod
    def financial_snapshot():
        return {
            "wallet_count": Wallet.objects.count(),
            "ledger_count": LedgerEntry.objects.count(),
            "settlement_count": MarketSettlement.objects.count(),
            "void_refund_count": MarketVoidRefund.objects.count(),
        }

    def test_publish_creates_immutable_result_and_evidence_without_mutating_market(
        self,
    ):
        market = self.close_market(self.create_market())
        transition_count = market.status_transitions.count()

        before = timezone.now()
        provisional = self.publish(market)
        after = timezone.now()

        market.refresh_from_db()

        self.assertEqual(market.status, Market.Status.CLOSED)
        self.assertIsNone(market.winning_outcome)
        self.assertIsNone(market.resolved_at)
        self.assertEqual(
            market.status_transitions.count(),
            transition_count,
        )

        self.assertEqual(provisional.market, market)
        self.assertEqual(
            provisional.winning_outcome.market,
            market,
        )
        self.assertEqual(
            provisional.published_by,
            self.approver_user,
        )
        self.assertEqual(
            provisional.publisher_email,
            self.approver_user.email,
        )
        self.assertEqual(
            provisional.notes,
            "Official result published provisionally.",
        )
        self.assertGreaterEqual(provisional.published_at, before)
        self.assertLessEqual(provisional.published_at, after)
        self.assertEqual(
            provisional.dispute_deadline,
            provisional.published_at + timedelta(hours=48),
        )

        evidence = list(provisional.evidence_items.order_by("created_at", "id"))
        self.assertEqual(len(evidence), 2)
        self.assertEqual(
            evidence[0].evidence_type,
            MarketProvisionalEvidence.EvidenceType.OFFICIAL_RESULT,
        )
        self.assertEqual(
            evidence[0].recorded_by,
            self.approver_user,
        )
        self.assertEqual(
            evidence[0].recorder_email,
            self.approver_user.email,
        )

    def test_publish_requires_permission_and_independent_actor(self):
        market = self.close_market(self.create_market())
        winner = market.outcomes.get(side=MarketOutcome.Side.YES)

        with self.assertRaises(PermissionDenied):
            self.publish(
                market,
                actor=self.outsider_user,
                winning_outcome_id=winner.id,
            )

        UserRoleFactory(
            user=self.operations_user,
            role=self.approval_role,
        )

        with self.assertRaises(PermissionDenied):
            self.publish(
                market,
                actor=self.operations_user,
                winning_outcome_id=winner.id,
            )

        self.assertFalse(
            MarketProvisionalResult.objects.filter(
                market=market,
            ).exists()
        )

    def test_publish_requires_closed_market_and_matching_outcome(self):
        open_market = self.approve_market(self.create_market())
        MarketLifecycleService.open(
            market_id=open_market.id,
            actor=self.approver_user,
            notes="Trading opened.",
        )

        with self.assertRaises(ValidationError) as status_error:
            self.publish(open_market)

        self.assertIn(
            "status",
            status_error.exception.message_dict,
        )

        market = self.close_market(
            self.create_market(
                question="Will the home side score?",
            )
        )
        other_market = self.create_market(
            question="Will the away side score?",
        )
        other_outcome = other_market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        with self.assertRaises(ValidationError) as outcome_error:
            self.publish(
                market,
                winning_outcome_id=other_outcome.id,
            )

        self.assertIn(
            "winning_outcome",
            outcome_error.exception.message_dict,
        )

    def test_publish_validates_notes_evidence_and_window(self):
        market = self.close_market(self.create_market())

        invalid_cases = [
            (
                {"notes": "   "},
                "notes",
            ),
            (
                {"evidence_items": []},
                "evidence_items",
            ),
            (
                {
                    "evidence_items": [
                        {
                            "evidence_type": (
                                MarketProvisionalEvidence.EvidenceType.OFFICIAL_RESULT
                            ),
                            "label": "",
                            "reference": "OFFICIAL-RESULT-1",
                        }
                    ]
                },
                "evidence_items",
            ),
            (
                {"dispute_window_hours": 0},
                "dispute_window_hours",
            ),
            (
                {"dispute_window_hours": 169},
                "dispute_window_hours",
            ),
        ]

        for overrides, expected_field in invalid_cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValidationError) as error:
                    self.publish(market, **overrides)

                self.assertIn(
                    expected_field,
                    error.exception.message_dict,
                )

        self.assertFalse(
            MarketProvisionalResult.objects.filter(
                market=market,
            ).exists()
        )

    def test_market_can_have_only_one_provisional_result(self):
        market = self.close_market(self.create_market())
        first = self.publish(market)

        with self.assertRaises(ValidationError) as error:
            self.publish(
                market,
                notes="Attempted duplicate publication.",
            )

        self.assertIn(
            "provisional_result",
            error.exception.message_dict,
        )
        self.assertEqual(
            MarketProvisionalResult.objects.filter(
                market=market,
            ).count(),
            1,
        )
        self.assertEqual(
            MarketProvisionalResult.objects.get(
                market=market,
            ).id,
            first.id,
        )

    def test_provisional_result_and_evidence_are_immutable(self):
        market = self.close_market(self.create_market())
        provisional = self.publish(market)
        evidence = provisional.evidence_items.first()

        provisional.notes = "Changed notes."
        with self.assertRaises(ValidationError):
            provisional.save()

        with self.assertRaises(ValidationError):
            provisional.delete()

        with self.assertRaises(ValidationError):
            MarketProvisionalResult.objects.filter(
                pk=provisional.pk,
            ).update(notes="Changed through queryset.")

        evidence.reference = "CHANGED"
        with self.assertRaises(ValidationError):
            evidence.save()

        with self.assertRaises(ValidationError):
            evidence.delete()

        with self.assertRaises(ValidationError):
            MarketProvisionalEvidence.objects.filter(
                pk=evidence.pk,
            ).delete()

    def test_open_dispute_window_blocks_normal_settlement_without_mutation(
        self,
    ):
        market = self.close_market(self.create_market())
        self.publish(market)
        self.resolve(market)

        before = self.financial_snapshot()

        with self.assertRaises(ValidationError) as error:
            MarketSettlementService.settle_market(
                market_id=market.id,
                actor=self.approver_user,
            )

        self.assertIn(
            "dispute_window",
            error.exception.message_dict,
        )
        self.assertEqual(
            self.financial_snapshot(),
            before,
        )

    def test_open_dispute_window_blocks_void_refund_without_mutation(
        self,
    ):
        market = self.close_market(self.create_market())
        self.publish(market)
        self.void(market)

        before = self.financial_snapshot()

        with self.assertRaises(ValidationError) as error:
            MarketVoidRefundService.refund_void_market(
                market_id=market.id,
                actor=self.approver_user,
            )

        self.assertIn(
            "dispute_window",
            error.exception.message_dict,
        )
        self.assertEqual(
            self.financial_snapshot(),
            before,
        )

    def test_expired_dispute_window_allows_terminal_financial_actions(
        self,
    ):
        resolved_market = self.close_market(
            self.create_market(
                question="Will the resolved market finish YES?",
            )
        )

        historical_time = self.now - timedelta(hours=72)

        with patch(
            "markets.services.provisional_result_service.timezone.now",
            return_value=historical_time,
        ):
            provisional = self.publish(
                resolved_market,
                dispute_window_hours=48,
            )

        self.assertLess(
            provisional.dispute_deadline,
            timezone.now(),
        )

        self.resolve(resolved_market)

        settlement = MarketSettlementService.settle_market(
            market_id=resolved_market.id,
            actor=self.approver_user,
        )
        self.assertEqual(
            settlement.market_id,
            resolved_market.id,
        )

        void_market = self.close_market(
            self.create_market(
                question="Will the void market finish YES?",
            )
        )

        with patch(
            "markets.services.provisional_result_service.timezone.now",
            return_value=historical_time,
        ):
            self.publish(
                void_market,
                dispute_window_hours=48,
            )

        self.void(void_market)

        refund = MarketVoidRefundService.refund_void_market(
            market_id=void_market.id,
            actor=self.approver_user,
        )
        self.assertEqual(
            refund.market_id,
            void_market.id,
        )

    def test_legacy_terminal_markets_without_provisional_result_remain_supported(
        self,
    ):
        resolved_market = self.close_market(
            self.create_market(
                question="Will the legacy resolved market finish YES?",
            )
        )
        self.resolve(resolved_market)

        settlement = MarketSettlementService.settle_market(
            market_id=resolved_market.id,
            actor=self.approver_user,
        )

        self.assertEqual(
            settlement.market_id,
            resolved_market.id,
        )

        void_market = self.close_market(
            self.create_market(
                question="Will the legacy void market finish YES?",
            )
        )
        self.void(void_market)

        refund = MarketVoidRefundService.refund_void_market(
            market_id=void_market.id,
            actor=self.approver_user,
        )

        self.assertEqual(
            refund.market_id,
            void_market.id,
        )

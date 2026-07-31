from datetime import timedelta

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
    MarketScope,
    MarketStatusTransition,
)
from markets.services.catalog_service import (
    MarketCatalogService,
)
from markets.services.lifecycle_service import (
    MarketLifecycleService,
)
from markets.services.resolution_service import (
    MarketResolutionService,
)
from sports.models import (
    Competition,
    Sport,
    SportingEvent,
)


class MarketResolutionServiceTests(TestCase):
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
            name="Market Operations Admin",
            display_name="Market Operations Admin",
        )
        self.approval_role = RoleFactory(
            name="Market Approval Admin",
            display_name="Market Approval Admin",
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

        self.football = Sport.objects.create(
            name="Football",
            code="FOOTBALL",
        )
        self.category = MarketCategory.objects.create(
            name="Match Result",
        )
        self.competition = Competition.objects.create(
            sport=self.football,
            name="Uganda Premier League",
            country_code="UG",
            is_verified=True,
        )
        self.event = SportingEvent.objects.create(
            sport=self.football,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="KCCA FC vs Vipers SC",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

    def create_market(self, **overrides):
        values = {
            "sport": self.football,
            "category": self.category,
            "scope_type": MarketScope.EVENT,
            "sporting_event": self.event,
            "question": "Will KCCA FC beat Vipers SC?",
            "description": "Match result prediction.",
            "rules": ("Resolve YES if KCCA FC wins " "in regulation time."),
            "resolution_source": ("Official competition result"),
            "resolution_criteria": ("Use the verified regulation-time " "final score."),
            "status": Market.Status.DRAFT,
            "opens_at": self.now - timedelta(minutes=5),
            "closes_at": self.now + timedelta(days=1),
            "created_by": self.operations_user,
            "yes_label": "KCCA FC wins",
            "no_label": "Draw or Vipers SC",
        }
        values.update(overrides)

        return MarketCatalogService.create_market(
            **values,
        )

    def approve_market(self, market):
        market = MarketLifecycleService.submit(
            market_id=market.id,
            actor=self.operations_user,
            notes="Ready for independent review.",
        )

        return MarketLifecycleService.approve(
            market_id=market.id,
            actor=self.approver_user,
            notes="Market details verified.",
        )

    def open_market(self, market):
        market = self.approve_market(market)

        return MarketLifecycleService.open(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading opened.",
        )

    def suspend_market(self, market):
        market = self.open_market(market)

        return MarketLifecycleService.suspend(
            market_id=market.id,
            actor=self.approver_user,
            notes="Investigating event data.",
        )

    def close_market(self, market):
        market = self.open_market(market)

        return MarketLifecycleService.close(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading window completed.",
        )

    def resolve_market(
        self,
        market,
        **overrides,
    ):
        winner = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        values = {
            "market_id": market.id,
            "actor": self.approver_user,
            "winning_outcome_id": winner.id,
            "notes": ("Official final result confirmed."),
            "evidence": (
                "Uganda Premier League official " "match report: KCCA FC 2-1 " "Vipers SC."
            ),
        }
        values.update(overrides)

        return MarketResolutionService.resolve(
            **values,
        )

    def void_market(
        self,
        market,
        **overrides,
    ):
        values = {
            "market_id": market.id,
            "actor": self.approver_user,
            "notes": ("The underlying fixture was " "abandoned."),
            "evidence": ("Official competition notice " "confirming the abandoned match."),
        }
        values.update(overrides)

        return MarketResolutionService.void(
            **values,
        )

    def test_resolve_closed_market_records_winner(
        self,
    ):
        market = self.close_market(self.create_market())
        winner = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        market = self.resolve_market(
            market,
            winning_outcome_id=winner.id,
        )

        self.assertEqual(
            market.status,
            Market.Status.RESOLVED,
        )
        self.assertEqual(
            market.winning_outcome,
            winner,
        )
        self.assertEqual(
            market.resolved_by,
            self.approver_user,
        )
        self.assertIsNotNone(
            market.resolved_at,
        )
        self.assertEqual(
            market.resolution_notes,
            "Official final result confirmed.",
        )
        self.assertEqual(
            market.resolution_evidence,
            ("Uganda Premier League official " "match report: KCCA FC 2-1 " "Vipers SC."),
        )

        transition = market.status_transitions.latest(
            "created_at",
        )

        self.assertEqual(
            transition.action,
            MarketStatusTransition.Action.RESOLVE,
        )
        self.assertEqual(
            transition.from_status,
            Market.Status.CLOSED,
        )
        self.assertEqual(
            transition.to_status,
            Market.Status.RESOLVED,
        )
        self.assertEqual(
            transition.metadata["winning_outcome_id"],
            str(winner.id),
        )
        self.assertEqual(
            transition.metadata["winning_side"],
            MarketOutcome.Side.YES,
        )
        self.assertEqual(
            transition.metadata["evidence"],
            market.resolution_evidence,
        )

    def test_resolve_requires_approve_permission(
        self,
    ):
        market = self.close_market(self.create_market())
        winner = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        with self.assertRaises(PermissionDenied):
            MarketResolutionService.resolve(
                market_id=market.id,
                actor=self.outsider_user,
                winning_outcome_id=winner.id,
                notes="Attempted resolution.",
                evidence="Unsupported evidence.",
            )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.CLOSED,
        )
        self.assertIsNone(
            market.winning_outcome,
        )

    def test_resolve_requires_closed_market(self):
        market = self.open_market(self.create_market())
        winner = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        with self.assertRaises(ValidationError) as context:
            MarketResolutionService.resolve(
                market_id=market.id,
                actor=self.approver_user,
                winning_outcome_id=winner.id,
                notes="Premature resolution.",
                evidence="Official match report.",
            )

        self.assertIn(
            "status",
            context.exception.message_dict,
        )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.OPEN,
        )

    def test_resolve_rejects_outcome_from_other_market(
        self,
    ):
        market = self.close_market(
            self.create_market(
                question="Will KCCA FC win?",
            )
        )
        other_market = self.create_market(question="Will Vipers SC score?")
        other_winner = other_market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )
        transition_count = market.status_transitions.count()

        with self.assertRaises(ValidationError) as context:
            self.resolve_market(
                market,
                winning_outcome_id=(other_winner.id),
            )

        self.assertIn(
            "winning_outcome",
            context.exception.message_dict,
        )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.CLOSED,
        )
        self.assertIsNone(
            market.winning_outcome,
        )
        self.assertEqual(
            market.status_transitions.count(),
            transition_count,
        )

    def test_resolve_requires_notes(self):
        market = self.close_market(self.create_market())

        with self.assertRaises(ValidationError) as context:
            self.resolve_market(
                market,
                notes="",
            )

        self.assertIn(
            "notes",
            context.exception.message_dict,
        )

    def test_resolve_requires_evidence(self):
        market = self.close_market(self.create_market())

        with self.assertRaises(ValidationError) as context:
            self.resolve_market(
                market,
                evidence="",
            )

        self.assertIn(
            "evidence",
            context.exception.message_dict,
        )

    def test_creator_cannot_resolve_own_market(
        self,
    ):
        UserRoleFactory(
            user=self.operations_user,
            role=self.approval_role,
        )

        market = self.close_market(self.create_market())
        winner = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        with self.assertRaises(PermissionDenied):
            MarketResolutionService.resolve(
                market_id=market.id,
                actor=self.operations_user,
                winning_outcome_id=winner.id,
                notes="Self resolution attempt.",
                evidence="Official match report.",
            )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.CLOSED,
        )

    def test_void_supports_operational_states(self):
        builders = {
            Market.Status.APPROVED: (self.approve_market),
            Market.Status.OPEN: self.open_market,
            Market.Status.SUSPENDED: (self.suspend_market),
            Market.Status.CLOSED: (self.close_market),
        }

        for expected_status, builder in builders.items():
            with self.subTest(
                status=expected_status,
            ):
                market = builder(
                    self.create_market(question=("Void market from " f"{expected_status}"))
                )

                self.assertEqual(
                    market.status,
                    expected_status,
                )

                market = self.void_market(market)

                self.assertEqual(
                    market.status,
                    Market.Status.VOIDED,
                )
                self.assertIsNone(
                    market.winning_outcome,
                )
                self.assertEqual(
                    market.resolved_by,
                    self.approver_user,
                )
                self.assertIsNotNone(
                    market.resolved_at,
                )

                transition = market.status_transitions.latest(
                    "created_at",
                )

                self.assertEqual(
                    transition.action,
                    MarketStatusTransition.Action.VOID,
                )
                self.assertEqual(
                    transition.from_status,
                    expected_status,
                )
                self.assertEqual(
                    transition.to_status,
                    Market.Status.VOIDED,
                )
                self.assertEqual(
                    transition.metadata["evidence"],
                    market.resolution_evidence,
                )

    def test_void_rejects_draft_market(self):
        market = self.create_market()

        with self.assertRaises(ValidationError) as context:
            self.void_market(market)

        self.assertIn(
            "status",
            context.exception.message_dict,
        )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.DRAFT,
        )
        self.assertFalse(
            market.status_transitions.exists(),
        )

    def test_void_requires_notes(self):
        market = self.approve_market(self.create_market())

        with self.assertRaises(ValidationError) as context:
            self.void_market(
                market,
                notes="",
            )

        self.assertIn(
            "notes",
            context.exception.message_dict,
        )

    def test_void_requires_evidence(self):
        market = self.approve_market(self.create_market())

        with self.assertRaises(ValidationError) as context:
            self.void_market(
                market,
                evidence="",
            )

        self.assertIn(
            "evidence",
            context.exception.message_dict,
        )

    def test_creator_cannot_void_own_market(self):
        UserRoleFactory(
            user=self.operations_user,
            role=self.approval_role,
        )
        market = self.approve_market(self.create_market())

        with self.assertRaises(PermissionDenied):
            MarketResolutionService.void(
                market_id=market.id,
                actor=self.operations_user,
                notes="Self void attempt.",
                evidence="Official cancellation.",
            )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.APPROVED,
        )

    def test_resolved_and_voided_markets_are_terminal(
        self,
    ):
        resolved_market = self.resolve_market(
            self.close_market(self.create_market(question="Resolved terminal market"))
        )
        voided_market = self.void_market(
            self.approve_market(self.create_market(question="Voided terminal market"))
        )

        with self.assertRaises(ValidationError):
            self.void_market(resolved_market)

        voided_winner = voided_market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        with self.assertRaises(ValidationError):
            MarketResolutionService.resolve(
                market_id=voided_market.id,
                actor=self.approver_user,
                winning_outcome_id=(voided_winner.id),
                notes="Invalid resolution.",
                evidence="Invalid evidence.",
            )

        resolved_market.refresh_from_db()
        voided_market.refresh_from_db()

        self.assertEqual(
            resolved_market.status,
            Market.Status.RESOLVED,
        )
        self.assertEqual(
            voided_market.status,
            Market.Status.VOIDED,
        )

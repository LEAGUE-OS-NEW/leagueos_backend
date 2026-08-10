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
    MarketScope,
    MarketStatusTransition,
)
from markets.services.catalog_service import (
    MarketCatalogService,
)
from markets.services.lifecycle_service import (
    MarketLifecycleService,
)
from sports.models import (
    Competition,
    Sport,
    SportingEvent,
)


class MarketLifecycleServiceTests(TestCase):
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
        self.category = MarketCategory.objects.create(
            name="Match Result",
        )

    def create_market(self, **overrides):
        values = {
            "sport": self.football,
            "category": self.category,
            "scope_type": MarketScope.EVENT,
            "sporting_event": self.event,
            "question": "Will KCCA FC beat Vipers SC?",
            "description": "Match result prediction.",
            "rules": ("The market resolves YES if KCCA FC " "wins the match in regulation time."),
            "resolution_source": "Official competition result",
            "resolution_criteria": (
                "Use the verified final score published " "by the competition organiser."
            ),
            "status": Market.Status.DRAFT,
            "opens_at": self.now - timedelta(minutes=5),
            "closes_at": self.now + timedelta(days=1),
            "created_by": self.operations_user,
        }
        values.update(overrides)

        return MarketCatalogService.create_market(
            **values,
        )

    def submit(self, market, **overrides):
        values = {
            "market_id": market.id,
            "actor": self.operations_user,
            "notes": "Ready for independent review.",
        }
        values.update(overrides)

        return MarketLifecycleService.submit(
            **values,
        )

    def approve(self, market, **overrides):
        values = {
            "market_id": market.id,
            "actor": self.approver_user,
            "notes": "Market details verified.",
        }
        values.update(overrides)

        return MarketLifecycleService.approve(
            **values,
        )

    def test_submit_moves_draft_to_pending_approval(self):
        market = self.create_market()

        market = self.submit(market)

        self.assertEqual(
            market.status,
            Market.Status.PENDING_APPROVAL,
        )

        transition = market.status_transitions.get()

        self.assertEqual(
            transition.action,
            MarketStatusTransition.Action.SUBMIT,
        )
        self.assertEqual(
            transition.from_status,
            Market.Status.DRAFT,
        )
        self.assertEqual(
            transition.to_status,
            Market.Status.PENDING_APPROVAL,
        )
        self.assertEqual(
            transition.actor,
            self.operations_user,
        )
        self.assertEqual(
            transition.actor_email,
            self.operations_user.email,
        )

    def test_submit_requires_manage_market_permission(self):
        market = self.create_market()

        with self.assertRaises(PermissionDenied):
            MarketLifecycleService.submit(
                market_id=market.id,
                actor=self.outsider_user,
                notes="Attempted submission.",
            )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.DRAFT,
        )
        self.assertFalse(
            market.status_transitions.exists(),
        )

    def test_submit_requires_complete_resolution_details(self):
        market = self.create_market(
            resolution_source="",
            resolution_criteria="",
        )

        with self.assertRaises(ValidationError) as context:
            self.submit(market)

        self.assertIn(
            "resolution_source",
            context.exception.message_dict,
        )
        self.assertIn(
            "resolution_criteria",
            context.exception.message_dict,
        )

    def test_rejected_market_can_be_resubmitted(self):
        market = self.create_market()
        market = self.submit(market)

        market = MarketLifecycleService.reject(
            market_id=market.id,
            actor=self.approver_user,
            notes="Clarify the resolution criteria.",
        )

        self.assertEqual(
            market.status,
            Market.Status.REJECTED,
        )

        market.resolution_criteria = "Use the official final score after " "regulation time only."
        market.save(
            update_fields=[
                "resolution_criteria",
                "updated_at",
            ]
        )

        market = self.submit(
            market,
            notes="Resolution criteria corrected.",
        )

        self.assertEqual(
            market.status,
            Market.Status.PENDING_APPROVAL,
        )
        self.assertEqual(
            market.status_transitions.count(),
            3,
        )

    def test_creator_with_approval_permission_can_approve_own_market(self):
        UserRoleFactory(
            user=self.operations_user,
            role=self.approval_role,
        )

        market = self.create_market()
        market = self.submit(market)

        market = MarketLifecycleService.approve(
            market_id=market.id,
            actor=self.operations_user,
            notes="Creator approval permitted.",
        )

        self.assertEqual(
            market.status,
            Market.Status.APPROVED,
        )

        self.assertEqual(
            market.approved_by,
            self.operations_user,
        )

        self.assertIsNotNone(
            market.approved_at,
        )

    def test_approve_records_approver_and_timestamp(self):
        market = self.create_market()
        market = self.submit(market)

        market = self.approve(market)

        self.assertEqual(
            market.status,
            Market.Status.APPROVED,
        )
        self.assertEqual(
            market.approved_by,
            self.approver_user,
        )
        self.assertIsNotNone(
            market.approved_at,
        )
        self.assertEqual(
            market.approval_notes,
            "Market details verified.",
        )

        transition = market.status_transitions.latest(
            "created_at",
        )

        self.assertEqual(
            transition.action,
            MarketStatusTransition.Action.APPROVE,
        )

    def test_reject_requires_reason(self):
        market = self.create_market()
        market = self.submit(market)

        with self.assertRaises(ValidationError) as context:
            MarketLifecycleService.reject(
                market_id=market.id,
                actor=self.approver_user,
                notes="",
            )

        self.assertIn(
            "notes",
            context.exception.message_dict,
        )

    def test_open_requires_approved_market(self):
        market = self.create_market()

        with self.assertRaises(ValidationError):
            MarketLifecycleService.open(
                market_id=market.id,
                actor=self.approver_user,
                notes="Open market.",
            )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.DRAFT,
        )

    def test_open_requires_active_trading_window(self):
        market = self.create_market(
            opens_at=self.now + timedelta(hours=1),
            closes_at=self.now + timedelta(days=1),
        )
        market = self.submit(market)
        market = self.approve(market)

        with self.assertRaises(ValidationError) as context:
            MarketLifecycleService.open(
                market_id=market.id,
                actor=self.approver_user,
                notes="Opening too early.",
            )

        self.assertIn(
            "opens_at",
            context.exception.message_dict,
        )

    def test_suspend_and_reopen_market(self):
        market = self.create_market()
        market = self.submit(market)
        market = self.approve(market)

        market = MarketLifecycleService.open(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading opened.",
        )
        market = MarketLifecycleService.suspend(
            market_id=market.id,
            actor=self.approver_user,
            notes="Investigating event data.",
        )

        self.assertEqual(
            market.status,
            Market.Status.SUSPENDED,
        )

        market = MarketLifecycleService.reopen(
            market_id=market.id,
            actor=self.approver_user,
            notes="Event data confirmed.",
        )

        self.assertEqual(
            market.status,
            Market.Status.OPEN,
        )

        self.assertEqual(
            list(
                market.status_transitions.values_list(
                    "action",
                    flat=True,
                )
            ),
            [
                MarketStatusTransition.Action.SUBMIT,
                MarketStatusTransition.Action.APPROVE,
                MarketStatusTransition.Action.OPEN,
                MarketStatusTransition.Action.SUSPEND,
                MarketStatusTransition.Action.REOPEN,
            ],
        )

    def test_close_market_from_open_state(self):
        market = self.create_market()
        market = self.submit(market)
        market = self.approve(market)
        market = MarketLifecycleService.open(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading opened.",
        )

        market = MarketLifecycleService.close(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading window completed.",
        )

        self.assertEqual(
            market.status,
            Market.Status.CLOSED,
        )

    def test_invalid_transition_is_atomic(self):
        market = self.create_market()

        with self.assertRaises(ValidationError):
            MarketLifecycleService.close(
                market_id=market.id,
                actor=self.approver_user,
                notes="Invalid closure.",
            )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.DRAFT,
        )
        self.assertFalse(
            market.status_transitions.exists(),
        )

    def test_transition_history_is_immutable(self):
        market = self.create_market()
        market = self.submit(market)

        transition = market.status_transitions.get()
        transition.notes = "Changed history"

        with self.assertRaises(ValidationError):
            transition.save()

        with self.assertRaises(ValidationError):
            transition.delete()

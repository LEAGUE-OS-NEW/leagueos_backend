from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

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


class MarketLifecycleAPITests(APITestCase):
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

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

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

    def submit_market(self, market):
        return MarketLifecycleService.submit(
            market_id=market.id,
            actor=self.operations_user,
            notes="Ready for independent review.",
        )

    def approve_market(self, market):
        return MarketLifecycleService.approve(
            market_id=market.id,
            actor=self.approver_user,
            notes="Market details verified.",
        )

    def open_market(self, market):
        return MarketLifecycleService.open(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading opened.",
        )

    def action_url(self, market, action):
        return reverse(
            f"markets:admin-market-{action}",
            kwargs={
                "market_id": market.id,
            },
        )

    def test_submit_requires_authentication(self):
        market = self.create_market()

        response = self.client.post(
            self.action_url(market, "submit"),
            {
                "notes": "Ready for review.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_submit_rejects_user_without_manage_permission(
        self,
    ):
        market = self.create_market()
        self.authenticate(self.outsider_user)

        response = self.client.post(
            self.action_url(market, "submit"),
            {
                "notes": "Attempted submission.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.DRAFT,
        )

    def test_operations_admin_can_submit_draft_market(
        self,
    ):
        market = self.create_market()
        self.authenticate(self.operations_user)

        response = self.client.post(
            self.action_url(market, "submit"),
            {
                "notes": "Ready for review.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["status"],
            Market.Status.PENDING_APPROVAL,
        )
        self.assertEqual(
            response.data["status_transitions"][-1]["action"],
            MarketStatusTransition.Action.SUBMIT,
        )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.PENDING_APPROVAL,
        )

    def test_approval_admin_cannot_submit_market(self):
        market = self.create_market()
        self.authenticate(self.approver_user)

        response = self.client.post(
            self.action_url(market, "submit"),
            {
                "notes": "Approval user submission.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_operations_admin_cannot_approve_market(
        self,
    ):
        market = self.submit_market(self.create_market())
        self.authenticate(self.operations_user)

        response = self.client.post(
            self.action_url(market, "approve"),
            {
                "notes": "Attempted approval.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.PENDING_APPROVAL,
        )

    def test_approval_admin_can_approve_pending_market(
        self,
    ):
        market = self.submit_market(self.create_market())
        self.authenticate(self.approver_user)

        response = self.client.post(
            self.action_url(market, "approve"),
            {
                "notes": "Market details verified.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["status"],
            Market.Status.APPROVED,
        )
        self.assertEqual(
            response.data["approved_by"]["id"],
            str(self.approver_user.id),
        )
        self.assertEqual(
            response.data["status_transitions"][-1]["action"],
            MarketStatusTransition.Action.APPROVE,
        )

    def test_creator_with_approval_permission_can_approve_own_market(self):
        UserRoleFactory(
            user=self.operations_user,
            role=self.approval_role,
        )

        market = self.submit_market(self.create_market())

        self.authenticate(self.operations_user)

        response = self.client.post(
            self.action_url(
                market,
                "approve",
            ),
            {
                "notes": "Creator approval permitted.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        self.assertEqual(
            response.data["status"],
            Market.Status.APPROVED,
        )

        self.assertEqual(
            response.data["approved_by"]["id"],
            str(self.operations_user.id),
        )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.APPROVED,
        )

        self.assertEqual(
            market.approved_by,
            self.operations_user,
        )

    def test_reject_requires_notes(self):
        market = self.submit_market(self.create_market())
        self.authenticate(self.approver_user)

        response = self.client.post(
            self.action_url(market, "reject"),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            response.data,
        )
        self.assertIn(
            "notes",
            response.data,
        )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.PENDING_APPROVAL,
        )

    def test_approval_admin_can_reject_market(self):
        market = self.submit_market(self.create_market())
        self.authenticate(self.approver_user)

        response = self.client.post(
            self.action_url(market, "reject"),
            {
                "notes": ("Clarify the resolution criteria."),
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["status"],
            Market.Status.REJECTED,
        )
        self.assertEqual(
            response.data["status_transitions"][-1]["action"],
            MarketStatusTransition.Action.REJECT,
        )

    def test_approval_admin_can_open_approved_market(
        self,
    ):
        market = self.approve_market(self.submit_market(self.create_market()))
        self.authenticate(self.approver_user)

        response = self.client.post(
            self.action_url(market, "open"),
            {
                "notes": "Trading opened.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["status"],
            Market.Status.OPEN,
        )
        self.assertEqual(
            response.data["status_transitions"][-1]["action"],
            MarketStatusTransition.Action.OPEN,
        )

    def test_invalid_transition_returns_bad_request(
        self,
    ):
        market = self.create_market()
        self.authenticate(self.approver_user)

        response = self.client.post(
            self.action_url(market, "close"),
            {
                "notes": "Invalid draft closure.",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            response.data,
        )
        self.assertIn(
            "status",
            response.data,
        )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.DRAFT,
        )
        self.assertFalse(
            market.status_transitions.exists(),
        )

    def test_suspend_reopen_and_close_flow(self):
        market = self.open_market(self.approve_market(self.submit_market(self.create_market())))
        self.authenticate(self.approver_user)

        suspend_response = self.client.post(
            self.action_url(market, "suspend"),
            {
                "notes": ("Investigating event data."),
            },
            format="json",
        )

        self.assertEqual(
            suspend_response.status_code,
            status.HTTP_200_OK,
            suspend_response.data,
        )
        self.assertEqual(
            suspend_response.data["status"],
            Market.Status.SUSPENDED,
        )

        reopen_response = self.client.post(
            self.action_url(market, "reopen"),
            {
                "notes": "Event data confirmed.",
            },
            format="json",
        )

        self.assertEqual(
            reopen_response.status_code,
            status.HTTP_200_OK,
            reopen_response.data,
        )
        self.assertEqual(
            reopen_response.data["status"],
            Market.Status.OPEN,
        )

        close_response = self.client.post(
            self.action_url(market, "close"),
            {
                "notes": ("Trading window completed."),
            },
            format="json",
        )

        self.assertEqual(
            close_response.status_code,
            status.HTTP_200_OK,
            close_response.data,
        )
        self.assertEqual(
            close_response.data["status"],
            Market.Status.CLOSED,
        )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.CLOSED,
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
                MarketStatusTransition.Action.CLOSE,
            ],
        )

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
from sports.models import (
    Competition,
    Sport,
    SportingEvent,
)


class MarketResolutionAPITests(APITestCase):
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
        self.client.force_authenticate(
            user=user,
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
            "opens_at": (self.now - timedelta(minutes=5)),
            "closes_at": (self.now + timedelta(days=1)),
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

    def close_market(self, market):
        market = self.open_market(market)

        return MarketLifecycleService.close(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading window completed.",
        )

    def resolve_url(self, market):
        return reverse(
            "markets:admin-market-resolve",
            kwargs={
                "market_id": market.id,
            },
        )

    def void_url(self, market):
        return reverse(
            "markets:admin-market-void",
            kwargs={
                "market_id": market.id,
            },
        )

    def resolve_payload(
        self,
        market,
        **overrides,
    ):
        winner = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        payload = {
            "winning_outcome_id": str(winner.id),
            "notes": ("Official final result confirmed."),
            "evidence": (
                "Uganda Premier League official " "match report: KCCA FC 2-1 " "Vipers SC."
            ),
        }
        payload.update(overrides)

        return payload

    def void_payload(self, **overrides):
        payload = {
            "notes": ("The underlying fixture was " "abandoned."),
            "evidence": ("Official competition notice " "confirming the abandoned match."),
        }
        payload.update(overrides)

        return payload

    def test_resolve_requires_authentication(self):
        market = self.close_market(self.create_market())

        response = self.client.post(
            self.resolve_url(market),
            self.resolve_payload(market),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_resolve_requires_approve_permission(
        self,
    ):
        market = self.close_market(self.create_market())
        self.authenticate(self.outsider_user)

        response = self.client.post(
            self.resolve_url(market),
            self.resolve_payload(market),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.CLOSED,
        )
        self.assertIsNone(
            market.winning_outcome,
        )

    def test_approver_can_resolve_closed_market(
        self,
    ):
        market = self.close_market(self.create_market())
        winner = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )
        self.authenticate(self.approver_user)

        response = self.client.post(
            self.resolve_url(market),
            self.resolve_payload(
                market,
                winning_outcome_id=str(winner.id),
            ),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["status"],
            Market.Status.RESOLVED,
        )
        self.assertEqual(
            response.data["winning_outcome"],
            str(winner.id),
        )
        self.assertEqual(
            response.data["resolved_by"]["id"],
            str(self.approver_user.id),
        )
        self.assertIsNotNone(
            response.data["resolved_at"],
        )
        self.assertEqual(
            response.data["resolution_notes"],
            "Official final result confirmed.",
        )
        self.assertEqual(
            response.data["resolution_evidence"],
            ("Uganda Premier League official " "match report: KCCA FC 2-1 " "Vipers SC."),
        )

        transition = response.data["status_transitions"][-1]

        self.assertEqual(
            transition["action"],
            MarketStatusTransition.Action.RESOLVE,
        )
        self.assertEqual(
            transition["from_status"],
            Market.Status.CLOSED,
        )
        self.assertEqual(
            transition["to_status"],
            Market.Status.RESOLVED,
        )
        self.assertEqual(
            transition["metadata"]["winning_outcome_id"],
            str(winner.id),
        )
        self.assertEqual(
            transition["metadata"]["winning_side"],
            MarketOutcome.Side.YES,
        )

    def test_creator_cannot_resolve_own_market(
        self,
    ):
        UserRoleFactory(
            user=self.operations_user,
            role=self.approval_role,
        )

        market = self.close_market(self.create_market())
        self.authenticate(self.operations_user)

        response = self.client.post(
            self.resolve_url(market),
            self.resolve_payload(market),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.CLOSED,
        )

    def test_resolve_rejects_outcome_from_other_market(
        self,
    ):
        market = self.close_market(self.create_market(question="Will KCCA FC win?"))
        other_market = self.create_market(question="Will Vipers SC score?")
        other_outcome = other_market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )
        self.authenticate(self.approver_user)

        response = self.client.post(
            self.resolve_url(market),
            self.resolve_payload(
                market,
                winning_outcome_id=str(other_outcome.id),
            ),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            response.data,
        )
        self.assertIn(
            "winning_outcome",
            response.data,
        )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.CLOSED,
        )
        self.assertIsNone(
            market.winning_outcome,
        )

    def test_resolve_requires_complete_payload(
        self,
    ):
        market = self.close_market(self.create_market())
        self.authenticate(self.approver_user)

        response = self.client.post(
            self.resolve_url(market),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            response.data,
        )
        self.assertIn(
            "winning_outcome_id",
            response.data,
        )
        self.assertIn(
            "notes",
            response.data,
        )
        self.assertIn(
            "evidence",
            response.data,
        )

    def test_resolve_rejects_non_closed_market(
        self,
    ):
        market = self.open_market(self.create_market())
        self.authenticate(self.approver_user)

        response = self.client.post(
            self.resolve_url(market),
            self.resolve_payload(market),
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
            Market.Status.OPEN,
        )

    def test_approver_can_void_approved_market(
        self,
    ):
        market = self.approve_market(self.create_market())
        self.authenticate(self.approver_user)

        response = self.client.post(
            self.void_url(market),
            self.void_payload(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["status"],
            Market.Status.VOIDED,
        )
        self.assertIsNone(
            response.data["winning_outcome"],
        )
        self.assertEqual(
            response.data["resolved_by"]["id"],
            str(self.approver_user.id),
        )
        self.assertEqual(
            response.data["status_transitions"][-1]["action"],
            MarketStatusTransition.Action.VOID,
        )
        self.assertEqual(
            response.data["status_transitions"][-1]["metadata"]["evidence"],
            response.data["resolution_evidence"],
        )

    def test_operations_admin_cannot_void_market(
        self,
    ):
        market = self.approve_market(self.create_market())
        self.authenticate(self.operations_user)

        response = self.client.post(
            self.void_url(market),
            self.void_payload(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        market.refresh_from_db()

        self.assertEqual(
            market.status,
            Market.Status.APPROVED,
        )

    def test_void_rejects_draft_market(self):
        market = self.create_market()
        self.authenticate(self.approver_user)

        response = self.client.post(
            self.void_url(market),
            self.void_payload(),
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

    def test_void_requires_complete_payload(self):
        market = self.approve_market(self.create_market())
        self.authenticate(self.approver_user)

        response = self.client.post(
            self.void_url(market),
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
        self.assertIn(
            "evidence",
            response.data,
        )

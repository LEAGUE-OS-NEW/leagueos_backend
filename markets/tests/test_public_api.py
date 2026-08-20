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
from markets.services.settlement_service import MarketSettlementService
from markets.services.void_refund_service import MarketVoidRefundService
from sports.models import (
    Competition,
    Participant,
    Sport,
    SportingEvent,
)


class PublicMarketAPITests(APITestCase):
    def setUp(self):
        self.now = timezone.now()

        self.football = Sport.objects.create(
            name="Football",
            code="FOOTBALL",
        )
        self.category = MarketCategory.objects.create(
            name="Match Result",
            description="Binary match-result markets.",
        )
        self.inactive_category = MarketCategory.objects.create(
            name="Archived Markets",
            is_active=False,
        )

        self.competition = Competition.objects.create(
            sport=self.football,
            name="Uganda Premier League",
            country_code="UG",
            is_verified=True,
        )

        self.kcca = Participant.objects.create(
            sport=self.football,
            kind=Participant.Kind.TEAM,
            name="KCCA FC",
            country_code="UG",
            is_verified=True,
        )
        self.vipers = Participant.objects.create(
            sport=self.football,
            kind=Participant.Kind.TEAM,
            name="Vipers SC",
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

        self.open_market = MarketCatalogService.create_market(
            sport=self.football,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question="Will KCCA FC beat Vipers SC?",
            description="Match result market.",
            status=Market.Status.OPEN,
            opens_at=self.now,
            closes_at=self.now + timedelta(days=1),
            is_featured=True,
            yes_label="KCCA FC",
            no_label="Vipers SC or Draw",
        )

        self.closed_market = MarketCatalogService.create_market(
            sport=self.football,
            category=self.category,
            scope_type=MarketScope.PARTICIPANT,
            sporting_event=self.event,
            participant=self.kcca,
            question="Will KCCA FC score first?",
            status=Market.Status.CLOSED,
            opens_at=self.now - timedelta(days=2),
            closes_at=self.now - timedelta(days=1),
        )

        self.draft_market = MarketCatalogService.create_market(
            sport=self.football,
            category=self.category,
            scope_type=MarketScope.CUSTOM,
            custom_subject="Uganda football",
            question=("Will a Ugandan club reach " "a continental final?"),
            status=Market.Status.DRAFT,
        )

    def test_market_list_defaults_to_open_markets(self):
        response = self.client.get(
            reverse("markets:market-list"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["count"],
            1,
        )
        self.assertEqual(
            response.data["results"][0]["id"],
            str(self.open_market.id),
        )

    def test_market_list_can_filter_public_status(self):
        response = self.client.get(
            reverse("markets:market-list"),
            {
                "status": Market.Status.CLOSED,
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["count"],
            1,
        )
        self.assertEqual(
            response.data["results"][0]["id"],
            str(self.closed_market.id),
        )

    def test_market_list_supports_catalog_filters(self):
        response = self.client.get(
            reverse("markets:market-list"),
            {
                "sport": str(self.football.id),
                "category": str(self.category.id),
                "scope_type": MarketScope.EVENT,
                "is_featured": "true",
                "search": "KCCA",
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["count"],
            1,
        )
        self.assertEqual(
            response.data["results"][0]["id"],
            str(self.open_market.id),
        )

    def test_market_detail_contains_subject_and_outcomes(self):
        response = self.client.get(
            reverse(
                "markets:market-detail",
                kwargs={
                    "market_id": self.open_market.id,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["sporting_event"]["id"],
            str(self.event.id),
        )
        self.assertEqual(
            [outcome["side"] for outcome in response.data["outcomes"]],
            [
                "YES",
                "NO",
            ],
        )
        self.assertEqual(
            [outcome["label"] for outcome in response.data["outcomes"]],
            [
                "KCCA FC",
                "Vipers SC or Draw",
            ],
        )

    def test_draft_market_is_not_publicly_accessible(self):
        response = self.client.get(
            reverse(
                "markets:market-detail",
                kwargs={
                    "market_id": self.draft_market.id,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_category_list_excludes_inactive_categories(self):
        response = self.client.get(
            reverse("markets:category-list"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        category_ids = {item["id"] for item in response.data["results"]}

        self.assertIn(
            str(self.category.id),
            category_ids,
        )
        self.assertNotIn(
            str(self.inactive_category.id),
            category_ids,
        )


class PublicResolvedMarketAPITests(APITestCase):
    def setUp(self):
        self.now = timezone.now()

        manage_permission = PermissionFactory(
            name="manage_market",
            resource="market",
            action="manage",
        )
        approve_permission = PermissionFactory(
            name="approve_market",
            resource="market",
            action="approve",
        )

        operations_role = RoleFactory(
            name="Market Operations Admin",
            display_name="Market Operations Admin",
        )
        approval_role = RoleFactory(
            name="Market Approval Admin",
            display_name="Market Approval Admin",
        )

        RolePermissionFactory(
            role=operations_role,
            permission=manage_permission,
        )
        RolePermissionFactory(
            role=approval_role,
            permission=approve_permission,
        )

        self.operations_user = UserFactory()
        self.approver_user = UserFactory()

        UserRoleFactory(
            user=self.operations_user,
            role=operations_role,
        )
        UserRoleFactory(
            user=self.approver_user,
            role=approval_role,
        )

        football = Sport.objects.create(
            name="Football",
            code="FOOTBALL",
        )
        category = MarketCategory.objects.create(
            name="Match Result",
        )
        competition = Competition.objects.create(
            sport=football,
            name="Uganda Premier League",
            country_code="UG",
            is_verified=True,
        )
        event = SportingEvent.objects.create(
            sport=football,
            competition=competition,
            event_type=SportingEvent.EventType.MATCH,
            name="KCCA FC vs Vipers SC",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

        market = MarketCatalogService.create_market(
            sport=football,
            category=category,
            scope_type=MarketScope.EVENT,
            sporting_event=event,
            question="Will KCCA FC beat Vipers SC?",
            description="Match result market.",
            rules=("Resolve YES if KCCA FC wins " "in regulation time."),
            resolution_source=("Official competition result"),
            resolution_criteria=("Use the verified final score."),
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=1),
            created_by=self.operations_user,
            yes_label="KCCA FC wins",
            no_label="Draw or Vipers SC",
        )

        market = MarketLifecycleService.submit(
            market_id=market.id,
            actor=self.operations_user,
            notes="Ready for review.",
        )
        market = MarketLifecycleService.approve(
            market_id=market.id,
            actor=self.approver_user,
            notes="Market verified.",
        )
        market = MarketLifecycleService.open(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading opened.",
        )
        market = MarketLifecycleService.close(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading completed.",
        )

        self.winner = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        self.resolved_market = MarketResolutionService.resolve(
            market_id=market.id,
            actor=self.approver_user,
            winning_outcome_id=self.winner.id,
            notes="Official result confirmed.",
            evidence=("Official match report: " "KCCA FC 2-1 Vipers SC."),
        )

    def test_resolved_market_exposes_winning_outcome(
        self,
    ):
        response = self.client.get(
            reverse(
                "markets:market-detail",
                kwargs={
                    "market_id": (self.resolved_market.id),
                },
            )
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
            str(self.winner.id),
        )

        outcome_ids = {outcome["id"] for outcome in response.data["outcomes"]}

        self.assertIn(
            str(self.winner.id),
            outcome_ids,
        )
        self.assertNotIn(
            "resolution_evidence",
            response.data,
        )
        self.assertNotIn(
            "resolution_notes",
            response.data,
        )

    def test_resolved_market_shows_is_settled_only_after_settlement(self):
        detail_url = reverse(
            "markets:market-detail",
            kwargs={"market_id": self.resolved_market.id},
        )

        before = self.client.get(detail_url)
        self.assertFalse(before.data["is_settled"])
        self.assertFalse(before.data["is_refunded"])

        MarketSettlementService.settle_market(
            market_id=self.resolved_market.id,
            actor=self.approver_user,
        )

        after = self.client.get(detail_url)
        self.assertTrue(after.data["is_settled"])
        self.assertFalse(after.data["is_refunded"])

    def test_voided_market_shows_is_refunded_only_after_refund(self):
        event = SportingEvent.objects.create(
            sport=self.resolved_market.sport,
            competition=self.resolved_market.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="KCCA FC vs Vipers SC (void fixture)",
            starts_at=self.now + timedelta(days=3),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )
        market = MarketCatalogService.create_market(
            sport=self.resolved_market.sport,
            category=self.resolved_market.category,
            scope_type=MarketScope.EVENT,
            sporting_event=event,
            question="Will the fixture be postponed?",
            description="Void/refund visibility fixture.",
            rules="Void if the fixture is called off.",
            resolution_source="Official competition result",
            resolution_criteria="Use the verified final score.",
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=1),
            created_by=self.operations_user,
            yes_label="Postponed",
            no_label="Not postponed",
        )
        market = MarketLifecycleService.submit(
            market_id=market.id, actor=self.operations_user, notes="Ready."
        )
        market = MarketLifecycleService.approve(
            market_id=market.id, actor=self.approver_user, notes="Approved."
        )
        market = MarketLifecycleService.open(
            market_id=market.id, actor=self.approver_user, notes="Opened."
        )
        voided_market = MarketResolutionService.void(
            market_id=market.id,
            actor=self.approver_user,
            notes="Fixture cancelled by the league.",
            evidence="League statement confirming cancellation.",
        )

        detail_url = reverse(
            "markets:market-detail",
            kwargs={"market_id": voided_market.id},
        )

        before = self.client.get(detail_url)
        self.assertFalse(before.data["is_refunded"])
        self.assertFalse(before.data["is_settled"])

        MarketVoidRefundService.refund_void_market(
            market_id=voided_market.id,
            actor=self.approver_user,
        )

        after = self.client.get(detail_url)
        self.assertTrue(after.data["is_refunded"])
        self.assertFalse(after.data["is_settled"])

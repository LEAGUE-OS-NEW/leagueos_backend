from datetime import timedelta
from decimal import Decimal

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
    MarketPosition,
    MarketScope,
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


class MarketPositionHistoryAPITests(APITestCase):
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
        self.owner = UserFactory(
            is_verified=True,
        )
        self.other_user = UserFactory(
            is_verified=True,
        )
        self.read_only_user = UserFactory(
            is_verified=False,
        )
        self.empty_user = UserFactory(
            is_verified=True,
        )

        UserRoleFactory(
            user=self.operations_user,
            role=operations_role,
        )
        UserRoleFactory(
            user=self.approver_user,
            role=approval_role,
        )

        self.sport = Sport.objects.create(
            name="Football",
            code="FOOTBALL",
        )
        self.category = MarketCategory.objects.create(
            name="Match Result",
        )
        self.competition = Competition.objects.create(
            sport=self.sport,
            name="Uganda Premier League",
            country_code="UG",
            is_verified=True,
        )
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="KCCA FC vs Vipers SC",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

        self.market = self.open_market(self.create_market())
        self.yes_outcome = self.market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )
        self.no_outcome = self.market.outcomes.get(
            side=MarketOutcome.Side.NO,
        )

    def authenticate(self, user):
        self.client.force_authenticate(
            user=user,
        )

    def list_url(self):
        return reverse(
            "markets:market-position-list",
        )

    def detail_url(self, position):
        return reverse(
            "markets:market-position-detail",
            kwargs={
                "position_id": position.id,
            },
        )

    def create_market(self):
        return MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question="Will KCCA FC win?",
            description="Match prediction market.",
            rules=("Resolve using the official " "competition result."),
            resolution_source=("Official competition result"),
            resolution_criteria=("Use the verified final score."),
            status=Market.Status.DRAFT,
            opens_at=(self.now - timedelta(hours=1)),
            closes_at=(self.now + timedelta(hours=1)),
            created_by=self.operations_user,
            yes_label="Yes",
            no_label="No",
        )

    def open_market(self, market):
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

        return MarketLifecycleService.open(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading opened.",
        )

    def create_position(
        self,
        *,
        user=None,
        outcome=None,
        quantity=Decimal("10.0000"),
        reserved_quantity=Decimal("0.0000"),
        average_entry_price=Decimal("0.55000"),
        total_cost=Decimal("5.5000"),
        realized_pnl=Decimal("0.0000"),
    ):
        return MarketPosition.objects.create(
            user=user or self.owner,
            market=self.market,
            outcome=outcome or self.yes_outcome,
            quantity=quantity,
            reserved_quantity=reserved_quantity,
            average_entry_price=(average_entry_price),
            total_cost=total_cost,
            realized_pnl=realized_pnl,
        )

    def test_position_list_requires_authentication(
        self,
    ):
        response = self.client.get(
            self.list_url(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_position_list_only_returns_users_positions(
        self,
    ):
        first_position = self.create_position(
            outcome=self.yes_outcome,
        )
        second_position = self.create_position(
            outcome=self.no_outcome,
            quantity=Decimal("4.0000"),
            average_entry_price=Decimal("0.42000"),
            total_cost=Decimal("1.6800"),
        )
        other_position = self.create_position(
            user=self.other_user,
            outcome=self.yes_outcome,
        )
        self.authenticate(self.owner)

        response = self.client.get(
            self.list_url(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["count"],
            2,
        )

        returned_ids = {item["id"] for item in response.data["results"]}

        self.assertEqual(
            returned_ids,
            {
                str(first_position.id),
                str(second_position.id),
            },
        )
        self.assertNotIn(
            str(other_position.id),
            returned_ids,
        )

    def test_position_list_is_paginated_and_newest_first(
        self,
    ):
        first_position = self.create_position(
            outcome=self.yes_outcome,
        )
        second_position = self.create_position(
            outcome=self.no_outcome,
            quantity=Decimal("4.0000"),
            average_entry_price=Decimal("0.42000"),
            total_cost=Decimal("1.6800"),
        )
        self.authenticate(self.owner)

        response = self.client.get(
            self.list_url(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertIn(
            "count",
            response.data,
        )
        self.assertIn(
            "next",
            response.data,
        )
        self.assertIn(
            "previous",
            response.data,
        )
        self.assertIn(
            "results",
            response.data,
        )
        self.assertEqual(
            response.data["results"][0]["id"],
            str(second_position.id),
        )
        self.assertEqual(
            response.data["results"][1]["id"],
            str(first_position.id),
        )

    def test_position_list_can_be_empty(self):
        self.authenticate(self.empty_user)

        response = self.client.get(
            self.list_url(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["count"],
            0,
        )
        self.assertEqual(
            response.data["results"],
            [],
        )

    def test_position_detail_requires_authentication(
        self,
    ):
        position = self.create_position()

        response = self.client.get(
            self.detail_url(position),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_owner_can_retrieve_position_detail(
        self,
    ):
        position = self.create_position(
            realized_pnl=Decimal("1.2500"),
            reserved_quantity=Decimal("3.0000"),
        )
        self.authenticate(self.owner)

        response = self.client.get(
            self.detail_url(position),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["id"],
            str(position.id),
        )
        self.assertEqual(
            response.data["user"],
            str(self.owner.id),
        )
        self.assertEqual(
            response.data["market"],
            str(self.market.id),
        )
        self.assertEqual(
            response.data["outcome"],
            str(self.yes_outcome.id),
        )
        self.assertEqual(
            response.data["quantity"],
            "10.0000",
        )
        self.assertEqual(
            response.data["reserved_quantity"],
            "3.0000",
        )
        self.assertEqual(
            response.data["average_entry_price"],
            "0.55000",
        )
        self.assertEqual(
            response.data["total_cost"],
            "5.5000",
        )
        self.assertEqual(
            response.data["realized_pnl"],
            "1.2500",
        )

    def test_another_users_position_returns_404(
        self,
    ):
        position = self.create_position()
        self.authenticate(self.other_user)

        response = self.client.get(
            self.detail_url(position),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_user_can_read_positions_without_trading_permission(
        self,
    ):
        position = self.create_position(
            user=self.read_only_user,
        )
        self.authenticate(self.read_only_user)

        list_response = self.client.get(
            self.list_url(),
        )
        detail_response = self.client.get(
            self.detail_url(position),
        )

        self.assertEqual(
            list_response.status_code,
            status.HTTP_200_OK,
            list_response.data,
        )
        self.assertEqual(
            list_response.data["count"],
            1,
        )
        self.assertEqual(
            list_response.data["results"][0]["id"],
            str(position.id),
        )

        self.assertEqual(
            detail_response.status_code,
            status.HTTP_200_OK,
            detail_response.data,
        )
        self.assertEqual(
            detail_response.data["id"],
            str(position.id),
        )

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
    MarketOrder,
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
from markets.services.participation_service import (
    MarketParticipationService,
)
from markets.tests.eligibility_test_support import make_market_eligible
from markets.tests.wallet_test_support import (
    fund_market_wallet,
)
from sports.models import (
    Competition,
    Sport,
    SportingEvent,
)


class MarketOrderHistoryFixtureMixin:
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
        participate_permission = PermissionFactory(
            name="participate_market",
            resource="market",
            action="participate",
        )

        operations_role = RoleFactory(
            name="Market Operations Admin",
            display_name="Market Operations Admin",
        )
        approval_role = RoleFactory(
            name="Market Approval Admin",
            display_name="Market Approval Admin",
        )
        participant_role = RoleFactory(
            name="Verified Market User",
            display_name="Verified Market User",
        )

        RolePermissionFactory(
            role=operations_role,
            permission=manage_permission,
        )
        RolePermissionFactory(
            role=approval_role,
            permission=approve_permission,
        )
        RolePermissionFactory(
            role=participant_role,
            permission=participate_permission,
        )

        self.operations_user = UserFactory()
        self.approver_user = UserFactory()
        self.owner = UserFactory(
            is_verified=True,
        )
        self.other_participant = UserFactory(
            is_verified=True,
        )
        self.read_only_user = UserFactory(
            is_verified=False,
        )
        self.empty_user = UserFactory(
            is_verified=True,
        )
        make_market_eligible(self.owner)
        make_market_eligible(self.other_participant)

        fund_market_wallet(self.owner)
        fund_market_wallet(self.other_participant)

        UserRoleFactory(
            user=self.operations_user,
            role=operations_role,
        )
        UserRoleFactory(
            user=self.approver_user,
            role=approval_role,
        )
        UserRoleFactory(
            user=self.owner,
            role=participant_role,
        )
        UserRoleFactory(
            user=self.other_participant,
            role=participant_role,
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
        self.outcome = self.market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

    def authenticate(self, user):
        self.client.force_authenticate(
            user=user,
        )

    def list_url(self):
        return reverse(
            "markets:market-order-list",
        )

    def detail_url(self, order):
        return reverse(
            "markets:market-order-detail",
            kwargs={
                "order_id": order.id,
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

    def create_order(
        self,
        *,
        user=None,
        side=MarketOrder.Side.BUY,
        quantity=Decimal("10.0000"),
        limit_price=Decimal("0.55000"),
    ):
        make_market_eligible(user or self.owner)
        return MarketParticipationService.place_order(
            user=user or self.owner,
            market_id=self.market.id,
            outcome_id=self.outcome.id,
            side=side,
            quantity=quantity,
            limit_price=limit_price,
        )

    def create_read_only_order(self):
        return MarketOrder.objects.create(
            user=self.read_only_user,
            market=self.market,
            outcome=self.outcome,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("5.0000"),
            limit_price=Decimal("0.60000"),
            filled_quantity=Decimal("0.0000"),
            status=MarketOrder.Status.OPEN,
        )


class MarketOrderHistoryAPITests(
    MarketOrderHistoryFixtureMixin,
    APITestCase,
):

    def test_order_list_requires_authentication(
        self,
    ):
        response = self.client.get(
            self.list_url(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_order_list_only_returns_users_orders(
        self,
    ):
        first_order = self.create_order(
            quantity=Decimal("10.0000"),
        )
        MarketPosition.objects.create(
            user=self.owner,
            market=self.market,
            outcome=self.outcome,
            quantity=Decimal("4.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("1.6000"),
        )
        second_order = self.create_order(
            side=MarketOrder.Side.SELL,
            quantity=Decimal("4.0000"),
        )
        other_order = self.create_order(
            user=self.other_participant,
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
                str(first_order.id),
                str(second_order.id),
            },
        )
        self.assertNotIn(
            str(other_order.id),
            returned_ids,
        )

    def test_order_list_is_paginated_and_newest_first(
        self,
    ):
        first_order = self.create_order(
            quantity=Decimal("10.0000"),
        )
        second_order = self.create_order(
            quantity=Decimal("12.0000"),
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
            str(second_order.id),
        )
        self.assertEqual(
            response.data["results"][1]["id"],
            str(first_order.id),
        )

    def test_order_list_can_be_empty(self):
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

    def test_order_detail_requires_authentication(
        self,
    ):
        order = self.create_order()

        response = self.client.get(
            self.detail_url(order),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_owner_can_retrieve_order_detail(self):
        order = self.create_order()
        self.authenticate(self.owner)

        response = self.client.get(
            self.detail_url(order),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["id"],
            str(order.id),
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
            str(self.outcome.id),
        )
        self.assertEqual(
            response.data["status"],
            MarketOrder.Status.OPEN,
        )
        self.assertEqual(
            response.data["quantity"],
            "10.0000",
        )
        self.assertEqual(
            response.data["limit_price"],
            "0.55000",
        )

    def test_another_users_order_detail_returns_404(
        self,
    ):
        order = self.create_order()
        self.authenticate(self.other_participant)

        response = self.client.get(
            self.detail_url(order),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_user_can_read_history_without_trading_permission(
        self,
    ):
        order = self.create_read_only_order()
        self.authenticate(self.read_only_user)

        list_response = self.client.get(
            self.list_url(),
        )
        detail_response = self.client.get(
            self.detail_url(order),
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
            str(order.id),
        )

        self.assertEqual(
            detail_response.status_code,
            status.HTTP_200_OK,
            detail_response.data,
        )
        self.assertEqual(
            detail_response.data["id"],
            str(order.id),
        )

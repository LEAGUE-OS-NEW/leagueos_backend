from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from authentication.models import UserRole
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
from markets.services.fill_service import (
    MarketFillService,
)
from markets.services.lifecycle_service import (
    MarketLifecycleService,
)
from markets.services.participation_service import (
    MarketParticipationService,
)
from markets.tests.wallet_test_support import (
    fund_market_wallet,
)
from sports.models import (
    Competition,
    Sport,
    SportingEvent,
)


class MarketFillHistoryAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
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
        self.participant_role = RoleFactory(
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
            role=self.participant_role,
            permission=participate_permission,
        )

        self.operations_user = UserFactory()
        self.approver_user = UserFactory()

        self.buyer = self.create_participant()
        self.seller = self.create_participant()
        self.other_buyer = self.create_participant()
        self.other_seller = self.create_participant()
        self.unrelated_user = self.create_participant()

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
        self.outcome = self.market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        self.create_position(
            user=self.seller,
            quantity=Decimal("50.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("20.0000"),
        )
        self.create_position(
            user=self.other_seller,
            quantity=Decimal("50.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("20.0000"),
        )

        self.fill = self.execute_fill(
            buyer=self.buyer,
            seller=self.seller,
            quantity=Decimal("4.0000"),
            price=Decimal("0.55000"),
        )
        self.other_fill = self.execute_fill(
            buyer=self.other_buyer,
            seller=self.other_seller,
            quantity=Decimal("3.0000"),
            price=Decimal("0.50000"),
        )

    def create_participant(self):
        user = UserFactory(
            is_verified=True,
        )
        UserRoleFactory(
            user=user,
            role=self.participant_role,
        )
        fund_market_wallet(user)
        return user

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
        user,
        quantity,
        average_entry_price,
        total_cost,
    ):
        position = MarketPosition(
            user=user,
            market=self.market,
            outcome=self.outcome,
            quantity=quantity,
            average_entry_price=(average_entry_price),
            total_cost=total_cost,
            realized_pnl=Decimal("0.0000"),
        )
        position.full_clean()
        position.save()
        return position

    def create_order(
        self,
        *,
        user,
        side,
        quantity,
        limit_price,
    ):
        return MarketParticipationService.place_order(
            user=user,
            market_id=self.market.id,
            outcome_id=self.outcome.id,
            side=side,
            quantity=quantity,
            limit_price=limit_price,
        )

    def execute_fill(
        self,
        *,
        buyer,
        seller,
        quantity,
        price,
    ):
        buy_order = self.create_order(
            user=buyer,
            side=MarketOrder.Side.BUY,
            quantity=quantity,
            limit_price=Decimal("0.70000"),
        )
        sell_order = self.create_order(
            user=seller,
            side=MarketOrder.Side.SELL,
            quantity=quantity,
            limit_price=Decimal("0.40000"),
        )

        return MarketFillService.execute_fill(
            execution_reference=uuid4(),
            buy_order_id=buy_order.id,
            sell_order_id=sell_order.id,
            maker_order_id=sell_order.id,
            taker_order_id=buy_order.id,
            quantity=quantity,
            price=price,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def test_unauthenticated_user_cannot_list_fills(
        self,
    ):
        response = self.client.get(reverse("markets:market-fill-list"))

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_buyer_list_contains_only_participating_fills(
        self,
    ):
        self.authenticate(self.buyer)

        response = self.client.get(reverse("markets:market-fill-list"))

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        returned_ids = {item["id"] for item in response.data["results"]}

        self.assertEqual(
            returned_ids,
            {str(self.fill.id)},
        )
        self.assertNotIn(
            str(self.other_fill.id),
            returned_ids,
        )

    def test_seller_can_list_fill(
        self,
    ):
        self.authenticate(self.seller)

        response = self.client.get(reverse("markets:market-fill-list"))

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
            str(self.fill.id),
        )

    def test_fill_list_is_paginated_and_newest_first(
        self,
    ):
        second_fill = self.execute_fill(
            buyer=self.buyer,
            seller=self.seller,
            quantity=Decimal("2.0000"),
            price=Decimal("0.60000"),
        )
        self.authenticate(self.buyer)

        response = self.client.get(reverse("markets:market-fill-list"))

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertIn("count", response.data)
        self.assertIn("next", response.data)
        self.assertIn("previous", response.data)
        self.assertIn("results", response.data)

        returned_ids = [item["id"] for item in response.data["results"]]

        self.assertEqual(
            returned_ids,
            [
                str(second_fill.id),
                str(self.fill.id),
            ],
        )

    def test_unrelated_user_receives_empty_fill_list(
        self,
    ):
        self.authenticate(self.unrelated_user)

        response = self.client.get(reverse("markets:market-fill-list"))

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["count"],
            0,
        )
        self.assertEqual(
            response.data["results"],
            [],
        )

    def test_unauthenticated_user_cannot_retrieve_fill(
        self,
    ):
        response = self.client.get(
            reverse(
                "markets:market-fill-detail",
                kwargs={
                    "fill_id": self.fill.id,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_buyer_can_retrieve_fill_detail(
        self,
    ):
        self.authenticate(self.buyer)

        response = self.client.get(
            reverse(
                "markets:market-fill-detail",
                kwargs={
                    "fill_id": self.fill.id,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["id"],
            str(self.fill.id),
        )
        self.assertEqual(
            response.data["market"],
            self.market.id,
        )
        self.assertEqual(
            response.data["outcome"],
            self.outcome.id,
        )
        self.assertEqual(
            response.data["buy_order"],
            self.fill.buy_order_id,
        )
        self.assertEqual(
            response.data["sell_order"],
            self.fill.sell_order_id,
        )
        self.assertEqual(
            response.data["maker_order"],
            self.fill.maker_order_id,
        )
        self.assertEqual(
            response.data["taker_order"],
            self.fill.taker_order_id,
        )
        self.assertEqual(
            response.data["quantity"],
            "4.0000",
        )
        self.assertEqual(
            response.data["price"],
            "0.55000",
        )
        self.assertIn(
            "created_at",
            response.data,
        )
        self.assertNotIn(
            "execution_reference",
            response.data,
        )

    def test_seller_can_retrieve_fill_detail(
        self,
    ):
        self.authenticate(self.seller)

        response = self.client.get(
            reverse(
                "markets:market-fill-detail",
                kwargs={
                    "fill_id": self.fill.id,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["id"],
            str(self.fill.id),
        )

    def test_unrelated_fill_detail_returns_not_found(
        self,
    ):
        self.authenticate(self.unrelated_user)

        response = self.client.get(
            reverse(
                "markets:market-fill-detail",
                kwargs={
                    "fill_id": self.fill.id,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_historical_fills_remain_readable_after_eligibility_loss(
        self,
    ):
        self.buyer.is_verified = False
        self.buyer.save(
            update_fields=[
                "is_verified",
            ]
        )
        UserRole.objects.filter(
            user=self.buyer,
        ).delete()

        self.authenticate(self.buyer)

        list_response = self.client.get(reverse("markets:market-fill-list"))
        detail_response = self.client.get(
            reverse(
                "markets:market-fill-detail",
                kwargs={
                    "fill_id": self.fill.id,
                },
            )
        )

        self.assertEqual(
            list_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            list_response.data["count"],
            1,
        )
        self.assertEqual(
            detail_response.status_code,
            status.HTTP_200_OK,
        )

    def test_fill_list_endpoint_is_read_only(
        self,
    ):
        self.authenticate(self.buyer)

        response = self.client.post(
            reverse("markets:market-fill-list"),
            {
                "quantity": "1.0000",
                "price": "0.50000",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

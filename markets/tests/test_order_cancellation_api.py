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


class MarketOrderCancellationAPITests(APITestCase):
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
        self.unverified_owner = UserFactory(
            is_verified=False,
        )
        self.outsider = UserFactory(
            is_verified=True,
        )

        fund_market_wallet(self.owner)

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
        UserRoleFactory(
            user=self.unverified_owner,
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
            event_type=(SportingEvent.EventType.MATCH),
            name="KCCA FC vs Vipers SC",
            starts_at=(self.now + timedelta(days=2)),
            status=(SportingEvent.Status.SCHEDULED),
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

    def create_order(self, *, user=None):
        make_market_eligible(user or self.owner)
        return MarketParticipationService.place_order(
            user=user or self.owner,
            market_id=self.market.id,
            outcome_id=self.outcome.id,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("10.0000"),
            limit_price=Decimal("0.55000"),
        )

    def cancel_url(self, order):
        return reverse(
            "markets:market-order-cancel",
            kwargs={
                "order_id": order.id,
            },
        )

    def test_cancellation_requires_authentication(
        self,
    ):
        order = self.create_order()

        response = self.client.post(
            self.cancel_url(order),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        order.refresh_from_db()

        self.assertEqual(
            order.status,
            MarketOrder.Status.OPEN,
        )

    def test_owner_can_cancel_open_order(self):
        order = self.create_order()
        self.authenticate(self.owner)

        response = self.client.post(
            self.cancel_url(order),
            {},
            format="json",
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
            response.data["status"],
            MarketOrder.Status.CANCELLED,
        )
        self.assertEqual(
            response.data["filled_quantity"],
            "0.0000",
        )
        self.assertIsNone(
            response.data["average_fill_price"],
        )

        order.refresh_from_db()

        self.assertEqual(
            order.status,
            MarketOrder.Status.CANCELLED,
        )

    def test_owner_can_cancel_partially_filled_order(
        self,
    ):
        order = self.create_order()
        order.status = MarketOrder.Status.PARTIALLY_FILLED
        order.filled_quantity = Decimal("4.0000")
        order.average_fill_price = Decimal("0.54000")
        order.save(
            update_fields=[
                "status",
                "filled_quantity",
                "average_fill_price",
                "updated_at",
            ]
        )
        self.authenticate(self.owner)

        response = self.client.post(
            self.cancel_url(order),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["status"],
            MarketOrder.Status.CANCELLED,
        )
        self.assertEqual(
            response.data["filled_quantity"],
            "4.0000",
        )
        self.assertEqual(
            response.data["average_fill_price"],
            "0.54000",
        )

    def test_another_users_order_returns_not_found(
        self,
    ):
        order = self.create_order()
        self.authenticate(self.other_participant)

        response = self.client.post(
            self.cancel_url(order),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

        order.refresh_from_db()

        self.assertEqual(
            order.status,
            MarketOrder.Status.OPEN,
        )

    def test_owner_without_permission_is_forbidden(
        self,
    ):
        order = MarketOrder.objects.create(
            user=self.outsider,
            market=self.market,
            outcome=self.outcome,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("10.0000"),
            limit_price=Decimal("0.55000"),
            filled_quantity=Decimal("0.0000"),
            status=MarketOrder.Status.OPEN,
        )
        self.authenticate(self.outsider)

        response = self.client.post(
            self.cancel_url(order),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        order.refresh_from_db()

        self.assertEqual(
            order.status,
            MarketOrder.Status.OPEN,
        )

    def test_unverified_owner_is_forbidden(self):
        order = MarketOrder.objects.create(
            user=self.unverified_owner,
            market=self.market,
            outcome=self.outcome,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("10.0000"),
            limit_price=Decimal("0.55000"),
            filled_quantity=Decimal("0.0000"),
            status=MarketOrder.Status.OPEN,
        )
        self.authenticate(self.unverified_owner)

        response = self.client.post(
            self.cancel_url(order),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        order.refresh_from_db()

        self.assertEqual(
            order.status,
            MarketOrder.Status.OPEN,
        )

    def test_filled_order_cannot_be_cancelled(self):
        order = self.create_order()
        order.status = MarketOrder.Status.FILLED
        order.filled_quantity = order.quantity
        order.average_fill_price = Decimal("0.55000")
        order.save(
            update_fields=[
                "status",
                "filled_quantity",
                "average_fill_price",
                "updated_at",
            ]
        )
        self.authenticate(self.owner)

        response = self.client.post(
            self.cancel_url(order),
            {},
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

        order.refresh_from_db()

        self.assertEqual(
            order.status,
            MarketOrder.Status.FILLED,
        )

    def test_cancelled_order_cannot_be_cancelled_again(
        self,
    ):
        order = self.create_order()
        order.status = MarketOrder.Status.CANCELLED
        order.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )
        self.authenticate(self.owner)

        response = self.client.post(
            self.cancel_url(order),
            {},
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

    def test_cancellation_does_not_create_position(
        self,
    ):
        order = self.create_order()
        self.authenticate(self.owner)

        response = self.client.post(
            self.cancel_url(order),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertFalse(self.owner.market_positions.exists())

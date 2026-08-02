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
from markets.tests.wallet_test_support import (
    fund_market_wallet,
)
from sports.models import (
    Competition,
    Sport,
    SportingEvent,
)


class MarketParticipationAPITests(APITestCase):
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
        self.participant = UserFactory(
            is_verified=True,
        )
        self.unverified_participant = UserFactory(
            is_verified=False,
        )
        self.outsider = UserFactory(
            is_verified=True,
        )

        fund_market_wallet(self.participant)

        UserRoleFactory(
            user=self.operations_user,
            role=operations_role,
        )
        UserRoleFactory(
            user=self.approver_user,
            role=approval_role,
        )
        UserRoleFactory(
            user=self.participant,
            role=participant_role,
        )
        UserRoleFactory(
            user=self.unverified_participant,
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

    def authenticate(self, user):
        self.client.force_authenticate(
            user=user,
        )

    def create_market(
        self,
        *,
        question="Will KCCA FC win?",
    ):
        return MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question=question,
            description="Match prediction market.",
            rules=("Resolve using the official " "competition result."),
            resolution_source=("Official competition result"),
            resolution_criteria=("Use the verified final score."),
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=1),
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

    def order_url(self, market):
        return reverse(
            "markets:market-order-create",
            kwargs={
                "market_id": market.id,
            },
        )

    def order_payload(
        self,
        market,
        **overrides,
    ):
        outcome = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        payload = {
            "outcome_id": str(outcome.id),
            "side": MarketOrder.Side.BUY,
            "quantity": "10.0000",
            "limit_price": "0.55000",
        }
        payload.update(overrides)

        return payload

    def test_order_requires_authentication(self):
        market = self.open_market(self.create_market())

        response = self.client.post(
            self.order_url(market),
            self.order_payload(market),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )
        self.assertFalse(MarketOrder.objects.exists())

    def test_verified_user_can_place_order(self):
        market = self.open_market(self.create_market())
        outcome = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )
        self.authenticate(self.participant)

        response = self.client.post(
            self.order_url(market),
            self.order_payload(market),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )
        self.assertEqual(
            response.data["user"],
            str(self.participant.id),
        )
        self.assertEqual(
            response.data["market"],
            str(market.id),
        )
        self.assertEqual(
            response.data["outcome"],
            str(outcome.id),
        )
        self.assertEqual(
            response.data["side"],
            MarketOrder.Side.BUY,
        )
        self.assertEqual(
            response.data["quantity"],
            "10.0000",
        )
        self.assertEqual(
            response.data["limit_price"],
            "0.55000",
        )
        self.assertEqual(
            response.data["filled_quantity"],
            "0.0000",
        )
        self.assertIsNone(
            response.data["average_fill_price"],
        )
        self.assertEqual(
            response.data["status"],
            MarketOrder.Status.OPEN,
        )
        self.assertIsNotNone(
            response.data["created_at"],
        )

        order = MarketOrder.objects.get(
            id=response.data["id"],
        )

        self.assertEqual(
            order.user,
            self.participant,
        )

    def test_order_requires_permission(self):
        market = self.open_market(self.create_market())
        self.authenticate(self.outsider)

        response = self.client.post(
            self.order_url(market),
            self.order_payload(market),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertFalse(
            MarketOrder.objects.filter(
                user=self.outsider,
            ).exists()
        )

    def test_order_requires_verified_user(self):
        market = self.open_market(self.create_market())
        self.authenticate(self.unverified_participant)

        response = self.client.post(
            self.order_url(market),
            self.order_payload(market),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertFalse(
            MarketOrder.objects.filter(
                user=self.unverified_participant,
            ).exists()
        )

    def test_order_requires_open_market(self):
        market = self.create_market()
        self.authenticate(self.participant)

        response = self.client.post(
            self.order_url(market),
            self.order_payload(market),
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

    def test_outcome_must_belong_to_market(self):
        market = self.open_market(self.create_market(question="Will KCCA FC win?"))
        other_market = self.open_market(self.create_market(question="Will Vipers SC score?"))
        other_outcome = other_market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )
        self.authenticate(self.participant)

        response = self.client.post(
            self.order_url(market),
            self.order_payload(
                market,
                outcome_id=str(other_outcome.id),
            ),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            response.data,
        )
        self.assertIn(
            "outcome",
            response.data,
        )

    def test_order_requires_complete_payload(self):
        market = self.open_market(self.create_market())
        self.authenticate(self.participant)

        response = self.client.post(
            self.order_url(market),
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            response.data,
        )
        self.assertIn(
            "outcome_id",
            response.data,
        )
        self.assertIn(
            "side",
            response.data,
        )
        self.assertIn(
            "quantity",
            response.data,
        )
        self.assertIn(
            "limit_price",
            response.data,
        )

    def test_order_rejects_invalid_numeric_values(
        self,
    ):
        market = self.open_market(self.create_market())
        self.authenticate(self.participant)

        response = self.client.post(
            self.order_url(market),
            self.order_payload(
                market,
                quantity="0.0000",
                limit_price="1.00000",
            ),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            response.data,
        )
        self.assertIn(
            "quantity",
            response.data,
        )
        self.assertIn(
            "limit_price",
            response.data,
        )

    def test_sell_order_can_be_created(self):
        market = self.open_market(self.create_market())
        self.authenticate(self.participant)

        response = self.client.post(
            self.order_url(market),
            self.order_payload(
                market,
                side=MarketOrder.Side.SELL,
            ),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )
        self.assertEqual(
            response.data["side"],
            MarketOrder.Side.SELL,
        )

    def test_order_does_not_create_position(self):
        market = self.open_market(self.create_market())
        self.authenticate(self.participant)

        response = self.client.post(
            self.order_url(market),
            self.order_payload(market),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )
        self.assertFalse(self.participant.market_positions.exists())

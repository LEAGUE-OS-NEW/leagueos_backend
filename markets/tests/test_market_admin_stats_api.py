from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

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
    MarketFill,
    MarketOrder,
    MarketOutcome,
    MarketScope,
)
from markets.services.catalog_service import (
    MarketCatalogService,
)
from sports.models import (
    Competition,
    Sport,
    SportingEvent,
)


class MarketAdminStatsAPITests(APITestCase):
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
        RolePermissionFactory(
            role=self.operations_role,
            permission=self.manage_permission,
        )

        self.operations_user = UserFactory()
        UserRoleFactory(
            user=self.operations_user,
            role=self.operations_role,
        )

        self.outsider_user = UserFactory()

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

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def create_event(self, name):
        return SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name=name,
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

    def create_market(self, *, event, question, status=Market.Status.OPEN):
        return MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=event,
            question=question,
            rules="Official result.",
            resolution_source="Official result",
            resolution_criteria="Verified final score.",
            status=status,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(days=1),
        )

    def create_fill(self, market, quantity, price):
        outcome = market.outcomes.get(side=MarketOutcome.Side.YES)
        buyer = UserFactory()
        seller = UserFactory()

        buy_order = MarketOrder.objects.create(
            user=buyer,
            market=market,
            outcome=outcome,
            side=MarketOrder.Side.BUY,
            quantity=quantity,
            limit_price=price,
            filled_quantity=quantity,
            average_fill_price=price,
            status=MarketOrder.Status.FILLED,
        )
        sell_order = MarketOrder.objects.create(
            user=seller,
            market=market,
            outcome=outcome,
            side=MarketOrder.Side.SELL,
            quantity=quantity,
            limit_price=price,
            filled_quantity=quantity,
            average_fill_price=price,
            status=MarketOrder.Status.FILLED,
        )
        return MarketFill.objects.create(
            execution_reference=uuid4(),
            market=market,
            outcome=outcome,
            buy_order=buy_order,
            sell_order=sell_order,
            maker_order=buy_order,
            taker_order=sell_order,
            quantity=quantity,
            price=price,
        )

    def test_missing_market_ids_returns_400(self):
        self.authenticate(self.operations_user)

        response = self.client.get(reverse("markets:admin-market-stats"))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("market_ids", response.data)

    def test_invalid_market_id_format_returns_400(self):
        self.authenticate(self.operations_user)

        response = self.client.get(
            reverse("markets:admin-market-stats"),
            {"market_ids": "not-a-uuid"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_market_id_is_silently_omitted(self):
        self.authenticate(self.operations_user)

        response = self.client.get(
            reverse("markets:admin-market-stats"),
            {"market_ids": str(uuid4())},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["markets"], [])

    def test_market_with_zero_fills_included_with_zero_stats(self):
        self.authenticate(self.operations_user)
        market = self.create_market(
            event=self.create_event("KCCA FC vs Vipers SC"),
            question="Will KCCA FC beat Vipers SC?",
        )

        response = self.client.get(
            reverse("markets:admin-market-stats"),
            {"market_ids": str(market.id)},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["markets"]), 1)
        entry = response.data["markets"][0]
        self.assertEqual(entry["market_id"], str(market.id))
        self.assertEqual(Decimal(entry["total_volume_ugx"]), Decimal("0.00"))
        self.assertEqual(entry["fill_count"], 0)

    def test_market_with_multiple_fills_aggregates_correctly(self):
        self.authenticate(self.operations_user)
        market = self.create_market(
            event=self.create_event("Express FC vs SC Villa"),
            question="Will Express FC beat SC Villa?",
        )

        fills = [
            (Decimal("100.0000"), Decimal("0.60000")),
            (Decimal("50.0000"), Decimal("0.45000")),
            (Decimal("25.0000"), Decimal("0.30000")),
        ]
        expected_volume = Decimal("0")
        for quantity, price in fills:
            self.create_fill(market, quantity, price)
            expected_volume += quantity * price

        response = self.client.get(
            reverse("markets:admin-market-stats"),
            {"market_ids": str(market.id)},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entry = response.data["markets"][0]
        self.assertEqual(entry["fill_count"], len(fills))
        self.assertEqual(
            Decimal(entry["total_volume_ugx"]),
            expected_volume.quantize(Decimal("0.01")),
        )

    def test_multiple_markets_do_not_cross_contaminate(self):
        self.authenticate(self.operations_user)
        market_a = self.create_market(
            event=self.create_event("KOBS vs Heathens"),
            question="Will KOBS beat Heathens?",
        )
        market_b = self.create_market(
            event=self.create_event("City Oilers vs KIU Titans"),
            question="Will City Oilers beat KIU Titans?",
        )

        self.create_fill(market_a, Decimal("10.0000"), Decimal("0.50000"))
        self.create_fill(market_b, Decimal("20.0000"), Decimal("0.25000"))
        self.create_fill(market_b, Decimal("20.0000"), Decimal("0.25000"))

        response = self.client.get(
            reverse("markets:admin-market-stats"),
            {"market_ids": f"{market_a.id},{market_b.id}"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_id = {item["market_id"]: item for item in response.data["markets"]}

        self.assertEqual(by_id[str(market_a.id)]["fill_count"], 1)
        self.assertEqual(
            Decimal(by_id[str(market_a.id)]["total_volume_ugx"]),
            Decimal("5.00"),
        )
        self.assertEqual(by_id[str(market_b.id)]["fill_count"], 2)
        self.assertEqual(
            Decimal(by_id[str(market_b.id)]["total_volume_ugx"]),
            Decimal("10.00"),
        )

    def test_draft_and_suspended_markets_are_included(self):
        self.authenticate(self.operations_user)
        draft_market = self.create_market(
            event=self.create_event("Draft Fixture"),
            question="Draft market question?",
            status=Market.Status.DRAFT,
        )
        suspended_market = self.create_market(
            event=self.create_event("Suspended Fixture"),
            question="Suspended market question?",
            status=Market.Status.SUSPENDED,
        )

        response = self.client.get(
            reverse("markets:admin-market-stats"),
            {"market_ids": f"{draft_market.id},{suspended_market.id}"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {item["market_id"] for item in response.data["markets"]}
        self.assertIn(str(draft_market.id), returned_ids)
        self.assertIn(str(suspended_market.id), returned_ids)

    def test_permission_denied_for_user_without_market_permission(self):
        self.authenticate(self.outsider_user)
        market = self.create_market(
            event=self.create_event("Jinja Hippos vs Black Pirates"),
            question="Will Jinja Hippos beat Black Pirates?",
        )

        response = self.client.get(
            reverse("markets:admin-market-stats"),
            {"market_ids": str(market.id)},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_request_rejected(self):
        response = self.client.get(
            reverse("markets:admin-market-stats"),
            {"market_ids": str(uuid4())},
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import AuditLog
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
from markets.tests.eligibility_test_support import make_market_eligible
from markets.tests.wallet_test_support import (
    fund_market_wallet,
)
from sports.models import (
    Competition,
    Sport,
    SportingEvent,
)
from wallets.models import LedgerEntry, Wallet


class MarketParticipationAPITests(APITestCase):
    def test_ineligible_order_returns_structured_403_without_financial_mutation(self):
        market = self.open_market(self.create_market())
        self.participant.profile.date_of_birth = None
        self.participant.profile.save(update_fields=["date_of_birth", "updated_at"])
        Wallet.objects.filter(user=self.participant).delete()
        self.authenticate(self.participant)

        response = self.client.post(
            self.order_url(market), self.order_payload(market), format="json"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "market_participation_ineligible")
        self.assertIn("DATE_OF_BIRTH_REQUIRED", response.data["reason_codes"])
        self.assertFalse(MarketOrder.objects.filter(user=self.participant).exists())
        self.assertFalse(Wallet.objects.filter(user=self.participant).exists())
        self.assertFalse(LedgerEntry.objects.filter(wallet__user=self.participant).exists())
        audit = AuditLog.objects.get(action="MARKET_ORDER_BLOCKED")
        self.assertEqual(audit.metadata["participant_id"], str(self.participant.id))
        self.assertNotIn("email", audit.metadata)
        self.assertEqual(AuditLog.objects.filter(action="MARKET_ORDER_BLOCKED").count(), 1)
        self.assertEqual(
            set(audit.metadata),
            {"participant_id", "market_id", "outcome_id", "side", "reason_codes", "evaluated_at"},
        )

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

        make_market_eligible(self.participant)

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
        self.assertFalse(AuditLog.objects.filter(action="MARKET_ORDER_BLOCKED").exists())

    def test_ineligible_order_has_bounded_queries(self):
        market = self.open_market(self.create_market())
        self.participant.profile.date_of_birth = None
        self.participant.profile.save(update_fields=["date_of_birth", "updated_at"])
        self.authenticate(self.participant)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.post(
                self.order_url(market), self.order_payload(market), format="json"
            )
        self.assertEqual(response.status_code, 403)
        self.assertLessEqual(len(queries), 15)

    def test_order_create_schema_documents_201_and_403(self):
        schema = self.client.get(reverse("api-schema"), {"format": "json"}).json()
        operation = schema["paths"]["/api/v1/markets/{market_id}/orders/"]["post"]
        self.assertEqual(set(operation["responses"]), {"201", "403"})
        forbidden = operation["responses"]["403"]["content"]["application/json"]["schema"]
        self.assertTrue(forbidden["$ref"].endswith("/IneligibleOrderResponse"))

    def test_api_is_the_only_production_place_order_entry_point_and_audits_it(self):
        project_root = Path(__file__).resolve().parents[2]
        callers = []
        for path in project_root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            if "MarketParticipationService.place_order(" in source:
                callers.append((path.relative_to(project_root).as_posix(), source))
        self.assertEqual([path for path, _ in callers], ["markets/participation_views.py"])
        self.assertIn("except MarketParticipationIneligible", callers[0][1])
        self.assertIn('action="MARKET_ORDER_BLOCKED"', callers[0][1])

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
        outcome = market.outcomes.get(side=MarketOutcome.Side.YES)
        position = MarketPosition.objects.create(
            user=self.participant,
            market=market,
            outcome=outcome,
            quantity="10.0000",
            average_entry_price="0.40000",
            total_cost="4.0000",
        )
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
        position.refresh_from_db()
        self.assertEqual(position.reserved_quantity, Decimal("10.0000"))

    def test_sell_order_without_position_returns_position_error(self):
        market = self.open_market(self.create_market())
        self.authenticate(self.participant)

        response = self.client.post(
            self.order_url(market),
            self.order_payload(market, side=MarketOrder.Side.SELL),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn("position", response.data)
        self.assertFalse(MarketOrder.objects.filter(market=market).exists())

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

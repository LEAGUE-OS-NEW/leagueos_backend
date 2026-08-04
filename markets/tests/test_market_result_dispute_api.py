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
    MarketProvisionalEvidence,
    MarketResultDispute,
    MarketScope,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.provisional_result_service import (
    MarketProvisionalResultService,
)
from markets.services.result_dispute_service import (
    MarketResultDisputeService,
)
from sports.models import Competition, Sport, SportingEvent


class MarketResultDisputeAPITests(APITestCase):
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
            name="Dispute API Operations",
            display_name="Dispute API Operations",
        )
        self.approval_role = RoleFactory(
            name="Dispute API Approver",
            display_name="Dispute API Approver",
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
        self.participant_user = UserFactory()
        self.second_participant = UserFactory()
        self.outsider_user = UserFactory()

        UserRoleFactory(
            user=self.operations_user,
            role=self.operations_role,
        )
        UserRoleFactory(
            user=self.approver_user,
            role=self.approval_role,
        )

        self.sport = Sport.objects.create(
            name="Dispute API Football",
            code="DISPUTE_API_FOOTBALL",
        )
        self.category = MarketCategory.objects.create(
            name="Dispute API Result",
        )
        self.competition = Competition.objects.create(
            sport=self.sport,
            name="Dispute API League",
            country_code="UG",
            is_verified=True,
        )
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="Dispute API United v Review API City",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

    def create_market(self, **overrides):
        values = {
            "sport": self.sport,
            "category": self.category,
            "scope_type": MarketScope.EVENT,
            "sporting_event": self.event,
            "question": "Will Dispute API United win?",
            "description": "Participant dispute API contract.",
            "rules": "Resolve YES if Dispute API United wins.",
            "resolution_source": "Official competition result",
            "resolution_criteria": "Use the verified final score.",
            "status": Market.Status.DRAFT,
            "opens_at": self.now - timedelta(minutes=5),
            "closes_at": self.now + timedelta(days=1),
            "created_by": self.operations_user,
            "yes_label": "Dispute API United wins",
            "no_label": "Dispute API United does not win",
        }
        values.update(overrides)

        return MarketCatalogService.create_market(**values)

    def close_market(self, market):
        MarketLifecycleService.submit(
            market_id=market.id,
            actor=self.operations_user,
            notes="Ready for approval.",
        )
        MarketLifecycleService.approve(
            market_id=market.id,
            actor=self.approver_user,
            notes="Approved.",
        )
        MarketLifecycleService.open(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading opened.",
        )
        return MarketLifecycleService.close(
            market_id=market.id,
            actor=self.approver_user,
            notes="Trading closed.",
        )

    def create_position(self, market, user):
        outcome = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        return MarketPosition.objects.create(
            user=user,
            market=market,
            outcome=outcome,
            quantity=Decimal("5.0000"),
            reserved_quantity=Decimal("0.0000"),
            average_entry_price=Decimal("0.50000"),
            total_cost=Decimal("2.5000"),
            realized_pnl=Decimal("0.0000"),
        )

    def publish(self, market):
        winner = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        return MarketProvisionalResultService.publish(
            market_id=market.id,
            actor=self.approver_user,
            winning_outcome_id=winner.id,
            notes="Official result published provisionally.",
            dispute_window_hours=48,
            evidence_items=[
                {
                    "evidence_type": (MarketProvisionalEvidence.EvidenceType.OFFICIAL_RESULT),
                    "label": "Official final score",
                    "reference": "OFFICIAL-DISPUTE-API-0042",
                }
            ],
        )

    def submit_directly(self, market, user):
        return MarketResultDisputeService.submit(
            market_id=market.id,
            actor=user,
            category=(MarketResultDispute.Category.INCORRECT_OUTCOME),
            explanation=("The provisional result conflicts with a corrected " "official report."),
            evidence_items=[
                {
                    "label": "Corrected official report",
                    "reference": "CORRECTED-REPORT-API-0099",
                }
            ],
        )

    def payload(self, **overrides):
        values = {
            "category": (MarketResultDispute.Category.INCORRECT_OUTCOME),
            "explanation": (
                "The provisional result conflicts with a corrected " "official report."
            ),
            "evidence_items": [
                {
                    "label": "Corrected official report",
                    "reference": "CORRECTED-REPORT-API-0099",
                },
                {
                    "label": "Competition correction notice",
                    "reference": ("https://league.example/corrections/" "dispute-api-united"),
                },
            ],
        }
        values.update(overrides)
        return values

    def submit_url(self, market):
        return reverse(
            "markets:market-result-dispute-submit",
            kwargs={"market_id": market.id},
        )

    def participant_list_url(self):
        return reverse(
            "markets:participant-market-result-dispute-list",
        )

    def participant_detail_url(self, dispute):
        return reverse(
            "markets:participant-market-result-dispute-detail",
            kwargs={"dispute_id": dispute.id},
        )

    def admin_list_url(self):
        return reverse(
            "markets:admin-market-result-dispute-list",
        )

    def admin_detail_url(self, dispute):
        return reverse(
            "markets:admin-market-result-dispute-detail",
            kwargs={"dispute_id": dispute.id},
        )

    @staticmethod
    def response_items(response):
        if isinstance(response.data, dict) and "results" in response.data:
            return response.data["results"]

        return response.data

    def test_submit_requires_authentication_and_market_participation(self):
        market = self.close_market(self.create_market())
        self.publish(market)

        response = self.client.post(
            self.submit_url(market),
            self.payload(),
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        self.client.force_authenticate(self.outsider_user)

        response = self.client.post(
            self.submit_url(market),
            self.payload(),
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("participant", response.data)

    def test_participant_can_submit_privacy_safe_dispute(self):
        market = self.close_market(self.create_market())
        self.create_position(market, self.participant_user)
        self.publish(market)

        self.client.force_authenticate(self.participant_user)

        response = self.client.post(
            self.submit_url(market),
            self.payload(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
        )
        self.assertEqual(
            response.data["market_id"],
            str(market.id),
        )
        self.assertEqual(
            response.data["category"],
            MarketResultDispute.Category.INCORRECT_OUTCOME,
        )
        self.assertEqual(
            len(response.data["evidence_items"]),
            2,
        )

        serialized = str(response.data)
        self.assertNotIn(
            self.participant_user.email,
            serialized,
        )
        self.assertNotIn(
            "participant_email",
            response.data,
        )

    def test_submit_validates_payload_and_duplicate_submission(self):
        market = self.close_market(self.create_market())
        self.create_position(market, self.participant_user)
        self.publish(market)

        self.client.force_authenticate(self.participant_user)

        response = self.client.post(
            self.submit_url(market),
            {
                "category": "INVALID",
                "explanation": " ",
                "evidence_items": [],
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("category", response.data)
        self.assertIn("explanation", response.data)
        self.assertIn("evidence_items", response.data)

        first = self.client.post(
            self.submit_url(market),
            self.payload(),
            format="json",
        )
        self.assertEqual(
            first.status_code,
            status.HTTP_201_CREATED,
        )

        duplicate = self.client.post(
            self.submit_url(market),
            self.payload(),
            format="json",
        )
        self.assertEqual(
            duplicate.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("dispute", duplicate.data)

    def test_participant_list_contains_only_own_disputes(self):
        first_market = self.close_market(self.create_market())
        self.create_position(first_market, self.participant_user)
        self.publish(first_market)
        own_dispute = self.submit_directly(
            first_market,
            self.participant_user,
        )

        second_market = self.close_market(
            self.create_market(
                question="Will the second API market resolve YES?",
            )
        )
        self.create_position(second_market, self.second_participant)
        self.publish(second_market)
        other_dispute = self.submit_directly(
            second_market,
            self.second_participant,
        )

        self.client.force_authenticate(self.participant_user)

        response = self.client.get(
            self.participant_list_url(),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        items = self.response_items(response)
        dispute_ids = {item["id"] for item in items}

        self.assertIn(
            str(own_dispute.id),
            dispute_ids,
        )
        self.assertNotIn(
            str(other_dispute.id),
            dispute_ids,
        )

    def test_participant_can_read_own_detail_but_not_another(self):
        market = self.close_market(self.create_market())
        self.create_position(market, self.participant_user)
        self.publish(market)
        own_dispute = self.submit_directly(
            market,
            self.participant_user,
        )

        other_market = self.close_market(
            self.create_market(
                question="Will another dispute API market resolve YES?",
            )
        )
        self.create_position(
            other_market,
            self.second_participant,
        )
        self.publish(other_market)
        other_dispute = self.submit_directly(
            other_market,
            self.second_participant,
        )

        self.client.force_authenticate(self.participant_user)

        own_response = self.client.get(
            self.participant_detail_url(own_dispute),
        )
        self.assertEqual(
            own_response.status_code,
            status.HTTP_200_OK,
        )

        other_response = self.client.get(
            self.participant_detail_url(other_dispute),
        )
        self.assertEqual(
            other_response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_participant_tracking_requires_authentication(self):
        response = self.client.get(
            self.participant_list_url(),
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_admin_list_requires_approve_permission(self):
        self.client.force_authenticate(self.participant_user)

        response = self.client.get(
            self.admin_list_url(),
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.client.force_authenticate(self.approver_user)

        response = self.client.get(
            self.admin_list_url(),
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

    def test_admin_can_list_and_read_privacy_safe_disputes(self):
        market = self.close_market(self.create_market())
        self.create_position(market, self.participant_user)
        self.publish(market)
        dispute = self.submit_directly(
            market,
            self.participant_user,
        )

        self.client.force_authenticate(self.approver_user)

        list_response = self.client.get(
            self.admin_list_url(),
        )
        self.assertEqual(
            list_response.status_code,
            status.HTTP_200_OK,
        )

        items = self.response_items(list_response)
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["participant_id"],
            str(self.participant_user.id),
        )

        detail_response = self.client.get(
            self.admin_detail_url(dispute),
        )
        self.assertEqual(
            detail_response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            detail_response.data["participant_id"],
            str(self.participant_user.id),
        )

        serialized = str(detail_response.data)
        self.assertNotIn(
            self.participant_user.email,
            serialized,
        )
        self.assertNotIn(
            "participant_email",
            detail_response.data,
        )

    def test_dispute_endpoints_are_method_restricted(self):
        market = self.close_market(self.create_market())
        self.create_position(market, self.participant_user)
        self.publish(market)
        dispute = self.submit_directly(
            market,
            self.participant_user,
        )

        self.client.force_authenticate(self.participant_user)

        self.assertEqual(
            self.client.get(
                self.submit_url(market),
            ).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.delete(
                self.participant_detail_url(dispute),
            ).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

        self.client.force_authenticate(self.approver_user)

        self.assertEqual(
            self.client.post(
                self.admin_list_url(),
                {},
                format="json",
            ).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.patch(
                self.admin_detail_url(dispute),
                {},
                format="json",
            ).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

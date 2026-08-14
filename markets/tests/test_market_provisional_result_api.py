from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
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
    MarketProvisionalEvidence,
    MarketResultDevelopmentAcceleration,
    MarketScope,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.provisional_result_service import (
    MarketProvisionalResultService,
)
from sports.models import Competition, Sport, SportingEvent


class MarketProvisionalResultAPITests(APITestCase):
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
            name="Provisional API Operations",
            display_name="Provisional API Operations",
        )
        self.approval_role = RoleFactory(
            name="Provisional API Approver",
            display_name="Provisional API Approver",
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

        UserRoleFactory(
            user=self.operations_user,
            role=self.operations_role,
        )
        UserRoleFactory(
            user=self.approver_user,
            role=self.approval_role,
        )

        self.sport = Sport.objects.create(
            name="Provisional API Football",
            code="PROVISIONAL_API_FOOTBALL",
        )
        self.category = MarketCategory.objects.create(
            name="Provisional API Result",
        )
        self.competition = Competition.objects.create(
            sport=self.sport,
            name="Provisional API League",
            country_code="UG",
            is_verified=True,
        )
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="API United v Contract City",
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
            "question": "Will API United win?",
            "description": "Provisional API contract market.",
            "rules": "Resolve YES if API United wins.",
            "resolution_source": "Official competition result",
            "resolution_criteria": "Use the verified final score.",
            "status": Market.Status.DRAFT,
            "opens_at": self.now - timedelta(minutes=5),
            "closes_at": self.now + timedelta(days=1),
            "created_by": self.operations_user,
            "yes_label": "API United wins",
            "no_label": "API United does not win",
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

    def publish_url(self, market):
        return reverse(
            "markets:market-provisional-result-publish",
            kwargs={"market_id": market.id},
        )

    def detail_url(self, market):
        return reverse(
            "markets:market-provisional-result-detail",
            kwargs={"market_id": market.id},
        )

    def payload(self, market, **overrides):
        winner = market.outcomes.get(side=MarketOutcome.Side.YES)

        values = {
            "winning_outcome_id": str(winner.id),
            "notes": "Official score published provisionally.",
            "dispute_window_hours": 48,
            "evidence_items": [
                {
                    "evidence_type": (MarketProvisionalEvidence.EvidenceType.OFFICIAL_RESULT),
                    "label": "Official final score",
                    "reference": ("https://league.example/results/api-united-contract-city"),
                },
                {
                    "evidence_type": (MarketProvisionalEvidence.EvidenceType.DOCUMENT_REFERENCE),
                    "label": "Signed match report",
                    "reference": "MATCH-REPORT-API-0042",
                },
            ],
        }
        values.update(overrides)

        return values

    def publish_directly(self, market, **overrides):
        winner = market.outcomes.get(side=MarketOutcome.Side.YES)

        values = {
            "market_id": market.id,
            "actor": self.approver_user,
            "winning_outcome_id": winner.id,
            "notes": "Official score published provisionally.",
            "dispute_window_hours": 48,
            "evidence_items": self.payload(market)["evidence_items"],
        }
        values.update(overrides)

        return MarketProvisionalResultService.publish(**values)

    def accelerator_url(self, market):
        return reverse(
            "markets:admin-result-verification-dev-end-window",
            kwargs={"market_id": market.id},
        )

    @override_settings(DEBUG=False, DEV_RESULT_ACCELERATOR_ENABLED=True)
    def test_development_accelerator_is_unavailable_outside_debug(self):
        market = self.close_market(self.create_market())
        self.publish_directly(market)
        self.approver_user.email = "results.local@leagueos.test"
        self.approver_user.save(update_fields=["email"])
        self.client.force_authenticate(self.approver_user)
        self.assertEqual(self.client.post(self.accelerator_url(market)).status_code, 404)

    @override_settings(DEBUG=True, DEV_RESULT_ACCELERATOR_ENABLED=False)
    def test_development_accelerator_is_unavailable_when_disabled(self):
        market = self.close_market(self.create_market())
        self.publish_directly(market)
        self.approver_user.email = "results.local@leagueos.test"
        self.approver_user.save(update_fields=["email"])
        self.client.force_authenticate(self.approver_user)
        self.assertEqual(self.client.post(self.accelerator_url(market)).status_code, 404)

    @override_settings(DEBUG=True, DEV_RESULT_ACCELERATOR_ENABLED=True)
    def test_development_accelerator_requires_permission(self):
        market = self.close_market(self.create_market())
        self.publish_directly(market)
        self.participant_user.email = "fan.local@leagueos.test"
        self.participant_user.save(update_fields=["email"])
        self.client.force_authenticate(self.participant_user)
        self.assertEqual(self.client.post(self.accelerator_url(market)).status_code, 403)

    @override_settings(DEBUG=True, DEV_RESULT_ACCELERATOR_ENABLED=True)
    def test_development_accelerator_only_marks_synthetic_window_closed(self):
        self.operations_user.email = "market.ops.local@leagueos.test"
        self.operations_user.save(update_fields=["email"])
        self.approver_user.email = "results.local@leagueos.test"
        self.approver_user.save(update_fields=["email"])
        market = self.close_market(self.create_market())
        provisional = self.publish_directly(market)
        original_deadline = provisional.dispute_deadline
        self.client.force_authenticate(self.approver_user)

        response = self.client.post(self.accelerator_url(market))

        self.assertEqual(response.status_code, 200)
        market.refresh_from_db()
        provisional.refresh_from_db()
        self.assertEqual(market.status, Market.Status.CLOSED)
        self.assertFalse(hasattr(market, "settlement"))
        self.assertEqual(provisional.dispute_deadline, original_deadline)
        marker = MarketResultDevelopmentAcceleration.objects.get(provisional_result=provisional)
        self.assertEqual(marker.accelerated_by, self.approver_user)

    def test_publish_requires_authentication_and_permission(self):
        market = self.close_market(self.create_market())
        url = self.publish_url(market)

        response = self.client.post(
            url,
            self.payload(market),
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        self.client.force_authenticate(self.participant_user)
        response = self.client.post(
            url,
            self.payload(market),
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_approver_can_publish_provisional_result(self):
        market = self.close_market(self.create_market())

        self.client.force_authenticate(self.approver_user)
        response = self.client.post(
            self.publish_url(market),
            self.payload(market),
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
            response.data["winning_outcome"]["side"],
            MarketOutcome.Side.YES,
        )
        self.assertEqual(
            response.data["dispute_status"],
            "OPEN",
        )
        self.assertTrue(
            response.data["financial_finalisation_blocked"],
        )
        self.assertEqual(
            len(response.data["evidence_items"]),
            2,
        )

        forbidden_fields = {
            "publisher_email",
            "published_by",
            "recorder_email",
            "recorded_by",
        }

        self.assertTrue(forbidden_fields.isdisjoint(response.data.keys()))

        for evidence_item in response.data["evidence_items"]:
            self.assertTrue(forbidden_fields.isdisjoint(evidence_item.keys()))

    def test_publish_validates_payload_and_returns_field_errors(self):
        market = self.close_market(self.create_market())

        self.client.force_authenticate(self.approver_user)

        response = self.client.post(
            self.publish_url(market),
            {
                "winning_outcome_id": "",
                "notes": " ",
                "dispute_window_hours": 0,
                "evidence_items": [],
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn("winning_outcome_id", response.data)
        self.assertIn("notes", response.data)
        self.assertIn("dispute_window_hours", response.data)
        self.assertIn("evidence_items", response.data)

    def test_publish_rejects_outcome_from_another_market(self):
        market = self.close_market(self.create_market())

        other_market = self.create_market(
            question="Will another API market resolve YES?",
        )
        other_outcome = other_market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        self.client.force_authenticate(self.approver_user)

        response = self.client.post(
            self.publish_url(market),
            self.payload(
                market,
                winning_outcome_id=str(other_outcome.id),
            ),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn(
            "winning_outcome",
            response.data,
        )

    def test_duplicate_publication_is_rejected(self):
        market = self.close_market(self.create_market())
        self.publish_directly(market)

        self.client.force_authenticate(self.approver_user)

        response = self.client.post(
            self.publish_url(market),
            self.payload(market),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertIn(
            "provisional_result",
            response.data,
        )

    def test_public_detail_returns_privacy_safe_result_and_evidence(self):
        market = self.close_market(self.create_market())
        provisional = self.publish_directly(market)

        self.client.force_authenticate(user=None)

        response = self.client.get(
            self.detail_url(market),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["id"],
            str(provisional.id),
        )
        self.assertEqual(
            response.data["market_id"],
            str(market.id),
        )
        self.assertEqual(
            response.data["winning_outcome"]["side"],
            MarketOutcome.Side.YES,
        )
        self.assertEqual(
            response.data["dispute_status"],
            "OPEN",
        )
        self.assertTrue(
            response.data["financial_finalisation_blocked"],
        )

        serialized_text = str(response.data)
        self.assertNotIn(
            self.approver_user.email,
            serialized_text,
        )
        self.assertNotIn(
            str(self.approver_user.id),
            serialized_text,
        )

    def test_public_detail_reports_closed_dispute_window(self):
        market = self.close_market(self.create_market())

        historical_time = self.now - timedelta(hours=72)

        with patch(
            "markets.services.provisional_result_service.timezone.now",
            return_value=historical_time,
        ):
            self.publish_directly(
                market,
                dispute_window_hours=48,
            )

        response = self.client.get(
            self.detail_url(market),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["dispute_status"],
            "CLOSED",
        )
        self.assertFalse(
            response.data["financial_finalisation_blocked"],
        )

    def test_public_detail_returns_not_found_without_result(self):
        market = self.close_market(self.create_market())

        response = self.client.get(
            self.detail_url(market),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_provisional_result_endpoints_are_method_restricted(self):
        market = self.close_market(self.create_market())
        self.publish_directly(market)

        self.client.force_authenticate(self.approver_user)

        publish_url = self.publish_url(market)
        detail_url = self.detail_url(market)

        self.assertEqual(
            self.client.get(publish_url).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.put(detail_url, {}, format="json").status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.patch(detail_url, {}, format="json").status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.delete(detail_url).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

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
    MarketResultDisputeDecision,
    MarketScope,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.provisional_result_service import (
    MarketProvisionalResultService,
)
from markets.services.result_dispute_decision_service import (
    MarketResultDisputeDecisionService,
)
from markets.services.result_dispute_service import (
    MarketResultDisputeService,
)
from sports.models import Competition, Sport, SportingEvent


class MarketResultDisputeDecisionAPITests(APITestCase):
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
            name="Decision API Operations",
            display_name="Decision API Operations",
        )
        self.approval_role = RoleFactory(
            name="Decision API Approver",
            display_name="Decision API Approver",
        )

        RolePermissionFactory(
            role=self.operations_role,
            permission=self.manage_permission,
        )
        RolePermissionFactory(
            role=self.approval_role,
            permission=self.approve_permission,
        )

        self.creator_user = UserFactory()
        self.publisher_user = UserFactory()
        self.decision_user = UserFactory()
        self.participant_user = UserFactory()
        self.outsider_user = UserFactory()

        UserRoleFactory(
            user=self.creator_user,
            role=self.operations_role,
        )

        for user in [
            self.creator_user,
            self.publisher_user,
            self.decision_user,
            self.participant_user,
        ]:
            UserRoleFactory(
                user=user,
                role=self.approval_role,
            )

        self.sport = Sport.objects.create(
            name="Decision API Football",
            code="DECISION_API_FOOTBALL",
        )
        self.category = MarketCategory.objects.create(
            name="Decision API Result",
        )
        self.competition = Competition.objects.create(
            sport=self.sport,
            name="Decision API League",
            country_code="UG",
            is_verified=True,
        )
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="Decision API United v Final API City",
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
            "question": "Will Decision API United win?",
            "description": "Independent decision API contract.",
            "rules": "Resolve YES if Decision API United wins.",
            "resolution_source": "Official competition result",
            "resolution_criteria": "Use the verified final score.",
            "status": Market.Status.DRAFT,
            "opens_at": self.now - timedelta(minutes=5),
            "closes_at": self.now + timedelta(days=1),
            "created_by": self.creator_user,
            "yes_label": "Decision API United wins",
            "no_label": "Decision API United does not win",
        }
        values.update(overrides)

        return MarketCatalogService.create_market(**values)

    def close_market(self, market):
        MarketLifecycleService.submit(
            market_id=market.id,
            actor=self.creator_user,
            notes="Ready for approval.",
        )
        MarketLifecycleService.approve(
            market_id=market.id,
            actor=self.publisher_user,
            notes="Approved.",
        )
        MarketLifecycleService.open(
            market_id=market.id,
            actor=self.publisher_user,
            notes="Trading opened.",
        )
        return MarketLifecycleService.close(
            market_id=market.id,
            actor=self.publisher_user,
            notes="Trading closed.",
        )

    def create_position(self, market, user=None):
        outcome = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        return MarketPosition.objects.create(
            user=user or self.participant_user,
            market=market,
            outcome=outcome,
            quantity=Decimal("5.0000"),
            reserved_quantity=Decimal("0.0000"),
            average_entry_price=Decimal("0.50000"),
            total_cost=Decimal("2.5000"),
            realized_pnl=Decimal("0.0000"),
        )

    def publish(self, market, published_at):
        provisional_winner = market.outcomes.get(
            side=MarketOutcome.Side.YES,
        )

        with patch(
            "markets.services.provisional_result_service.timezone.now",
            return_value=published_at,
        ):
            return MarketProvisionalResultService.publish(
                market_id=market.id,
                actor=self.publisher_user,
                winning_outcome_id=provisional_winner.id,
                notes="Official result published provisionally.",
                dispute_window_hours=48,
                evidence_items=[
                    {
                        "evidence_type": (MarketProvisionalEvidence.EvidenceType.OFFICIAL_RESULT),
                        "label": "Official provisional score",
                        "reference": "DECISION-API-PROVISIONAL-0042",
                    }
                ],
            )

    def submit_dispute(self, market, submitted_at):
        with patch(
            "markets.services.result_dispute_service.timezone.now",
            return_value=submitted_at,
        ):
            return MarketResultDisputeService.submit(
                market_id=market.id,
                actor=self.participant_user,
                category=(MarketResultDispute.Category.INCORRECT_OUTCOME),
                explanation=(
                    "The provisional result conflicts with a corrected "
                    "official competition report."
                ),
                evidence_items=[
                    {
                        "label": "Corrected competition report",
                        "reference": "DECISION-API-CORRECTED-0099",
                    }
                ],
            )

    def create_disputed_market(self, **overrides):
        market = self.close_market(self.create_market(**overrides))
        self.create_position(market)

        published_at = self.now - timedelta(hours=72)
        self.publish(
            market,
            published_at,
        )
        self.submit_dispute(
            market,
            published_at + timedelta(hours=1),
        )

        return market

    def decide_directly(
        self,
        market,
        *,
        decision_type=(MarketResultDisputeDecision.DecisionType.CONFIRM),
        winning_outcome_id=None,
        review_extension_hours=None,
    ):
        return MarketResultDisputeDecisionService.decide(
            market_id=market.id,
            actor=self.decision_user,
            decision_type=decision_type,
            winning_outcome_id=winning_outcome_id,
            review_extension_hours=review_extension_hours,
            notes="Independent review completed.",
            evidence="Reviewed provisional and dispute evidence.",
        )

    def payload(self, **overrides):
        values = {
            "decision_type": (MarketResultDisputeDecision.DecisionType.CONFIRM),
            "winning_outcome_id": None,
            "review_extension_hours": None,
            "notes": "Independent review completed.",
            "evidence": ("Reviewed provisional and dispute evidence."),
        }
        values.update(overrides)
        return values

    def create_url(self, market):
        return reverse(
            "markets:admin-market-result-dispute-decision-create",
            kwargs={"market_id": market.id},
        )

    def public_history_url(self, market):
        return reverse(
            "markets:market-result-dispute-decision-list",
            kwargs={"market_id": market.id},
        )

    def admin_detail_url(self, decision):
        return reverse(
            "markets:admin-market-result-dispute-decision-detail",
            kwargs={"decision_id": decision.id},
        )

    @staticmethod
    def response_items(response):
        if isinstance(response.data, dict) and "results" in response.data:
            return response.data["results"]

        return response.data

    def test_create_requires_authentication_and_permission(self):
        market = self.create_disputed_market()

        response = self.client.post(
            self.create_url(market),
            self.payload(),
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

        self.client.force_authenticate(self.outsider_user)

        response = self.client.post(
            self.create_url(market),
            self.payload(),
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_create_rejects_conflicted_decision_makers(self):
        market = self.create_disputed_market()

        for conflicted_actor in [
            self.creator_user,
            self.publisher_user,
            self.participant_user,
        ]:
            with self.subTest(actor=conflicted_actor.id):
                self.client.force_authenticate(conflicted_actor)

                response = self.client.post(
                    self.create_url(market),
                    self.payload(),
                    format="json",
                )

                self.assertEqual(
                    response.status_code,
                    status.HTTP_403_FORBIDDEN,
                )

        self.assertFalse(
            MarketResultDisputeDecision.objects.filter(
                provisional_result__market=market,
            ).exists()
        )

    def test_independent_approver_can_confirm_result(self):
        market = self.create_disputed_market()

        self.client.force_authenticate(self.decision_user)

        response = self.client.post(
            self.create_url(market),
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
            response.data["sequence"],
            1,
        )
        self.assertEqual(
            response.data["decision_type"],
            MarketResultDisputeDecision.DecisionType.CONFIRM,
        )
        self.assertTrue(
            response.data["is_final"],
        )
        self.assertEqual(
            response.data["decision_maker_id"],
            str(self.decision_user.id),
        )

        serialized = str(response.data)
        self.assertNotIn(
            self.decision_user.email,
            serialized,
        )
        self.assertNotIn(
            "decision_maker_email",
            response.data,
        )

        market.refresh_from_db()
        self.assertEqual(
            market.status,
            Market.Status.RESOLVED,
        )

    def test_create_supports_correct_void_and_extension(self):
        corrected_market = self.create_disputed_market(
            question="Should the API decision be corrected?",
        )
        corrected_winner = corrected_market.outcomes.get(
            side=MarketOutcome.Side.NO,
        )

        self.client.force_authenticate(self.decision_user)

        corrected_response = self.client.post(
            self.create_url(corrected_market),
            self.payload(
                decision_type=(MarketResultDisputeDecision.DecisionType.CORRECT),
                winning_outcome_id=str(corrected_winner.id),
            ),
            format="json",
        )
        self.assertEqual(
            corrected_response.status_code,
            status.HTTP_201_CREATED,
        )
        self.assertEqual(
            corrected_response.data["winning_outcome"]["id"],
            str(corrected_winner.id),
        )

        void_market = self.create_disputed_market(
            question="Should the API decision void this market?",
        )

        void_response = self.client.post(
            self.create_url(void_market),
            self.payload(
                decision_type=(MarketResultDisputeDecision.DecisionType.VOID),
            ),
            format="json",
        )
        self.assertEqual(
            void_response.status_code,
            status.HTTP_201_CREATED,
        )
        self.assertIsNone(
            void_response.data["winning_outcome"],
        )

        extension_market = self.create_disputed_market(
            question="Should the API review be extended?",
        )

        extension_response = self.client.post(
            self.create_url(extension_market),
            self.payload(
                decision_type=(MarketResultDisputeDecision.DecisionType.EXTEND_REVIEW),
                review_extension_hours=24,
            ),
            format="json",
        )
        self.assertEqual(
            extension_response.status_code,
            status.HTTP_201_CREATED,
        )
        self.assertFalse(
            extension_response.data["is_final"],
        )
        self.assertIsNotNone(
            extension_response.data["review_extended_until"],
        )

    def test_create_returns_action_specific_validation_errors(self):
        market = self.create_disputed_market()

        self.client.force_authenticate(self.decision_user)

        invalid_cases = [
            (
                {
                    "decision_type": "INVALID",
                },
                "decision_type",
            ),
            (
                {
                    "notes": " ",
                },
                "notes",
            ),
            (
                {
                    "evidence": " ",
                },
                "evidence",
            ),
            (
                {
                    "decision_type": (MarketResultDisputeDecision.DecisionType.CORRECT),
                },
                "winning_outcome",
            ),
            (
                {
                    "decision_type": (MarketResultDisputeDecision.DecisionType.EXTEND_REVIEW),
                    "review_extension_hours": None,
                },
                "review_extension_hours",
            ),
        ]

        for overrides, expected_field in invalid_cases:
            with self.subTest(overrides=overrides):
                response = self.client.post(
                    self.create_url(market),
                    self.payload(**overrides),
                    format="json",
                )

                self.assertEqual(
                    response.status_code,
                    status.HTTP_400_BAD_REQUEST,
                )
                self.assertIn(
                    expected_field,
                    response.data,
                )

        self.assertFalse(
            MarketResultDisputeDecision.objects.filter(
                provisional_result__market=market,
            ).exists()
        )

    def test_public_history_is_ordered_and_privacy_safe(self):
        market = self.create_disputed_market()

        extension = self.decide_directly(
            market,
            decision_type=(MarketResultDisputeDecision.DecisionType.EXTEND_REVIEW),
            review_extension_hours=24,
        )

        final_time = extension.review_extended_until + timedelta(seconds=1)

        with patch(
            ("markets.services." "result_dispute_decision_service.timezone.now"),
            return_value=final_time,
        ):
            final_decision = self.decide_directly(market)

        self.client.force_authenticate(user=None)

        response = self.client.get(
            self.public_history_url(market),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )

        items = self.response_items(response)
        self.assertEqual(
            [item["id"] for item in items],
            [
                str(extension.id),
                str(final_decision.id),
            ],
        )
        self.assertEqual(
            [item["sequence"] for item in items],
            [1, 2],
        )

        serialized = str(response.data)
        self.assertNotIn(
            self.decision_user.email,
            serialized,
        )
        self.assertNotIn(
            str(self.decision_user.id),
            serialized,
        )
        self.assertNotIn(
            "decision_maker_id",
            serialized,
        )
        self.assertNotIn(
            "decision_maker_email",
            serialized,
        )

    def test_public_history_without_decisions_returns_empty_list(self):
        market = self.create_disputed_market()

        response = self.client.get(
            self.public_history_url(market),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.response_items(response),
            [],
        )

    def test_admin_detail_requires_permission_and_exposes_safe_actor_id(
        self,
    ):
        market = self.create_disputed_market()
        decision = self.decide_directly(market)

        self.client.force_authenticate(self.outsider_user)

        response = self.client.get(
            self.admin_detail_url(decision),
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.client.force_authenticate(self.decision_user)

        response = self.client.get(
            self.admin_detail_url(decision),
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["decision_maker_id"],
            str(self.decision_user.id),
        )

        serialized = str(response.data)
        self.assertNotIn(
            self.decision_user.email,
            serialized,
        )
        self.assertNotIn(
            "decision_maker_email",
            response.data,
        )

    def test_decision_endpoints_are_method_restricted(self):
        market = self.create_disputed_market()
        decision = self.decide_directly(market)

        self.client.force_authenticate(self.decision_user)

        self.assertEqual(
            self.client.get(
                self.create_url(market),
            ).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.post(
                self.public_history_url(market),
                {},
                format="json",
            ).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.patch(
                self.admin_detail_url(decision),
                {},
                format="json",
            ).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )
        self.assertEqual(
            self.client.delete(
                self.admin_detail_url(decision),
            ).status_code,
            status.HTTP_405_METHOD_NOT_ALLOWED,
        )

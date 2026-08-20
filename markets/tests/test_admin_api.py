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
    MarketOutcome,
    MarketScope,
    MarketStatusTransition,
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


class MarketAdminAPITests(APITestCase):
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
        self.approval_role = RoleFactory(
            name="Market Approval Admin",
            display_name="Market Approval Admin",
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
        self.outsider_user = UserFactory()

        UserRoleFactory(
            user=self.operations_user,
            role=self.operations_role,
        )
        UserRoleFactory(
            user=self.approver_user,
            role=self.approval_role,
        )

        self.football = Sport.objects.create(
            name="Football",
            code="FOOTBALL",
        )
        self.category = MarketCategory.objects.create(
            name="Match Result",
            description="Binary match-result markets.",
        )
        self.competition = Competition.objects.create(
            sport=self.football,
            name="Uganda Premier League",
            country_code="UG",
            is_verified=True,
        )
        self.event = SportingEvent.objects.create(
            sport=self.football,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="KCCA FC vs Vipers SC",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

        self.draft_market = self.create_market(
            question="Will KCCA FC beat Vipers SC?",
        )
        self.pending_market = self.create_market(
            question="Will KCCA FC score first?",
        )
        self.pending_market = MarketLifecycleService.submit(
            market_id=self.pending_market.id,
            actor=self.operations_user,
            notes="Ready for independent review.",
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def create_market(self, **overrides):
        values = {
            "sport": self.football,
            "category": self.category,
            "scope_type": MarketScope.EVENT,
            "sporting_event": self.event,
            "question": "Will KCCA FC win?",
            "description": "Match result prediction.",
            "rules": ("The market resolves YES if KCCA FC " "wins in regulation time."),
            "resolution_source": ("Official competition result"),
            "resolution_criteria": (
                "Use the verified final score published " "by the competition organiser."
            ),
            "status": Market.Status.DRAFT,
            "opens_at": self.now - timedelta(minutes=5),
            "closes_at": self.now + timedelta(days=1),
            "created_by": self.operations_user,
            "yes_label": "KCCA FC",
            "no_label": "Vipers SC or Draw",
        }
        values.update(overrides)

        return MarketCatalogService.create_market(
            **values,
        )

    def create_payload(self, **overrides):
        values = {
            "sport_id": str(self.football.id),
            "category_id": str(self.category.id),
            "scope_type": MarketScope.EVENT,
            "sporting_event_id": str(self.event.id),
            "question": ("Will KCCA FC keep a clean sheet?"),
            "description": ("Clean-sheet prediction market."),
            "rules": ("Resolve YES when KCCA FC concedes " "no goals in regulation time."),
            "resolution_source": ("Official competition result"),
            "resolution_criteria": ("Use the verified regulation-time " "final score."),
            "opens_at": (self.now - timedelta(minutes=5)).isoformat(),
            "closes_at": (self.now + timedelta(days=1)).isoformat(),
            "is_featured": True,
            "yes_label": "Clean sheet",
            "no_label": "Concedes a goal",
        }
        values.update(overrides)

        return values

    def test_list_requires_authentication(self):
        response = self.client.get(
            reverse("markets:admin-market-list"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_list_rejects_user_without_market_permission(self):
        self.authenticate(self.outsider_user)

        response = self.client.get(
            reverse("markets:admin-market-list"),
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_operations_admin_can_list_all_market_states(self):
        self.authenticate(self.operations_user)

        response = self.client.get(
            reverse("markets:admin-market-list"),
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

        market_ids = {item["id"] for item in response.data["results"]}

        self.assertEqual(
            market_ids,
            {
                str(self.draft_market.id),
                str(self.pending_market.id),
            },
        )

    def test_approval_admin_can_list_markets(self):
        self.authenticate(self.approver_user)

        response = self.client.get(
            reverse("markets:admin-market-list"),
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

    def test_list_supports_status_and_search_filters(self):
        self.authenticate(self.approver_user)

        response = self.client.get(
            reverse("markets:admin-market-list"),
            {
                "status": Market.Status.PENDING_APPROVAL,
                "search": "score first",
            },
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["count"],
            1,
        )
        self.assertEqual(
            response.data["results"][0]["id"],
            str(self.pending_market.id),
        )

    def test_detail_contains_creator_outcomes_and_history(self):
        self.authenticate(self.approver_user)

        response = self.client.get(
            reverse(
                "markets:admin-market-detail",
                kwargs={
                    "market_id": self.pending_market.id,
                },
            )
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )
        self.assertEqual(
            response.data["created_by"]["id"],
            str(self.operations_user.id),
        )
        self.assertEqual(
            [item["side"] for item in response.data["outcomes"]],
            [
                MarketOutcome.Side.YES,
                MarketOutcome.Side.NO,
            ],
        )
        self.assertEqual(
            len(response.data["status_transitions"]),
            1,
        )
        self.assertEqual(
            response.data["status_transitions"][0]["action"],
            MarketStatusTransition.Action.SUBMIT,
        )
        self.assertEqual(
            response.data["status_transitions"][0]["actor_email"],
            self.operations_user.email,
        )
        # Inherited from MarketPublicSerializer — proves the general admin
        # read serializer carries settlement/refund visibility too, not just
        # the dedicated result-verification serializer.
        self.assertIn("is_settled", response.data)
        self.assertIn("is_refunded", response.data)
        self.assertFalse(response.data["is_settled"])
        self.assertFalse(response.data["is_refunded"])

    def test_operations_admin_can_create_draft_market(self):
        self.authenticate(self.operations_user)

        response = self.client.post(
            reverse("markets:admin-market-list"),
            self.create_payload(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_201_CREATED,
            response.data,
        )

        market = Market.objects.get(
            id=response.data["id"],
        )

        self.assertEqual(
            market.status,
            Market.Status.DRAFT,
        )
        self.assertEqual(
            market.created_by,
            self.operations_user,
        )
        self.assertTrue(
            market.is_featured,
        )
        self.assertEqual(
            list(
                market.outcomes.values_list(
                    "side",
                    "label",
                )
            ),
            [
                (
                    MarketOutcome.Side.YES,
                    "Clean sheet",
                ),
                (
                    MarketOutcome.Side.NO,
                    "Concedes a goal",
                ),
            ],
        )

    def test_future_scheduled_event_market_is_accepted(self):
        self.authenticate(self.operations_user)

        response = self.client.post(
            reverse("markets:admin-market-list"),
            self.create_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_past_scheduled_event_market_is_rejected(self):
        self.event.starts_at = self.now - timedelta(minutes=1)
        self.event.save(update_fields=["starts_at", "updated_at"])
        self.authenticate(self.operations_user)

        response = self.client.post(
            reverse("markets:admin-market-list"),
            self.create_payload(closes_at=(self.now - timedelta(hours=1)).isoformat()),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn("sporting_event_id", response.data)

    def test_non_scheduled_event_market_is_rejected(self):
        self.authenticate(self.operations_user)

        for event_status in (
            SportingEvent.Status.COMPLETED,
            SportingEvent.Status.LIVE,
            SportingEvent.Status.CANCELLED,
            SportingEvent.Status.ABANDONED,
            SportingEvent.Status.DRAFT,
        ):
            with self.subTest(event_status=event_status):
                self.event.status = event_status
                self.event.save(update_fields=["status", "updated_at"])
                response = self.client.post(
                    reverse("markets:admin-market-list"),
                    self.create_payload(question=f"Market for {event_status}"),
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
                self.assertIn("sporting_event_id", response.data)

    def test_unverified_event_market_is_rejected(self):
        self.event.is_verified = False
        self.event.save(update_fields=["is_verified", "updated_at"])
        self.authenticate(self.operations_user)

        response = self.client.post(
            reverse("markets:admin-market-list"),
            self.create_payload(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn("sporting_event_id", response.data)

    def test_event_market_cannot_close_after_event_starts(self):
        self.authenticate(self.operations_user)

        response = self.client.post(
            reverse("markets:admin-market-list"),
            self.create_payload(
                closes_at=(self.event.starts_at + timedelta(seconds=1)).isoformat()
            ),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn("closes_at", response.data)

    def test_settles_by_persists_through_create_read_and_update(self):
        self.authenticate(self.operations_user)
        initial_settles_by = self.now + timedelta(days=1, hours=2)

        created = self.client.post(
            reverse("markets:admin-market-list"),
            self.create_payload(settles_by=initial_settles_by.isoformat()),
            format="json",
        )

        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        self.assertEqual(
            timezone.datetime.fromisoformat(created.data["settles_by"]),
            initial_settles_by,
        )
        market = Market.objects.get(id=created.data["id"])
        self.assertEqual(market.settles_by, initial_settles_by)

        updated_settles_by = self.now + timedelta(days=1, hours=3)
        updated = self.client.patch(
            reverse("markets:admin-market-detail", kwargs={"market_id": market.id}),
            {"settles_by": updated_settles_by.isoformat()},
            format="json",
        )

        self.assertEqual(updated.status_code, status.HTTP_200_OK, updated.data)
        market.refresh_from_db()
        self.assertEqual(market.settles_by, updated_settles_by)
        self.assertEqual(
            timezone.datetime.fromisoformat(updated.data["settles_by"]),
            updated_settles_by,
        )

    def test_create_rejects_settles_by_before_closes_at(self):
        self.authenticate(self.operations_user)

        response = self.client.post(
            reverse("markets:admin-market-list"),
            self.create_payload(settles_by=self.now.isoformat()),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn("settles_by", response.data)

    def test_create_rejects_lifecycle_owned_status(self):
        self.authenticate(self.operations_user)

        response = self.client.post(
            reverse("markets:admin-market-list"),
            self.create_payload(
                status=Market.Status.OPEN,
            ),
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

    def test_approval_admin_cannot_create_market(self):
        self.authenticate(self.approver_user)

        response = self.client.post(
            reverse("markets:admin-market-list"),
            self.create_payload(),
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_operations_admin_can_edit_draft_market(self):
        self.authenticate(self.operations_user)

        response = self.client.patch(
            reverse(
                "markets:admin-market-detail",
                kwargs={
                    "market_id": self.draft_market.id,
                },
            ),
            {
                "question": ("Will KCCA FC win in regulation time?"),
                "yes_label": "KCCA FC wins",
                "no_label": "Draw or Vipers SC",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
            response.data,
        )

        self.draft_market.refresh_from_db()

        self.assertEqual(
            self.draft_market.question,
            "Will KCCA FC win in regulation time?",
        )
        self.assertEqual(
            list(
                self.draft_market.outcomes.values_list(
                    "side",
                    "label",
                )
            ),
            [
                (
                    MarketOutcome.Side.YES,
                    "KCCA FC wins",
                ),
                (
                    MarketOutcome.Side.NO,
                    "Draw or Vipers SC",
                ),
            ],
        )

    def test_pending_market_cannot_be_edited(self):
        self.authenticate(self.operations_user)

        original_question = self.pending_market.question

        response = self.client.patch(
            reverse(
                "markets:admin-market-detail",
                kwargs={
                    "market_id": self.pending_market.id,
                },
            ),
            {
                "question": "Unauthorised pending edit",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
            response.data,
        )

        self.pending_market.refresh_from_db()

        self.assertEqual(
            self.pending_market.question,
            original_question,
        )

    def test_approval_admin_cannot_edit_market(self):
        self.authenticate(self.approver_user)

        response = self.client.patch(
            reverse(
                "markets:admin-market-detail",
                kwargs={
                    "market_id": self.draft_market.id,
                },
            ),
            {
                "question": "Approval admin edit",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

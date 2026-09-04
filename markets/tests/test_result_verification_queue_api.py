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
from markets.models import Market, MarketCategory, MarketScope
from markets.services.catalog_service import MarketCatalogService
from markets.services.lifecycle_service import MarketLifecycleService
from sports.models import Competition, Sport, SportingEvent


class ResultVerificationQueueFixtureMixin:
    def setUp(self):
        super().setUp()
        self.now = timezone.now()

        approve_permission = PermissionFactory(
            name="approve_market", resource="market", action="approve"
        )
        manage_permission = PermissionFactory(
            name="manage_market", resource="market", action="manage"
        )
        approval_role = RoleFactory(name="Queue API Approver", display_name="Queue API Approver")
        operations_role = RoleFactory(
            name="Queue API Operations", display_name="Queue API Operations"
        )
        RolePermissionFactory(role=approval_role, permission=approve_permission)
        RolePermissionFactory(role=operations_role, permission=manage_permission)

        self.actor = UserFactory()
        self.outsider = UserFactory()
        UserRoleFactory(user=self.actor, role=approval_role)
        UserRoleFactory(user=self.outsider, role=operations_role)

        self.sport = Sport.objects.create(name="Queue API Football", code="QUEUE_API_FOOTBALL")
        self.category = MarketCategory.objects.create(name="Queue API")
        self.competition = Competition.objects.create(
            sport=self.sport, name="Queue API League", country_code="UG", is_verified=True
        )
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="Queue API United v Queue API City",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

    def create_market(self, *, opens_at, closes_at, question="Queue API market?"):
        return MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question=question,
            description="Queue API test.",
            rules="Official result applies.",
            resolution_source="Official result",
            resolution_criteria="Use final score.",
            status=Market.Status.DRAFT,
            opens_at=opens_at,
            closes_at=closes_at,
            created_by=self.outsider,
            yes_label="Yes",
            no_label="No",
        )

    def open_market(self, market):
        market = MarketLifecycleService.submit(
            market_id=market.id, actor=self.outsider, notes="Ready."
        )
        market = MarketLifecycleService.approve(
            market_id=market.id, actor=self.actor, notes="Approved."
        )
        return MarketLifecycleService.open(market_id=market.id, actor=self.actor, notes="Opened.")


class ResultVerificationQueueAPITests(ResultVerificationQueueFixtureMixin, APITestCase):
    def queue_url(self):
        return reverse("markets:admin-result-verification-queue")

    def authenticate(self, user):
        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def test_overdue_open_market_appears_as_ready_to_close(self):
        market = self.open_market(
            self.create_market(
                opens_at=self.now - timedelta(hours=2),
                closes_at=self.now + timedelta(minutes=5),
            )
        )
        Market.objects.filter(id=market.id).update(closes_at=self.now - timedelta(minutes=5))

        self.authenticate(self.actor)
        response = self.client.get(self.queue_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = next(item for item in response.data if item["id"] == str(market.id))
        self.assertEqual(row["workflow_state"], "READY_TO_CLOSE")
        self.assertTrue(row["can_close"])
        self.assertTrue(row["can_void"])
        self.assertFalse(row["can_settle"])

    def test_not_yet_due_open_market_is_excluded_entirely(self):
        market = self.open_market(
            self.create_market(
                opens_at=self.now - timedelta(hours=1),
                closes_at=self.now + timedelta(hours=1),
            )
        )

        self.authenticate(self.actor)
        response = self.client.get(self.queue_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(any(item["id"] == str(market.id) for item in response.data))

    def test_closed_market_still_appears_as_awaiting_result(self):
        market = self.open_market(
            self.create_market(
                opens_at=self.now - timedelta(hours=1),
                closes_at=self.now + timedelta(hours=1),
            )
        )
        market = MarketLifecycleService.close(
            market_id=market.id, actor=self.actor, notes="Closed."
        )

        self.authenticate(self.actor)
        response = self.client.get(self.queue_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = next(item for item in response.data if item["id"] == str(market.id))
        self.assertEqual(row["workflow_state"], "AWAITING_RESULT")
        self.assertFalse(row["can_close"])

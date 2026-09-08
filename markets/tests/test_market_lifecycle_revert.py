from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APITestCase

from authentication.tests.factories import (
    PermissionFactory,
    RoleFactory,
    RolePermissionFactory,
    UserFactory,
    UserRoleFactory,
)
from markets.models import Market, MarketCategory, MarketOutcome, MarketScope
from markets.services.catalog_service import MarketCatalogService
from markets.services.liquidity_service import MarketLiquidityService
from markets.services.lifecycle_service import MarketLifecycleService
from sports.models import Competition, Sport, SportingEvent


class MarketRevertToDraftTests(APITestCase):
    """Covers the recovery path for a market that fails to open (e.g. a
    missing treasury provider) and gets stuck at APPROVED — see
    lifecycle_service.py::revert_to_draft."""

    def setUp(self):
        self.now = timezone.now()
        self.actor = UserFactory()
        manage_permission = PermissionFactory(
            name="manage_market", resource="market", action="manage"
        )
        approve_permission = PermissionFactory(
            name="approve_market", resource="market", action="approve"
        )
        actor_role = RoleFactory(name="Revert Test Market Operator")
        RolePermissionFactory(role=actor_role, permission=manage_permission)
        RolePermissionFactory(role=actor_role, permission=approve_permission)
        UserRoleFactory(user=self.actor, role=actor_role)
        sport = Sport.objects.create(name="Revert Test Football", code="REVERT_TEST_FOOTBALL")
        category = MarketCategory.objects.create(name="Revert Test")
        competition = Competition.objects.create(
            sport=sport, name="Revert Test League", country_code="UG", is_verified=True
        )
        event = SportingEvent.objects.create(
            sport=sport,
            competition=competition,
            event_type=SportingEvent.EventType.MATCH,
            name="Revert Test United v Revert Test City",
            starts_at=self.now,
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )
        self.market = MarketCatalogService.create_market(
            sport=sport,
            category=category,
            scope_type=MarketScope.EVENT,
            sporting_event=event,
            question="Revert test market?",
            description="Revert to draft test.",
            rules="Official result applies.",
            resolution_source="Official result",
            resolution_criteria="Use final score.",
            status=Market.Status.DRAFT,
            opens_at=self.now,
            closes_at=self.now + timedelta(hours=1),
            created_by=self.actor,
            yes_label="Yes",
            no_label="No",
        )
        # Opening prices required by activate_opening_liquidity, so the
        # failure we hit below is specifically the missing-treasury check.
        yes = self.market.outcomes.get(side=MarketOutcome.Side.YES)
        no = self.market.outcomes.get(side=MarketOutcome.Side.NO)
        yes.opening_price = Decimal("0.50000")
        no.opening_price = Decimal("0.50000")
        yes.save(update_fields=["opening_price"])
        no.save(update_fields=["opening_price"])

        MarketLiquidityService.configure(
            market=self.market, actor=self.actor, initial_liquidity_ugx=Decimal("500000")
        )

    def approve_market(self):
        MarketLifecycleService.submit(market_id=self.market.id, actor=self.actor, notes="Ready.")
        return MarketLifecycleService.approve(
            market_id=self.market.id, actor=self.actor, notes="Approved."
        )

    def test_failed_open_leaves_market_at_approved_not_corrupted(self):
        self.approve_market()

        with self.assertRaises(ValidationError):
            MarketLifecycleService.open(market_id=self.market.id, actor=self.actor, notes="Opened.")

        self.market.refresh_from_db()
        self.assertEqual(self.market.status, Market.Status.APPROVED)

    def test_revert_to_draft_recovers_a_stuck_market(self):
        self.approve_market()
        with self.assertRaises(ValidationError):
            MarketLifecycleService.open(market_id=self.market.id, actor=self.actor, notes="Opened.")

        reverted = MarketLifecycleService.revert_to_draft(
            market_id=self.market.id, actor=self.actor, notes="Missing treasury provider."
        )

        self.assertEqual(reverted.status, Market.Status.DRAFT)
        self.assertIsNone(reverted.approved_by)
        self.assertIsNone(reverted.approved_at)

    def test_revert_to_draft_rejects_markets_not_approved(self):
        # Still DRAFT — never submitted/approved.
        with self.assertRaises(ValidationError):
            MarketLifecycleService.revert_to_draft(
                market_id=self.market.id, actor=self.actor, notes="Not approved yet."
            )

    def test_market_is_editable_and_republishable_after_revert(self):
        self.approve_market()
        with self.assertRaises(ValidationError):
            MarketLifecycleService.open(market_id=self.market.id, actor=self.actor, notes="Opened.")
        MarketLifecycleService.revert_to_draft(
            market_id=self.market.id, actor=self.actor, notes="Missing treasury provider."
        )

        # Fix the root cause (drop initial liquidity to 0 so activate_opening_liquidity
        # short-circuits) and confirm the market can be resubmitted, approved, and
        # opened successfully this time.
        MarketLiquidityService.configure(
            market=self.market, actor=self.actor, initial_liquidity_ugx=Decimal("0")
        )
        opened = self.approve_market()
        opened = MarketLifecycleService.open(
            market_id=opened.id, actor=self.actor, notes="Opened for real."
        )

        self.assertEqual(opened.status, Market.Status.OPEN)

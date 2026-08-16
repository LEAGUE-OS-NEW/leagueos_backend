from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

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
    MarketSettlement,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.fill_service import MarketFillService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.matching_service import MarketMatchingService
from markets.services.participation_service import MarketParticipationService
from markets.services.resolution_service import MarketResolutionService
from markets.services.settlement_service import MarketSettlementService
from markets.tests.eligibility_test_support import make_market_eligible
from markets.tests.wallet_test_support import fund_market_wallet
from sports.models import Competition, Sport, SportingEvent


class MarketCapacityAndSettlementTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.manage_permission = PermissionFactory(
            name="manage_market", resource="market", action="manage"
        )
        self.approve_permission = PermissionFactory(
            name="approve_market", resource="market", action="approve"
        )
        self.participate_permission = PermissionFactory(
            name="participate_market", resource="market", action="participate"
        )
        self.verify_permission = PermissionFactory(
            name="verify_results", resource="market", action="verify"
        )

        self.operations_role = RoleFactory(name="Operations", display_name="Operations")
        self.approval_role = RoleFactory(name="Approval", display_name="Approval")
        self.participant_role = RoleFactory(name="Participant", display_name="Participant")
        self.verifier_role = RoleFactory(name="Verifier", display_name="Verifier")

        RolePermissionFactory(role=self.operations_role, permission=self.manage_permission)
        RolePermissionFactory(role=self.approval_role, permission=self.approve_permission)
        RolePermissionFactory(role=self.participant_role, permission=self.participate_permission)
        RolePermissionFactory(role=self.verifier_role, permission=self.verify_permission)

        self.operator = UserFactory()
        self.approver = UserFactory()
        self.verifier = UserFactory()
        UserRoleFactory(user=self.operator, role=self.operations_role)
        UserRoleFactory(user=self.approver, role=self.approval_role)
        UserRoleFactory(user=self.verifier, role=self.verifier_role)

        self.trader = UserFactory()
        UserRoleFactory(user=self.trader, role=self.participant_role)
        fund_market_wallet(self.trader)

        self.sport = Sport.objects.create(name="Football", code="FOOTBALL")
        self.category = MarketCategory.objects.create(name="Match Result")
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

    def create_market(self, max_market_amount=None, settlement_unit=5000):
        market = MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question="Will KCCA FC win?",
            description="Prediction market.",
            rules="Official result.",
            resolution_source="Official result",
            resolution_criteria="Verified score.",
            status=Market.Status.DRAFT,
            opens_at=self.now - timedelta(hours=1),
            closes_at=self.now + timedelta(hours=1),
            created_by=self.operator,
            yes_label="Yes",
            no_label="No",
            settlement_unit=settlement_unit,
            max_market_amount=max_market_amount,
        )
        from markets.services.opening_pricing_service import MarketOpeningPricingService

        return MarketOpeningPricingService.configure(
            market=market,
            actor=self.operator,
            face_value_ugx=settlement_unit,
            yes_probability=Decimal("50"),
        )

    def open_market(self, market=None):
        market = market or self.create_market()
        market = MarketLifecycleService.submit(
            market_id=market.id, actor=self.operator, notes="Ready."
        )
        market = MarketLifecycleService.approve(
            market_id=market.id, actor=self.approver, notes="Approved."
        )
        return MarketLifecycleService.open(
            market_id=market.id, actor=self.approver, notes="Opened."
        )

    def test_settlement_unit_defaults_to_5000(self):
        market = self.create_market()
        self.assertEqual(market.settlement_unit, 5000)
        self.assertEqual(market.face_value_ugx, 5000)

    def test_settlement_unit_stored_on_market(self):
        market = self.create_market(settlement_unit=5000)
        self.assertEqual(market.settlement_unit, 5000)

    def test_market_capacity_tracks_executed_buy_volume(self):
        market = self.open_market()
        market.max_market_amount = Decimal("100.0000")
        market.save(update_fields=["max_market_amount", "updated_at"])

        make_market_eligible(self.trader)
        sell_user = UserFactory()
        UserRoleFactory(user=sell_user, role=self.participant_role)
        fund_market_wallet(sell_user)
        make_market_eligible(sell_user)
        from markets.models import MarketPosition

        MarketPosition.objects.create(
            user=sell_user,
            market=market,
            outcome=market.outcomes.get(side=MarketOutcome.Side.YES),
            quantity=Decimal("100.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("40.0000"),
        )

        sell_order = MarketParticipationService.place_order(
            user=sell_user,
            market_id=market.id,
            outcome_id=market.outcomes.get(side=MarketOutcome.Side.YES).id,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("10.0000"),
            limit_price=Decimal("0.40000"),
        )

        order = MarketParticipationService.place_order(
            user=self.trader,
            market_id=market.id,
            outcome_id=market.outcomes.get(side=MarketOutcome.Side.YES).id,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("10.0000"),
            limit_price=Decimal("0.50000"),
        )
        MarketMatchingService.match_order(order.id)

        sell_order.refresh_from_db()
        self.assertEqual(sell_order.status, MarketOrder.Status.FILLED)

        market.refresh_from_db()
        self.assertGreaterEqual(market.current_market_amount, Decimal("4.0000"))
        self.assertLessEqual(market.current_market_amount, Decimal("5.1000"))

    def test_market_auto_closes_when_capacity_reached(self):
        market = self.open_market()
        market.max_market_amount = Decimal("5.0000")
        market.save(update_fields=["max_market_amount", "updated_at"])

        make_market_eligible(self.trader)
        sell_user = UserFactory()
        UserRoleFactory(user=sell_user, role=self.participant_role)
        fund_market_wallet(sell_user)
        make_market_eligible(sell_user)
        from markets.models import MarketPosition

        MarketPosition.objects.create(
            user=sell_user,
            market=market,
            outcome=market.outcomes.get(side=MarketOutcome.Side.YES),
            quantity=Decimal("100.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("40.0000"),
        )

        sell_order = MarketParticipationService.place_order(
            user=sell_user,
            market_id=market.id,
            outcome_id=market.outcomes.get(side=MarketOutcome.Side.YES).id,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("20.0000"),
            limit_price=Decimal("0.40000"),
        )

        order = MarketParticipationService.place_order(
            user=self.trader,
            market_id=market.id,
            outcome_id=market.outcomes.get(side=MarketOutcome.Side.YES).id,
            side=MarketOrder.Side.BUY,
            quantity=Decimal("20.0000"),
            limit_price=Decimal("0.50000"),
        )
        MarketMatchingService.match_order(order.id)

        sell_order.refresh_from_db()
        self.assertEqual(sell_order.status, MarketOrder.Status.FILLED)

        market.refresh_from_db()
        self.assertEqual(market.status, Market.Status.CLOSED)
        self.assertEqual(market.close_reason, Market.MarketCloseReason.MAXIMUM_AMOUNT_REACHED)

    def test_market_order_buy_places_with_amount(self):
        market = self.open_market()
        make_market_eligible(self.trader)

        sell_user = UserFactory()
        UserRoleFactory(user=sell_user, role=self.participant_role)
        fund_market_wallet(sell_user)
        make_market_eligible(sell_user)

        sell_outcome = market.outcomes.get(side=MarketOutcome.Side.YES)
        MarketPosition.objects.create(
            user=sell_user,
            market=market,
            outcome=sell_outcome,
            quantity=Decimal("100.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("40.0000"),
        )

        order = MarketParticipationService.place_order(
            user=self.trader,
            market_id=market.id,
            outcome_id=market.outcomes.get(side=MarketOutcome.Side.YES).id,
            side=MarketOrder.Side.BUY,
            quantity=None,
            limit_price=None,
            order_type=MarketOrder.OrderType.MARKET,
            amount=Decimal("10.0000"),
        )
        self.assertEqual(order.order_type, MarketOrder.OrderType.MARKET)
        self.assertIsNotNone(order.amount)

    def test_market_order_sell_places_with_quantity(self):
        market = self.open_market()
        make_market_eligible(self.trader)

        from markets.models import MarketPosition

        MarketPosition.objects.create(
            user=self.trader,
            market=market,
            outcome=market.outcomes.get(side=MarketOutcome.Side.YES),
            quantity=Decimal("20.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("8.0000"),
        )

        order = MarketParticipationService.place_order(
            user=self.trader,
            market_id=market.id,
            outcome_id=market.outcomes.get(side=MarketOutcome.Side.YES).id,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("10.0000"),
            limit_price=Decimal("0.00001"),
            order_type=MarketOrder.OrderType.MARKET,
        )
        self.assertEqual(order.order_type, MarketOrder.OrderType.MARKET)

    def test_position_available_and_locked_shares(self):
        market = self.open_market()
        position = MarketPosition.objects.create(
            user=self.trader,
            market=market,
            outcome=market.outcomes.get(side=MarketOutcome.Side.YES),
            quantity=Decimal("20.0000"),
            reserved_quantity=Decimal("5.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("8.0000"),
        )
        self.assertEqual(position.available_shares, Decimal("15.0000"))
        self.assertEqual(position.locked_shares, Decimal("5.0000"))

    def test_settlement_uses_settlement_unit_for_payout(self):
        market = self.open_market()
        market.settlement_unit = 5000
        market.save(update_fields=["settlement_unit", "updated_at"])

        winner = MarketPosition.objects.create(
            user=self.trader,
            market=market,
            outcome=market.outcomes.get(side=MarketOutcome.Side.YES),
            quantity=Decimal("10.0000"),
            average_entry_price=Decimal("0.40000"),
            total_cost=Decimal("4.0000"),
        )

        MarketLifecycleService.close(
            market_id=market.id, actor=self.approver, notes="Closed."
        )
        MarketResolutionService.resolve(
            market_id=market.id,
            actor=self.verifier,
            winning_outcome_id=market.outcomes.get(side=MarketOutcome.Side.YES).id,
            notes="Result confirmed.",
            evidence="Official result.",
        )
        settlement = MarketSettlementService.settle_market(
            market_id=market.id, actor=self.verifier
        )

        position_settlement = settlement.position_settlements.get(market_position=winner)
        self.assertEqual(position_settlement.payout_amount, Decimal("10.0000"))

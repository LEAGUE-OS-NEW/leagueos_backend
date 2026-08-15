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
from markets.admin_serializers import MarketAdminReadSerializer
from markets.models import (
    Market,
    MarketCategory,
    MarketCollateralEntry,
    MarketCollateralPool,
    MarketCompleteSetIssuance,
    MarketFill,
    MarketLiquidityProvider,
    MarketOrder,
    MarketOutcome,
    MarketPosition,
    MarketResultDevelopmentAcceleration,
    MarketScope,
)
from markets.services.catalog_service import MarketCatalogService
from markets.services.lifecycle_service import MarketLifecycleService
from markets.services.liquidity_service import MarketLiquidityService
from markets.services.opening_pricing_service import MarketOpeningPricingService
from markets.services.participation_service import MarketParticipationService
from markets.services.provisional_result_service import MarketProvisionalResultService
from markets.services.resolution_service import MarketResolutionService
from markets.services.settlement_service import MarketSettlementService
from markets.tests.eligibility_test_support import make_market_eligible
from markets.tests.wallet_test_support import fund_market_wallet
from sports.models import Competition, Sport, SportingEvent
from wallets.models import Wallet


class HybridLiquidityFinalVerificationTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        permissions = {
            name: PermissionFactory(name=name, resource="market", action=action)
            for name, action in (
                ("manage_market", "manage"),
                ("approve_market", "approve"),
                ("participate_market", "participate"),
            )
        }
        operations = RoleFactory(name="Final Hybrid Operations", display_name="Operations")
        approval = RoleFactory(name="Final Hybrid Approval", display_name="Approval")
        self.participant_role = RoleFactory(
            name="Final Hybrid Participant", display_name="Participant"
        )
        RolePermissionFactory(role=operations, permission=permissions["manage_market"])
        RolePermissionFactory(role=approval, permission=permissions["approve_market"])
        RolePermissionFactory(
            role=self.participant_role, permission=permissions["participate_market"]
        )
        self.operator = UserFactory()
        self.approver = UserFactory()
        UserRoleFactory(user=self.operator, role=operations)
        UserRoleFactory(user=self.approver, role=approval)
        self.provider_user = self.trader()
        self.provider = MarketLiquidityProvider.objects.create(
            code="PLATFORM_TREASURY",
            provider_type=MarketLiquidityProvider.ProviderType.PLATFORM_TREASURY,
            user=self.provider_user,
            display_name="Platform Treasury",
        )
        self.sport = Sport.objects.create(name="Final Hybrid Football", code="FINAL_HYBRID")
        self.category = MarketCategory.objects.create(name="Final Hybrid Result")
        self.competition = Competition.objects.create(
            sport=self.sport, name="Final Hybrid League", country_code="UG", is_verified=True
        )
        self.event = SportingEvent.objects.create(
            sport=self.sport,
            competition=self.competition,
            event_type=SportingEvent.EventType.MATCH,
            name="Final Hybrid Home vs Away",
            starts_at=self.now + timedelta(days=2),
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
            verified_at=self.now,
        )

    def trader(self):
        user = UserFactory(is_verified=True)
        UserRoleFactory(user=user, role=self.participant_role)
        make_market_eligible(user)
        fund_market_wallet(user)
        return user

    def market(self, question, liquidity="0"):
        market = MarketCatalogService.create_market(
            sport=self.sport,
            category=self.category,
            scope_type=MarketScope.EVENT,
            sporting_event=self.event,
            question=question,
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
        )
        MarketOpeningPricingService.configure(
            market=market,
            actor=self.operator,
            face_value_ugx=Decimal("10000"),
            yes_probability=60,
        )
        MarketLiquidityService.configure(
            market=market,
            actor=self.operator,
            provider=self.provider,
            initial_liquidity_ugx=Decimal(liquidity),
            opening_spread_bps=100,
        )
        MarketLifecycleService.submit(market_id=market.id, actor=self.operator, notes="Ready.")
        MarketLifecycleService.approve(market_id=market.id, actor=self.approver, notes="Approved.")
        return MarketLifecycleService.open(
            market_id=market.id, actor=self.approver, notes="Opened."
        )

    def buy(self, user, market, side, quantity, price, time_in_force="GTC"):
        return MarketParticipationService.place_order(
            user=user,
            market_id=market.id,
            outcome_id=market.outcomes.get(side=side).id,
            side=MarketOrder.Side.BUY,
            quantity=Decimal(quantity),
            limit_price=Decimal(price),
            time_in_force=time_in_force,
        )

    def settle_yes(self, market):
        yes = market.outcomes.get(side=MarketOutcome.Side.YES)
        MarketLifecycleService.close(market_id=market.id, actor=self.approver, notes="Closed.")
        provisional = MarketProvisionalResultService.publish(
            market_id=market.id,
            actor=self.approver,
            winning_outcome_id=yes.id,
            notes="Official YES result.",
            evidence_items=[
                {
                    "evidence_type": "OFFICIAL_RESULT",
                    "label": "Official result",
                    "reference": "https://league.example/results/final-hybrid",
                }
            ],
            dispute_window_hours=1,
        )
        MarketResultDevelopmentAcceleration.objects.create(
            provisional_result=provisional, accelerated_by=self.approver
        )
        MarketResolutionService.resolve(
            market_id=market.id,
            actor=self.approver,
            winning_outcome_id=yes.id,
            notes="Confirmed.",
            evidence="Official evidence reviewed.",
        )
        return MarketSettlementService.settle_market(market_id=market.id, actor=self.approver)

    def test_platform_opening_liquidity_runs_collateralized_lifecycle_to_idempotent_settlement(
        self,
    ):
        market = self.market("Will opening liquidity settle correctly?", liquidity="500000")
        pool = MarketCollateralPool.objects.get(market=market)
        self.assertEqual(pool.locked_collateral, Decimal("500000.0000"))
        provider_orders = MarketOrder.objects.filter(
            market=market, user=self.provider_user, side=MarketOrder.Side.SELL
        )
        self.assertEqual(
            set(provider_orders.values_list("outcome__side", flat=True)), {"YES", "NO"}
        )

        fan = self.trader()
        yes = market.outcomes.get(side="YES")
        provider_before = MarketPosition.objects.get(
            market=market, user=self.provider_user, outcome=yes
        ).quantity
        fan_wallet = Wallet.objects.get(user=fan, currency="UGX")
        order = self.buy(fan, market, "YES", "10", "0.60500")
        self.assertEqual(order.status, MarketOrder.Status.FILLED)
        self.assertEqual(MarketFill.objects.filter(market=market).count(), 1)
        self.assertEqual(
            MarketPosition.objects.get(
                market=market, user=self.provider_user, outcome=yes
            ).quantity,
            provider_before - Decimal("10.0000"),
        )
        self.assertEqual(
            MarketPosition.objects.get(market=market, user=fan, outcome=yes).quantity,
            Decimal("10.0000"),
        )
        pool.refresh_from_db()
        self.assertEqual(pool.locked_collateral, Decimal("500000.0000"))

        fan_wallet.refresh_from_db()
        wallet_before_settlement = fan_wallet.available_balance
        first = self.settle_yes(market)
        fan_wallet.refresh_from_db()
        self.assertEqual(
            fan_wallet.available_balance - wallet_before_settlement, Decimal("10.0000")
        )
        pool.refresh_from_db()
        self.assertEqual(pool.locked_collateral, Decimal("0.0000"))
        self.assertEqual(pool.settled_collateral, Decimal("500000.0000"))
        entry = MarketCollateralEntry.objects.get(
            market=market, entry_type=MarketCollateralEntry.EntryType.SETTLEMENT_PAYOUT
        )
        self.assertEqual(entry.amount, Decimal("500000.0000"))
        second = MarketSettlementService.settle_market(market_id=market.id, actor=self.approver)
        self.assertEqual(second.id, first.id)
        self.assertEqual(
            MarketCollateralEntry.objects.filter(
                market=market,
                entry_type=MarketCollateralEntry.EntryType.SETTLEMENT_PAYOUT,
            ).count(),
            1,
        )

    def test_complementary_issuance_settles_without_fake_order_or_fill(self):
        market = self.market("Will complementary liquidity settle correctly?")
        fan_a, fan_b = self.trader(), self.trader()
        before_orders = MarketOrder.objects.count()
        self.buy(fan_a, market, "YES", "10", "0.60000")
        before_second_order_fills = MarketFill.objects.count()
        self.buy(fan_b, market, "NO", "10", "0.40000")
        issuance = MarketCompleteSetIssuance.objects.get(market=market)
        self.assertEqual(
            issuance.yes_execution_price + issuance.no_execution_price, Decimal("1.00000")
        )
        self.assertEqual(issuance.collateral_amount, Decimal("10.0000"))
        self.assertEqual(MarketCollateralPool.objects.get(market=market).locked_collateral, 10)
        self.assertEqual(MarketOrder.objects.count(), before_orders + 2)
        self.assertEqual(MarketFill.objects.count(), before_second_order_fills)
        self.assertFalse(MarketOrder.objects.filter(market=market, side="SELL").exists())
        self.assertEqual(MarketPosition.objects.get(market=market, user=fan_a).quantity, 10)
        self.assertEqual(MarketPosition.objects.get(market=market, user=fan_b).quantity, 10)

        a_wallet = Wallet.objects.get(user=fan_a, currency="UGX")
        b_wallet = Wallet.objects.get(user=fan_b, currency="UGX")
        a_before, b_before = a_wallet.available_balance, b_wallet.available_balance
        first = self.settle_yes(market)
        a_wallet.refresh_from_db()
        b_wallet.refresh_from_db()
        self.assertEqual(a_wallet.available_balance - a_before, Decimal("10.0000"))
        self.assertEqual(b_wallet.available_balance - b_before, Decimal("0.0000"))
        pool = MarketCollateralPool.objects.get(market=market)
        self.assertEqual(
            (pool.locked_collateral, pool.settled_collateral), (Decimal("0"), Decimal("10"))
        )
        replay = MarketSettlementService.settle_market(market_id=market.id, actor=self.approver)
        self.assertEqual(replay.id, first.id)

    def _prepare_mixed_depth(self, question, complementary_quantity):
        market = self.market(question, liquidity="500000")
        seller, opposite_buyer, fok_buyer = self.trader(), self.trader(), self.trader()
        self.buy(seller, market, "YES", "4", "0.60500")
        for order in list(MarketOrder.objects.filter(market=market, user=self.provider_user)):
            order.refresh_from_db()
            if MarketParticipationService.is_order_cancellable(order):
                MarketParticipationService.cancel_order(user=self.provider_user, order_id=order.id)
        MarketParticipationService.place_order(
            user=seller,
            market_id=market.id,
            outcome_id=market.outcomes.get(side="YES").id,
            side=MarketOrder.Side.SELL,
            quantity=Decimal("4"),
            limit_price=Decimal("0.60000"),
        )
        self.buy(opposite_buyer, market, "NO", complementary_quantity, "0.40000")
        return market, fok_buyer

    def test_fok_combines_ordinary_and_complementary_depth_atomically(self):
        market, buyer = self._prepare_mixed_depth("Will mixed FOK depth fill?", "6")
        order = self.buy(buyer, market, "YES", "10", "0.60000", "FOK")
        self.assertEqual(order.status, MarketOrder.Status.FILLED)
        self.assertEqual(order.filled_quantity, Decimal("10.0000"))
        self.assertEqual(MarketFill.objects.filter(market=market).count(), 2)
        self.assertEqual(
            MarketCompleteSetIssuance.objects.filter(
                market=market,
                issuance_type=MarketCompleteSetIssuance.IssuanceType.COMPLEMENTARY_BUYS,
            ).count(),
            1,
        )

    def test_fok_insufficient_mixed_depth_has_no_partial_financial_mutations(self):
        market, buyer = self._prepare_mixed_depth("Will insufficient mixed FOK cancel?", "5")
        wallet = Wallet.objects.get(user=buyer, currency="UGX")
        before = {
            "available": wallet.available_balance,
            "reserved": wallet.reserved_balance,
            "positions": MarketPosition.objects.filter(market=market).count(),
            "collateral": MarketCollateralPool.objects.get(market=market).locked_collateral,
            "issuances": MarketCompleteSetIssuance.objects.filter(market=market).count(),
            "fills": MarketFill.objects.filter(market=market).count(),
        }
        order = self.buy(buyer, market, "YES", "10", "0.60000", "FOK")
        wallet.refresh_from_db()
        self.assertEqual((order.status, order.filled_quantity), (MarketOrder.Status.CANCELLED, 0))
        self.assertEqual(
            (wallet.available_balance, wallet.reserved_balance),
            (before["available"], before["reserved"]),
        )
        self.assertFalse(MarketPosition.objects.filter(market=market, user=buyer).exists())
        self.assertEqual(MarketPosition.objects.filter(market=market).count(), before["positions"])
        self.assertEqual(
            MarketCollateralPool.objects.get(market=market).locked_collateral, before["collateral"]
        )
        self.assertEqual(
            MarketCompleteSetIssuance.objects.filter(market=market).count(), before["issuances"]
        )
        self.assertEqual(MarketFill.objects.filter(market=market).count(), before["fills"])

    def test_quantity_and_face_value_display_contract(self):
        market = self.market("Will quantity units remain explicit?", liquidity="500000")
        data = MarketAdminReadSerializer(market).data["liquidity"]
        self.assertEqual(Decimal(data["issued_complete_sets"]), Decimal("500000.0000"))
        self.assertEqual(
            Decimal(data["issued_complete_sets"]) / Decimal(market.face_value_ugx),
            Decimal("50.0000"),
        )
        self.assertNotIn("shares", data)

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from markets.models import MarketOrder, MarketResponsibleParticipation
from markets.services.responsible_participation_service import (
    MarketResponsibleParticipationService,
)


class ResponsibleParticipationOrderGatingTests(TestCase):
    def setUp(self):
        self.participant = get_user_model().objects.create_user(
            username="order-gating", email="order-gating@example.com", password="password"
        )

    def evaluate(self, side, controls):
        return MarketResponsibleParticipationService.evaluate_order(
            participant=self.participant,
            market=None,
            outcome=None,
            side=side,
            quantity=Decimal("1"),
            limit_price=Decimal("1"),
            controls=controls,
        )

    def test_sell_does_not_increase_exposure_or_buy_commitment(self):
        controls = MarketResponsibleParticipation(
            participant=self.participant,
            max_order_notional=Decimal("1"),
            max_open_buy_commitment=Decimal("0"),
            max_market_exposure=Decimal("0"),
            max_total_exposure=Decimal("0"),
        )
        result = self.evaluate(MarketOrder.Side.SELL, controls)
        self.assertTrue(result.allowed)
        self.assertEqual(result.open_buy_commitment, Decimal("0.0000"))
        self.assertEqual(result.market_exposure, Decimal("0.0000"))
        self.assertEqual(result.total_exposure, Decimal("0.0000"))

    def test_buy_is_blocked_by_multiple_capacity_controls_once(self):
        controls = MarketResponsibleParticipation(
            participant=self.participant,
            max_order_notional=Decimal("1"),
            daily_buy_notional_limit=Decimal("0"),
            weekly_buy_notional_limit=Decimal("0"),
            max_open_buy_commitment=Decimal("0"),
            max_market_exposure=Decimal("0"),
            max_total_exposure=Decimal("0"),
        )
        result = self.evaluate(MarketOrder.Side.BUY, controls)
        self.assertFalse(result.allowed)
        self.assertEqual(len(result.reason_codes), 5)

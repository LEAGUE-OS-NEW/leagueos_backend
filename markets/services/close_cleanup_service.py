from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError

from markets.models import MarketCloseCleanup, MarketCloseOrderCancellation, MarketOrder
from markets.services.participation_service import MarketParticipationService


class MarketCloseCleanupService:
    QUANTITY_QUANTUM = Decimal("0.0001")
    MONEY_QUANTUM = Decimal("0.0001")

    @classmethod
    def cleanup_locked_market(cls, *, market, actor) -> MarketCloseCleanup:
        if MarketCloseCleanup.objects.filter(market=market).exists():
            raise ValidationError(
                {"close_cleanup": "This market already has a close cleanup audit."}
            )

        orders = list(
            MarketOrder.objects.select_for_update(of=("self",))
            .select_related("user", "market", "outcome")
            .filter(
                market=market,
                status__in=(MarketOrder.Status.OPEN, MarketOrder.Status.PARTIALLY_FILLED),
            )
            .order_by("id")
        )
        buy_count = sell_count = 0
        released_buy = released_sell = Decimal("0.0000")
        cancellation_results = []
        for order in orders:
            result = MarketParticipationService.cancel_locked_order(order=order)
            cancellation_results.append((order, result))
            if order.side == MarketOrder.Side.BUY:
                buy_count += 1
                released_buy += result["released_wallet_amount"]
            else:
                sell_count += 1
                released_sell += result["released_position_quantity"]
        cleanup = MarketCloseCleanup.objects.create(
            market=market,
            total_cancelled_order_count=len(orders),
            cancelled_buy_order_count=buy_count,
            cancelled_sell_order_count=sell_count,
            total_released_buy_reservation_amount=cls._money(released_buy),
            total_released_sell_reservation_quantity=cls._quantity(released_sell),
            executed_by=actor,
        )
        for order, result in cancellation_results:
            MarketCloseOrderCancellation.objects.create(
                market_close_cleanup=cleanup,
                market_order=order,
                order_side=order.side,
                remaining_quantity_cancelled=cls._quantity(result["remaining_quantity"]),
                released_wallet_reservation_amount=cls._money(result["released_wallet_amount"]),
                released_position_reservation_quantity=cls._quantity(
                    result["released_position_quantity"]
                ),
                wallet_release_ledger_entry=result["wallet_entry"],
            )
        return cleanup

    @classmethod
    def _quantity(cls, value):
        return Decimal(value).quantize(cls.QUANTITY_QUANTUM, rounding=ROUND_HALF_UP)

    @classmethod
    def _money(cls, value):
        return Decimal(value).quantize(cls.MONEY_QUANTUM, rounding=ROUND_HALF_UP)

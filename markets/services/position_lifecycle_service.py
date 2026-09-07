from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q, Sum

from markets.models import MarketFill, MarketPositionExit


class MarketPositionLifecycleService:
    MONEY_QUANTUM = Decimal("0.0001")
    QUANTITY_QUANTUM = Decimal("0.0001")

    @classmethod
    def record_exit(cls, *, position, closing_fill):
        existing = MarketPositionExit.objects.filter(closing_fill=closing_fill).first()
        if existing is not None:
            return existing

        previous = (
            MarketPositionExit.objects.select_for_update()
            .filter(market_position=position)
            .order_by("-exited_at", "-id")
            .first()
        )
        fills = (
            MarketFill.objects.filter(market=position.market, outcome=position.outcome)
            .filter(Q(buy_order__user=position.user) | Q(sell_order__user=position.user))
            .select_related("buy_order", "sell_order")
            .order_by("created_at", "id")
        )
        if previous is not None:
            fills = fills.filter(created_at__gt=previous.exited_at)

        prior_realized = MarketPositionExit.objects.filter(market_position=position).aggregate(
            total=Sum("realized_pnl")
        )["total"] or Decimal("0")

        acquired_quantity = Decimal("0")
        exited_quantity = Decimal("0")
        proceeds = Decimal("0")
        opened_at = closing_fill.created_at
        for fill in fills:
            if fill.buy_order.user_id == position.user_id:
                if acquired_quantity == 0:
                    opened_at = fill.created_at
                acquired_quantity += fill.quantity
            if fill.sell_order.user_id == position.user_id:
                exited_quantity += fill.quantity
                proceeds += fill.quantity * fill.price

        def money(value):
            return value.quantize(cls.MONEY_QUANTUM, rounding=ROUND_HALF_UP)

        realized_pnl = money(position.realized_pnl - prior_realized)
        if acquired_quantity == 0:
            acquired_quantity = exited_quantity
        cost_basis = money(proceeds - realized_pnl)
        return MarketPositionExit.objects.create(
            market_position=position,
            participant=position.user,
            market=position.market,
            outcome=position.outcome,
            closing_fill=closing_fill,
            opened_at=opened_at,
            exited_at=closing_fill.created_at,
            acquired_quantity=acquired_quantity.quantize(cls.QUANTITY_QUANTUM),
            exited_quantity=exited_quantity.quantize(cls.QUANTITY_QUANTUM),
            cost_basis=money(cost_basis),
            realized_proceeds=money(proceeds),
            realized_pnl=realized_pnl,
        )

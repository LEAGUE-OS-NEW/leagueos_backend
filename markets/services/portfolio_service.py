from decimal import ROUND_HALF_UP, Decimal

from django.db.models import DecimalField, F, OuterRef, Q, Subquery
from django.utils import timezone

from markets.models import Market, MarketFill, MarketOrder, MarketPosition
from markets.services.open_order_service import ParticipantOpenOrderService
from markets.services.participation_service import MarketParticipationService
from wallets.services.wallet_read_service import WalletReadService


class MarketPortfolioService:
    CURRENCY = MarketParticipationService.MARKET_CURRENCY
    MONEY_QUANTUM = Decimal("0.0001")
    QUANTITY_QUANTUM = Decimal("0.0001")
    PRICE_QUANTUM = Decimal("0.00001")

    @classmethod
    def get_summary(cls, *, user, filters=None, as_of=None):
        filters = filters or {}
        as_of = as_of or timezone.now()
        market_id = filters.get("market_id")

        position_queryset = MarketPosition.objects.filter(user=user)
        order_queryset = MarketOrder.objects.filter(
            user=user,
            status__in=ParticipantOpenOrderService.ACTIVE_STATUSES,
            quantity__gt=F("filled_quantity"),
        ).select_related("market", "outcome")
        if market_id is not None:
            position_queryset = position_queryset.filter(market_id=market_id)
            order_queryset = order_queryset.filter(market_id=market_id)

        external_bid = (
            MarketOrder.objects.filter(
                outcome_id=OuterRef("outcome_id"),
                market__status=Market.Status.OPEN,
                side=MarketOrder.Side.BUY,
                status__in=ParticipantOpenOrderService.ACTIVE_STATUSES,
                quantity__gt=F("filled_quantity"),
            )
            .exclude(user=user)
            .filter(Q(market__closes_at__isnull=True) | Q(market__closes_at__gt=as_of))
            .order_by("-limit_price", "-created_at", "-id")
            .values("limit_price")[:1]
        )
        latest_fill = (
            MarketFill.objects.filter(outcome_id=OuterRef("outcome_id"))
            .order_by("-created_at", "-id")
            .values("price")[:1]
        )
        positions = list(
            position_queryset.select_related("market", "outcome").annotate(
                external_best_bid=Subquery(
                    external_bid,
                    output_field=DecimalField(max_digits=6, decimal_places=5),
                ),
                latest_fill_price=Subquery(
                    latest_fill,
                    output_field=DecimalField(max_digits=6, decimal_places=5),
                ),
            )
        )
        orders = list(order_queryset)
        wallet = WalletReadService.get_wallet(user=user, currency=cls.CURRENCY)

        return {
            "currency": cls.CURRENCY,
            "scope": {"market_id": market_id},
            "wallet": cls._wallet_summary(wallet),
            "positions": cls._position_summary(positions),
            "orders": cls._order_summary(orders),
            "as_of": as_of,
        }

    @classmethod
    def _wallet_summary(cls, wallet):
        available = wallet.available_balance if wallet else Decimal("0")
        reserved = wallet.reserved_balance if wallet else Decimal("0")
        return {
            "exists": wallet is not None,
            "available_balance": cls._money(available),
            "reserved_balance": cls._money(reserved),
            "total_balance": cls._money(available + reserved),
        }

    @classmethod
    def _position_summary(cls, positions):
        zero = Decimal("0")
        open_positions = [position for position in positions if position.quantity > zero]
        realized = sum((position.realized_pnl for position in positions), zero)
        totals = {
            "total_quantity": zero,
            "reserved_quantity": zero,
            "total_cost_basis": zero,
            "marked_cost_basis": zero,
            "unpriced_cost_basis": zero,
            "marked_market_value": zero,
            "marked_unrealized_pnl": zero,
        }
        sources = {
            "resolution": 0,
            "void_cost_basis": 0,
            "best_bid": 0,
            "last_trade": 0,
            "unpriced": 0,
        }
        marked_count = 0
        for position in open_positions:
            totals["total_quantity"] += position.quantity
            totals["reserved_quantity"] += position.reserved_quantity
            totals["total_cost_basis"] += position.total_cost
            mark, source = cls._mark(position)
            sources[source] += 1
            if mark is None:
                totals["unpriced_cost_basis"] += position.total_cost
                continue
            marked_count += 1
            market_value = cls._money(position.quantity * mark)
            totals["marked_cost_basis"] += position.total_cost
            totals["marked_market_value"] += market_value
            totals["marked_unrealized_pnl"] += market_value - position.total_cost

        valuation_complete = marked_count == len(open_positions)
        unrealized = cls._money(totals["marked_unrealized_pnl"])
        return {
            "open_position_count": len(open_positions),
            "market_count": len({position.market_id for position in open_positions}),
            "total_quantity": cls._quantity(totals["total_quantity"]),
            "reserved_quantity": cls._quantity(totals["reserved_quantity"]),
            "available_quantity": cls._quantity(
                totals["total_quantity"] - totals["reserved_quantity"]
            ),
            "total_cost_basis": cls._money(totals["total_cost_basis"]),
            "marked_position_count": marked_count,
            "unpriced_position_count": len(open_positions) - marked_count,
            "marked_cost_basis": cls._money(totals["marked_cost_basis"]),
            "unpriced_cost_basis": cls._money(totals["unpriced_cost_basis"]),
            "marked_market_value": cls._money(totals["marked_market_value"]),
            "realized_pnl": cls._money(realized),
            "marked_unrealized_pnl": unrealized,
            "total_pnl": cls._money(realized + unrealized) if valuation_complete else None,
            "valuation_complete": valuation_complete,
            "mark_sources": sources,
        }

    @classmethod
    def _mark(cls, position):
        market = position.market
        if market.status == Market.Status.RESOLVED and market.winning_outcome_id:
            return (
                (
                    Decimal("1.00000")
                    if position.outcome_id == market.winning_outcome_id
                    else Decimal("0.00000")
                ),
                "resolution",
            )
        if market.status == Market.Status.VOIDED:
            return (
                (position.total_cost / position.quantity).quantize(
                    cls.PRICE_QUANTUM, rounding=ROUND_HALF_UP
                ),
                "void_cost_basis",
            )
        if position.external_best_bid is not None:
            return position.external_best_bid, "best_bid"
        if position.latest_fill_price is not None:
            return position.latest_fill_price, "last_trade"
        return None, "unpriced"

    @classmethod
    def _order_summary(cls, orders):
        zero = Decimal("0")
        remaining_total = zero
        reserved_buy = zero
        reserved_sell = zero
        buy_count = 0
        sell_count = 0
        for order in orders:
            remaining = order.quantity - order.filled_quantity
            remaining_total += remaining
            if order.side == MarketOrder.Side.BUY:
                buy_count += 1
                reserved_buy += MarketParticipationService.calculate_buy_cancellation_release(order)
            else:
                sell_count += 1
                reserved_sell += remaining
        return {
            "open_order_count": len(orders),
            "open_buy_order_count": buy_count,
            "open_sell_order_count": sell_count,
            "remaining_order_quantity": cls._quantity(remaining_total),
            "reserved_buy_amount": cls._money(reserved_buy),
            "reserved_sell_quantity": cls._quantity(reserved_sell),
        }

    @classmethod
    def _money(cls, value):
        return Decimal(value).quantize(cls.MONEY_QUANTUM, rounding=ROUND_HALF_UP)

    @classmethod
    def _quantity(cls, value):
        return Decimal(value).quantize(cls.QUANTITY_QUANTUM, rounding=ROUND_HALF_UP)

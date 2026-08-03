from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, OuterRef, Q, Subquery, Sum
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
    MARK_SOURCES = (
        "resolution",
        "void_cost_basis",
        "best_bid",
        "last_trade",
        "unpriced",
    )

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

        positions = list(cls._position_queryset(user=user, queryset=position_queryset, as_of=as_of))
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
    def list_positions(cls, *, user, filters=None, as_of=None):
        filters = filters or {}
        as_of = as_of or timezone.now()
        queryset = MarketPosition.objects.filter(user=user, quantity__gt=Decimal("0"))
        for field in ("market_id", "outcome_id"):
            value = filters.get(field)
            if value is not None:
                queryset = queryset.filter(**{field: value})
        market_status = filters.get("market_status")
        if market_status is not None:
            queryset = queryset.filter(market__status=market_status)
        queryset = queryset.order_by(
            F("market__closes_at").asc(nulls_last=True),
            "market__question",
            "outcome__label",
            "id",
        )
        positions = list(cls._position_queryset(user=user, queryset=queryset, as_of=as_of))
        results = []
        for position in positions:
            valuation = cls.value_position(position)
            for name, value in valuation.items():
                setattr(position, name, value)
            position.open_sell_order_count = position.active_sell_order_count or 0
            position.reserved_sell_order_quantity = (
                position.active_sell_reserved_quantity or Decimal("0.0000")
            )
            results.append(position)
        mark_source = filters.get("mark_source")
        if mark_source is not None:
            results = [position for position in results if position.mark_source == mark_source]
        valuation_complete = filters.get("valuation_complete")
        if valuation_complete is not None:
            results = [
                position
                for position in results
                if position.valuation_complete is valuation_complete
            ]
        return results

    @classmethod
    def _position_queryset(cls, *, user, queryset, as_of):
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
        remaining = ExpressionWrapper(
            F("quantity") - F("filled_quantity"),
            output_field=DecimalField(max_digits=18, decimal_places=4),
        )
        active_sells = MarketOrder.objects.filter(
            user=user,
            market_id=OuterRef("market_id"),
            outcome_id=OuterRef("outcome_id"),
            side=MarketOrder.Side.SELL,
            status__in=ParticipantOpenOrderService.ACTIVE_STATUSES,
            quantity__gt=F("filled_quantity"),
        )
        sell_count = (
            active_sells.values("market_id", "outcome_id")
            .annotate(total=Count("id"))
            .values("total")[:1]
        )
        sell_quantity = (
            active_sells.values("market_id", "outcome_id")
            .annotate(total=Sum(remaining))
            .values("total")[:1]
        )
        return queryset.select_related("market", "outcome").annotate(
            external_best_bid=Subquery(
                external_bid,
                output_field=DecimalField(max_digits=6, decimal_places=5),
            ),
            latest_fill_price=Subquery(
                latest_fill,
                output_field=DecimalField(max_digits=6, decimal_places=5),
            ),
            active_sell_order_count=Subquery(sell_count),
            active_sell_reserved_quantity=Subquery(
                sell_quantity,
                output_field=DecimalField(max_digits=18, decimal_places=4),
            ),
        )

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
            valuation = cls.value_position(position)
            sources[valuation["mark_source"]] += 1
            if not valuation["valuation_complete"]:
                totals["unpriced_cost_basis"] += position.total_cost
                continue
            marked_count += 1
            totals["marked_cost_basis"] += position.total_cost
            totals["marked_market_value"] += valuation["market_value"]
            totals["marked_unrealized_pnl"] += valuation["unrealized_pnl"]

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
    def value_position(cls, position):
        mark, source = cls._mark(position)
        if mark is None:
            return {
                "mark_price": None,
                "mark_source": source,
                "market_value": None,
                "unrealized_pnl": None,
                "total_position_pnl": None,
                "valuation_complete": False,
            }
        mark = Decimal(mark).quantize(cls.PRICE_QUANTUM, rounding=ROUND_HALF_UP)
        market_value = cls._money(position.quantity * mark)
        unrealized = cls._money(market_value - position.total_cost)
        return {
            "mark_price": mark,
            "mark_source": source,
            "market_value": market_value,
            "unrealized_pnl": unrealized,
            "total_position_pnl": cls._money(position.realized_pnl + unrealized),
            "valuation_complete": True,
        }

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

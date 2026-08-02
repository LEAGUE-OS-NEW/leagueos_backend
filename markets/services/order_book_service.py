from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, OuterRef, Subquery, Sum

from markets.models import MarketOrder, MarketOutcome
from markets.serializers import PUBLIC_MARKET_STATUSES


class MarketOrderBookService:
    ELIGIBLE_STATUSES = (
        MarketOrder.Status.OPEN,
        MarketOrder.Status.PARTIALLY_FILLED,
    )
    QUANTITY_FIELD = DecimalField(max_digits=18, decimal_places=4)

    @classmethod
    def get_order_book(
        cls,
        *,
        market_id,
        outcome_id,
        level_limit=20,
        trade_limit=20,
    ):
        outcome = MarketOutcome.objects.select_related("market").get(
            id=outcome_id,
            market_id=market_id,
            market__status__in=PUBLIC_MARKET_STATUSES,
        )
        bids, total_bid_quantity = cls._levels(
            market_id=market_id,
            outcome_id=outcome_id,
            side=MarketOrder.Side.BUY,
            limit=level_limit,
        )
        asks, total_ask_quantity = cls._levels(
            market_id=market_id,
            outcome_id=outcome_id,
            side=MarketOrder.Side.SELL,
            limit=level_limit,
        )

        recent_trades = []
        if trade_limit:
            recent_trades = list(
                outcome.fills.order_by("-created_at", "-id").values(
                    "id", "price", "quantity", "created_at"
                )[:trade_limit]
            )

        best_bid = bids[0]["price"] if bids else None
        best_ask = asks[0]["price"] if asks else None

        return {
            "market_id": outcome.market_id,
            "outcome": outcome,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": (
                best_ask - best_bid if best_bid is not None and best_ask is not None else None
            ),
            "total_bid_quantity": total_bid_quantity,
            "total_ask_quantity": total_ask_quantity,
            "bids": bids,
            "asks": asks,
            "recent_trades": recent_trades,
        }

    @classmethod
    def _levels(cls, *, market_id, outcome_id, side, limit):
        remaining = ExpressionWrapper(
            F("quantity") - F("filled_quantity"), output_field=cls.QUANTITY_FIELD
        )
        eligible = MarketOrder.objects.filter(
            market_id=market_id,
            outcome_id=outcome_id,
            side=side,
            status__in=cls.ELIGIBLE_STATUSES,
            quantity__gt=F("filled_quantity"),
        )
        total_subquery = (
            eligible.filter(side=OuterRef("side"))
            .values("side")
            .annotate(total=Sum(remaining))
            .values("total")
        )
        ordering = "-limit_price" if side == MarketOrder.Side.BUY else "limit_price"
        rows = list(
            eligible.values("side", "limit_price")
            .annotate(
                quantity=Sum(remaining),
                order_count=Count("id"),
                total_quantity=Subquery(total_subquery, output_field=cls.QUANTITY_FIELD),
            )
            .order_by(ordering)[:limit]
        )
        levels = [
            {
                "price": row["limit_price"],
                "quantity": row["quantity"],
                "order_count": row["order_count"],
            }
            for row in rows
        ]
        total = rows[0]["total_quantity"] if rows else Decimal("0.0000")
        return levels, total

from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q

from markets.models import (
    MarketCloseOrderCancellation,
    MarketFill,
    MarketOrder,
    MarketPositionSettlement,
    MarketPositionVoidRefund,
    MarketVoidOrderCancellation,
)
from markets.services.participation_service import MarketParticipationService


class MarketPortfolioActivityService:
    CURRENCY = "UGX"
    MONEY_QUANTUM = Decimal("0.0001")

    @classmethod
    def list_activity(cls, *, user, filters):
        event_type = filters.get("event_type")
        events = []
        if event_type in (None, "BUY_FILL", "SELL_FILL"):
            events.extend(cls._fill_events(user=user, filters=filters))
        if event_type in (None, "ORDER_CANCELLED"):
            events.extend(cls._manual_cancellations(user=user, filters=filters))
            events.extend(cls._cleanup_cancellations(user=user, filters=filters))
        if event_type in (None, "SETTLEMENT_WIN", "SETTLEMENT_LOSS"):
            events.extend(cls._settlements(user=user, filters=filters))
        if event_type in (None, "VOID_REFUND"):
            events.extend(cls._void_refunds(user=user, filters=filters))
        if event_type is not None:
            events = [event for event in events if event["event_type"] == event_type]
        return sorted(events, key=lambda event: (event["occurred_at"], event["id"]), reverse=True)

    @staticmethod
    def _filter(queryset, filters, *, timestamp, market="market_id", outcome="outcome_id"):
        if filters.get("market_id"):
            queryset = queryset.filter(**{market: filters["market_id"]})
        if filters.get("outcome_id"):
            queryset = queryset.filter(**{outcome: filters["outcome_id"]})
        if filters.get("occurred_from"):
            queryset = queryset.filter(**{f"{timestamp}__gte": filters["occurred_from"]})
        if filters.get("occurred_to"):
            queryset = queryset.filter(**{f"{timestamp}__lte": filters["occurred_to"]})
        return queryset

    @classmethod
    def _base(cls, *, event_id, event_type, occurred_at, market, outcome):
        return {
            "id": event_id,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "currency": cls.CURRENCY,
            "market_id": market.id,
            "outcome_id": outcome.id,
            "market_question": market.question,
            "outcome_label": outcome.label,
            "side": None,
            "order_id": None,
            "fill_id": None,
            "quantity": None,
            "price": None,
            "notional_amount": None,
            "wallet_amount": None,
            "realized_pnl_delta": None,
            "released_wallet_amount": None,
            "released_position_quantity": None,
            "cancellation_reason": None,
        }

    @classmethod
    def _fill_events(cls, *, user, filters):
        queryset = MarketFill.objects.filter(
            Q(buy_order__user=user) | Q(sell_order__user=user)
        ).select_related("market", "outcome", "buy_order", "sell_order")
        queryset = cls._filter(queryset, filters, timestamp="created_at")
        events = []
        for fill in queryset:
            fill_events = []
            if fill.buy_order.user_id == user.id:
                event = cls._base(
                    event_id=f"market-fill:{fill.id}:buy",
                    event_type="BUY_FILL",
                    occurred_at=fill.created_at,
                    market=fill.market,
                    outcome=fill.outcome,
                )
                event.update(side="BUY", order_id=fill.buy_order_id)
                fill_events.append(event)
            if fill.sell_order.user_id == user.id:
                event = cls._base(
                    event_id=f"market-fill:{fill.id}:sell",
                    event_type="SELL_FILL",
                    occurred_at=fill.created_at,
                    market=fill.market,
                    outcome=fill.outcome,
                )
                event.update(side="SELL", order_id=fill.sell_order_id)
                fill_events.append(event)
            for event in fill_events:
                event.update(
                    fill_id=fill.id,
                    quantity=fill.quantity,
                    price=fill.price,
                    notional_amount=(fill.quantity * fill.price).quantize(
                        cls.MONEY_QUANTUM, rounding=ROUND_HALF_UP
                    ),
                )
            events.extend(fill_events)
        return events

    @classmethod
    def _manual_cancellations(cls, *, user, filters):
        queryset = (
            MarketOrder.objects.filter(user=user, status=MarketOrder.Status.CANCELLED)
            .filter(close_cancellation_record__isnull=True, void_cancellation_record__isnull=True)
            .select_related("market", "outcome")
        )
        queryset = cls._filter(queryset, filters, timestamp="updated_at")
        events = []
        for order in queryset:
            remaining = order.quantity - order.filled_quantity
            event = cls._base(
                event_id=f"market-order:{order.id}:cancel",
                event_type="ORDER_CANCELLED",
                occurred_at=order.updated_at,
                market=order.market,
                outcome=order.outcome,
            )
            event.update(
                side=order.side,
                order_id=order.id,
                quantity=remaining,
                price=order.limit_price,
                cancellation_reason="MANUAL",
                released_wallet_amount=(
                    MarketParticipationService.calculate_buy_cancellation_release(order)
                    if order.side == MarketOrder.Side.BUY
                    else None
                ),
                released_position_quantity=(
                    remaining if order.side == MarketOrder.Side.SELL else None
                ),
            )
            events.append(event)
        return events

    @classmethod
    def _cleanup_cancellations(cls, *, user, filters):
        events = []
        sources = (
            (
                MarketCloseOrderCancellation,
                "market_close_cleanup",
                "MARKET_CLOSE",
                "market-close-cancellation",
            ),
            (
                MarketVoidOrderCancellation,
                "market_void_refund",
                "MARKET_VOID",
                "market-void-cancellation",
            ),
        )
        for model, parent, reason, prefix in sources:
            queryset = model.objects.filter(market_order__user=user).select_related(
                "market_order__market", "market_order__outcome", parent
            )
            queryset = cls._filter(
                queryset,
                filters,
                timestamp="created_at",
                market="market_order__market_id",
                outcome="market_order__outcome_id",
            )
            for row in queryset:
                order = row.market_order
                event = cls._base(
                    event_id=f"{prefix}:{row.id}:cancel",
                    event_type="ORDER_CANCELLED",
                    occurred_at=row.created_at or getattr(row, parent).executed_at,
                    market=order.market,
                    outcome=order.outcome,
                )
                event.update(
                    side=row.order_side,
                    order_id=order.id,
                    quantity=row.remaining_quantity_cancelled,
                    price=order.limit_price,
                    cancellation_reason=reason,
                    released_wallet_amount=(
                        row.released_wallet_reservation_amount
                        if row.order_side == MarketOrder.Side.BUY
                        else None
                    ),
                    released_position_quantity=(
                        row.released_position_reservation_quantity
                        if row.order_side == MarketOrder.Side.SELL
                        else None
                    ),
                )
                events.append(event)
        return events

    @classmethod
    def _settlements(cls, *, user, filters):
        queryset = MarketPositionSettlement.objects.filter(participant=user).select_related(
            "market_settlement__market", "outcome"
        )
        queryset = cls._filter(
            queryset,
            filters,
            timestamp="created_at",
            market="market_settlement__market_id",
        )
        events = []
        for row in queryset:
            kind = "win" if row.was_winner else "loss"
            event = cls._base(
                event_id=f"position-settlement:{row.id}:{kind}",
                event_type=f"SETTLEMENT_{kind.upper()}",
                occurred_at=row.created_at or row.market_settlement.executed_at,
                market=row.market_settlement.market,
                outcome=row.outcome,
            )
            event.update(
                quantity=row.settled_quantity,
                wallet_amount=row.net_payout_amount,
                realized_pnl_delta=row.realized_pnl_delta,
            )
            events.append(event)
        return events

    @classmethod
    def _void_refunds(cls, *, user, filters):
        queryset = MarketPositionVoidRefund.objects.filter(participant=user).select_related(
            "market_void_refund__market", "outcome"
        )
        queryset = cls._filter(
            queryset,
            filters,
            timestamp="created_at",
            market="market_void_refund__market_id",
        )
        events = []
        for row in queryset:
            event = cls._base(
                event_id=f"position-void-refund:{row.id}:refund",
                event_type="VOID_REFUND",
                occurred_at=row.created_at or row.market_void_refund.executed_at,
                market=row.market_void_refund.market,
                outcome=row.outcome,
            )
            event.update(
                quantity=row.refunded_quantity,
                wallet_amount=row.net_refund_amount,
                realized_pnl_delta=row.realized_pnl_delta,
            )
            events.append(event)
        return events

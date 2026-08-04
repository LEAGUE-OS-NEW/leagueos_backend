from decimal import Decimal
from uuid import uuid5

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from markets.models import Market, MarketFill, MarketOrder
from markets.services.fill_service import MarketFillService


class MarketMatchingService:
    FILLABLE_STATUSES = {
        MarketOrder.Status.OPEN,
        MarketOrder.Status.PARTIALLY_FILLED,
    }

    @classmethod
    @transaction.atomic
    def match_order(cls, order_id) -> list[MarketFill]:
        taker = cls._get_locked_order(order_id)
        if not cls._is_fillable(taker):
            return []
        if (
            taker.market.status != Market.Status.OPEN
            or taker.market.closes_at is None
            or timezone.now() >= taker.market.closes_at
        ):
            return []

        candidate_ids = cls._candidate_ids(taker)
        makers = cls._lock_and_prioritize_makers(
            taker=taker,
            candidate_ids=candidate_ids,
        )
        if taker.time_in_force == MarketOrder.TimeInForce.FOK:
            required = taker.quantity - taker.filled_quantity
            available = sum(
                (
                    maker.quantity - maker.filled_quantity
                    for maker in makers
                    if cls._is_eligible_maker(taker=taker, maker=maker)
                ),
                Decimal("0.0000"),
            )
            if available < required:
                return []
        fills = []

        for maker in makers:
            if not cls._is_fillable(taker):
                break
            if not cls._is_eligible_maker(taker=taker, maker=maker):
                continue

            taker_remaining = taker.quantity - taker.filled_quantity
            maker_remaining = maker.quantity - maker.filled_quantity
            quantity = min(taker_remaining, maker_remaining)
            if quantity <= Decimal("0.0000"):
                continue

            fill = MarketFillService.execute_fill(
                execution_reference=cls._execution_reference(
                    taker=taker,
                    maker=maker,
                ),
                buy_order_id=(taker.id if taker.side == MarketOrder.Side.BUY else maker.id),
                sell_order_id=(taker.id if taker.side == MarketOrder.Side.SELL else maker.id),
                maker_order_id=maker.id,
                taker_order_id=taker.id,
                quantity=quantity,
                price=maker.limit_price,
            )
            fills.append(fill)
            taker.refresh_from_db()
            maker.refresh_from_db()

        return fills

    @staticmethod
    def _get_locked_order(order_id) -> MarketOrder:
        return (
            MarketOrder.objects.select_for_update(of=("self",))
            .select_related("user", "market", "outcome")
            .get(id=order_id)
        )

    @classmethod
    def _candidate_ids(cls, taker: MarketOrder) -> list:
        queryset = (
            MarketOrder.objects.filter(
                market_id=taker.market_id,
                outcome_id=taker.outcome_id,
                status__in=cls.FILLABLE_STATUSES,
                quantity__gt=F("filled_quantity"),
            )
            .exclude(user_id=taker.user_id)
            .exclude(id=taker.id)
            .exclude(
                time_in_force=MarketOrder.TimeInForce.GTD,
                expires_at__lte=timezone.now(),
            )
        )

        if taker.side == MarketOrder.Side.BUY:
            queryset = queryset.filter(
                side=MarketOrder.Side.SELL,
                limit_price__lte=taker.limit_price,
            ).order_by("limit_price", "created_at", "id")
        else:
            queryset = queryset.filter(
                side=MarketOrder.Side.BUY,
                limit_price__gte=taker.limit_price,
            ).order_by("-limit_price", "created_at", "id")

        return list(queryset.values_list("id", flat=True))

    @classmethod
    def _lock_and_prioritize_makers(
        cls,
        *,
        taker: MarketOrder,
        candidate_ids: list,
    ) -> list[MarketOrder]:
        if not candidate_ids:
            return []

        locked = list(
            MarketOrder.objects.select_for_update(of=("self",))
            .select_related("user", "market", "outcome")
            .filter(id__in=candidate_ids)
            .order_by("id")
        )
        eligible = [maker for maker in locked if cls._is_eligible_maker(taker=taker, maker=maker)]
        reverse_price = taker.side == MarketOrder.Side.SELL
        return sorted(
            eligible,
            key=lambda maker: (
                -maker.limit_price if reverse_price else maker.limit_price,
                maker.created_at,
                maker.id,
            ),
        )

    @classmethod
    def _is_fillable(cls, order: MarketOrder) -> bool:
        return (
            order.status in cls.FILLABLE_STATUSES
            and order.quantity - order.filled_quantity > Decimal("0.0000")
            and not (
                order.time_in_force == MarketOrder.TimeInForce.GTD
                and order.expires_at is not None
                and order.expires_at <= timezone.now()
            )
        )

    @classmethod
    def _is_eligible_maker(
        cls,
        *,
        taker: MarketOrder,
        maker: MarketOrder,
    ) -> bool:
        if not cls._is_fillable(maker):
            return False
        if maker.market_id != taker.market_id or maker.outcome_id != taker.outcome_id:
            return False
        if maker.user_id == taker.user_id or maker.side == taker.side:
            return False
        if taker.side == MarketOrder.Side.BUY:
            return maker.limit_price <= taker.limit_price
        return maker.limit_price >= taker.limit_price

    @staticmethod
    def _execution_reference(
        *,
        taker: MarketOrder,
        maker: MarketOrder,
    ):
        return uuid5(
            taker.id,
            f"{maker.id}:{taker.filled_quantity}:{maker.filled_quantity}",
        )

from markets.models import MarketOrder


class ParticipantOpenOrderService:
    ACTIVE_STATUSES = (
        MarketOrder.Status.OPEN,
        MarketOrder.Status.PARTIALLY_FILLED,
    )

    @classmethod
    def list_open_orders(cls, *, user, filters):
        queryset = MarketOrder.objects.filter(
            user=user,
            status__in=cls.ACTIVE_STATUSES,
        ).select_related("market", "outcome")

        for field in ("market_id", "outcome_id", "side", "status"):
            value = filters.get(field)
            if value is not None:
                queryset = queryset.filter(**{field: value})

        return queryset.order_by("-created_at", "-id")

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from markets.models import MarketFill

FOUR_PLACES = Decimal("0.0001")


class MarketPriceHistoryService:
    AGGREGATE_MAX_RANGES = {
        "HOUR": timedelta(days=31),
        "DAY": timedelta(days=730),
    }

    @classmethod
    def resolve_aggregate_range(cls, *, interval, start=None, end=None):
        """
        Return a complete, bounded time range for aggregated history.

        Caller-supplied timestamps are never shifted. Missing timestamps receive
        deterministic defaults so HOUR and DAY requests cannot scan unlimited
        history.
        """
        maximum = cls.AGGREGATE_MAX_RANGES[interval]

        if start is None and end is None:
            end = timezone.now()
            start = end - maximum
        elif start is None:
            start = end - maximum
        elif end is None:
            end = start + maximum

        if start > end:
            raise ValueError("start must be before or equal to end")

        if end - start > maximum:
            raise ValueError(f"{interval} history cannot exceed {maximum.days} days")

        return start, end

    @classmethod
    def history(
        cls,
        *,
        market_id,
        outcome_id,
        interval,
        start=None,
        end=None,
        limit=200,
    ):
        fills = MarketFill.objects.filter(
            market_id=market_id,
            outcome_id=outcome_id,
        ).only(
            "id",
            "created_at",
            "price",
            "quantity",
        )

        if interval in cls.AGGREGATE_MAX_RANGES:
            start, end = cls.resolve_aggregate_range(
                interval=interval,
                start=start,
                end=end,
            )

        if start is not None:
            fills = fills.filter(created_at__gte=start)

        if end is not None:
            fills = fills.filter(created_at__lte=end)

        fills = fills.order_by("created_at", "id")

        if interval == "RAW":
            # RAW limit applies to immutable executed fill points.
            return [
                {
                    "fill_id": fill.id,
                    "executed_at": fill.created_at,
                    "price": fill.price.quantize(
                        FOUR_PLACES,
                        rounding=ROUND_HALF_UP,
                    ),
                    "quantity": fill.quantity.quantize(
                        FOUR_PLACES,
                        rounding=ROUND_HALF_UP,
                    ),
                }
                for fill in fills[:limit]
            ]

        # Aggregated limits apply to complete buckets, never source fills.
        # The validated time range bounds the source query.
        project_timezone = ZoneInfo(settings.TIME_ZONE)
        buckets = {}

        for fill in fills:
            local_time = timezone.localtime(
                fill.created_at,
                project_timezone,
            )

            if interval == "HOUR":
                bucket_start = local_time.replace(
                    minute=0,
                    second=0,
                    microsecond=0,
                )
            else:
                bucket_start = local_time.replace(
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0,
                )

            bucket = buckets.setdefault(
                bucket_start,
                {
                    "bucket_start": bucket_start,
                    "open": fill.price,
                    "high": fill.price,
                    "low": fill.price,
                    "close": fill.price,
                    "volume": Decimal("0.0000"),
                    "trade_count": 0,
                },
            )

            bucket["high"] = max(bucket["high"], fill.price)
            bucket["low"] = min(bucket["low"], fill.price)
            bucket["close"] = fill.price
            bucket["volume"] += fill.quantity
            bucket["trade_count"] += 1

        completed_buckets = list(buckets.values())

        for bucket in completed_buckets:
            for field in (
                "open",
                "high",
                "low",
                "close",
                "volume",
            ):
                bucket[field] = bucket[field].quantize(
                    FOUR_PLACES,
                    rounding=ROUND_HALF_UP,
                )

        # Fill ordering makes dictionary insertion order chronological.
        return completed_buckets[:limit]

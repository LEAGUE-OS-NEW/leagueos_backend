from rest_framework import serializers

from markets.services.price_history_service import MarketPriceHistoryService


class PriceHistoryQuerySerializer(serializers.Serializer):
    interval = serializers.ChoiceField(
        choices=["RAW", "HOUR", "DAY"],
        default="RAW",
    )
    start = serializers.DateTimeField(required=False)
    end = serializers.DateTimeField(required=False)
    limit = serializers.IntegerField(
        min_value=1,
        max_value=1000,
        default=200,
    )

    def to_internal_value(self, data):
        for field in ("start", "end"):
            value = data.get(field)

            if (
                isinstance(value, str)
                and value
                and not (value.endswith("Z") or "+" in value[10:] or "-" in value[10:])
            ):
                raise serializers.ValidationError(
                    {field: ("A timezone-aware ISO-8601 timestamp " "is required.")}
                )

        return super().to_internal_value(data)

    def validate(self, attrs):
        interval = attrs["interval"]
        start = attrs.get("start")
        end = attrs.get("end")

        if start is not None and end is not None and start > end:
            raise serializers.ValidationError({"code": "market_price_history_invalid_range"})

        if interval in MarketPriceHistoryService.AGGREGATE_MAX_RANGES:
            try:
                start, end = MarketPriceHistoryService.resolve_aggregate_range(
                    interval=interval,
                    start=start,
                    end=end,
                )
            except ValueError as error:
                raise serializers.ValidationError(
                    {
                        "code": "market_price_history_invalid_range",
                        "detail": str(error),
                    }
                ) from error

            attrs["start"] = start
            attrs["end"] = end

        return attrs


class RawPricePointSerializer(serializers.Serializer):
    fill_id = serializers.UUIDField()
    executed_at = serializers.DateTimeField()
    price = serializers.DecimalField(
        max_digits=6,
        decimal_places=4,
    )
    quantity = serializers.DecimalField(
        max_digits=18,
        decimal_places=4,
    )


class OHLCVPriceBucketSerializer(serializers.Serializer):
    bucket_start = serializers.DateTimeField()
    open = serializers.DecimalField(
        max_digits=6,
        decimal_places=4,
    )
    high = serializers.DecimalField(
        max_digits=6,
        decimal_places=4,
    )
    low = serializers.DecimalField(
        max_digits=6,
        decimal_places=4,
    )
    close = serializers.DecimalField(
        max_digits=6,
        decimal_places=4,
    )
    volume = serializers.DecimalField(
        max_digits=22,
        decimal_places=4,
    )
    trade_count = serializers.IntegerField()


class PriceHistoryResponseSerializer(serializers.Serializer):
    market_id = serializers.UUIDField()
    outcome_id = serializers.UUIDField()
    interval = serializers.ChoiceField(choices=["RAW", "HOUR", "DAY"])
    start = serializers.DateTimeField(
        allow_null=True,
        required=False,
    )
    end = serializers.DateTimeField(
        allow_null=True,
        required=False,
    )
    points = serializers.ListField()


class RawPriceHistoryResponseSerializer(PriceHistoryResponseSerializer):
    points = RawPricePointSerializer(many=True)


class OHLCVPriceHistoryResponseSerializer(PriceHistoryResponseSerializer):
    points = OHLCVPriceBucketSerializer(many=True)


class PriceHistoryErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    errors = serializers.JSONField(required=False)
    detail = serializers.CharField(required=False)

import uuid

from rest_framework import serializers


class MarketSportStatsSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    code = serializers.CharField()
    slug = serializers.CharField()
    total_markets = serializers.IntegerField()
    open_markets = serializers.IntegerField()
    live_markets = serializers.IntegerField()
    featured_open_markets = serializers.IntegerField()
    total_volume_ugx = serializers.DecimalField(
        max_digits=24,
        decimal_places=2,
    )
    trader_count = serializers.IntegerField()


class MarketStatsSerializer(serializers.Serializer):
    total_markets = serializers.IntegerField()
    open_markets = serializers.IntegerField()
    live_markets = serializers.IntegerField()
    featured_open_markets = serializers.IntegerField()
    total_volume_ugx = serializers.DecimalField(
        max_digits=24,
        decimal_places=2,
    )
    trader_count = serializers.IntegerField()
    sports = MarketSportStatsSerializer(
        many=True,
    )


class MarketAdminStatsQuerySerializer(serializers.Serializer):
    market_ids = serializers.CharField(
        required=True,
        allow_blank=False,
    )

    def validate_market_ids(self, value):
        raw_ids = [item.strip() for item in value.split(",") if item.strip()]

        if not raw_ids:
            raise serializers.ValidationError(
                "At least one market id is required.",
            )

        parsed_ids = []

        for raw_id in raw_ids:
            try:
                parsed_ids.append(uuid.UUID(raw_id))
            except (ValueError, AttributeError, TypeError) as error:
                raise serializers.ValidationError(
                    f"'{raw_id}' is not a valid UUID.",
                ) from error

        return parsed_ids


class MarketAdminStatItemSerializer(serializers.Serializer):
    market_id = serializers.UUIDField()
    total_volume_ugx = serializers.DecimalField(
        max_digits=24,
        decimal_places=2,
    )
    fill_count = serializers.IntegerField()


class MarketAdminStatsSerializer(serializers.Serializer):
    markets = MarketAdminStatItemSerializer(
        many=True,
    )

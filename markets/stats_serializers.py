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

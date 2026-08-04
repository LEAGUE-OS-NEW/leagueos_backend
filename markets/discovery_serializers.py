from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from markets.models import MarketRecentView, MarketWatchlistEntry
from markets.serializers import MarketPublicSerializer


class MarketWatchlistEntrySerializer(serializers.ModelSerializer):
    market = serializers.SerializerMethodField()

    class Meta:
        model = MarketWatchlistEntry
        fields = ["market", "followed_at"]

    @extend_schema_field(MarketPublicSerializer)
    def get_market(self, obj):
        obj.market.is_watchlisted = True
        return MarketPublicSerializer(obj.market).data


class MarketRecentViewSerializer(serializers.ModelSerializer):
    market = MarketPublicSerializer(read_only=True)
    is_watchlisted = serializers.BooleanField(read_only=True)

    class Meta:
        model = MarketRecentView
        fields = [
            "market",
            "first_viewed_at",
            "last_viewed_at",
            "view_count",
            "is_watchlisted",
        ]


class MarketDiscoveryQuerySerializer(serializers.Serializer):
    section_limit = serializers.IntegerField(min_value=1, max_value=20, default=5)


class MarketDiscoveryResponseSerializer(serializers.Serializer):
    watchlist = MarketWatchlistEntrySerializer(many=True)
    recently_viewed = MarketRecentViewSerializer(many=True)
    related_markets = MarketPublicSerializer(many=True)

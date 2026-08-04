from django.contrib.auth import get_user_model
from django.db import transaction

from markets.models import Market, MarketWatchlistEntry
from markets.services.discovery_common import visible_market_query


class MarketWatchlistService:
    @classmethod
    @transaction.atomic
    def follow(cls, *, participant, market_id):
        get_user_model().objects.select_for_update().get(pk=participant.pk)
        market = Market.objects.filter(visible_market_query()).get(pk=market_id)
        return MarketWatchlistEntry.objects.get_or_create(participant=participant, market=market)

    @staticmethod
    def unfollow(*, participant, market_id):
        MarketWatchlistEntry.objects.filter(participant=participant, market_id=market_id).delete()

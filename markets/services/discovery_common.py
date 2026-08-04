from django.db.models import Q

from markets.models import Market, MarketEventGroup
from markets.serializers import PUBLIC_MARKET_STATUSES

ACTIVE_DISCOVERABLE_MARKET_STATUSES = (Market.Status.OPEN,)


def visible_market_query():
    return Q(status__in=PUBLIC_MARKET_STATUSES) & (
        Q(event_group__isnull=True) | Q(event_group__status=MarketEventGroup.Status.PUBLISHED)
    )

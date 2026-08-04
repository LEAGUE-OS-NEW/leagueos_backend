from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from markets.models import Market, MarketRecentView
from markets.services.discovery_common import visible_market_query


class MarketRecentViewService:
    @classmethod
    @transaction.atomic
    def record(cls, *, participant, market_id):
        get_user_model().objects.select_for_update().get(pk=participant.pk)
        market = Market.objects.filter(visible_market_query()).get(pk=market_id)
        now = timezone.now()
        row, created = MarketRecentView.objects.get_or_create(
            participant=participant,
            market=market,
            defaults={"first_viewed_at": now, "last_viewed_at": now, "view_count": 1},
        )
        if not created:
            row.last_viewed_at = now
            row.view_count += 1
            row.save(update_fields=["last_viewed_at", "view_count", "updated_at"])
        return row, created

    @staticmethod
    def remove(*, participant, market_id):
        MarketRecentView.objects.filter(participant=participant, market_id=market_id).delete()

    @staticmethod
    def clear(*, participant):
        MarketRecentView.objects.filter(participant=participant).delete()

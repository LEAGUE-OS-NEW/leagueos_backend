from decimal import Decimal

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.models import (
    Market,
    MarketFill,
)
from markets.services.discovery_common import (
    visible_market_query,
)
from sports.models import (
    Sport,
    SportingEvent,
)


class MarketStatsView(APIView):
    """Public statistics derived from real market records."""

    permission_classes = [AllowAny]

    def get(self, request):
        sports = list(
            Sport.objects.filter(
                is_active=True,
            ).order_by("name")
        )

        market_rows = list(
            Market.objects.filter(
                visible_market_query(),
            ).select_related(
                "sport",
                "sporting_event",
            )
        )

        stats_by_sport = {
            sport.id: {
                "id": str(sport.id),
                "name": sport.name,
                "code": sport.code,
                "slug": sport.slug,
                "total_markets": 0,
                "open_markets": 0,
                "live_markets": 0,
                "featured_open_markets": 0,
                "total_volume_ugx": Decimal("0"),
                "trader_ids": set(),
            }
            for sport in sports
        }

        total_open = 0
        total_live = 0
        total_featured = 0

        for market in market_rows:
            sport_stats = stats_by_sport.get(
                market.sport_id,
            )

            if sport_stats is None:
                continue

            sport_stats["total_markets"] += 1

            if market.status == Market.Status.OPEN:
                sport_stats["open_markets"] += 1
                total_open += 1

                if market.is_featured:
                    sport_stats["featured_open_markets"] += 1
                    total_featured += 1

                if (
                    market.sporting_event_id
                    and market.sporting_event.status == SportingEvent.Status.LIVE
                ):
                    sport_stats["live_markets"] += 1
                    total_live += 1

        market_ids = [market.id for market in market_rows]

        total_volume = Decimal("0")
        all_trader_ids = set()

        if market_ids:
            fills = (
                MarketFill.objects.filter(
                    market_id__in=market_ids,
                )
                .values(
                    "market__sport_id",
                    "quantity",
                    "price",
                    "buy_order__user_id",
                    "sell_order__user_id",
                )
                .iterator()
            )

            for fill in fills:
                sport_id = fill["market__sport_id"]

                sport_stats = stats_by_sport.get(
                    sport_id,
                )

                quantity = Decimal(
                    str(fill["quantity"]),
                )
                price = Decimal(
                    str(fill["price"]),
                )
                notional = quantity * price

                total_volume += notional

                if sport_stats is not None:
                    sport_stats["total_volume_ugx"] += notional

                for trader_key in (
                    "buy_order__user_id",
                    "sell_order__user_id",
                ):
                    trader_id = fill[trader_key]

                    if trader_id is None:
                        continue

                    all_trader_ids.add(
                        trader_id,
                    )

                    if sport_stats is not None:
                        sport_stats["trader_ids"].add(
                            trader_id,
                        )

        sport_payload = []

        for sport in sports:
            item = stats_by_sport[sport.id]

            sport_payload.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "code": item["code"],
                    "slug": item["slug"],
                    "total_markets": item["total_markets"],
                    "open_markets": item["open_markets"],
                    "live_markets": item["live_markets"],
                    "featured_open_markets": item["featured_open_markets"],
                    "total_volume_ugx": str(
                        item["total_volume_ugx"].quantize(
                            Decimal("0.01"),
                        )
                    ),
                    "trader_count": len(
                        item["trader_ids"],
                    ),
                }
            )

        return Response(
            {
                "total_markets": len(
                    market_rows,
                ),
                "open_markets": total_open,
                "live_markets": total_live,
                "featured_open_markets": (total_featured),
                "total_volume_ugx": str(
                    total_volume.quantize(
                        Decimal("0.01"),
                    )
                ),
                "trader_count": len(
                    all_trader_ids,
                ),
                "sports": sport_payload,
            }
        )

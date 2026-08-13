from decimal import Decimal

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.models import (
    Market,
    MarketFill,
)
from markets.permissions import HasMarketAdminAccess
from markets.services.discovery_common import (
    visible_market_query,
)
from markets.stats_serializers import (
    MarketAdminStatsQuerySerializer,
    MarketAdminStatsSerializer,
    MarketStatsSerializer,
)
from sports.models import (
    Sport,
    SportingEvent,
)


class MarketStatsView(APIView):
    """Public statistics derived from real market records."""

    permission_classes = [AllowAny]
    serializer_class = MarketStatsSerializer

    @extend_schema(
        operation_id="market_stats_retrieve",
        responses={
            200: MarketStatsSerializer,
        },
        tags=["Markets"],
        description=(
            "Return public market counts plus "
            "fill-derived UGX volume and unique "
            "trader counts, overall and by sport."
        ),
    )
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


class MarketAdminStatsView(APIView):
    """Admin-only per-market volume and fill counts, keyed by market id."""

    permission_classes = [
        IsAuthenticated,
        HasMarketAdminAccess,
    ]
    serializer_class = MarketAdminStatsSerializer

    @extend_schema(
        operation_id="market_admin_stats_retrieve",
        parameters=[
            MarketAdminStatsQuerySerializer,
        ],
        responses={
            200: MarketAdminStatsSerializer,
        },
        tags=["Market Administration"],
        description=(
            "Return fill-derived UGX volume and fill counts "
            "for the requested market ids, for admin use. "
            "No public-visibility filtering is applied — "
            "markets in any status are eligible."
        ),
    )
    def get(self, request):
        query = MarketAdminStatsQuerySerializer(
            data=request.query_params,
        )
        query.is_valid(raise_exception=True)
        requested_market_ids = query.validated_data["market_ids"]

        markets = Market.objects.filter(
            id__in=requested_market_ids,
        )

        stats_by_market = {
            market.id: {
                "market_id": str(market.id),
                "total_volume_ugx": Decimal("0"),
                "fill_count": 0,
            }
            for market in markets
        }

        if stats_by_market:
            fills = (
                MarketFill.objects.filter(
                    market_id__in=stats_by_market.keys(),
                )
                .values(
                    "market_id",
                    "quantity",
                    "price",
                )
                .iterator()
            )

            for fill in fills:
                market_stats = stats_by_market.get(
                    fill["market_id"],
                )

                if market_stats is None:
                    continue

                quantity = Decimal(str(fill["quantity"]))
                price = Decimal(str(fill["price"]))

                market_stats["total_volume_ugx"] += quantity * price
                market_stats["fill_count"] += 1

        markets_payload = [
            {
                "market_id": item["market_id"],
                "total_volume_ugx": str(
                    item["total_volume_ugx"].quantize(
                        Decimal("0.01"),
                    )
                ),
                "fill_count": item["fill_count"],
            }
            for item in stats_by_market.values()
        ]

        return Response(
            {
                "markets": markets_payload,
            }
        )

from django.db.models import Case, Exists, IntegerField, OuterRef, Value, When
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from markets.discovery_serializers import (
    MarketDiscoveryQuerySerializer,
    MarketDiscoveryResponseSerializer,
    MarketRecentViewSerializer,
    MarketWatchlistEntrySerializer,
)
from markets.models import MarketRecentView, MarketWatchlistEntry
from markets.serializers import MarketPublicSerializer
from markets.services.discovery_common import ACTIVE_DISCOVERABLE_MARKET_STATUSES
from markets.services.recent_view_service import MarketRecentViewService
from markets.services.watchlist_service import MarketWatchlistService
from markets.views import catalogue_market_queryset
from system.pagination import PublicCatalogPagination


def preference_market_relations(queryset):
    return queryset.select_related(
        "market",
        "market__sport",
        "market__category",
        "market__template",
        "market__event_group",
        "market__sporting_event",
        "market__sporting_event__sport",
        "market__sporting_event__competition",
        "market__sporting_event__competition__sport",
        "market__competition",
        "market__competition__sport",
        "market__participant",
        "market__participant__sport",
        "market__winning_outcome",
        "market__liquidity_configuration__provider",
        "market__settlement",
        "market__void_refund",
    ).prefetch_related(
        "market__outcomes",
        "market__sporting_event__event_participants__participant",
        "market__sporting_event__event_participants__participant__sport",
    )


class MarketWatchlistView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MarketWatchlistEntrySerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        visible_ids = catalogue_market_queryset(self.request.user).values("id")
        return preference_market_relations(
            MarketWatchlistEntry.objects.filter(
                participant=self.request.user, market_id__in=visible_ids
            )
        ).order_by("-followed_at", "-id")


class MarketWatchlistItemView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MarketWatchlistEntrySerializer

    @extend_schema(
        responses={200: MarketWatchlistEntrySerializer, 201: MarketWatchlistEntrySerializer}
    )
    def put(self, request, market_id):
        try:
            row, created = MarketWatchlistService.follow(
                participant=request.user, market_id=market_id
            )
        except row_market_does_not_exist():
            return Response(
                {"code": "market_watchlist_market_unavailable"},
                status=status.HTTP_404_NOT_FOUND,
            )
        market = catalogue_market_queryset(request.user).get(pk=row.market_id)
        row.market = market
        return Response(
            MarketWatchlistEntrySerializer(row).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(operation_id="markets_recently_viewed_clear", responses={204: None})
    def delete(self, request, market_id):
        MarketWatchlistService.unfollow(participant=request.user, market_id=market_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


def row_market_does_not_exist():
    from markets.models import Market

    return Market.DoesNotExist


class MarketRecentlyViewedView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MarketRecentViewSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        markets = catalogue_market_queryset(self.request.user)
        return (
            preference_market_relations(
                MarketRecentView.objects.filter(
                    participant=self.request.user, market_id__in=markets.values("id")
                )
            )
            .annotate(
                is_watchlisted=Exists(
                    MarketWatchlistEntry.objects.filter(
                        participant=self.request.user, market_id=OuterRef("market_id")
                    )
                )
            )
            .order_by("-last_viewed_at", "-id")
        )

    @extend_schema(operation_id="markets_recently_viewed_item_destroy", responses={204: None})
    def delete(self, request, *args, **kwargs):
        MarketRecentViewService.clear(participant=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MarketRecentlyViewedItemView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MarketRecentViewSerializer

    @extend_schema(responses={200: MarketRecentViewSerializer, 201: MarketRecentViewSerializer})
    def put(self, request, market_id):
        try:
            row, created = MarketRecentViewService.record(
                participant=request.user, market_id=market_id
            )
        except row_market_does_not_exist():
            return Response(
                {"code": "market_recent_view_market_unavailable"},
                status=status.HTTP_404_NOT_FOUND,
            )
        row.market = catalogue_market_queryset(request.user).get(pk=row.market_id)
        return Response(
            MarketRecentViewSerializer(row).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(responses={204: None})
    def delete(self, request, market_id):
        MarketRecentViewService.remove(participant=request.user, market_id=market_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MarketDiscoveryView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MarketDiscoveryResponseSerializer

    @extend_schema(
        parameters=[MarketDiscoveryQuerySerializer],
        responses=MarketDiscoveryResponseSerializer,
    )
    def get(self, request):
        query = MarketDiscoveryQuerySerializer(data=request.query_params)
        if not query.is_valid():
            return Response(
                {"code": "market_discovery_invalid_section_limit", "errors": query.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        limit = query.validated_data["section_limit"]
        related_limit = 10 if "section_limit" not in request.query_params else limit
        markets = catalogue_market_queryset(request.user)
        visible_ids = markets.values("id")
        watchlist = list(
            preference_market_relations(
                MarketWatchlistEntry.objects.filter(
                    participant=request.user, market_id__in=visible_ids
                )
            ).order_by("-followed_at", "-id")[:limit]
        )
        recent = list(
            preference_market_relations(
                MarketRecentView.objects.filter(participant=request.user, market_id__in=visible_ids)
            )
            .annotate(
                is_watchlisted=Exists(
                    MarketWatchlistEntry.objects.filter(
                        participant=request.user, market_id=OuterRef("market_id")
                    )
                )
            )
            .order_by("-last_viewed_at", "-id")[:limit]
        )
        source_ids = {row.market_id for row in watchlist} | {row.market_id for row in recent}
        sources = list(markets.filter(id__in=source_ids))
        group_ids = {m.event_group_id for m in sources if m.event_group_id}
        event_ids = {m.sporting_event_id for m in sources if m.sporting_event_id}
        category_ids = {m.category_id for m in sources}
        sport_ids = {m.sport_id for m in sources}
        related = (
            markets.filter(status__in=ACTIVE_DISCOVERABLE_MARKET_STATUSES)
            .exclude(id__in=source_ids)
            .annotate(
                relevance=Case(
                    When(event_group_id__in=group_ids, then=Value(400)),
                    When(sporting_event_id__in=event_ids, then=Value(300)),
                    When(category_id__in=category_ids, then=Value(200)),
                    When(sport_id__in=sport_ids, then=Value(100)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )
            .order_by("-relevance", "closes_at", "id")[:related_limit]
        )
        for row in watchlist:
            row.market = next((m for m in sources if m.id == row.market_id), row.market)
        for row in recent:
            row.market = next((m for m in sources if m.id == row.market_id), row.market)
        data = {
            "watchlist": MarketWatchlistEntrySerializer(watchlist, many=True).data,
            "recently_viewed": MarketRecentViewSerializer(recent, many=True).data,
            "related_markets": MarketPublicSerializer(related, many=True).data,
        }
        return Response(data)

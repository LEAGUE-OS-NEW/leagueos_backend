from django.db.models import BooleanField, Exists, OuterRef, Prefetch, Q, Value
from drf_spectacular.utils import extend_schema
from rest_framework.generics import (
    ListAPIView,
    RetrieveAPIView,
)
from rest_framework.permissions import AllowAny

from markets.models import (
    Market,
    MarketCategory,
    MarketFill,
    MarketOrder,
    MarketWatchlistEntry,
)
from markets.serializers import (
    MarketCategoryPublicSerializer,
    MarketListQuerySerializer,
    MarketPublicSerializer,
)
from markets.services.discovery_common import visible_market_query
from system.pagination import PublicCatalogPagination


def public_market_queryset(user=None):
    queryset = (
        Market.objects.filter(visible_market_query())
        .select_related(
            "sport",
            "category",
            "template",
            "event_group",
            "sporting_event",
            "sporting_event__sport",
            "sporting_event__competition",
            "sporting_event__competition__sport",
            "competition",
            "competition__sport",
            "participant",
            "participant__sport",
            "winning_outcome",
            "liquidity_configuration__provider",
        )
        .prefetch_related(
            "outcomes",
            Prefetch(
                "orders",
                queryset=MarketOrder.objects.select_related("outcome"),
                to_attr="snapshot_orders",
            ),
            Prefetch(
                "fills",
                queryset=MarketFill.objects.select_related(
                    "outcome", "buy_order", "sell_order"
                ).order_by("-created_at", "-id"),
                to_attr="snapshot_fills",
            ),
            "sporting_event__event_participants__participant",
            "sporting_event__event_participants__participant__sport",
        )
    )
    if user is not None and user.is_authenticated:
        return queryset.annotate(
            is_watchlisted=Exists(
                MarketWatchlistEntry.objects.filter(participant=user, market_id=OuterRef("pk"))
            )
        )
    return queryset.annotate(is_watchlisted=Value(False, output_field=BooleanField()))


def catalogue_market_queryset(user=None):
    """
    Public markets that should appear in browse/discovery surfaces.

    Historical markets can remain publicly addressable by ID while being
    removed from the active catalogue.
    """
    return public_market_queryset(user).filter(
        is_catalog_visible=True,
    )


class MarketCategoryListView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = MarketCategoryPublicSerializer
    pagination_class = PublicCatalogPagination
    queryset = MarketCategory.objects.filter(
        is_active=True,
    ).order_by(
        "display_order",
        "name",
    )

    @extend_schema(tags=["Markets"])
    def get(self, request, *args, **kwargs):
        return super().get(
            request,
            *args,
            **kwargs,
        )


class PublicMarketQuerysetMixin:
    def get_public_queryset(self):
        return public_market_queryset(self.request.user)

    def get_catalogue_queryset(self):
        return catalogue_market_queryset(
            self.request.user,
        )


class MarketListView(
    PublicMarketQuerysetMixin,
    ListAPIView,
):
    permission_classes = [AllowAny]
    serializer_class = MarketPublicSerializer
    pagination_class = PublicCatalogPagination

    @extend_schema(
        parameters=[
            MarketListQuerySerializer,
        ],
        tags=["Markets"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(
            request,
            *args,
            **kwargs,
        )

    def get_queryset(self):
        query = MarketListQuerySerializer(
            data=self.request.query_params,
        )
        query.is_valid(
            raise_exception=True,
        )
        filters = query.validated_data

        market_status = filters.get("status") or Market.Status.OPEN

        queryset = self.get_catalogue_queryset().filter(
            status=market_status,
        )

        if sport_id := filters.get("sport"):
            queryset = queryset.filter(
                sport_id=sport_id,
            )

        if category_id := filters.get("category"):
            queryset = queryset.filter(
                category_id=category_id,
            )

        if event_group_id := filters.get("event_group_id"):
            queryset = queryset.filter(event_group_id=event_group_id)

        if sporting_event_id := filters.get("sporting_event_id"):
            queryset = queryset.filter(sporting_event_id=sporting_event_id)

        if scope_type := filters.get("scope_type"):
            queryset = queryset.filter(
                scope_type=scope_type,
            )

        if "is_featured" in self.request.query_params:
            queryset = queryset.filter(
                is_featured=filters["is_featured"],
            )

        if search := filters.get("search"):
            queryset = queryset.filter(
                Q(question__icontains=search)
                | Q(description__icontains=search)
                | Q(custom_subject__icontains=(search))
                | Q(sporting_event__name__icontains=(search))
                | Q(competition__name__icontains=(search))
                | Q(participant__name__icontains=(search))
            )

        return queryset.order_by(
            "-is_featured",
            "closes_at",
            "-created_at",
        )


class MarketDetailView(
    PublicMarketQuerysetMixin,
    RetrieveAPIView,
):
    permission_classes = [AllowAny]
    serializer_class = MarketPublicSerializer
    lookup_field = "id"
    lookup_url_kwarg = "market_id"

    @extend_schema(tags=["Markets"])
    def get(self, request, *args, **kwargs):
        return super().get(
            request,
            *args,
            **kwargs,
        )

    def get_queryset(self):
        return self.get_public_queryset()

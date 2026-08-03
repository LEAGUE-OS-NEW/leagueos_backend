from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.permissions import (
    IsAuthenticated,
)
from rest_framework.response import Response

from markets.admin_serializers import (
    MarketAdminListQuerySerializer,
    MarketAdminReadSerializer,
    MarketAdminWriteSerializer,
)
from markets.models import Market
from markets.permissions import (
    HasMarketAdminAccess,
)
from system.pagination import (
    PublicCatalogPagination,
)


class MarketAdminQuerysetMixin:
    def get_admin_queryset(self):
        return Market.objects.select_related(
            "sport",
            "category",
            "template",
            "event_group",
            "sporting_event",
            "sporting_event__sport",
            "sporting_event__competition",
            ("sporting_event__" "competition__sport"),
            "competition",
            "competition__sport",
            "participant",
            "participant__sport",
            "created_by",
            "approved_by",
            "resolved_by",
            "winning_outcome",
        ).prefetch_related(
            "outcomes",
            "status_transitions__actor",
            ("sporting_event__" "event_participants__" "participant"),
            ("sporting_event__" "event_participants__" "participant__sport"),
        )


class MarketAdminListCreateView(
    MarketAdminQuerysetMixin,
    ListCreateAPIView,
):
    permission_classes = [
        IsAuthenticated,
        HasMarketAdminAccess,
    ]
    pagination_class = PublicCatalogPagination
    serializer_class = MarketAdminReadSerializer

    def get_serializer_class(self):
        if self.request.method == "POST":
            return MarketAdminWriteSerializer

        return MarketAdminReadSerializer

    def get_queryset(self):
        query = MarketAdminListQuerySerializer(
            data=self.request.query_params,
        )
        query.is_valid(
            raise_exception=True,
        )
        filters = query.validated_data

        queryset = self.get_admin_queryset()

        if sport_id := filters.get("sport"):
            queryset = queryset.filter(
                sport_id=sport_id,
            )

        if category_id := filters.get("category"):
            queryset = queryset.filter(
                category_id=category_id,
            )

        if scope_type := filters.get("scope_type"):
            queryset = queryset.filter(
                scope_type=scope_type,
            )

        if market_status := filters.get("status"):
            queryset = queryset.filter(
                status=market_status,
            )

        if search := filters.get("search"):
            queryset = queryset.filter(
                Q(question__icontains=search)
                | Q(description__icontains=search)
                | Q(custom_subject__icontains=(search))
                | Q(sporting_event__name__icontains=(search))
                | Q(competition__name__icontains=(search))
                | Q(participant__name__icontains=(search))
                | Q(created_by__email__icontains=(search))
            )

        return queryset.distinct().order_by(
            "-updated_at",
            "-created_at",
        )

    @extend_schema(
        parameters=[
            MarketAdminListQuerySerializer,
        ],
        responses=MarketAdminReadSerializer,
        tags=["Market Administration"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(
            request,
            *args,
            **kwargs,
        )

    @extend_schema(
        request=MarketAdminWriteSerializer,
        responses={
            201: MarketAdminReadSerializer,
        },
        tags=["Market Administration"],
    )
    def post(self, request, *args, **kwargs):
        return super().post(
            request,
            *args,
            **kwargs,
        )

    def create(self, request, *args, **kwargs):
        serializer = MarketAdminWriteSerializer(
            data=request.data,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(
            raise_exception=True,
        )
        market = serializer.save()

        market = self.get_admin_queryset().get(
            id=market.id,
        )

        response_serializer = MarketAdminReadSerializer(
            market,
            context=(self.get_serializer_context()),
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )


class MarketAdminDetailView(
    MarketAdminQuerysetMixin,
    RetrieveUpdateAPIView,
):
    permission_classes = [
        IsAuthenticated,
        HasMarketAdminAccess,
    ]
    serializer_class = MarketAdminReadSerializer
    lookup_field = "id"
    lookup_url_kwarg = "market_id"
    http_method_names = [
        "get",
        "patch",
        "head",
        "options",
    ]

    def get_queryset(self):
        return self.get_admin_queryset()

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return MarketAdminWriteSerializer

        return MarketAdminReadSerializer

    @extend_schema(
        responses=MarketAdminReadSerializer,
        tags=["Market Administration"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(
            request,
            *args,
            **kwargs,
        )

    @extend_schema(
        request=MarketAdminWriteSerializer,
        responses=MarketAdminReadSerializer,
        tags=["Market Administration"],
    )
    def patch(
        self,
        request,
        *args,
        **kwargs,
    ):
        return super().patch(
            request,
            *args,
            **kwargs,
        )

    def update(
        self,
        request,
        *args,
        **kwargs,
    ):
        partial = kwargs.pop(
            "partial",
            False,
        )
        instance = self.get_object()

        serializer = MarketAdminWriteSerializer(
            instance,
            data=request.data,
            partial=partial,
            context=self.get_serializer_context(),
        )
        serializer.is_valid(
            raise_exception=True,
        )
        market = serializer.save()

        market = self.get_admin_queryset().get(
            id=market.id,
        )

        response_serializer = MarketAdminReadSerializer(
            market,
            context=(self.get_serializer_context()),
        )

        return Response(response_serializer.data)

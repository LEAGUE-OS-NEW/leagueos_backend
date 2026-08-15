from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, F, Q
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.event_serializers import (
    MarketAttachmentSerializer,
    MarketEventErrorSerializer,
    MarketEventListQuerySerializer,
    MarketEventPublicSerializer,
    MarketEventWriteSerializer,
)
from markets.models import Market, MarketEventGroup
from markets.permissions import (
    HasApproveMarketPermission,
    HasManageMarketPermission,
    HasMarketAdminAccess,
)
from markets.serializers import PUBLIC_MARKET_STATUSES, MarketPublicSerializer
from markets.services.event_service import MarketEventService
from system.pagination import PublicCatalogPagination


def event_queryset():
    return MarketEventGroup.objects.select_related("category", "sporting_event").annotate(
        market_count=Count("markets", filter=Q(markets__status__in=PUBLIC_MARKET_STATUSES)),
        open_market_count=Count("markets", filter=Q(markets__status=Market.Status.OPEN)),
    )


class PublicEventQueryMixin:
    def filtered_queryset(self):
        query = MarketEventListQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        qs = event_queryset().filter(status=MarketEventGroup.Status.PUBLISHED)
        for field in ("event_type", "category_id", "sporting_event_id"):
            if value := values.get(field):
                qs = qs.filter(**{field: value})
        if value := values.get("scheduled_from"):
            qs = qs.filter(scheduled_at__gte=value)
        if value := values.get("scheduled_to"):
            qs = qs.filter(scheduled_at__lte=value)
        if value := values.get("search"):
            qs = qs.filter(Q(title__icontains=value) | Q(description__icontains=value))
        return qs.order_by(F("scheduled_at").asc(nulls_last=True), "title", "id")


class MarketEventListView(PublicEventQueryMixin, ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = MarketEventPublicSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        return self.filtered_queryset()


class MarketEventDetailView(RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = MarketEventPublicSerializer
    lookup_url_kwarg = "event_id"
    lookup_field = "id"

    def get_queryset(self):
        return event_queryset().filter(status=MarketEventGroup.Status.PUBLISHED)


class MarketEventMarketListView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = MarketPublicSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        return (
            Market.objects.filter(
                event_group_id=self.kwargs["event_id"],
                event_group__status=MarketEventGroup.Status.PUBLISHED,
                status__in=PUBLIC_MARKET_STATUSES,
            )
            .select_related(
                "sport",
                "category",
                "template",
                "event_group",
                "sporting_event",
                "sporting_event__sport",
                "sporting_event__competition",
                "competition",
                "participant",
                "winning_outcome",
                "liquidity_configuration__provider",
            )
            .prefetch_related("outcomes", "sporting_event__event_participants__participant")
        )


class AdminMarketEventListCreateView(ListCreateAPIView):
    permission_classes = [IsAuthenticated, HasMarketAdminAccess]
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        return event_queryset().order_by("-created_at")

    def get_serializer_class(self):
        return (
            MarketEventWriteSerializer
            if self.request.method == "POST"
            else MarketEventPublicSerializer
        )


class AdminMarketEventDetailView(RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, HasMarketAdminAccess]
    serializer_class = MarketEventWriteSerializer
    lookup_url_kwarg = "event_id"
    lookup_field = "id"
    http_method_names = ["get", "patch", "head", "options"]
    queryset = MarketEventGroup.objects.all()


class AdminMarketEventLifecycleView(APIView):
    permission_classes = [IsAuthenticated, HasApproveMarketPermission]
    serializer_class = MarketEventPublicSerializer
    action = None

    @extend_schema(
        responses={
            200: MarketEventPublicSerializer,
            400: MarketEventErrorSerializer,
            403: MarketEventErrorSerializer,
            404: MarketEventErrorSerializer,
        }
    )
    def post(self, request, event_id):
        try:
            group = getattr(MarketEventService, self.action)(event_id=event_id, actor=request.user)
        except DjangoValidationError as error:
            return Response(error.message_dict, status=status.HTTP_400_BAD_REQUEST)
        return Response(MarketEventPublicSerializer(event_queryset().get(id=group.id)).data)


class AdminMarketEventPublishView(AdminMarketEventLifecycleView):
    action = "publish"


class AdminMarketEventArchiveView(AdminMarketEventLifecycleView):
    action = "archive"


class AdminMarketEventAttachView(APIView):
    permission_classes = [IsAuthenticated, HasManageMarketPermission]
    serializer_class = MarketAttachmentSerializer

    @extend_schema(
        responses={
            200: MarketAttachmentSerializer,
            400: MarketEventErrorSerializer,
            403: MarketEventErrorSerializer,
            404: MarketEventErrorSerializer,
            409: MarketEventErrorSerializer,
        }
    )
    def post(self, request, event_id):
        serializer = MarketAttachmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            market = MarketEventService.attach_market(
                event_id=event_id, market_id=serializer.validated_data["market_id"]
            )
        except DjangoValidationError as error:
            code = error.message_dict.get("code", [""])[0]
            return Response(
                error.message_dict,
                status=(
                    status.HTTP_409_CONFLICT
                    if code == "market_event_market_conflict"
                    else status.HTTP_400_BAD_REQUEST
                ),
            )
        return Response({"event_id": str(event_id), "market_id": str(market.id)})


class AdminMarketEventDetachView(APIView):
    permission_classes = [IsAuthenticated, HasManageMarketPermission]
    serializer_class = MarketAttachmentSerializer

    def delete(self, request, event_id, market_id):
        MarketEventService.detach_market(event_id=event_id, market_id=market_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

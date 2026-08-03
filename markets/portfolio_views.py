from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.models import Market
from markets.portfolio_position_serializers import (
    MarketPortfolioPositionFilterSerializer,
    MarketPortfolioPositionSerializer,
)
from markets.portfolio_serializers import (
    MarketPortfolioFilterSerializer,
    MarketPortfolioSummarySerializer,
)
from markets.services.portfolio_service import MarketPortfolioService
from system.pagination import PublicCatalogPagination


class MarketPortfolioSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "market_id",
                type={"type": "string", "format": "uuid"},
                description="Optionally restrict positions and order exposure to one market.",
            )
        ],
        responses=MarketPortfolioSummarySerializer,
        tags=["Market Participation"],
        description=(
            "Return the authenticated participant's read-only UGX portfolio summary. "
            "Money and quantities use four decimal places. total_pnl is null when any "
            "positive position is unpriced; mark_sources reports valuation coverage."
        ),
    )
    def get(self, request):
        filter_serializer = MarketPortfolioFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        summary = MarketPortfolioService.get_summary(
            user=request.user,
            filters=filter_serializer.validated_data,
        )
        return Response(MarketPortfolioSummarySerializer(summary).data)


class MarketPortfolioPositionListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MarketPortfolioPositionSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        filters = MarketPortfolioPositionFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return MarketPortfolioService.list_positions(
            user=self.request.user,
            filters=filters.validated_data,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("market_id", type={"type": "string", "format": "uuid"}),
            OpenApiParameter("outcome_id", type={"type": "string", "format": "uuid"}),
            OpenApiParameter("market_status", type=str, enum=Market.Status.values),
            OpenApiParameter("mark_source", type=str, enum=MarketPortfolioService.MARK_SOURCES),
            OpenApiParameter("valuation_complete", type=bool),
        ],
        responses=MarketPortfolioPositionSerializer(many=True),
        tags=["Market Participation"],
        description=(
            "Return the authenticated participant's positive current positions "
            "with valuation details."
        ),
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

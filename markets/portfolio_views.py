from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.portfolio_serializers import (
    MarketPortfolioFilterSerializer,
    MarketPortfolioSummarySerializer,
)
from markets.services.portfolio_service import MarketPortfolioService


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

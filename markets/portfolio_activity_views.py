from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from markets.portfolio_activity_serializers import (
    MarketPortfolioActivityFilterSerializer,
    MarketPortfolioActivitySerializer,
)
from markets.services.portfolio_activity_service import MarketPortfolioActivityService
from system.pagination import PublicCatalogPagination


class MarketPortfolioActivityListView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MarketPortfolioActivitySerializer
    pagination_class = PublicCatalogPagination

    @extend_schema(
        parameters=[
            OpenApiParameter("market_id", type={"type": "string", "format": "uuid"}),
            OpenApiParameter("outcome_id", type={"type": "string", "format": "uuid"}),
            OpenApiParameter(
                "event_type",
                type=str,
                enum=list(MarketPortfolioActivityFilterSerializer().fields["event_type"].choices),
            ),
            OpenApiParameter("occurred_from", type={"type": "string", "format": "date-time"}),
            OpenApiParameter("occurred_to", type={"type": "string", "format": "date-time"}),
        ],
        responses=MarketPortfolioActivitySerializer(many=True),
        tags=["Market Participation"],
        description=(
            "Return the authenticated participant's read-only, paginated UGX market "
            "activity across fills, cancellations, settlements, and void refunds."
        ),
    )
    def get(self, request):
        filters = MarketPortfolioActivityFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        activity = MarketPortfolioActivityService.list_activity(
            user=request.user, filters=filters.validated_data
        )
        page = self.paginate_queryset(activity)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

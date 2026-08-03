from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from markets.open_order_serializers import (
    ParticipantOpenOrderFilterSerializer,
    ParticipantOpenOrderSerializer,
)
from markets.services.open_order_service import ParticipantOpenOrderService
from system.pagination import PublicCatalogPagination


class ParticipantOpenOrderListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ParticipantOpenOrderSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        filters = ParticipantOpenOrderFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return ParticipantOpenOrderService.list_open_orders(
            user=self.request.user,
            filters=filters.validated_data,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter("market_id", type={"type": "string", "format": "uuid"}),
            OpenApiParameter("outcome_id", type={"type": "string", "format": "uuid"}),
            OpenApiParameter("side", type=str, enum=["BUY", "SELL"]),
            OpenApiParameter("status", type=str, enum=["OPEN", "PARTIALLY_FILLED"]),
        ],
        responses=ParticipantOpenOrderSerializer(many=True),
        tags=["Market Participation"],
        description=(
            "Return the authenticated participant's active OPEN and " "PARTIALLY_FILLED orders."
        ),
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

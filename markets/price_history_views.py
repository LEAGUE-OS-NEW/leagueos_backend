from drf_spectacular.utils import (
    PolymorphicProxySerializer,
    extend_schema,
)
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.models import MarketOutcome
from markets.price_history_serializers import (
    OHLCVPriceHistoryResponseSerializer,
    PriceHistoryErrorSerializer,
    PriceHistoryQuerySerializer,
    RawPriceHistoryResponseSerializer,
)
from markets.services.price_history_service import (
    MarketPriceHistoryService,
)
from markets.views import public_market_queryset


class MarketOutcomePriceHistoryView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[PriceHistoryQuerySerializer],
        responses={
            200: PolymorphicProxySerializer(
                component_name="MarketPriceHistoryResponse",
                serializers=[
                    RawPriceHistoryResponseSerializer,
                    OHLCVPriceHistoryResponseSerializer,
                ],
                resource_type_field_name="interval",
            ),
            400: PriceHistoryErrorSerializer,
            404: PriceHistoryErrorSerializer,
        },
        description=(
            "Read-only executed-price history from immutable fills. "
            "RAW limit means executed fill points. HOUR and DAY limits "
            "mean complete OHLCV buckets. HOUR requests are bounded to "
            "31 days and DAY requests to 730 days. Buckets use the "
            "configured Africa/Kampala timezone. Open-order quotes, "
            "current mutable prices and unmatched bids are excluded."
        ),
        tags=["Markets"],
    )
    def get(self, request, market_id, outcome_id):
        market_exists = public_market_queryset(request.user).filter(pk=market_id).exists()

        if not market_exists:
            return Response(
                {"code": "market_price_history_outcome_mismatch"},
                status=status.HTTP_404_NOT_FOUND,
            )

        outcome_exists = MarketOutcome.objects.filter(
            pk=outcome_id,
            market_id=market_id,
        ).exists()

        if not outcome_exists:
            return Response(
                {"code": "market_price_history_outcome_mismatch"},
                status=status.HTTP_404_NOT_FOUND,
            )

        query = PriceHistoryQuerySerializer(data=request.query_params)

        if not query.is_valid():
            errors = query.errors

            if "interval" in errors:
                code = "market_price_history_invalid_interval"
            elif "limit" in errors:
                code = "market_price_history_invalid_limit"
            else:
                code = "market_price_history_invalid_range"

            return Response(
                {
                    "code": code,
                    "errors": errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        values = query.validated_data
        interval = values["interval"]

        points = MarketPriceHistoryService.history(
            market_id=market_id,
            outcome_id=outcome_id,
            interval=interval,
            start=values.get("start"),
            end=values.get("end"),
            limit=values["limit"],
        )

        response_data = {
            "market_id": market_id,
            "outcome_id": outcome_id,
            "interval": interval,
            "start": values.get("start"),
            "end": values.get("end"),
            "points": points,
        }

        serializer_class = (
            RawPriceHistoryResponseSerializer
            if interval == "RAW"
            else OHLCVPriceHistoryResponseSerializer
        )

        return Response(serializer_class(response_data).data)

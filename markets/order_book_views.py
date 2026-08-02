from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.models import MarketOutcome
from markets.order_book_serializers import (
    MarketOrderBookQuerySerializer,
    MarketOrderBookSerializer,
)
from markets.services.order_book_service import MarketOrderBookService


class MarketOrderBookView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[MarketOrderBookQuerySerializer],
        responses={200: MarketOrderBookSerializer},
        tags=["Markets"],
    )
    def get(self, request, market_id, outcome_id):
        query = MarketOrderBookQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            book = MarketOrderBookService.get_order_book(
                market_id=market_id,
                outcome_id=outcome_id,
                level_limit=query.validated_data["levels"],
                trade_limit=query.validated_data["trades"],
            )
        except MarketOutcome.DoesNotExist as error:
            raise Http404 from error
        return Response(MarketOrderBookSerializer(book).data)

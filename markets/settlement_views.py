from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.models import Market
from markets.permissions import HasResultVerificationPermission
from markets.services.settlement_service import MarketSettlementService
from markets.settlement_serializers import (
    MarketSettlementRequestSerializer,
    MarketSettlementSerializer,
)


class MarketSettlementView(APIView):
    permission_classes = [IsAuthenticated, HasResultVerificationPermission]

    @extend_schema(
        request=MarketSettlementRequestSerializer,
        responses=MarketSettlementSerializer,
        tags=["Market Administration"],
    )
    def post(self, request, market_id):
        get_object_or_404(Market, id=market_id)
        request_serializer = MarketSettlementRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        try:
            settlement = MarketSettlementService.settle_market(
                market_id=market_id,
                actor=request.user,
            )
        except DjangoValidationError as error:
            if hasattr(error, "message_dict"):
                raise serializers.ValidationError(error.message_dict) from error
            raise serializers.ValidationError({"non_field_errors": error.messages}) from error
        return Response(MarketSettlementSerializer(settlement).data)

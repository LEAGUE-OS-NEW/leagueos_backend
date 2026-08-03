from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.models import Market
from markets.permissions import HasApproveMarketPermission
from markets.services.void_refund_service import MarketVoidRefundService
from markets.void_refund_serializers import (
    MarketVoidRefundRequestSerializer,
    MarketVoidRefundSerializer,
)


class MarketVoidRefundView(APIView):
    permission_classes = [IsAuthenticated, HasApproveMarketPermission]

    @extend_schema(
        request=MarketVoidRefundRequestSerializer,
        responses=MarketVoidRefundSerializer,
        tags=["Market Administration"],
    )
    def post(self, request, market_id):
        get_object_or_404(Market, id=market_id)
        request_serializer = MarketVoidRefundRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        try:
            refund = MarketVoidRefundService.refund_void_market(
                market_id=market_id, actor=request.user
            )
        except DjangoValidationError as error:
            if hasattr(error, "message_dict"):
                raise serializers.ValidationError(error.message_dict) from error
            raise serializers.ValidationError({"non_field_errors": error.messages}) from error
        return Response(MarketVoidRefundSerializer(refund).data)

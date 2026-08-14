from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.generics import GenericAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from markets.models import Market, MarketProvisionalResult
from markets.permissions import HasResultVerificationPermission
from markets.provisional_result_serializers import (
    MarketProvisionalResultPublishSerializer,
    MarketProvisionalResultReadSerializer,
)
from markets.services.discovery_common import visible_market_query
from markets.services.provisional_result_service import (
    MarketProvisionalResultService,
)


class MarketProvisionalResultPublishView(GenericAPIView):
    permission_classes = [
        IsAuthenticated,
        HasResultVerificationPermission,
    ]
    serializer_class = MarketProvisionalResultPublishSerializer

    @extend_schema(
        request=MarketProvisionalResultPublishSerializer,
        responses={
            201: MarketProvisionalResultReadSerializer,
        },
        tags=["Market Administration"],
    )
    def post(
        self,
        request,
        market_id,
    ):
        get_object_or_404(
            Market,
            id=market_id,
        )

        serializer = self.get_serializer(
            data=request.data,
        )
        serializer.is_valid(
            raise_exception=True,
        )

        try:
            provisional_result = MarketProvisionalResultService.publish(
                market_id=market_id,
                actor=request.user,
                winning_outcome_id=(serializer.validated_data["winning_outcome_id"]),
                notes=serializer.validated_data["notes"],
                evidence_items=(serializer.validated_data["evidence_items"]),
                dispute_window_hours=(serializer.validated_data["dispute_window_hours"]),
            )
        except DjangoValidationError as error:
            self.raise_api_validation_error(error)

        response_serializer = MarketProvisionalResultReadSerializer(
            provisional_result,
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def raise_api_validation_error(
        error: DjangoValidationError,
    ) -> None:
        if hasattr(error, "message_dict"):
            raise serializers.ValidationError(error.message_dict) from error

        raise serializers.ValidationError(
            {
                "non_field_errors": error.messages,
            }
        ) from error


class MarketProvisionalResultDetailView(RetrieveAPIView):
    permission_classes = [AllowAny]
    serializer_class = MarketProvisionalResultReadSerializer
    lookup_field = "market_id"
    lookup_url_kwarg = "market_id"

    @extend_schema(
        responses=MarketProvisionalResultReadSerializer,
        tags=["Markets"],
    )
    def get(
        self,
        request,
        *args,
        **kwargs,
    ):
        return super().get(
            request,
            *args,
            **kwargs,
        )

    def get_queryset(self):
        visible_market_ids = Market.objects.filter(visible_market_query()).values("id")

        return (
            MarketProvisionalResult.objects.filter(
                market_id__in=visible_market_ids,
            )
            .select_related(
                "market",
                "winning_outcome",
            )
            .prefetch_related(
                "evidence_items",
            )
        )

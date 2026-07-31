from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import (
    IsAuthenticated,
)
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.admin_serializers import (
    MarketAdminReadSerializer,
    MarketResolveSerializer,
    MarketVoidSerializer,
)
from markets.admin_views import (
    MarketAdminQuerysetMixin,
)
from markets.models import Market
from markets.permissions import (
    HasApproveMarketPermission,
)
from markets.services.resolution_service import (
    MarketResolutionService,
)


class MarketResolutionActionView(
    MarketAdminQuerysetMixin,
    APIView,
):
    permission_classes = [
        IsAuthenticated,
        HasApproveMarketPermission,
    ]

    def get_market_response(
        self,
        *,
        market_id,
        request,
    ) -> Response:
        market = self.get_admin_queryset().get(
            id=market_id,
        )

        serializer = MarketAdminReadSerializer(
            market,
            context={
                "request": request,
            },
        )

        return Response(serializer.data)

    @staticmethod
    def raise_api_validation_error(
        error: DjangoValidationError,
    ) -> None:
        if hasattr(error, "message_dict"):
            raise serializers.ValidationError(error.message_dict) from error

        raise serializers.ValidationError(
            {
                "non_field_errors": (error.messages),
            }
        ) from error


class MarketResolveView(MarketResolutionActionView):
    @extend_schema(
        request=MarketResolveSerializer,
        responses=MarketAdminReadSerializer,
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

        serializer = MarketResolveSerializer(
            data=request.data,
        )
        serializer.is_valid(
            raise_exception=True,
        )

        try:
            market = MarketResolutionService.resolve(
                market_id=market_id,
                actor=request.user,
                winning_outcome_id=(serializer.validated_data["winning_outcome_id"]),
                notes=(serializer.validated_data["notes"]),
                evidence=(serializer.validated_data["evidence"]),
            )
        except DjangoValidationError as error:
            self.raise_api_validation_error(error)

        return self.get_market_response(
            market_id=market.id,
            request=request,
        )


class MarketVoidView(MarketResolutionActionView):
    @extend_schema(
        request=MarketVoidSerializer,
        responses=MarketAdminReadSerializer,
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

        serializer = MarketVoidSerializer(
            data=request.data,
        )
        serializer.is_valid(
            raise_exception=True,
        )

        try:
            market = MarketResolutionService.void(
                market_id=market_id,
                actor=request.user,
                notes=(serializer.validated_data["notes"]),
                evidence=(serializer.validated_data["evidence"]),
            )
        except DjangoValidationError as error:
            self.raise_api_validation_error(error)

        return self.get_market_response(
            market_id=market.id,
            request=request,
        )

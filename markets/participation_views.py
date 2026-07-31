from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import (
    ValidationError as APIValidationError,
)
from rest_framework.permissions import (
    IsAuthenticated,
)
from rest_framework.response import Response
from rest_framework.views import APIView

from markets.models import Market
from markets.participation_serializers import (
    MarketOrderCreateSerializer,
    MarketOrderReadSerializer,
)
from markets.services.participation_service import (
    MarketParticipationService,
)


class MarketOrderCreateView(APIView):
    permission_classes = [
        IsAuthenticated,
    ]

    @extend_schema(
        request=MarketOrderCreateSerializer,
        responses={
            201: MarketOrderReadSerializer,
        },
        tags=["Market Participation"],
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

        serializer = MarketOrderCreateSerializer(
            data=request.data,
        )
        serializer.is_valid(
            raise_exception=True,
        )

        try:
            order = MarketParticipationService.place_order(
                user=request.user,
                market_id=market_id,
                outcome_id=(serializer.validated_data["outcome_id"]),
                side=(serializer.validated_data["side"]),
                quantity=(serializer.validated_data["quantity"]),
                limit_price=(serializer.validated_data["limit_price"]),
            )
        except DjangoValidationError as error:
            self.raise_api_validation_error(error)

        response_serializer = MarketOrderReadSerializer(order)

        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def raise_api_validation_error(
        error: DjangoValidationError,
    ) -> None:
        if hasattr(error, "message_dict"):
            raise APIValidationError(error.message_dict) from error

        raise APIValidationError(
            {
                "non_field_errors": (error.messages),
            }
        ) from error

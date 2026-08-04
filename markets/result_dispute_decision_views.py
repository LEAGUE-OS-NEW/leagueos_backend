from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.generics import (
    GenericAPIView,
    ListAPIView,
    RetrieveAPIView,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from markets.models import (
    Market,
    MarketResultDisputeDecision,
)
from markets.permissions import HasApproveMarketPermission
from markets.result_dispute_decision_serializers import (
    MarketResultDisputeDecisionAdminSerializer,
    MarketResultDisputeDecisionCreateSerializer,
    MarketResultDisputeDecisionPublicSerializer,
)
from markets.services.result_dispute_decision_service import (
    MarketResultDisputeDecisionService,
)
from system.pagination import PublicCatalogPagination


class ResultDisputeDecisionValidationMixin:
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


class AdminMarketResultDisputeDecisionCreateView(
    ResultDisputeDecisionValidationMixin,
    GenericAPIView,
):
    permission_classes = [
        IsAuthenticated,
        HasApproveMarketPermission,
    ]
    serializer_class = MarketResultDisputeDecisionCreateSerializer

    @extend_schema(
        request=MarketResultDisputeDecisionCreateSerializer,
        responses={
            201: MarketResultDisputeDecisionAdminSerializer,
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
            decision = MarketResultDisputeDecisionService.decide(
                market_id=market_id,
                actor=request.user,
                decision_type=(serializer.validated_data["decision_type"]),
                winning_outcome_id=(serializer.validated_data.get("winning_outcome_id")),
                review_extension_hours=(serializer.validated_data.get("review_extension_hours")),
                notes=serializer.validated_data["notes"],
                evidence=serializer.validated_data["evidence"],
            )
        except DjangoValidationError as error:
            self.raise_api_validation_error(error)

        return Response(
            MarketResultDisputeDecisionAdminSerializer(
                decision,
            ).data,
            status=status.HTTP_201_CREATED,
        )


class MarketResultDisputeDecisionListView(ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = MarketResultDisputeDecisionPublicSerializer
    pagination_class = PublicCatalogPagination

    @extend_schema(
        responses=MarketResultDisputeDecisionPublicSerializer(many=True),
        tags=["Markets"],
    )
    def get_queryset(self):
        return (
            MarketResultDisputeDecision.objects.filter(
                provisional_result__market_id=(self.kwargs["market_id"]),
            )
            .select_related(
                "provisional_result",
                "provisional_result__market",
                "winning_outcome",
            )
            .order_by(
                "sequence",
                "id",
            )
        )


class AdminMarketResultDisputeDecisionDetailView(RetrieveAPIView):
    permission_classes = [
        IsAuthenticated,
        HasApproveMarketPermission,
    ]
    serializer_class = MarketResultDisputeDecisionAdminSerializer
    lookup_field = "id"
    lookup_url_kwarg = "decision_id"

    @extend_schema(
        responses=MarketResultDisputeDecisionAdminSerializer,
        tags=["Market Administration"],
    )
    def get_queryset(self):
        return MarketResultDisputeDecision.objects.select_related(
            "provisional_result",
            "provisional_result__market",
            "winning_outcome",
            "decided_by",
        )

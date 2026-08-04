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
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from markets.models import Market, MarketResultDispute
from markets.permissions import HasApproveMarketPermission
from markets.result_dispute_serializers import (
    MarketResultDisputeAdminSerializer,
    MarketResultDisputeParticipantSerializer,
    MarketResultDisputeSubmitSerializer,
)
from markets.services.result_dispute_service import (
    MarketResultDisputeService,
)
from system.pagination import PublicCatalogPagination


class ResultDisputeValidationMixin:
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


class MarketResultDisputeSubmitView(
    ResultDisputeValidationMixin,
    GenericAPIView,
):
    permission_classes = [IsAuthenticated]
    serializer_class = MarketResultDisputeSubmitSerializer

    @extend_schema(
        request=MarketResultDisputeSubmitSerializer,
        responses={
            201: MarketResultDisputeParticipantSerializer,
        },
        tags=["Market Result Disputes"],
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
            dispute = MarketResultDisputeService.submit(
                market_id=market_id,
                actor=request.user,
                category=serializer.validated_data["category"],
                explanation=serializer.validated_data["explanation"],
                evidence_items=serializer.validated_data["evidence_items"],
            )
        except DjangoValidationError as error:
            self.raise_api_validation_error(error)

        return Response(
            MarketResultDisputeParticipantSerializer(
                dispute,
            ).data,
            status=status.HTTP_201_CREATED,
        )


class ParticipantMarketResultDisputeListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MarketResultDisputeParticipantSerializer
    pagination_class = PublicCatalogPagination

    @extend_schema(
        responses=MarketResultDisputeParticipantSerializer(many=True),
        tags=["Market Result Disputes"],
    )
    def get_queryset(self):
        return (
            MarketResultDispute.objects.filter(
                participant=self.request.user,
            )
            .select_related(
                "provisional_result",
                "provisional_result__market",
            )
            .prefetch_related(
                "evidence_items",
            )
            .order_by(
                "-submitted_at",
                "-id",
            )
        )


class ParticipantMarketResultDisputeDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MarketResultDisputeParticipantSerializer
    lookup_field = "id"
    lookup_url_kwarg = "dispute_id"

    @extend_schema(
        responses=MarketResultDisputeParticipantSerializer,
        tags=["Market Result Disputes"],
    )
    def get_queryset(self):
        return (
            MarketResultDispute.objects.filter(
                participant=self.request.user,
            )
            .select_related(
                "provisional_result",
                "provisional_result__market",
            )
            .prefetch_related(
                "evidence_items",
            )
        )


class AdminMarketResultDisputeMixin:
    permission_classes = [
        IsAuthenticated,
        HasApproveMarketPermission,
    ]

    @staticmethod
    def base_queryset():
        return MarketResultDispute.objects.select_related(
            "participant",
            "provisional_result",
            "provisional_result__market",
        ).prefetch_related(
            "evidence_items",
        )


class AdminMarketResultDisputeListView(
    AdminMarketResultDisputeMixin,
    ListAPIView,
):
    serializer_class = MarketResultDisputeAdminSerializer
    pagination_class = PublicCatalogPagination

    @extend_schema(
        responses=MarketResultDisputeAdminSerializer(many=True),
        tags=["Market Administration"],
    )
    def get_queryset(self):
        return self.base_queryset().order_by(
            "-submitted_at",
            "-id",
        )


class AdminMarketResultDisputeDetailView(
    AdminMarketResultDisputeMixin,
    RetrieveAPIView,
):
    serializer_class = MarketResultDisputeAdminSerializer
    lookup_field = "id"
    lookup_url_kwarg = "dispute_id"

    @extend_schema(
        responses=MarketResultDisputeAdminSerializer,
        tags=["Market Administration"],
    )
    def get_queryset(self):
        return self.base_queryset()

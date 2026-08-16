from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema
from rest_framework import status
from rest_framework.exceptions import (
    ValidationError as APIValidationError,
)
from rest_framework.generics import (
    ListAPIView,
    RetrieveAPIView,
)
from rest_framework.permissions import (
    IsAuthenticated,
)
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import AuditLog
from markets.compliance_serializers import IneligibleOrderResponseSerializer
from markets.exceptions import MarketParticipationIneligible, MarketResponsibleParticipationBlocked
from markets.models import (
    Market,
    MarketFill,
    MarketOrder,
    MarketPosition,
)
from markets.participation_serializers import (
    MarketFillReadSerializer,
    MarketOrderCreateSerializer,
    MarketOrderReadSerializer,
    MarketPositionReadSerializer,
)
from markets.responsible_participation_serializers import (
    ResponsibleOrderBlockedResponseSerializer,
)
from markets.services.participation_service import (
    MarketParticipationService,
)
from system.pagination import PublicCatalogPagination


class MarketOrderCreateView(APIView):
    permission_classes = [
        IsAuthenticated,
    ]

    @extend_schema(
        request=MarketOrderCreateSerializer,
        responses={
            201: MarketOrderReadSerializer,
            403: PolymorphicProxySerializer(
                component_name="MarketOrderForbiddenResponse",
                serializers=[
                    IneligibleOrderResponseSerializer,
                    ResponsibleOrderBlockedResponseSerializer,
                ],
                resource_type_field_name=None,
            ),
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
                quantity=(serializer.validated_data.get("quantity")),
                limit_price=(serializer.validated_data.get("limit_price")),
                time_in_force=serializer.validated_data["time_in_force"],
                expires_at=serializer.validated_data.get("expires_at"),
                order_type=serializer.validated_data.get("order_type", MarketOrder.OrderType.LIMIT),
                amount=serializer.validated_data.get("amount"),
            )
        except MarketParticipationIneligible as error:
            AuditLog.objects.create(
                user=request.user,
                action="MARKET_ORDER_BLOCKED",
                metadata={
                    "participant_id": str(request.user.id),
                    "market_id": str(market_id),
                    "outcome_id": str(serializer.validated_data["outcome_id"]),
                    "side": serializer.validated_data["side"],
                    "reason_codes": list(error.result.reason_codes),
                    "evaluated_at": error.result.evaluated_at.isoformat(),
                },
            )
            return Response(
                {
                    "detail": "Market participation is not available.",
                    "code": "market_participation_ineligible",
                    "eligible": False,
                    "reason_codes": error.result.reason_codes,
                    "next_actions": error.result.next_actions,
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        except MarketResponsibleParticipationBlocked as error:
            AuditLog.objects.create(
                user=request.user,
                action="MARKET_ORDER_BLOCKED",
                metadata={
                    "participant_id": str(request.user.id),
                    "market_id": str(market_id),
                    "outcome_id": str(serializer.validated_data["outcome_id"]),
                    "side": serializer.validated_data["side"],
                    "reason_codes": list(error.result.reason_codes),
                    "evaluated_at": error.result.evaluated_at.isoformat(),
                    "block_source": "RESPONSIBLE_PARTICIPATION",
                },
            )
            return Response(
                {
                    "detail": "Market participation is temporarily unavailable.",
                    "code": "market_responsible_participation_blocked",
                    "allowed": False,
                    "reason_codes": error.result.reason_codes,
                    "next_actions": error.result.next_actions,
                    "utilization": error.result.utilization(),
                },
                status=status.HTTP_403_FORBIDDEN,
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


class MarketOrderCancelView(APIView):
    permission_classes = [
        IsAuthenticated,
    ]

    @extend_schema(
        request=None,
        responses={
            200: MarketOrderReadSerializer,
        },
        tags=["Market Participation"],
    )
    def post(
        self,
        request,
        order_id,
    ):
        get_object_or_404(
            MarketOrder.objects.filter(
                user=request.user,
            ),
            id=order_id,
        )

        try:
            order = MarketParticipationService.cancel_order(
                user=request.user,
                order_id=order_id,
            )
        except DjangoValidationError as error:
            MarketOrderCreateView.raise_api_validation_error(error)

        serializer = MarketOrderReadSerializer(order)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )


class MarketOrderListView(ListAPIView):
    permission_classes = [
        IsAuthenticated,
    ]
    serializer_class = MarketOrderReadSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        queryset = (
            MarketOrder.objects.filter(
                user=self.request.user,
            )
            .select_related(
                "market",
                "outcome",
            )
            .order_by(
                "-created_at",
                "-id",
            )
        )
        requested_status = self.request.query_params.get("status")
        if requested_status:
            if requested_status not in MarketOrder.Status.values:
                raise APIValidationError({"status": "A valid order status is required."})
            queryset = queryset.filter(status=requested_status)
        return queryset

    @extend_schema(
        responses=MarketOrderReadSerializer(many=True),
        tags=["Market Participation"],
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


class MarketOrderDetailView(RetrieveAPIView):
    permission_classes = [
        IsAuthenticated,
    ]
    serializer_class = MarketOrderReadSerializer
    lookup_field = "id"
    lookup_url_kwarg = "order_id"

    def get_queryset(self):
        return MarketOrder.objects.filter(
            user=self.request.user,
        ).select_related(
            "market",
            "outcome",
        )

    @extend_schema(
        responses=MarketOrderReadSerializer,
        tags=["Market Participation"],
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


class MarketPositionListView(ListAPIView):
    permission_classes = [
        IsAuthenticated,
    ]
    serializer_class = MarketPositionReadSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        return (
            MarketPosition.objects.filter(
                user=self.request.user,
            )
            .select_related(
                "market",
                "outcome",
            )
            .order_by(
                "-created_at",
                "-id",
            )
        )

    @extend_schema(
        responses=MarketPositionReadSerializer(many=True),
        tags=["Market Participation"],
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


class MarketPositionDetailView(RetrieveAPIView):
    permission_classes = [
        IsAuthenticated,
    ]
    serializer_class = MarketPositionReadSerializer
    lookup_field = "id"
    lookup_url_kwarg = "position_id"

    def get_queryset(self):
        return MarketPosition.objects.filter(
            user=self.request.user,
        ).select_related(
            "market",
            "outcome",
        )

    @extend_schema(
        responses=MarketPositionReadSerializer,
        tags=["Market Participation"],
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


@extend_schema(tags=["Market Participation"])
class MarketFillListView(ListAPIView):
    serializer_class = MarketFillReadSerializer
    permission_classes = [
        IsAuthenticated,
    ]
    pagination_class = PublicCatalogPagination
    queryset = MarketFill.objects.none()

    def get_queryset(self):
        user = self.request.user

        return (
            MarketFill.objects.filter(
                Q(
                    buy_order__user=user,
                )
                | Q(
                    sell_order__user=user,
                )
            )
            .select_related(
                "market",
                "outcome",
                "buy_order",
                "sell_order",
                "maker_order",
                "taker_order",
            )
            .distinct()
            .order_by(
                "-created_at",
                "-id",
            )
        )


@extend_schema(tags=["Market Participation"])
class MarketFillDetailView(RetrieveAPIView):
    serializer_class = MarketFillReadSerializer
    permission_classes = [
        IsAuthenticated,
    ]
    lookup_field = "id"
    lookup_url_kwarg = "fill_id"
    queryset = MarketFill.objects.none()

    def get_queryset(self):
        user = self.request.user

        return (
            MarketFill.objects.filter(
                Q(
                    buy_order__user=user,
                )
                | Q(
                    sell_order__user=user,
                )
            )
            .select_related(
                "market",
                "outcome",
                "buy_order",
                "sell_order",
                "maker_order",
                "taker_order",
            )
            .distinct()
        )

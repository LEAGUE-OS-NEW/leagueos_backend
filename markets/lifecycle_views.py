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
    MarketLifecycleActionSerializer,
)
from markets.admin_views import (
    MarketAdminQuerysetMixin,
)
from markets.models import Market
from markets.permissions import (
    HasApproveMarketPermission,
    HasManageMarketPermission,
)
from markets.services.lifecycle_service import (
    MarketLifecycleService,
)


class MarketLifecycleActionView(
    MarketAdminQuerysetMixin,
    APIView,
):
    permission_classes = [
        IsAuthenticated,
    ]
    service_method_name = ""

    @extend_schema(
        request=MarketLifecycleActionSerializer,
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

        request_serializer = MarketLifecycleActionSerializer(
            data=request.data,
        )
        request_serializer.is_valid(
            raise_exception=True,
        )

        service_method = getattr(
            MarketLifecycleService,
            self.service_method_name,
        )

        try:
            market = service_method(
                market_id=market_id,
                actor=request.user,
                notes=(request_serializer.validated_data["notes"]),
            )
        except DjangoValidationError as error:
            self._raise_api_validation_error(error)

        market = self.get_admin_queryset().get(
            id=market.id,
        )

        response_serializer = MarketAdminReadSerializer(
            market,
            context={
                "request": request,
            },
        )

        return Response(response_serializer.data)

    @staticmethod
    def _raise_api_validation_error(
        error: DjangoValidationError,
    ) -> None:
        if hasattr(
            error,
            "message_dict",
        ):
            raise serializers.ValidationError(error.message_dict) from error

        raise serializers.ValidationError(
            {
                "non_field_errors": (error.messages),
            }
        ) from error


class MarketSubmitView(MarketLifecycleActionView):
    permission_classes = [
        IsAuthenticated,
        HasManageMarketPermission,
    ]
    service_method_name = "submit"


class MarketApproveView(MarketLifecycleActionView):
    permission_classes = [
        IsAuthenticated,
        HasApproveMarketPermission,
    ]
    service_method_name = "approve"


class MarketRejectView(MarketLifecycleActionView):
    permission_classes = [
        IsAuthenticated,
        HasApproveMarketPermission,
    ]
    service_method_name = "reject"


class MarketOpenView(MarketLifecycleActionView):
    permission_classes = [
        IsAuthenticated,
        HasApproveMarketPermission,
    ]
    service_method_name = "open"


class MarketRevertToDraftView(MarketLifecycleActionView):
    permission_classes = [
        IsAuthenticated,
        HasApproveMarketPermission,
    ]
    service_method_name = "revert_to_draft"


class MarketSuspendView(MarketLifecycleActionView):
    permission_classes = [
        IsAuthenticated,
        HasApproveMarketPermission,
    ]
    service_method_name = "suspend"


class MarketReopenView(MarketLifecycleActionView):
    permission_classes = [
        IsAuthenticated,
        HasApproveMarketPermission,
    ]
    service_method_name = "reopen"


class MarketCloseView(MarketLifecycleActionView):
    permission_classes = [
        IsAuthenticated,
        HasApproveMarketPermission,
    ]
    service_method_name = "close"

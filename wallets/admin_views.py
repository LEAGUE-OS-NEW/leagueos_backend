"""Finance Admin wallet withdrawal API."""

from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from authentication.permissions import HasPermission
from system.pagination import PublicCatalogPagination
from wallets.admin_serializers import (
    AdminWithdrawalCompleteSerializer,
    AdminWithdrawalFilterSerializer,
    AdminWithdrawalReadSerializer,
    AdminWithdrawalReasonSerializer,
)
from wallets.models import WithdrawalRequest
from wallets.services.wallet_service import WalletService

ADMIN_WITHDRAWAL_TAG = ["Wallet Finance Administration"]


def admin_withdrawal_queryset():
    return WithdrawalRequest.objects.select_related(
        "wallet",
        "wallet__user",
        "transaction",
        "approved_by",
    ).order_by(
        "-created_at",
        "-id",
    )


def raise_lifecycle_validation(error):
    if hasattr(error, "message_dict"):
        raise ValidationError(error.message_dict) from error

    raise ValidationError(
        {
            "detail": error.messages,
        }
    ) from error


def serialize_withdrawal(withdrawal):
    return AdminWithdrawalReadSerializer(withdrawal).data


@extend_schema(tags=ADMIN_WITHDRAWAL_TAG)
class AdminWithdrawalListView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasPermission,
    ]
    required_permissions = [
        "view_finance",
        "review_withdrawal",
    ]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "status",
                str,
                enum=[choice for choice, _label in WithdrawalRequest.Status.choices],
            ),
            OpenApiParameter(
                "currency",
                str,
            ),
            OpenApiParameter(
                "created_from",
                str,
            ),
            OpenApiParameter(
                "created_to",
                str,
            ),
        ],
        responses={
            200: AdminWithdrawalReadSerializer(
                many=True,
            ),
            400: OpenApiResponse(
                description="Invalid filter value.",
            ),
            401: OpenApiResponse(
                description=("Authentication credentials " "are required."),
            ),
            403: OpenApiResponse(
                description=("Finance permission is required."),
            ),
        },
    )
    def get(self, request):
        serializer = AdminWithdrawalFilterSerializer(
            data=request.query_params,
        )
        serializer.is_valid(
            raise_exception=True,
        )
        filters = serializer.validated_data

        queryset = admin_withdrawal_queryset()

        status_value = filters.get("status")
        if status_value:
            queryset = queryset.filter(
                status=status_value,
            )

        currency = filters.get("currency")
        if currency:
            queryset = queryset.filter(
                wallet__currency=currency,
            )

        created_from = filters.get("created_from")
        if created_from:
            queryset = queryset.filter(
                created_at__gte=created_from,
            )

        created_to = filters.get("created_to")
        if created_to:
            queryset = queryset.filter(
                created_at__lte=created_to,
            )

        paginator = PublicCatalogPagination()
        page = paginator.paginate_queryset(
            queryset,
            request,
            view=self,
        )

        return paginator.get_paginated_response(
            AdminWithdrawalReadSerializer(
                page,
                many=True,
            ).data
        )


@extend_schema(tags=ADMIN_WITHDRAWAL_TAG)
class AdminWithdrawalDetailView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasPermission,
    ]
    required_permissions = [
        "view_finance",
        "review_withdrawal",
    ]

    @extend_schema(
        responses={
            200: AdminWithdrawalReadSerializer,
            401: OpenApiResponse(
                description=("Authentication credentials " "are required."),
            ),
            403: OpenApiResponse(
                description=("Finance permission is required."),
            ),
            404: OpenApiResponse(
                description="Withdrawal not found.",
            ),
        },
    )
    def get(self, request, request_id):
        withdrawal = get_object_or_404(
            admin_withdrawal_queryset(),
            id=request_id,
        )

        return Response(serialize_withdrawal(withdrawal))


@extend_schema(tags=ADMIN_WITHDRAWAL_TAG)
class AdminWithdrawalApproveView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasPermission,
    ]
    required_permission = "review_withdrawal"

    @extend_schema(
        request=None,
        responses={
            200: AdminWithdrawalReadSerializer,
            400: OpenApiResponse(
                description=("Withdrawal cannot be approved."),
            ),
            403: OpenApiResponse(
                description=("Withdrawal review permission " "is required."),
            ),
        },
    )
    def post(self, request, request_id):
        try:
            withdrawal = WalletService.approve_withdrawal(
                withdrawal_id=request_id,
                actor=request.user,
            )
        except DjangoValidationError as error:
            raise_lifecycle_validation(error)

        return Response(serialize_withdrawal(withdrawal))


@extend_schema(tags=ADMIN_WITHDRAWAL_TAG)
class AdminWithdrawalRejectView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasPermission,
    ]
    required_permission = "review_withdrawal"

    @extend_schema(
        request=AdminWithdrawalReasonSerializer,
        responses={
            200: AdminWithdrawalReadSerializer,
            400: OpenApiResponse(
                description=("Withdrawal cannot be rejected."),
            ),
            403: OpenApiResponse(
                description=("Withdrawal review permission " "is required."),
            ),
        },
    )
    def post(self, request, request_id):
        serializer = AdminWithdrawalReasonSerializer(
            data=request.data,
        )
        serializer.is_valid(
            raise_exception=True,
        )

        try:
            withdrawal = WalletService.reject_withdrawal(
                withdrawal_id=request_id,
                actor=request.user,
                reason=(serializer.validated_data["reason"]),
            )
        except DjangoValidationError as error:
            raise_lifecycle_validation(error)

        return Response(serialize_withdrawal(withdrawal))


@extend_schema(tags=ADMIN_WITHDRAWAL_TAG)
class AdminWithdrawalProcessingView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasPermission,
    ]
    required_permission = "manage_finance"

    @extend_schema(
        request=None,
        responses={
            200: AdminWithdrawalReadSerializer,
            400: OpenApiResponse(
                description=("Withdrawal cannot enter " "processing."),
            ),
            403: OpenApiResponse(
                description=("Finance management permission " "is required."),
            ),
        },
    )
    def post(self, request, request_id):
        try:
            withdrawal = WalletService.mark_withdrawal_processing(
                withdrawal_id=request_id,
                actor=request.user,
            )
        except DjangoValidationError as error:
            raise_lifecycle_validation(error)

        return Response(serialize_withdrawal(withdrawal))


@extend_schema(tags=ADMIN_WITHDRAWAL_TAG)
class AdminWithdrawalCompleteView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasPermission,
    ]
    required_permission = "manage_finance"

    @extend_schema(
        request=AdminWithdrawalCompleteSerializer,
        responses={
            200: AdminWithdrawalReadSerializer,
            400: OpenApiResponse(
                description=("Withdrawal cannot be completed."),
            ),
            403: OpenApiResponse(
                description=("Finance management permission " "is required."),
            ),
        },
    )
    def post(self, request, request_id):
        serializer = AdminWithdrawalCompleteSerializer(
            data=request.data,
        )
        serializer.is_valid(
            raise_exception=True,
        )

        try:
            withdrawal = WalletService.complete_withdrawal(
                withdrawal_id=request_id,
                actor=request.user,
                provider_reference=(serializer.validated_data["provider_reference"]),
            )
        except DjangoValidationError as error:
            raise_lifecycle_validation(error)

        return Response(serialize_withdrawal(withdrawal))


@extend_schema(tags=ADMIN_WITHDRAWAL_TAG)
class AdminWithdrawalFailView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasPermission,
    ]
    required_permission = "manage_finance"

    @extend_schema(
        request=AdminWithdrawalReasonSerializer,
        responses={
            200: AdminWithdrawalReadSerializer,
            400: OpenApiResponse(
                description=("Withdrawal cannot be failed."),
            ),
            403: OpenApiResponse(
                description=("Finance management permission " "is required."),
            ),
        },
    )
    def post(self, request, request_id):
        serializer = AdminWithdrawalReasonSerializer(
            data=request.data,
        )
        serializer.is_valid(
            raise_exception=True,
        )

        try:
            withdrawal = WalletService.fail_withdrawal(
                withdrawal_id=request_id,
                actor=request.user,
                reason=(serializer.validated_data["reason"]),
            )
        except DjangoValidationError as error:
            raise_lifecycle_validation(error)

        return Response(serialize_withdrawal(withdrawal))

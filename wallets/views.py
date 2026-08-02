from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from system.pagination import PublicCatalogPagination
from wallets.serializers import (
    LedgerEntryFilterSerializer,
    LedgerEntryReadSerializer,
    WalletReadSerializer,
)
from wallets.services.wallet_read_service import WalletReadService


def raise_currency_validation(error):
    if hasattr(error, "message_dict"):
        raise ValidationError(error.message_dict) from error
    raise ValidationError({"currency": error.messages}) from error


class WalletListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = WalletReadSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        return WalletReadService.list_wallets(user=self.request.user)

    @extend_schema(
        responses={
            200: WalletReadSerializer(many=True),
            401: OpenApiResponse(description="Authentication credentials are required."),
        },
        tags=["Wallets"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class WalletDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: WalletReadSerializer,
            400: OpenApiResponse(description="Invalid currency."),
            401: OpenApiResponse(description="Authentication credentials are required."),
            404: OpenApiResponse(description="Wallet not found."),
        },
        tags=["Wallets"],
    )
    def get(self, request, currency):
        try:
            wallet = WalletReadService.get_wallet(user=request.user, currency=currency)
        except DjangoValidationError as error:
            raise_currency_validation(error)
        if wallet is None:
            raise Http404
        return Response(WalletReadSerializer(wallet).data)


class WalletLedgerListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LedgerEntryReadSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        filter_serializer = LedgerEntryFilterSerializer(data=self.request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        try:
            wallet, queryset = WalletReadService.list_ledger_entries(
                user=self.request.user,
                currency=self.kwargs["currency"],
                filters=filter_serializer.validated_data,
            )
        except DjangoValidationError as error:
            raise_currency_validation(error)
        if wallet is None:
            raise Http404
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter("entry_type", str, enum=["CREDIT", "DEBIT", "RESERVE", "RELEASE"]),
            OpenApiParameter("market_id", str),
            OpenApiParameter("order_id", str),
            OpenApiParameter("fill_id", str),
            OpenApiParameter("created_from", str),
            OpenApiParameter("created_to", str),
        ],
        responses={
            200: LedgerEntryReadSerializer(many=True),
            400: OpenApiResponse(description="Invalid currency or filter value."),
            401: OpenApiResponse(description="Authentication credentials are required."),
            404: OpenApiResponse(description="Wallet not found."),
        },
        tags=["Wallets"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

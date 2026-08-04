from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from system.pagination import PublicCatalogPagination
from wallets.serializers import (
    DepositCallbackSerializer,
    DepositIntentReadSerializer,
    DepositIntentSerializer,
    LedgerEntryFilterSerializer,
    LedgerEntryReadSerializer,
    WalletReadSerializer,
    WithdrawalRequestSerializer,
)
from wallets.services.wallet_read_service import WalletReadService
from wallets.services.wallet_service import WalletService


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


class DepositIntentView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DepositIntentSerializer

    @extend_schema(
        request=DepositIntentSerializer,
        responses={
            201: DepositIntentSerializer,
            400: OpenApiResponse(description="Invalid request data."),
            401: OpenApiResponse(description="Authentication credentials are required."),
        },
        tags=["Wallets"],
    )
    def post(self, request):
        try:
            intent = WalletService.create_deposit_intent(
                user=request.user,
                provider_code=request.data.get("provider_code"),
                amount=request.data.get("amount"),
                currency=request.data.get("currency"),
            )
        except DjangoValidationError as error:
            raise_currency_validation(error)
        data = DepositIntentReadSerializer(intent).data
        data["payment_url"] = f"/api/v1/wallets/deposits/{intent.id}/"
        return Response(data, status=201)


class DepositIntentDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = WalletReadSerializer

    def get_object(self):
        intent_id = self.kwargs["intent_id"]
        try:
            return WalletService.get_deposit_intent(user=self.request.user, intent_id=intent_id)
        except DjangoValidationError as error:
            raise_currency_validation(error)


class DepositCallbackView(APIView):
    permission_classes = []  # Public endpoint for provider callbacks
    serializer_class = DepositCallbackSerializer

    @extend_schema(
        request=DepositCallbackSerializer,
        responses={
            200: OpenApiResponse(description="Callback processed."),
            400: OpenApiResponse(description="Invalid callback payload."),
            404: OpenApiResponse(description="Provider not found."),
        },
        tags=["Wallets"],
    )
    def post(self, request, provider_code):
        try:
            WalletService.process_deposit_callback(
                provider_code=provider_code,
                payload=request.data,
            )
        except DjangoValidationError as error:
            raise_currency_validation(error)
        return Response({"status": "processed"})


class WithdrawalRequestView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = WithdrawalRequestSerializer

    @extend_schema(
        request=WithdrawalRequestSerializer,
        responses={
            201: WithdrawalRequestSerializer,
            400: OpenApiResponse(description="Invalid request data."),
            401: OpenApiResponse(description="Authentication credentials are required."),
        },
        tags=["Wallets"],
    )
    def post(self, request):
        try:
            withdrawal = WalletService.create_withdrawal_request(
                user=request.user,
                amount=request.data.get("amount"),
                currency=request.data.get("currency"),
                destination=request.data.get("destination"),
            )
        except DjangoValidationError as error:
            raise_currency_validation(error)
        return Response(
            {
                "id": str(withdrawal.id),
                "amount": str(withdrawal.amount),
                "currency": withdrawal.wallet.currency,
                "status": withdrawal.status,
                "created_at": withdrawal.created_at.isoformat(),
            },
            status=201,
        )


class WithdrawalRequestDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = WalletReadSerializer

    def get_object(self):
        request_id = self.kwargs["request_id"]
        try:
            return WalletService.get_withdrawal_request(
                user=self.request.user, request_id=request_id
            )
        except DjangoValidationError as error:
            raise_currency_validation(error)


class TransactionListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LedgerEntryReadSerializer
    pagination_class = PublicCatalogPagination

    def get_queryset(self):
        try:
            return WalletReadService.list_transactions(
                user=self.request.user,
                currency=self.kwargs.get("currency"),
            )
        except DjangoValidationError as error:
            raise_currency_validation(error)


class TransactionDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LedgerEntryReadSerializer

    def get_object(self):
        tx_id = self.kwargs["tx_id"]
        try:
            return WalletReadService.get_transaction(user=self.request.user, transaction_id=tx_id)
        except DjangoValidationError as error:
            raise_currency_validation(error)


class ReceiptDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: OpenApiResponse(description="Receipt file download."),
            404: OpenApiResponse(description="Receipt not found."),
        },
        tags=["Wallets"],
    )
    def get(self, request, tx_id):
        try:
            receipt_url = WalletReadService.get_receipt_download_url(
                user=request.user, transaction_id=tx_id
            )
        except DjangoValidationError as error:
            raise_currency_validation(error)
        if receipt_url is None:
            raise Http404
        return Response({"url": receipt_url})

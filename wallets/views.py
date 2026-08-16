import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from urllib.parse import urlencode

from django.http import Http404
from django.shortcuts import redirect
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
    PesapalCallbackResultSerializer,
    PesapalIpnAcknowledgementSerializer,
    PesapalNotificationSerializer,
    LedgerEntryFilterSerializer,
    LedgerEntryReadSerializer,
    WalletReadSerializer,
    WithdrawalRequestReadSerializer,
    WithdrawalRequestSerializer,
    WalletTransactionReadSerializer,
)
from wallets.services.pesapal_client import PesapalApiError
from wallets.services.pesapal_config import get_pesapal_config
from wallets.services.pesapal_deposit_service import (
    PesapalDepositService,
    pesapal_deposit_read_data,
)
from wallets.services.wallet_read_service import WalletReadService
from wallets.services.wallet_service import WalletService

logger = logging.getLogger(__name__)


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
            201: DepositIntentReadSerializer,
            400: OpenApiResponse(description="Invalid request data."),
            401: OpenApiResponse(description="Authentication credentials are required."),
            502: OpenApiResponse(
                description=("Pesapal Sandbox checkout " "could not be confirmed.")
            ),
        },
        tags=["Wallets"],
    )
    def post(self, request):
        serializer = DepositIntentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        values = serializer.validated_data
        provider_code = values["provider_code"].strip().upper()

        try:
            if provider_code == PesapalDepositService.PROVIDER_CODE:
                pesapal = PesapalDepositService.start_deposit(
                    user=request.user,
                    amount=values["amount"],
                    currency=values["currency"],
                    idempotency_key=values.get("idempotency_key"),
                )

                data = pesapal_deposit_read_data(pesapal)

            else:
                intent = WalletService.create_deposit_intent(
                    user=request.user,
                    provider_code=provider_code,
                    amount=values["amount"],
                    currency=values["currency"],
                    idempotency_key=values.get("idempotency_key"),
                )

                data = DepositIntentReadSerializer(intent).data

                data["provider_code"] = intent.provider.code

        except PesapalApiError:
            logger.warning(
                "Pesapal checkout start failed " "user_id=%s provider_code=%s",
                request.user.pk,
                provider_code,
            )

            return Response(
                {
                    "provider": [
                        "Pesapal Sandbox checkout "
                        "could not be confirmed. "
                        "Do not automatically retry "
                        "this request."
                    ]
                },
                status=502,
            )

        except DjangoValidationError as error:
            raise_currency_validation(error)

        return Response(
            data,
            status=201,
        )


class DepositIntentDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: DepositIntentReadSerializer,
            401: OpenApiResponse(description="Authentication credentials are required."),
            404: OpenApiResponse(description="Deposit intent not found."),
        },
        tags=["Wallets"],
    )
    def get(self, request, intent_id):
        try:
            intent = WalletService.get_deposit_intent(
                user=request.user,
                intent_id=intent_id,
            )
        except DjangoValidationError as error:
            raise_currency_validation(error)

        data = DepositIntentReadSerializer(intent).data
        data["provider_code"] = intent.provider.code

        if hasattr(
            intent,
            "pesapal",
        ):
            pesapal = intent.pesapal
            data["payment_url"] = pesapal.redirect_url
            data["order_tracking_id"] = pesapal.order_tracking_id
            data["provider_status"] = pesapal.provider_status

        return Response(data)


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


class PesapalCallbackView(APIView):
    permission_classes = []

    @extend_schema(
        parameters=[
            PesapalNotificationSerializer,
        ],
        responses={
            200: PesapalCallbackResultSerializer,
            302: OpenApiResponse(
                description=(
                    "Redirects the browser to the " "configured frontend wallet return URL."
                )
            ),
        },
        tags=["Wallets"],
    )
    def get(self, request):
        tracking_id = request.query_params.get("OrderTrackingId")
        merchant_reference = request.query_params.get("OrderMerchantReference")

        result_status = "error"
        intent_id = ""

        try:
            result = PesapalDepositService.reconcile_notification(
                order_tracking_id=tracking_id,
                merchant_reference=merchant_reference,
            )

            deposit = result["deposit"]
            intent_id = str(deposit.intent_id)
            result_status = deposit.intent.status.lower()

        except (
            DjangoValidationError,
            PesapalApiError,
        ):
            result_status = "error"

        config = get_pesapal_config(require_credentials=False)

        if config.frontend_return_url:
            separator = "&" if "?" in config.frontend_return_url else "?"

            query = urlencode(
                {
                    "deposit": intent_id,
                    "status": result_status,
                }
            )

            return redirect(config.frontend_return_url + separator + query)

        return Response(
            {
                "deposit": intent_id,
                "status": result_status,
            }
        )


class PesapalIpnView(APIView):
    permission_classes = []

    @extend_schema(
        parameters=[
            PesapalNotificationSerializer,
        ],
        responses={
            200: PesapalIpnAcknowledgementSerializer,
            500: PesapalIpnAcknowledgementSerializer,
        },
        tags=["Wallets"],
    )
    def get(self, request):
        return self._process(request.query_params)

    @extend_schema(
        request=PesapalNotificationSerializer,
        responses={
            200: PesapalIpnAcknowledgementSerializer,
            500: PesapalIpnAcknowledgementSerializer,
        },
        tags=["Wallets"],
    )
    def post(self, request):
        return self._process(request.data)

    @staticmethod
    def _process(payload):
        notification_type = str(payload.get("OrderNotificationType") or "")

        tracking_id = str(payload.get("OrderTrackingId") or "")

        merchant_reference = str(payload.get("OrderMerchantReference") or "")

        try:
            PesapalDepositService.reconcile_notification(
                order_tracking_id=tracking_id,
                merchant_reference=merchant_reference,
            )

        except (
            DjangoValidationError,
            PesapalApiError,
        ):
            return Response(
                {
                    "orderNotificationType": notification_type,
                    "orderTrackingId": tracking_id,
                    "orderMerchantReference": merchant_reference,
                    "status": 500,
                },
                status=500,
            )

        return Response(
            {
                "orderNotificationType": notification_type,
                "orderTrackingId": tracking_id,
                "orderMerchantReference": merchant_reference,
                "status": 200,
            }
        )


class WithdrawalRequestView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = WithdrawalRequestSerializer

    @extend_schema(
        request=WithdrawalRequestSerializer,
        responses={
            201: WithdrawalRequestReadSerializer,
            400: OpenApiResponse(description="Invalid request data."),
            401: OpenApiResponse(description="Authentication credentials are required."),
        },
        tags=["Wallets"],
    )
    def post(self, request):
        serializer = WithdrawalRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data

        try:
            withdrawal = WalletService.create_withdrawal_request(
                user=request.user,
                amount=values["amount"],
                currency=values["currency"],
                destination=values["destination"],
                idempotency_key=values.get("idempotency_key"),
            )
        except DjangoValidationError as error:
            raise_currency_validation(error)
        return Response(
            WithdrawalRequestReadSerializer(
                {
                    "id": withdrawal.id,
                    "amount": withdrawal.amount,
                    "currency": withdrawal.wallet.currency,
                    "destination": withdrawal.destination,
                    "status": withdrawal.status,
                    "risk_status": withdrawal.risk_status,
                    "risk_reasons": withdrawal.risk_reasons,
                    "approval_mode": withdrawal.approval_mode,
                    "approval_policy_version": withdrawal.approval_policy_version,
                    "approved_at": withdrawal.approved_at,
                    "rejection_reason": withdrawal.rejection_reason,
                    "created_at": withdrawal.created_at,
                    "updated_at": withdrawal.updated_at,
                    "transaction_id": withdrawal.transaction_id,
                }
            ).data,
            status=201,
        )


class WithdrawalRequestDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = WithdrawalRequestReadSerializer

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
    serializer_class = WalletTransactionReadSerializer
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
    serializer_class = WalletTransactionReadSerializer

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

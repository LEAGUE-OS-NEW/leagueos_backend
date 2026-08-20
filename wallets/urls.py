"""URL configuration for the wallets module."""

from django.urls import path

from wallets.admin_views import (
    AdminWithdrawalApproveView,
    AdminWithdrawalCompleteView,
    AdminWithdrawalDetailView,
    AdminWithdrawalFailView,
    AdminWithdrawalListView,
    AdminWithdrawalProcessingView,
    AdminWithdrawalRejectView,
)
from wallets.views import (
    DepositCallbackView,
    DepositIntentDetailView,
    DepositIntentView,
    PesapalCallbackView,
    PesapalIpnView,
    ReceiptDownloadView,
    TransactionDetailView,
    TransactionListView,
    WalletDetailView,
    WalletLedgerListView,
    WalletListView,
    WalletSpendView,
    WithdrawalRequestDetailView,
    WithdrawalRequestView,
)

app_name = "wallets"

urlpatterns = [
    path("", WalletListView.as_view(), name="wallet-list"),
    # Deposits
    path("deposits/", DepositIntentView.as_view(), name="deposit-intent-create"),
    path(
        "deposits/pesapal/callback/",
        PesapalCallbackView.as_view(),
        name="pesapal-callback",
    ),
    path(
        "deposits/pesapal/ipn/",
        PesapalIpnView.as_view(),
        name="pesapal-ipn",
    ),
    path(
        "deposits/callback/<str:provider_code>/",
        DepositCallbackView.as_view(),
        name="deposit-callback",
    ),
    path(
        "deposits/<uuid:intent_id>/",
        DepositIntentDetailView.as_view(),
        name="deposit-intent-detail",
    ),
    # Immediate wallet spends for fan purchases
    path("spend/", WalletSpendView.as_view(), name="wallet-spend"),
    # Withdrawals
    path("withdrawals/", WithdrawalRequestView.as_view(), name="withdrawal-request-create"),
    path(
        "withdrawals/<uuid:request_id>/",
        WithdrawalRequestDetailView.as_view(),
        name="withdrawal-request-detail",
    ),
    # Finance Admin withdrawals
    path(
        "admin/withdrawals/",
        AdminWithdrawalListView.as_view(),
        name="admin-withdrawal-list",
    ),
    path(
        "admin/withdrawals/<uuid:request_id>/",
        AdminWithdrawalDetailView.as_view(),
        name="admin-withdrawal-detail",
    ),
    path(
        "admin/withdrawals/<uuid:request_id>/approve/",
        AdminWithdrawalApproveView.as_view(),
        name="admin-withdrawal-approve",
    ),
    path(
        "admin/withdrawals/<uuid:request_id>/reject/",
        AdminWithdrawalRejectView.as_view(),
        name="admin-withdrawal-reject",
    ),
    path(
        "admin/withdrawals/<uuid:request_id>/processing/",
        AdminWithdrawalProcessingView.as_view(),
        name="admin-withdrawal-processing",
    ),
    path(
        "admin/withdrawals/<uuid:request_id>/complete/",
        AdminWithdrawalCompleteView.as_view(),
        name="admin-withdrawal-complete",
    ),
    path(
        "admin/withdrawals/<uuid:request_id>/fail/",
        AdminWithdrawalFailView.as_view(),
        name="admin-withdrawal-fail",
    ),
    # Transactions & Receipts
    path("transactions/", TransactionListView.as_view(), name="transaction-list"),
    path(
        "transactions/<uuid:tx_id>/",
        TransactionDetailView.as_view(),
        name="transaction-detail",
    ),
    path(
        "transactions/<uuid:tx_id>/receipt/",
        ReceiptDownloadView.as_view(),
        name="receipt-download",
    ),
    # Wallet currency-specific routes (keep last to avoid capturing keywords)
    path("<str:currency>/ledger/", WalletLedgerListView.as_view(), name="wallet-ledger"),
    path("<str:currency>/", WalletDetailView.as_view(), name="wallet-detail"),
]

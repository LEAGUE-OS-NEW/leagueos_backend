"""URL configuration for the wallets module."""

from django.urls import path

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
    # Withdrawals
    path("withdrawals/", WithdrawalRequestView.as_view(), name="withdrawal-request-create"),
    path(
        "withdrawals/<uuid:request_id>/",
        WithdrawalRequestDetailView.as_view(),
        name="withdrawal-request-detail",
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

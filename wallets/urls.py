from django.urls import path

from wallets.views import WalletDetailView, WalletLedgerListView, WalletListView

app_name = "wallets"

urlpatterns = [
    path("wallets/", WalletListView.as_view(), name="wallet-list"),
    path("wallets/<str:currency>/", WalletDetailView.as_view(), name="wallet-detail"),
    path(
        "wallets/<str:currency>/ledger/",
        WalletLedgerListView.as_view(),
        name="wallet-ledger-list",
    ),
]

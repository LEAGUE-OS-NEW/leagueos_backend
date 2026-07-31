from django.urls import path

from markets.admin_views import (
    MarketAdminDetailView,
    MarketAdminListCreateView,
)
from markets.lifecycle_views import (
    MarketApproveView,
    MarketCloseView,
    MarketOpenView,
    MarketRejectView,
    MarketReopenView,
    MarketSubmitView,
    MarketSuspendView,
)
from markets.views import (
    MarketCategoryListView,
    MarketDetailView,
    MarketListView,
)

app_name = "markets"

urlpatterns = [
    path(
        "market-admin/markets/",
        MarketAdminListCreateView.as_view(),
        name="admin-market-list",
    ),
    path(
        "market-admin/markets/<uuid:market_id>/",
        MarketAdminDetailView.as_view(),
        name="admin-market-detail",
    ),
    path(
        ("market-admin/markets/" "<uuid:market_id>/submit/"),
        MarketSubmitView.as_view(),
        name="admin-market-submit",
    ),
    path(
        ("market-admin/markets/" "<uuid:market_id>/approve/"),
        MarketApproveView.as_view(),
        name="admin-market-approve",
    ),
    path(
        ("market-admin/markets/" "<uuid:market_id>/reject/"),
        MarketRejectView.as_view(),
        name="admin-market-reject",
    ),
    path(
        ("market-admin/markets/" "<uuid:market_id>/open/"),
        MarketOpenView.as_view(),
        name="admin-market-open",
    ),
    path(
        ("market-admin/markets/" "<uuid:market_id>/suspend/"),
        MarketSuspendView.as_view(),
        name="admin-market-suspend",
    ),
    path(
        ("market-admin/markets/" "<uuid:market_id>/reopen/"),
        MarketReopenView.as_view(),
        name="admin-market-reopen",
    ),
    path(
        ("market-admin/markets/" "<uuid:market_id>/close/"),
        MarketCloseView.as_view(),
        name="admin-market-close",
    ),
    path(
        "markets/categories/",
        MarketCategoryListView.as_view(),
        name="category-list",
    ),
    path(
        "markets/",
        MarketListView.as_view(),
        name="market-list",
    ),
    path(
        "markets/<uuid:market_id>/",
        MarketDetailView.as_view(),
        name="market-detail",
    ),
]

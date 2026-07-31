from django.urls import path

from markets.admin_views import (
    MarketAdminDetailView,
    MarketAdminListCreateView,
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

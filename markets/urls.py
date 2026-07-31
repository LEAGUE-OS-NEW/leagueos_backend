from django.urls import path

from markets.views import (
    MarketCategoryListView,
    MarketDetailView,
    MarketListView,
)

app_name = "markets"

urlpatterns = [
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

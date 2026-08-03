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
from markets.open_order_views import ParticipantOpenOrderListView
from markets.order_book_views import MarketOrderBookView
from markets.participation_views import (
    MarketFillDetailView,
    MarketFillListView,
    MarketOrderCancelView,
    MarketOrderCreateView,
    MarketOrderDetailView,
    MarketOrderListView,
    MarketPositionDetailView,
    MarketPositionListView,
)
from markets.portfolio_views import MarketPortfolioSummaryView
from markets.resolution_views import (
    MarketResolveView,
    MarketVoidView,
)
from markets.settlement_views import MarketSettlementView
from markets.views import (
    MarketCategoryListView,
    MarketDetailView,
    MarketListView,
)
from markets.void_refund_views import MarketVoidRefundView

app_name = "markets"

urlpatterns = [
    path(
        "markets/portfolio/summary/",
        MarketPortfolioSummaryView.as_view(),
        name="market-portfolio-summary",
    ),
    path(
        "markets/orders/open/",
        ParticipantOpenOrderListView.as_view(),
        name="participant-open-orders",
    ),
    path(
        "market-positions/",
        MarketPositionListView.as_view(),
        name="market-position-list",
    ),
    path(
        "market-positions/<uuid:position_id>/",
        MarketPositionDetailView.as_view(),
        name="market-position-detail",
    ),
    path(
        "market-orders/",
        MarketOrderListView.as_view(),
        name="market-order-list",
    ),
    path(
        "market-orders/<uuid:order_id>/",
        MarketOrderDetailView.as_view(),
        name="market-order-detail",
    ),
    path(
        "market-orders/<uuid:order_id>/cancel/",
        MarketOrderCancelView.as_view(),
        name="market-order-cancel",
    ),
    path(
        "markets/<uuid:market_id>/orders/",
        MarketOrderCreateView.as_view(),
        name="market-order-create",
    ),
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
        ("market-admin/markets/" "<uuid:market_id>/resolve/"),
        MarketResolveView.as_view(),
        name="admin-market-resolve",
    ),
    path(
        ("market-admin/markets/" "<uuid:market_id>/void/"),
        MarketVoidView.as_view(),
        name="admin-market-void",
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
    path(
        "markets/<uuid:market_id>/settle/",
        MarketSettlementView.as_view(),
        name="market-settle",
    ),
    path(
        "markets/<uuid:market_id>/void-refund/",
        MarketVoidRefundView.as_view(),
        name="market-void-refund",
    ),
    path(
        "markets/<uuid:market_id>/outcomes/<uuid:outcome_id>/order-book/",
        MarketOrderBookView.as_view(),
        name="market-order-book",
    ),
    path(
        "market-fills/",
        MarketFillListView.as_view(),
        name="market-fill-list",
    ),
    path(
        "market-fills/<uuid:fill_id>/",
        MarketFillDetailView.as_view(),
        name="market-fill-detail",
    ),
]

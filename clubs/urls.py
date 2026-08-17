"""URL configuration for club management."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from clubs.views import (
    ClubAdminInviteView,
    ClubAuditLogViewSet,
    ClubLogoView,
    ClubMediaViewSet,
    ClubNewsViewSet,
    ClubProfileVersionViewSet,
    ClubWorkspaceViewSet,
    MembershipPlanViewSet,
    MerchandiseProductViewSet,
    NewsSubmissionView,
    ProductCategoryViewSet,
    StaffInvitationAcceptView,
    StaffInvitationViewSet,
    StoreOrderViewSet,
    TicketProductViewSet,
)

router = DefaultRouter()
router.register(r"workspaces", ClubWorkspaceViewSet, basename="club-workspace")
router.register(r"profiles", ClubProfileVersionViewSet, basename="club-profile")
router.register(r"media", ClubMediaViewSet, basename="club-media")
router.register(r"news", ClubNewsViewSet, basename="club-news")
router.register(r"membership-plans", MembershipPlanViewSet, basename="membership-plan")
router.register(r"ticket-products", TicketProductViewSet, basename="ticket-product")
router.register(r"merchandise", MerchandiseProductViewSet, basename="merchandise-product")
router.register(r"categories", ProductCategoryViewSet, basename="product-category")
router.register(r"orders", StoreOrderViewSet, basename="store-order")
router.register(r"audit-logs", ClubAuditLogViewSet, basename="club-audit-log")
router.register(r"staff-invitations", StaffInvitationViewSet, basename="staff-invitation")

app_name = "clubs"

urlpatterns = [
    path(
        "staff-invitations/accept/",
        StaffInvitationAcceptView.as_view(),
        name="staff-invitation-accept",
    ),
    path(
        "<uuid:club_pk>/workspaces/",
        ClubWorkspaceViewSet.as_view({"get": "list", "post": "create"}),
        name="club-workspace-list",
    ),
    path(
        "<uuid:club_pk>/workspaces/<uuid:pk>/",
        ClubWorkspaceViewSet.as_view(
            {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
        ),
        name="club-workspace-detail",
    ),
    path(
        "<uuid:club_pk>/profiles/",
        ClubProfileVersionViewSet.as_view({"get": "list", "post": "create"}),
        name="club-profile-list",
    ),
    path(
        "<uuid:club_pk>/profiles/<uuid:pk>/",
        ClubProfileVersionViewSet.as_view(
            {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
        ),
        name="club-profile-detail",
    ),
    path(
        "<uuid:club_pk>/profiles/<uuid:pk>/publish/",
        ClubProfileVersionViewSet.as_view({"post": "publish"}),
        name="club-profile-publish",
    ),
    path(
        "<uuid:club_pk>/profiles/<uuid:pk>/schedule/",
        ClubProfileVersionViewSet.as_view({"post": "schedule"}),
        name="club-profile-schedule",
    ),
    path(
        "<uuid:club_pk>/media/",
        ClubMediaViewSet.as_view({"get": "list", "post": "create"}),
        name="club-media-list",
    ),
    path(
        "<uuid:club_pk>/media/<uuid:pk>/",
        ClubMediaViewSet.as_view(
            {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
        ),
        name="club-media-detail",
    ),
    path(
        "<uuid:club_pk>/media/<uuid:pk>/publish/",
        ClubMediaViewSet.as_view({"post": "publish"}),
        name="club-media-publish",
    ),
    path(
        "<uuid:club_pk>/media/<uuid:pk>/schedule/",
        ClubMediaViewSet.as_view({"post": "schedule"}),
        name="club-media-schedule",
    ),
    path(
        "<uuid:club_pk>/news/",
        ClubNewsViewSet.as_view({"get": "list", "post": "create"}),
        name="club-news-list",
    ),
    path(
        "<uuid:club_pk>/news/<uuid:pk>/",
        ClubNewsViewSet.as_view(
            {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
        ),
        name="club-news-detail",
    ),
    path(
        "<uuid:club_pk>/news/<uuid:pk>/publish/",
        ClubNewsViewSet.as_view({"post": "publish"}),
        name="club-news-publish",
    ),
    path(
        "<uuid:club_pk>/news/<uuid:pk>/schedule/",
        ClubNewsViewSet.as_view({"post": "schedule"}),
        name="club-news-schedule",
    ),
    path(
        "<uuid:club_pk>/news-submissions/",
        NewsSubmissionView.as_view(),
        name="club-news-submission-list",
    ),
    path(
        "<uuid:club_pk>/logo/",
        ClubLogoView.as_view(),
        name="club-logo",
    ),
    path(
        "<uuid:club_pk>/membership-plans/",
        MembershipPlanViewSet.as_view({"get": "list", "post": "create"}),
        name="membership-plan-list",
    ),
    path(
        "<uuid:club_pk>/membership-plans/<uuid:pk>/",
        MembershipPlanViewSet.as_view(
            {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
        ),
        name="membership-plan-detail",
    ),
    path(
        "<uuid:club_pk>/ticket-products/",
        TicketProductViewSet.as_view({"get": "list", "post": "create"}),
        name="ticket-product-list",
    ),
    path(
        "<uuid:club_pk>/ticket-products/<uuid:pk>/",
        TicketProductViewSet.as_view(
            {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
        ),
        name="ticket-product-detail",
    ),
    path(
        "<uuid:club_pk>/merchandise/",
        MerchandiseProductViewSet.as_view({"get": "list", "post": "create"}),
        name="merchandise-list",
    ),
    path(
        "<uuid:club_pk>/merchandise/<uuid:pk>/",
        MerchandiseProductViewSet.as_view(
            {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
        ),
        name="merchandise-detail",
    ),
    path(
        "<uuid:club_pk>/categories/",
        ProductCategoryViewSet.as_view({"get": "list", "post": "create"}),
        name="product-category-list",
    ),
    path(
        "<uuid:club_pk>/categories/<uuid:pk>/",
        ProductCategoryViewSet.as_view(
            {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
        ),
        name="product-category-detail",
    ),
    path(
        "<uuid:club_pk>/orders/",
        StoreOrderViewSet.as_view({"get": "list"}),
        name="store-order-list",
    ),
    path(
        "<uuid:club_pk>/audit-logs/",
        ClubAuditLogViewSet.as_view({"get": "list"}),
        name="club-audit-log-list",
    ),
    path(
        "<uuid:club_pk>/staff-invitations/",
        StaffInvitationViewSet.as_view({"get": "list", "post": "create"}),
        name="staff-invitation-list",
    ),
    path(
        "<uuid:club_pk>/staff-invitations/invite-admin/",
        ClubAdminInviteView.as_view(),
        name="club-admin-invite",
    ),
    path(
        "<uuid:club_pk>/staff-invitations/<uuid:pk>/",
        StaffInvitationViewSet.as_view(
            {"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}
        ),
        name="staff-invitation-detail",
    ),
]

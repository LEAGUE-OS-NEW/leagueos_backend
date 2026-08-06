"""URL configuration for club management."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from clubs.views import (
    ClubWorkspaceViewSet,
    ClubProfileVersionViewSet,
    ClubMediaViewSet,
    ClubNewsViewSet,
    MembershipPlanViewSet,
    TicketProductViewSet,
    MerchandiseProductViewSet,
    StoreOrderViewSet,
    ClubAuditLogViewSet,
    StaffInvitationViewSet,
)

router = DefaultRouter()
router.register(r"workspaces", ClubWorkspaceViewSet, basename="club-workspace")
router.register(r"profiles", ClubProfileVersionViewSet, basename="club-profile")
router.register(r"media", ClubMediaViewSet, basename="club-media")
router.register(r"news", ClubNewsViewSet, basename="club-news")
router.register(r"membership-plans", MembershipPlanViewSet, basename="membership-plan")
router.register(r"ticket-products", TicketProductViewSet, basename="ticket-product")
router.register(r"merchandise", MerchandiseProductViewSet, basename="merchandise-product")
router.register(r"orders", StoreOrderViewSet, basename="store-order")
router.register(r"audit-logs", ClubAuditLogViewSet, basename="club-audit-log")
router.register(r"staff-invitations", StaffInvitationViewSet, basename="staff-invitation")

app_name = "clubs"

urlpatterns = [
    path(
        "<uuid:club_pk>/workspaces/",
        ClubWorkspaceViewSet.as_view({"get": "list", "post": "create"}),
        name="club-workspace-list",
    ),
    path(
        "<uuid:club_pk>/workspaces/<uuid:pk>/",
        ClubWorkspaceViewSet.as_view({"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}),
        name="club-workspace-detail",
    ),
    path(
        "<uuid:club_pk>/profiles/",
        ClubProfileVersionViewSet.as_view({"get": "list", "post": "create"}),
        name="club-profile-list",
    ),
    path(
        "<uuid:club_pk>/profiles/<uuid:pk>/",
        ClubProfileVersionViewSet.as_view({"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}),
        name="club-profile-detail",
    ),
    path(
        "<uuid:club_pk>/media/",
        ClubMediaViewSet.as_view({"get": "list", "post": "create"}),
        name="club-media-list",
    ),
    path(
        "<uuid:club_pk>/media/<uuid:pk>/",
        ClubMediaViewSet.as_view({"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}),
        name="club-media-detail",
    ),
    path(
        "<uuid:club_pk>/membership-plans/",
        MembershipPlanViewSet.as_view({"get": "list", "post": "create"}),
        name="membership-plan-list",
    ),
    path(
        "<uuid:club_pk>/membership-plans/<uuid:pk>/",
        MembershipPlanViewSet.as_view({"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}),
        name="membership-plan-detail",
    ),
    path(
        "<uuid:club_pk>/ticket-products/",
        TicketProductViewSet.as_view({"get": "list", "post": "create"}),
        name="ticket-product-list",
    ),
    path(
        "<uuid:club_pk>/ticket-products/<uuid:pk>/",
        TicketProductViewSet.as_view({"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}),
        name="ticket-product-detail",
    ),
    path(
        "<uuid:club_pk>/merchandise/",
        MerchandiseProductViewSet.as_view({"get": "list", "post": "create"}),
        name="merchandise-list",
    ),
    path(
        "<uuid:club_pk>/merchandise/<uuid:pk>/",
        MerchandiseProductViewSet.as_view({"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}),
        name="merchandise-detail",
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
        "<uuid:club_pk>/staff-invitations/<uuid:pk>/",
        StaffInvitationViewSet.as_view({"get": "retrieve", "put": "update", "patch": "partial_update", "delete": "destroy"}),
        name="staff-invitation-detail",
    ),
]

from django.urls import path

from platform_admin.views import (
    MyPlatformMembershipView,
    PlatformMembershipCancelView,
    PlatformMembershipSubscribeView,
    PublicPlatformMembershipPlanListView,
)

app_name = "platform_memberships"

urlpatterns = [
    path("plans/", PublicPlatformMembershipPlanListView.as_view(), name="plan-list"),
    path("me/", MyPlatformMembershipView.as_view(), name="my-memberships"),
    path("subscribe/", PlatformMembershipSubscribeView.as_view(), name="subscribe"),
    path(
        "subscriptions/<uuid:subscription_id>/cancel/",
        PlatformMembershipCancelView.as_view(),
        name="cancel",
    ),
]

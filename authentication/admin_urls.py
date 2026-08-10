from django.urls import include, path
from rest_framework.routers import DefaultRouter

from authentication.admin_views import (
    AvailablePermissionsView,
    AvailableRolesView,
    SubordinateUserViewSet,
)

app_name = "admin_authentication"

router = DefaultRouter()
router.register("users", SubordinateUserViewSet, basename="subordinate-user")

urlpatterns = [
    path("", include(router.urls)),
    path("available-roles/", AvailableRolesView.as_view(), name="available-roles"),
    path(
        "available-permissions/", AvailablePermissionsView.as_view(), name="available-permissions"
    ),
]

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "api/v1/schema/",
        SpectacularAPIView.as_view(),
        name="api-schema",
    ),
    path(
        "api/v1/docs/",
        SpectacularSwaggerView.as_view(url_name="api-schema"),
        name="api-docs",
    ),
    path(
        "api/v1/redoc/",
        SpectacularRedocView.as_view(url_name="api-schema"),
        name="api-redoc",
    ),
    path("api/v1/", include("accounts.urls")),
    path("api/v1/auth/", include("authentication.urls")),
    path("api/v1/auth/admin/", include("authentication.admin_urls")),
    path("api/v1/admin/", include("platform_admin.urls")),
    path("api/v1/", include("dashboard.urls")),
    path("api/v1/", include("clubs.urls")),
    path("api/v1/", include("discovery.urls")),
    path(
        "api/v1/",
        include("markets.urls"),
    ),
    path("api/v1/wallets/", include("wallets.urls")),
    path("api/v1/", include("profiles.urls")),
    path("api/v1/", include("onboarding.urls")),
    path("api/v1/", include("notifications.urls")),
    path(
        "api/v1/",
        include("sports.urls"),
    ),
    path("api/v1/system/", include("system.urls")),
    path("api/v1/", include("kyc.urls")),
]

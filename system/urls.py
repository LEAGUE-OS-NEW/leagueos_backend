from django.urls import path

from system.views import (
    health_check,
    market_catalogue_audit,
    market_catalogue_cleanup,
    pesapal_diagnostic,
)

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path(
        "review/markets/catalogue-cleanup/",
        market_catalogue_cleanup,
        name="market-catalogue-cleanup",
    ),
    path(
        "review/markets/catalogue-audit/",
        market_catalogue_audit,
        name="market-catalogue-audit",
    ),
    path(
        "integrations/pesapal/diagnostic/",
        pesapal_diagnostic,
        name="pesapal-diagnostic",
    ),
]

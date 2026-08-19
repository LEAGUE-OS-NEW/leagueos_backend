from django.urls import path

from system.views import (
    health_check,
    market_catalogue_audit,
    market_purge_preflight,
    pesapal_diagnostic,
)

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path(
        "review/markets/catalogue-audit/",
        market_catalogue_audit,
        name="market-catalogue-audit",
    ),
    path(
        "review/markets/purge-preflight/",
        market_purge_preflight,
        name="market-purge-preflight",
    ),
    path(
        "integrations/pesapal/diagnostic/",
        pesapal_diagnostic,
        name="pesapal-diagnostic",
    ),
]

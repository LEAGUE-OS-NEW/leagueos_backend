from django.urls import path

from system.views import health_check, pesapal_diagnostic

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path(
        "integrations/pesapal/diagnostic/",
        pesapal_diagnostic,
        name="pesapal-diagnostic",
    ),
]

from django.urls import path

from system.views import health_check

urlpatterns = [
    path("health/", health_check, name="health-check"),
]

"""URL routing for the dashboard module."""

from django.urls import path

from dashboard.views import (
    AnalyticsView,
    DashboardView,
    ModulesView,
    NavigationView,
    WidgetsView,
)

app_name = "dashboard"

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("navigation/", NavigationView.as_view(), name="navigation"),
    path("widgets/", WidgetsView.as_view(), name="widgets"),
    path("modules/", ModulesView.as_view(), name="modules"),
    path("analytics/", AnalyticsView.as_view(), name="analytics"),
]

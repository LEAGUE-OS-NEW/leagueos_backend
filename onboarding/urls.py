"""URL configuration for the Fan Onboarding & Personalization module."""

from django.urls import path

from onboarding.views import (
    ClubCatalogueView,
    ClubSelectionView,
    CompetitionCatalogueView,
    CompetitionSelectionView,
    CompleteOnboardingView,
    CountryCatalogueView,
    CountrySelectionView,
    DashboardConfigurationView,
    OnboardingStatusView,
    SkipStepView,
    SportCatalogueView,
    SportSelectionView,
)

app_name = "onboarding"

urlpatterns = [
    # Preference Catalogues
    path("preferences/countries/", CountryCatalogueView.as_view(), name="preference-countries"),
    path("preferences/sports/", SportCatalogueView.as_view(), name="preference-sports"),
    path(
        "preferences/competitions/",
        CompetitionCatalogueView.as_view(),
        name="preference-competitions",
    ),
    path("preferences/clubs/", ClubCatalogueView.as_view(), name="preference-clubs"),
    # Onboarding
    path("onboarding/", OnboardingStatusView.as_view(), name="onboarding-status"),
    path("onboarding/country/", CountrySelectionView.as_view(), name="onboarding-country"),
    path("onboarding/sports/", SportSelectionView.as_view(), name="onboarding-sports"),
    path(
        "onboarding/competitions/",
        CompetitionSelectionView.as_view(),
        name="onboarding-competitions",
    ),
    path("onboarding/clubs/", ClubSelectionView.as_view(), name="onboarding-clubs"),
    path("onboarding/skip/", SkipStepView.as_view(), name="onboarding-skip"),
    path("onboarding/complete/", CompleteOnboardingView.as_view(), name="onboarding-complete"),
    path(
        "onboarding/dashboard/",
        DashboardConfigurationView.as_view(),
        name="onboarding-dashboard",
    ),
]

"""URL patterns for the profiles app.

Routes:
    GET  /api/v1/profile/                    — Retrieve profile
    PATCH  /api/v1/profile/                  — Update profile
    POST   /api/v1/profile/avatar/           — Upload or replace avatar
    DELETE /api/v1/profile/avatar/           — Delete avatar
    GET    /api/v1/profile/avatar/           — Retrieve avatar metadata
    GET    /api/v1/lookups/countries/        — List countries
    GET    /api/v1/lookups/languages/        — List languages
    GET    /api/v1/lookups/timezones/        — List timezones
    GET    /api/v1/lookups/genders/          — List genders
    GET    /api/v1/clubs/                    — List clubs
"""

from django.urls import path

from profiles.views import (
    AvatarView,
    ClubListView,
    CountryListView,
    GenderListView,
    LanguageListView,
    ProfileView,
    TimezoneListView,
)

urlpatterns = [
    path("profile/", ProfileView.as_view(), name="profile"),
    path("profile/avatar/", AvatarView.as_view(), name="avatar"),
    path("lookups/countries/", CountryListView.as_view(), name="countries"),
    path("lookups/languages/", LanguageListView.as_view(), name="languages"),
    path("lookups/timezones/", TimezoneListView.as_view(), name="timezones"),
    path("lookups/genders/", GenderListView.as_view(), name="genders"),
    path("clubs/", ClubListView.as_view(), name="clubs"),
]

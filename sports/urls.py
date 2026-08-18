from django.urls import path

from sports.views import (
    CompetitionListView,
    ParticipantListView,
    SportingEventListView,
    SportListView,
)

app_name = "sports"

urlpatterns = [
    path(
        "sports/",
        SportListView.as_view(),
        name="sport-list",
    ),
    path(
        "competitions/",
        CompetitionListView.as_view(),
        name="competition-list",
    ),
    # Dedicated writable endpoint used by the admin UI to create canonical
    # competitions. The public-facing /competitions/ route is served by the
    # discovery app (GET-only ListAPIView), so this distinct path avoids the
    # URL shadowing conflict.
    path(
        "admin/sports/competitions/",
        CompetitionListView.as_view(),
        name="admin-competition-create",
    ),
    path(
        "participants/",
        ParticipantListView.as_view(),
        name="participant-list",
    ),
    path(
        "sporting-events/",
        SportingEventListView.as_view(),
        name="event-list",
    ),
]

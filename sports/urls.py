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

"""URL configuration for the discovery module."""

from django.urls import path

from discovery.views import (
    ClubDetailView,
    ClubFollowView,
    ClubListView,
    ClubMediaListView,
    CompetitionListView,
    FixtureDetailView,
    FixtureListView,
    FollowingListView,
    MatchCentreView,
    NewsCategoryListView,
    NewsDetailView,
    NewsListView,
    PlayerDetailView,
    PlayerListView,
    ResultListView,
    SearchAutocompleteView,
    SearchSuggestionsView,
    SearchView,
)

app_name = "discovery"

urlpatterns = [
    # Search
    path("search/", SearchView.as_view(), name="search"),
    path(
        "search/autocomplete/",
        SearchAutocompleteView.as_view(),
        name="search-autocomplete",
    ),
    path(
        "search/suggestions/",
        SearchSuggestionsView.as_view(),
        name="search-suggestions",
    ),
    # Clubs
    path("clubs/", ClubListView.as_view(), name="club-list"),
    path("clubs/<uuid:club_id>/", ClubDetailView.as_view(), name="club-detail"),
    path(
        "clubs/<uuid:club_id>/media/",
        ClubMediaListView.as_view(),
        name="club-media-list",
    ),
    path(
        "clubs/<uuid:club_id>/follow/",
        ClubFollowView.as_view(),
        name="club-follow",
    ),
    # Players
    path("players/", PlayerListView.as_view(), name="player-list"),
    path(
        "players/<uuid:player_id>/",
        PlayerDetailView.as_view(),
        name="player-detail",
    ),
    # Competitions
    path(
        "competitions/",
        CompetitionListView.as_view(),
        name="competition-list",
    ),
    # Fixtures & Results
    path("fixtures/", FixtureListView.as_view(), name="fixture-list"),
    path(
        "fixtures/<uuid:fixture_id>/",
        FixtureDetailView.as_view(),
        name="fixture-detail",
    ),
    path("results/", ResultListView.as_view(), name="result-list"),
    # News
    path("news/", NewsListView.as_view(), name="news-list"),
    path("news/<uuid:news_id>/", NewsDetailView.as_view(), name="news-detail"),
    path("news-categories/", NewsCategoryListView.as_view(), name="news-category-list"),
    # Match Centre
    path(
        "match-centre/<uuid:fixture_id>/",
        MatchCentreView.as_view(),
        name="match-centre",
    ),
    # Following
    path(
        "profile/following/",
        FollowingListView.as_view(),
        name="following-list",
    ),
]

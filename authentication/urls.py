from django.urls import path

from authentication.views import (
    LoginView,
    LogoutAllView,
    LogoutView,
    MeView,
    ProfileView,
    SessionListView,
)

app_name = "authentication"

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("logout-all/", LogoutAllView.as_view(), name="logout-all"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("me/", MeView.as_view(), name="me"),
    path("sessions/", SessionListView.as_view(), name="sessions"),
]

from django.urls import path

from authentication.views import ChangePasswordView

app_name = "authentication"

urlpatterns = [
    path("change-password/", ChangePasswordView.as_view(), name="auth_change_password"),
]

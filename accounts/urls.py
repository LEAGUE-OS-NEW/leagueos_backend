from django.urls import path

from accounts.account_status_views import (
    AccountCancelDeletionView,
    AccountDeactivateView,
    AccountReactivateView,
    AccountRequestDeletionView,
    AccountStatusView,
)
from accounts.views import (
    AccountSetupCompleteView,
    RegisterView,
    RegistrationStatusView,
    ResendOTPView,
    VerifyOTPView,
)

app_name = "accounts"

urlpatterns = [
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/verify-otp/", VerifyOTPView.as_view(), name="verify-otp"),
    path("auth/resend-otp/", ResendOTPView.as_view(), name="resend-otp"),
    path("auth/resend-verification/", ResendOTPView.as_view(), name="resend-verification"),
    path("auth/registration-status/", RegistrationStatusView.as_view(), name="registration-status"),
    path("auth/account-setup/", AccountSetupCompleteView.as_view(), name="account-setup"),
    path("account/status/", AccountStatusView.as_view(), name="account-status"),
    path("account/deactivate/", AccountDeactivateView.as_view(), name="account-deactivate"),
    path("account/reactivate/", AccountReactivateView.as_view(), name="account-reactivate"),
    path(
        "account/delete/request/",
        AccountRequestDeletionView.as_view(),
        name="account-delete-request",
    ),
    path(
        "account/delete/cancel/", AccountCancelDeletionView.as_view(), name="account-delete-cancel"
    ),
]

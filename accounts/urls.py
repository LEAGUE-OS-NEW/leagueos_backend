from django.urls import path

from accounts.views import (
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
]

from django.urls import path
from kyc.views import (
    AdminKYCDetailView,
    AdminKYCDocumentUrlView,
    AdminKYCListView,
    AdminKYCReviewActionView,
    FanKYCRetryView,
    FanKYCStatusView,
    FanKYCSubmitView,
)

app_name = "kyc"

urlpatterns = [
    # Fan endpoints
    path("fans/kyc/", FanKYCSubmitView.as_view(), name="fan-kyc-submit"),
    path("fans/kyc/status/", FanKYCStatusView.as_view(), name="fan-kyc-status"),
    path("fans/kyc/retry/", FanKYCRetryView.as_view(), name="fan-kyc-retry"),
    # Admin endpoints
    path("admin/kyc/verifications/", AdminKYCListView.as_view(), name="admin-kyc-list"),
    path(
        "admin/kyc/verifications/<uuid:verification_id>/",
        AdminKYCDetailView.as_view(),
        name="admin-kyc-detail",
    ),
    path(
        "admin/kyc/verifications/<uuid:verification_id>/document-url/",
        AdminKYCDocumentUrlView.as_view(),
        name="admin-kyc-document-url",
    ),
    path(
        "admin/kyc/verifications/<uuid:verification_id>/review/",
        AdminKYCReviewActionView.as_view(),
        name="admin-kyc-review",
    ),
]

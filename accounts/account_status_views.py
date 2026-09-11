"""Fan-facing account status, deactivation, and deletion-request endpoints.

Backs the frontend's Settings -> Account tab (src/services/accountService.ts).
`User.account_status` already models ACTIVE/SUSPENDED/DEACTIVATED/etc; the
only gap was a "pending deletion" concept and the endpoints to drive it.
"""

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.serializers import build_response
from accounts.views import log_audit


def account_status_payload(user: User) -> dict:
    if user.deletion_requested_at is not None:
        mapped = "Pending Deletion"
    elif user.account_status == User.AccountStatus.DEACTIVATED:
        mapped = "Deactivated"
    else:
        mapped = "Active"
    return {"status": mapped}


class AccountStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response(
            build_response(True, "Account status.", data=account_status_payload(request.user))
        )


class AccountDeactivateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={200: dict})
    def post(self, request):
        user = request.user
        user.account_status = User.AccountStatus.DEACTIVATED
        user.save(update_fields=["account_status", "updated_at"])
        log_audit(user, "ACCOUNT_DEACTIVATED", ip_address=request.META.get("REMOTE_ADDR"))
        return Response(
            build_response(True, "Account deactivated.", data=account_status_payload(user))
        )


class AccountReactivateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={200: dict})
    def post(self, request):
        user = request.user
        if user.account_status == User.AccountStatus.DEACTIVATED:
            user.account_status = User.AccountStatus.ACTIVE
            user.save(update_fields=["account_status", "updated_at"])
        log_audit(user, "ACCOUNT_REACTIVATED", ip_address=request.META.get("REMOTE_ADDR"))
        return Response(
            build_response(True, "Account reactivated.", data=account_status_payload(user))
        )


class AccountRequestDeletionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={200: dict})
    def post(self, request):
        user = request.user
        user.deletion_requested_at = timezone.now()
        user.save(update_fields=["deletion_requested_at", "updated_at"])
        log_audit(user, "ACCOUNT_DELETION_REQUESTED", ip_address=request.META.get("REMOTE_ADDR"))
        return Response(
            build_response(True, "Account deletion requested.", data=account_status_payload(user))
        )


class AccountCancelDeletionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses={200: dict})
    def post(self, request):
        user = request.user
        user.deletion_requested_at = None
        user.save(update_fields=["deletion_requested_at", "updated_at"])
        log_audit(user, "ACCOUNT_DELETION_CANCELLED", ip_address=request.META.get("REMOTE_ADDR"))
        return Response(
            build_response(True, "Account deletion cancelled.", data=account_status_payload(user))
        )

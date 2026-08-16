"""Finance Admin API coverage for wallet withdrawals."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from authentication.tests.factories import (
    PermissionFactory,
    RoleFactory,
    RolePermissionFactory,
    UserFactory,
    UserRoleFactory,
)
from wallets.models import (
    LedgerEntry,
    WithdrawalRequest,
    WalletTransaction,
)
from wallets.services.wallet_service import WalletService
from wallets.tests.factories import WalletFactory

pytestmark = pytest.mark.django_db


def client_for(user):
    client = APIClient()
    client.force_authenticate(
        user=user,
    )
    return client


def grant_permission(user, code):
    permission = PermissionFactory(
        name=code,
        code=code,
        resource="finance",
        action=code,
    )
    role = RoleFactory()

    RolePermissionFactory(
        role=role,
        permission=permission,
    )
    UserRoleFactory(
        user=user,
        role=role,
    )

    return permission


@pytest.fixture
def withdrawal_case(settings):
    settings.WALLET_WITHDRAWAL_AUTO_APPROVAL_ENABLED = False

    def create():
        owner = UserFactory(
            is_verified=True,
        )
        wallet = WalletFactory(
            user=owner,
            currency="UGX",
            available_balance=Decimal("100000.0000"),
            reserved_balance=Decimal("0.0000"),
        )

        withdrawal = WalletService.create_withdrawal_request(
            user=owner,
            amount=Decimal("20000.0000"),
            currency="UGX",
            destination={
                "method": "MOBILE_MONEY",
                "network": "MTN",
                "mobile_money_number": ("0777123456"),
                "account_name": "Test Fan",
            },
            idempotency_key=uuid4(),
        )

        wallet.refresh_from_db()

        assert withdrawal.status == WithdrawalRequest.Status.PENDING_APPROVAL
        assert wallet.available_balance == Decimal("80000.0000")
        assert wallet.reserved_balance == Decimal("20000.0000")

        return owner, wallet, withdrawal

    return create


class TestFinanceWithdrawalAdminAPI:
    def test_ordinary_user_is_denied_but_finance_viewer_can_read(
        self,
        withdrawal_case,
    ):
        owner, _wallet, withdrawal = withdrawal_case()

        ordinary = UserFactory()
        denied = client_for(ordinary).get(reverse("wallets:admin-withdrawal-list"))

        assert denied.status_code == status.HTTP_403_FORBIDDEN

        viewer = UserFactory()
        grant_permission(
            viewer,
            "view_finance",
        )
        viewer_client = client_for(viewer)

        response = viewer_client.get(reverse("wallets:admin-withdrawal-list"))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["id"] == str(withdrawal.id)
        assert response.data["results"][0]["user_id"] == str(owner.id)
        assert response.data["results"][0]["currency"] == "UGX"

        detail = viewer_client.get(
            reverse(
                "wallets:admin-withdrawal-detail",
                kwargs={
                    "request_id": withdrawal.id,
                },
            )
        )

        assert detail.status_code == status.HTTP_200_OK
        assert detail.data["id"] == str(withdrawal.id)

    def test_finance_viewer_cannot_approve(
        self,
        withdrawal_case,
    ):
        _owner, _wallet, withdrawal = withdrawal_case()

        viewer = UserFactory()
        grant_permission(
            viewer,
            "view_finance",
        )

        response = client_for(viewer).post(
            reverse(
                "wallets:admin-withdrawal-approve",
                kwargs={
                    "request_id": withdrawal.id,
                },
            ),
            {},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

        withdrawal.refresh_from_db()
        assert withdrawal.status == WithdrawalRequest.Status.PENDING_APPROVAL

    def test_reviewer_can_approve_but_cannot_start_processing(
        self,
        withdrawal_case,
    ):
        _owner, wallet, withdrawal = withdrawal_case()

        reviewer = UserFactory()
        grant_permission(
            reviewer,
            "review_withdrawal",
        )
        reviewer_client = client_for(reviewer)

        approved = reviewer_client.post(
            reverse(
                "wallets:admin-withdrawal-approve",
                kwargs={
                    "request_id": withdrawal.id,
                },
            ),
            {},
            format="json",
        )

        assert approved.status_code == status.HTTP_200_OK
        assert approved.data["status"] == WithdrawalRequest.Status.APPROVED
        assert approved.data["approved_by_id"] == str(reviewer.id)

        wallet.refresh_from_db()

        assert wallet.available_balance == Decimal("80000.0000")
        assert wallet.reserved_balance == Decimal("20000.0000")

        processing = reviewer_client.post(
            reverse(
                "wallets:admin-withdrawal-processing",
                kwargs={
                    "request_id": withdrawal.id,
                },
            ),
            {},
            format="json",
        )

        assert processing.status_code == status.HTTP_403_FORBIDDEN

    def test_reviewer_can_reject_and_release_reservation(
        self,
        withdrawal_case,
    ):
        _owner, wallet, withdrawal = withdrawal_case()

        reviewer = UserFactory()
        grant_permission(
            reviewer,
            "review_withdrawal",
        )

        response = client_for(reviewer).post(
            reverse(
                "wallets:admin-withdrawal-reject",
                kwargs={
                    "request_id": withdrawal.id,
                },
            ),
            {
                "reason": ("Destination ownership " "could not be confirmed."),
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == WithdrawalRequest.Status.REJECTED

        withdrawal.refresh_from_db()
        withdrawal.transaction.refresh_from_db()
        wallet.refresh_from_db()

        assert wallet.available_balance == Decimal("100000.0000")
        assert wallet.reserved_balance == Decimal("0.0000")
        assert withdrawal.transaction.status == WalletTransaction.Status.CANCELLED

        assert (
            LedgerEntry.objects.filter(
                transaction=withdrawal.transaction,
                entry_type=(LedgerEntry.EntryType.RELEASE),
            ).count()
            == 1
        )

    def test_finance_manager_can_process_and_complete_payout(
        self,
        withdrawal_case,
    ):
        _owner, wallet, withdrawal = withdrawal_case()

        approval_actor = UserFactory()
        WalletService.approve_withdrawal(
            withdrawal_id=withdrawal.id,
            actor=approval_actor,
        )

        manager = UserFactory()
        grant_permission(
            manager,
            "manage_finance",
        )
        manager_client = client_for(manager)

        processing = manager_client.post(
            reverse(
                "wallets:admin-withdrawal-processing",
                kwargs={
                    "request_id": withdrawal.id,
                },
            ),
            {},
            format="json",
        )

        assert processing.status_code == status.HTTP_200_OK
        assert processing.data["status"] == WithdrawalRequest.Status.PROCESSING

        completed = manager_client.post(
            reverse(
                "wallets:admin-withdrawal-complete",
                kwargs={
                    "request_id": withdrawal.id,
                },
            ),
            {
                "provider_reference": ("MTN-MANUAL-PAYOUT-001"),
            },
            format="json",
        )

        assert completed.status_code == status.HTTP_200_OK
        assert completed.data["status"] == WithdrawalRequest.Status.COMPLETED
        assert completed.data["provider_reference"] == "MTN-MANUAL-PAYOUT-001"

        withdrawal.refresh_from_db()
        withdrawal.transaction.refresh_from_db()
        wallet.refresh_from_db()

        assert wallet.available_balance == Decimal("80000.0000")
        assert wallet.reserved_balance == Decimal("0.0000")
        assert withdrawal.transaction.status == WalletTransaction.Status.COMPLETED

        assert (
            LedgerEntry.objects.filter(
                transaction=withdrawal.transaction,
                entry_type=(LedgerEntry.EntryType.DEBIT),
            ).count()
            == 1
        )

    def test_finance_manager_can_fail_payout_and_release_reservation(
        self,
        withdrawal_case,
    ):
        _owner, wallet, withdrawal = withdrawal_case()

        WalletService.approve_withdrawal(
            withdrawal_id=withdrawal.id,
            actor=UserFactory(),
        )

        manager = UserFactory()
        grant_permission(
            manager,
            "manage_finance",
        )

        response = client_for(manager).post(
            reverse(
                "wallets:admin-withdrawal-fail",
                kwargs={
                    "request_id": withdrawal.id,
                },
            ),
            {
                "reason": ("Manual mobile money " "payout failed."),
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == WithdrawalRequest.Status.FAILED

        withdrawal.refresh_from_db()
        wallet.refresh_from_db()

        assert wallet.available_balance == Decimal("100000.0000")
        assert wallet.reserved_balance == Decimal("0.0000")

        assert (
            LedgerEntry.objects.filter(
                transaction=withdrawal.transaction,
                entry_type=(LedgerEntry.EntryType.RELEASE),
            ).count()
            == 1
        )

    def test_superuser_can_review_without_seeded_role_assignment(
        self,
        withdrawal_case,
    ):
        _owner, _wallet, withdrawal = withdrawal_case()

        superuser = UserFactory(
            is_superuser=True,
            is_staff=True,
        )

        response = client_for(superuser).post(
            reverse(
                "wallets:admin-withdrawal-approve",
                kwargs={
                    "request_id": withdrawal.id,
                },
            ),
            {},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == WithdrawalRequest.Status.APPROVED

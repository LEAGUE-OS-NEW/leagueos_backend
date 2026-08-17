"""Tests for the wallets API."""

from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from authentication.tests.factories import UserFactory
from wallets.models import WithdrawalRequest
from wallets.services.pesapal_client import PesapalApiError
from wallets.services.pesapal_deposit_service import (
    PesapalDepositService,
)
from wallets.tests.factories import PaymentProviderFactory, WalletFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def auth_client():
    client = APIClient()
    user = UserFactory()
    client.force_authenticate(user=user)
    client.user = user
    return client


class TestWalletAPI:
    def test_list_wallets_unauthenticated(self, client):
        url = reverse("wallets:wallet-list")
        response = client.get(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_wallets_scoped_to_user(self, auth_client):
        WalletFactory(user=auth_client.user, currency="UGX")
        WalletFactory(user=auth_client.user, currency="USD")
        WalletFactory(user=UserFactory(), currency="UGX")  # Other user's wallet

        url = reverse("wallets:wallet-list")
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 2
        currencies = {item["currency"] for item in response.data["results"]}
        assert currencies == {"UGX", "USD"}

    def test_get_wallet_detail(self, auth_client):
        wallet = WalletFactory(user=auth_client.user, currency="UGX", available_balance=1000)
        url = reverse("wallets:wallet-detail", kwargs={"currency": "UGX"})
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(wallet.id)
        assert response.data["currency"] == "UGX"
        assert response.data["available_balance"] == "1000.0000"

    def test_get_wallet_detail_not_found(self, auth_client):
        url = reverse("wallets:wallet-detail", kwargs={"currency": "EUR"})
        response = auth_client.get(url)
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestDepositAPI:
    def test_create_deposit_intent(self, auth_client):
        provider = PaymentProviderFactory(code="MOCK", name="Mock Provider")
        url = reverse("wallets:deposit-intent-create")
        data = {
            "amount": "50000",
            "currency": "UGX",
            "provider_code": provider.code,
        }
        response = auth_client.post(url, data)

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["status"] == "PENDING"
        assert response.data["provider_code"] == "MOCK"
        assert "payment_url" not in response.data

    def test_create_deposit_intent_invalid_provider(self, auth_client):
        url = reverse("wallets:deposit-intent-create")
        data = {"amount": "50000", "currency": "UGX", "provider_code": "INVALID"}
        response = auth_client.post(url, data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_pesapal_provider_error_returns_safe_502(
        self,
        auth_client,
        monkeypatch,
    ):
        mocked_start = Mock(side_effect=PesapalApiError("Pesapal HTTP error 400."))

        monkeypatch.setattr(
            PesapalDepositService,
            "start_deposit",
            mocked_start,
        )

        url = reverse("wallets:deposit-intent-create")

        response = auth_client.post(
            url,
            {
                "amount": "50000",
                "currency": "UGX",
                "provider_code": ("PESAPAL_SANDBOX"),
                "idempotency_key": str(uuid4()),
            },
            format="json",
        )

        assert response.status_code == status.HTTP_502_BAD_GATEWAY

        assert response.data == {
            "provider": [
                "Pesapal Sandbox checkout "
                "could not be confirmed. "
                "Do not automatically retry "
                "this request."
            ]
        }


class TestWithdrawalAPI:
    def test_list_withdrawals_requires_authentication(
        self,
        client,
    ):
        url = reverse("wallets:withdrawal-request-create")

        response = client.get(url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_withdrawals_is_scoped_to_user(
        self,
        auth_client,
    ):
        own_wallet = WalletFactory(
            user=auth_client.user,
            currency="UGX",
        )
        other_wallet = WalletFactory(
            user=UserFactory(),
            currency="UGX",
        )

        first = WithdrawalRequest.objects.create(
            wallet=own_wallet,
            amount=Decimal("10000.0000"),
            destination={"mobile_money_number": "0777000001"},
            status=(WithdrawalRequest.Status.PENDING_APPROVAL),
        )
        second = WithdrawalRequest.objects.create(
            wallet=own_wallet,
            amount=Decimal("20000.0000"),
            destination={"mobile_money_number": "0777000002"},
            status=WithdrawalRequest.Status.COMPLETED,
        )

        WithdrawalRequest.objects.create(
            wallet=other_wallet,
            amount=Decimal("30000.0000"),
            destination={"mobile_money_number": "0777000003"},
            status=WithdrawalRequest.Status.COMPLETED,
        )

        url = reverse("wallets:withdrawal-request-create")

        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 2

        returned_ids = {item["id"] for item in response.data["results"]}

        assert returned_ids == {
            str(first.id),
            str(second.id),
        }

    def test_list_withdrawals_filters_status_and_currency(
        self,
        auth_client,
    ):
        ugx_wallet = WalletFactory(
            user=auth_client.user,
            currency="UGX",
        )
        usd_wallet = WalletFactory(
            user=auth_client.user,
            currency="USD",
        )

        expected = WithdrawalRequest.objects.create(
            wallet=ugx_wallet,
            amount=Decimal("10000.0000"),
            destination={"mobile_money_number": "0777000010"},
            status=WithdrawalRequest.Status.COMPLETED,
        )

        WithdrawalRequest.objects.create(
            wallet=ugx_wallet,
            amount=Decimal("20000.0000"),
            destination={"mobile_money_number": "0777000011"},
            status=(WithdrawalRequest.Status.PENDING_APPROVAL),
        )

        WithdrawalRequest.objects.create(
            wallet=usd_wallet,
            amount=Decimal("30.0000"),
            destination={"bank_account": "TEST-USD"},
            status=WithdrawalRequest.Status.COMPLETED,
        )

        url = reverse("wallets:withdrawal-request-create")

        response = auth_client.get(
            url,
            {
                "status": "COMPLETED",
                "currency": "UGX",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["results"][0]["id"] == str(expected.id)
        assert response.data["results"][0]["currency"] == "UGX"

    def test_create_withdrawal_request(self, auth_client):
        WalletFactory(user=auth_client.user, currency="UGX", available_balance=100000)
        url = reverse("wallets:withdrawal-request-create")
        data = {
            "amount": "20000",
            "currency": "UGX",
            "destination": {"mobile_money_number": "0777123456"},
        }
        response = auth_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["status"] == "PENDING_APPROVAL"

    def test_create_withdrawal_insufficient_funds(self, auth_client):
        WalletFactory(user=auth_client.user, currency="UGX", available_balance=10000)
        url = reverse("wallets:withdrawal-request-create")
        data = {
            "amount": "20000",
            "currency": "UGX",
            "destination": {"mobile_money_number": "0777123456"},
        }
        response = auth_client.post(url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "insufficient" in str(response.data).lower()


class TestTransactionAPI:
    def test_list_transactions(self, auth_client):
        WalletFactory(user=auth_client.user)
        # You would use your services to create transactions here
        # e.g., deposit_service.complete_deposit(...)

        url = reverse("wallets:transaction-list")
        response = auth_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        # Further assertions on transaction data

    def test_get_transaction_detail(self, auth_client):
        # Create a transaction using a service
        # tx = ...
        # url = reverse("wallets:transaction-detail", kwargs={"tx_id": tx.id})
        # response = auth_client.get(url)
        # assert response.status_code == status.HTTP_200_OK
        pass  # Placeholder

    def test_download_receipt(self, auth_client):
        # Create a transaction and a receipt
        # tx = ...
        # receipt = ...
        # url = reverse("wallets:receipt-download", kwargs={"tx_id": tx.id})
        # response = auth_client.get(url)
        # assert response.status_code == status.HTTP_200_OK
        pass  # Placeholder

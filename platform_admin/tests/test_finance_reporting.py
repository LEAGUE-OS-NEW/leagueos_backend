from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from authentication.models import Role
from authentication.services.role_service import RoleService
from authentication.tests.factories import UserFactory
from wallets.models import PaymentProvider, WalletTransaction
from wallets.services.wallet_service import WalletService


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_finance_permissions_deny_fan_and_club_admin_allow_super_and_finance_role():
    call_command("seed_roles", verbosity=0)
    fan, club_admin, finance_admin, super_admin = (
        UserFactory(),
        UserFactory(),
        UserFactory(),
        UserFactory(is_superuser=True, is_staff=True),
    )
    RoleService.assign_role(club_admin, Role.objects.get(name="Club Admin"))
    RoleService.assign_role(finance_admin, Role.objects.get(name="Finance Admin"))
    url = "/api/v1/admin/finance/?resource=deposits"
    assert client_for(fan).get(url).status_code == 403
    assert client_for(club_admin).get(url).status_code == 403
    assert client_for(super_admin).get(url).status_code == 200
    assert client_for(finance_admin).get(url).status_code == 200


@pytest.mark.django_db
def test_finance_deposit_pagination_filters_search_and_exact_aggregates():
    administrator = UserFactory(is_superuser=True, is_staff=True)
    fan = UserFactory(email="finance-fan@example.com")
    WalletService.credit(
        user=fan, currency="UGX", amount=Decimal("1.00"), idempotency_reference=uuid4()
    )
    wallet = fan.wallets.get(currency="UGX")
    provider = PaymentProvider.objects.create(
        code="MOCK_FINANCE",
        name="Mock Finance",
        provider_type=PaymentProvider.ProviderType.GENERIC,
    )
    older = timezone.now() - timedelta(days=10)
    for index, amount in enumerate((Decimal("10.10"), Decimal("20.20"), Decimal("30.30"))):
        transaction = WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=WalletTransaction.TransactionType.DEPOSIT,
            amount=amount,
            currency="UGX",
            status=(
                WalletTransaction.Status.COMPLETED if index else WalletTransaction.Status.FAILED
            ),
            provider=provider,
            provider_reference=f"PROVIDER-{index}",
            reference=f"DEPOSIT-EXACT-{index}",
        )
        if index == 0:
            WalletTransaction.objects.filter(id=transaction.id).update(created_at=older)
    api = client_for(administrator)
    first = api.get("/api/v1/admin/finance/", {"resource": "deposits", "page_size": 2, "page": 1})
    assert first.status_code == 200
    assert (
        first.data["count"] == 3
        and len(first.data["results"]) == 2
        and first.data["total_pages"] == 2
    )
    assert first.data["overview"]["deposit_total"] == "60.6000"
    filtered = api.get(
        "/api/v1/admin/finance/",
        {
            "resource": "deposits",
            "status": "COMPLETED",
            "search": "PROVIDER-2",
            "provider": "Mock Finance",
            "date_from": timezone.localdate().isoformat(),
        },
    )
    assert filtered.data["count"] == 1
    assert filtered.data["results"][0]["fan"] == "finance-fan@example.com"
    assert filtered.data["results"][0]["internal_reference"] == "DEPOSIT-EXACT-2"

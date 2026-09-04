from decimal import Decimal

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from platform_admin.models import PlatformMembershipSubscription
from wallets.tests.factories import WalletFactory

from .factories import UserFactory

pytestmark = pytest.mark.django_db


def test_super_admin_membership_plans_feed_fan_subscriptions():
    super_admin = UserFactory(is_superuser=True)
    fan = UserFactory(email="fan@example.com", username="fan")
    wallet = WalletFactory(user=fan, currency="UGX", available_balance="20000.0000")
    client = APIClient()

    client.force_authenticate(user=super_admin)
    create_response = client.post(
        "/api/v1/admin/membership/plans/",
        {
            "name": "LeagueOS Plus",
            "description": "Platform-wide fan benefits.",
            "price": "15000.00",
            "currency": "UGX",
            "billing_period": "MONTHLY",
            "benefits": ["Follow unlimited clubs", "Create fantasy leagues"],
        },
        format="json",
    )

    assert create_response.status_code == status.HTTP_201_CREATED
    plan_id = create_response.data["id"]

    activate_response = client.patch(
        f"/api/v1/admin/membership/plans/{plan_id}/status/",
        {"status": "ACTIVE"},
        format="json",
    )
    assert activate_response.status_code == status.HTTP_200_OK

    client.force_authenticate(user=fan)
    plans_response = client.get("/api/v1/membership/plans/")
    assert plans_response.status_code == status.HTTP_200_OK
    assert [plan["id"] for plan in plans_response.data] == [plan_id]

    subscribe_response = client.post(
        "/api/v1/membership/subscribe/",
        {"plan_id": plan_id},
        format="json",
    )
    assert subscribe_response.status_code == status.HTTP_201_CREATED
    assert str(subscribe_response.data["plan"]) == plan_id
    assert subscribe_response.data["fan_email"] == fan.email

    client.force_authenticate(user=super_admin)
    subscribers_response = client.get("/api/v1/admin/membership/subscribers/")
    assert subscribers_response.status_code == status.HTTP_200_OK
    assert [subscriber["id"] for subscriber in subscribers_response.data] == [
        subscribe_response.data["id"]
    ]
    assert subscribers_response.data[0]["plan_name"] == "LeagueOS Plus"

    subscription = PlatformMembershipSubscription.objects.get(id=subscribe_response.data["id"])
    wallet.refresh_from_db()
    assert wallet.available_balance == Decimal("5000.0000")

    cancel_response = client.post(f"/api/v1/admin/membership/subscribers/{subscription.id}/cancel/")
    assert cancel_response.status_code == status.HTTP_200_OK
    subscription.refresh_from_db()
    assert subscription.status == PlatformMembershipSubscription.Status.CANCELLED

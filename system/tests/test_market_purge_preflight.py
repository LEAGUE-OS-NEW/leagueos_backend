from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

User = get_user_model()

URL = "/api/v1/system/review/markets/" "purge-preflight/"


def make_user(email):
    return User.objects.create_user(
        username=email.split("@")[0],
        email=email,
        password="Purge-Preflight-Test-Only-123!",
        is_active=True,
        is_verified=True,
    )


def authenticate(user):
    client = APIClient()
    client.force_authenticate(
        user=user,
    )
    return client


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=False)
def test_preflight_hidden_when_review_tools_disabled():
    user = make_user(
        "superadmin.local@leagueos.test",
    )

    response = authenticate(user).get(URL)

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
def test_preflight_hidden_from_other_synthetic_accounts():
    user = make_user(
        "market.ops.local@leagueos.test",
    )

    response = authenticate(user).get(URL)

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
@pytest.mark.parametrize(
    "email",
    (
        "superadmin.local@leagueos.test",
        "results.local@leagueos.test",
    ),
)
@patch("system.views.build_purge_preflight")
def test_preflight_uses_exact_approved_actor(
    build_preflight,
    email,
):
    user = make_user(email)

    build_preflight.return_value = {
        "snapshot_version": "test-v1",
        "snapshot_digest": "abc",
        "database_market_count": 40,
        "snapshot_matches_database": True,
        "keeper_count": 4,
        "purge_target_count": 36,
        "unexpected_market_ids": [],
        "missing_snapshot_ids": [],
        "unsettled_financial_market_ids": [],
        "settled_market_ids": [],
        "void_required_market_ids": [],
        "actor_email": user.email,
        "actor_creator_conflict_ids": [],
        "actor_has_resolution_permission": True,
        "actor_has_refund_permission": True,
        "can_execute": True,
        "affected_ledger_entry_count": 0,
        "payment_counts": {
            "wallet_transactions": 0,
            "deposit_intents": 0,
            "pesapal_deposits": 0,
            "withdrawal_requests": 0,
        },
        "ledger_entry_count": 0,
    }

    response = authenticate(user).get(URL)

    assert response.status_code == 200
    assert response.json()["can_execute"] is True

    build_preflight.assert_called_once_with(
        actor=user,
    )

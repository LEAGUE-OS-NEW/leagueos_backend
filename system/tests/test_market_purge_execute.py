from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from markets.services.staging_market_purge_service import (
    CONFIRMATION_PHRASE,
)
from markets.services.staging_market_purge_snapshot import (
    SNAPSHOT_DIGEST,
)

User = get_user_model()

URL = "/api/v1/system/review/markets/" "purge-execute/"


def make_user(email):
    return User.objects.create_user(
        username=email.split("@")[0],
        email=email,
        password="Temporary-Purge-Test-Only-123!",
        is_active=True,
        is_verified=True,
    )


def authenticate(user):
    client = APIClient()
    client.force_authenticate(
        user=user,
    )
    return client


def payload():
    return {
        "confirmation": CONFIRMATION_PHRASE,
        "snapshot_digest": SNAPSHOT_DIGEST,
    }


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=False)
def test_execute_hidden_when_review_tools_disabled():
    user = make_user(
        "superadmin.local@leagueos.test",
    )

    response = authenticate(user).post(
        URL,
        payload(),
        format="json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
def test_execute_hidden_from_result_verifier():
    user = make_user(
        "results.local@leagueos.test",
    )

    response = authenticate(user).post(
        URL,
        payload(),
        format="json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
@patch("system.views.apply_staging_market_purge")
def test_execute_rejects_wrong_confirmation(
    apply_purge,
):
    user = make_user(
        "superadmin.local@leagueos.test",
    )

    request_payload = payload()
    request_payload["confirmation"] = "WRONG"

    response = authenticate(user).post(
        URL,
        request_payload,
        format="json",
    )

    assert response.status_code == 400
    apply_purge.assert_not_called()


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
@patch("system.views.apply_staging_market_purge")
def test_execute_rejects_wrong_digest(
    apply_purge,
):
    user = make_user(
        "superadmin.local@leagueos.test",
    )

    request_payload = payload()
    request_payload["snapshot_digest"] = "WRONG"

    response = authenticate(user).post(
        URL,
        request_payload,
        format="json",
    )

    assert response.status_code == 400
    apply_purge.assert_not_called()


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
@patch("system.views.apply_staging_market_purge")
@patch("system.views.build_purge_preflight")
def test_execute_aborts_when_preflight_not_green(
    build_preflight,
    apply_purge,
):
    resolution_actor = make_user(
        "results.local@leagueos.test",
    )
    refund_actor = make_user(
        "superadmin.local@leagueos.test",
    )

    build_preflight.return_value = {
        "can_execute": False,
    }

    response = authenticate(
        refund_actor,
    ).post(
        URL,
        payload(),
        format="json",
    )

    assert response.status_code == 409

    build_preflight.assert_called_once_with(
        resolution_actor=resolution_actor,
        refund_actor=refund_actor,
    )

    apply_purge.assert_not_called()


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
@patch("system.views.apply_staging_market_purge")
@patch("system.views.build_purge_preflight")
def test_execute_uses_exact_actor_pair(
    build_preflight,
    apply_purge,
):
    resolution_actor = make_user(
        "results.local@leagueos.test",
    )
    refund_actor = make_user(
        "superadmin.local@leagueos.test",
    )

    build_preflight.return_value = {
        "can_execute": True,
    }

    apply_purge.return_value = {
        "snapshot_version": "test-v2",
        "snapshot_digest": SNAPSHOT_DIGEST,
        "deleted_market_count": 42,
        "remaining_market_count": 4,
        "voided_market_count": 1,
        "refunded_market_count": 1,
        "preserved_existing_ledger_count": 132,
        "new_ledger_entry_count": 2,
        "wallets_never_lost_value": True,
        "payment_rows_unchanged": True,
        "deleted_by_model": {
            "markets.Market": 42,
        },
    }

    response = authenticate(
        refund_actor,
    ).post(
        URL,
        payload(),
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["deleted_market_count"] == 42
    assert response.json()["remaining_market_count"] == 4

    build_preflight.assert_called_once_with(
        resolution_actor=resolution_actor,
        refund_actor=refund_actor,
    )

    apply_purge.assert_called_once_with(
        resolution_actor=resolution_actor,
        refund_actor=refund_actor,
        confirmation=CONFIRMATION_PHRASE,
        snapshot_digest=SNAPSHOT_DIGEST,
    )

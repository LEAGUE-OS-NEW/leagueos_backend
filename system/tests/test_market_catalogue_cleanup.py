import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from markets.models import (
    Market,
    MarketCategory,
    MarketLiquidityConfiguration,
    MarketScope,
    MarketStatusTransition,
)
from markets.services.staging_catalogue_audit_service import (
    CANONICAL_QUESTIONS,
)
from markets.services.staging_catalogue_cleanup_service import (
    CONFIRMATION_PHRASE,
)
from markets.services.staging_catalogue_cleanup_snapshot import (
    CONFIG_ONLY_DELETE_IDS,
    DIRECT_DELETE_IDS,
    HIDE_IDS,
    KEEPER_IDS,
)
from sports.models import Sport

User = get_user_model()

URL = "/api/v1/system/review/markets/catalogue-cleanup/"


def make_user(email):
    return User.objects.create_user(
        username=email.split("@")[0],
        email=email,
        password="Cleanup-Test-Only-123!",
        is_active=True,
        is_verified=True,
    )


def authenticate(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_market(
    *,
    question,
    market_id=None,
    status=Market.Status.DRAFT,
    is_catalog_visible=True,
):
    sport, _ = Sport.objects.get_or_create(
        code="FOOTBALL",
        defaults={
            "name": "Football",
        },
    )

    category, _ = MarketCategory.objects.get_or_create(
        name="Match Result",
    )

    values = {
        "sport": sport,
        "category": category,
        "scope_type": MarketScope.CUSTOM,
        "custom_subject": "Staging cleanup test",
        "question": question,
        "status": status,
        "is_catalog_visible": is_catalog_visible,
    }

    if market_id is not None:
        values["id"] = market_id

    return Market.objects.create(
        **values,
    )


def seed_cleanup_snapshot():
    for market_id, question in zip(
        KEEPER_IDS,
        CANONICAL_QUESTIONS,
        strict=True,
    ):
        create_market(
            market_id=market_id,
            question=question,
        )

    for index, market_id in enumerate(
        DIRECT_DELETE_IDS,
        start=1,
    ):
        create_market(
            market_id=market_id,
            question=(f"Disposable direct-delete market {index}?"),
        )

    for index, market_id in enumerate(
        CONFIG_ONLY_DELETE_IDS,
        start=1,
    ):
        market = create_market(
            market_id=market_id,
            question=(f"Disposable config-only market {index}?"),
        )

        MarketLiquidityConfiguration.objects.create(
            market=market,
        )

    for index, market_id in enumerate(
        HIDE_IDS,
        start=1,
    ):
        create_market(
            market_id=market_id,
            question=(f"Preserved historical market {index}?"),
        )


@pytest.mark.django_db
@override_settings(
    REVIEW_WORKFLOW_TOOLS_ENABLED=False,
)
def test_cleanup_hidden_when_review_tools_disabled():
    user = make_user(
        "market.ops.local@leagueos.test",
    )

    response = authenticate(user).post(
        URL,
        {
            "confirmation": CONFIRMATION_PHRASE,
        },
        format="json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(
    REVIEW_WORKFLOW_TOOLS_ENABLED=True,
)
def test_cleanup_hidden_from_other_synthetic_accounts():
    user = make_user(
        "results.local@leagueos.test",
    )

    response = authenticate(user).post(
        URL,
        {
            "confirmation": CONFIRMATION_PHRASE,
        },
        format="json",
    )

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(
    REVIEW_WORKFLOW_TOOLS_ENABLED=True,
)
def test_cleanup_rejects_wrong_confirmation_without_changes():
    user = make_user(
        "market.ops.local@leagueos.test",
    )

    response = authenticate(user).post(
        URL,
        {
            "confirmation": "WRONG",
        },
        format="json",
    )

    assert response.status_code == 400
    assert Market.objects.count() == 0


@pytest.mark.django_db
@override_settings(
    REVIEW_WORKFLOW_TOOLS_ENABLED=True,
)
def test_cleanup_applies_snapshot_without_touching_new_market():
    seed_cleanup_snapshot()

    future_market = create_market(
        question=("Will a newly created market remain untouched?"),
    )

    user = make_user(
        "market.ops.local@leagueos.test",
    )
    client = authenticate(user)

    assert Market.objects.count() == 60

    response = client.post(
        URL,
        {
            "confirmation": CONFIRMATION_PHRASE,
        },
        format="json",
    )

    assert response.status_code == 200

    body = response.json()

    assert body["already_applied"] is False
    assert body["global_total_before"] == 60
    assert body["global_total_after"] == 41
    assert body["deleted_market_count"] == 19
    assert body["deleted_liquidity_configuration_count"] == 5
    assert body["newly_hidden_count"] == 36
    assert body["newly_visible_keeper_count"] == 0
    assert body["snapshot_remaining_count"] == 40
    assert body["snapshot_visible_count"] == 4

    assert (
        Market.objects.filter(
            id__in=DIRECT_DELETE_IDS,
        ).exists()
        is False
    )

    assert (
        Market.objects.filter(
            id__in=CONFIG_ONLY_DELETE_IDS,
        ).exists()
        is False
    )

    assert (
        MarketLiquidityConfiguration.objects.filter(
            market_id__in=CONFIG_ONLY_DELETE_IDS,
        ).exists()
        is False
    )

    assert (
        Market.objects.filter(
            id__in=HIDE_IDS,
            is_catalog_visible=False,
        ).count()
        == 36
    )

    assert (
        Market.objects.filter(
            id__in=KEEPER_IDS,
            is_catalog_visible=True,
        ).count()
        == 4
    )

    future_market.refresh_from_db()

    assert future_market.is_catalog_visible is True
    assert Market.objects.count() == 41

    second_response = client.post(
        URL,
        {
            "confirmation": CONFIRMATION_PHRASE,
        },
        format="json",
    )

    assert second_response.status_code == 200

    second_body = second_response.json()

    assert second_body["already_applied"] is True
    assert second_body["global_total_before"] == 41
    assert second_body["global_total_after"] == 41
    assert second_body["deleted_market_count"] == 0
    assert second_body["newly_hidden_count"] == 0

    future_market.refresh_from_db()

    assert future_market.is_catalog_visible is True
    assert Market.objects.count() == 41


@pytest.mark.django_db
@override_settings(
    REVIEW_WORKFLOW_TOOLS_ENABLED=True,
)
def test_cleanup_aborts_when_delete_target_gains_history():
    seed_cleanup_snapshot()

    user = make_user(
        "market.ops.local@leagueos.test",
    )

    target = Market.objects.get(
        id=DIRECT_DELETE_IDS[0],
    )

    MarketStatusTransition.objects.create(
        market=target,
        action=MarketStatusTransition.Action.SUBMIT,
        from_status=Market.Status.DRAFT,
        to_status=Market.Status.PENDING_APPROVAL,
        actor=user,
        actor_email=user.email,
        notes=("Synthetic history added after the " "cleanup snapshot."),
    )

    response = authenticate(user).post(
        URL,
        {
            "confirmation": CONFIRMATION_PHRASE,
        },
        format="json",
    )

    assert response.status_code == 400

    assert "changed after audit" in response.json()["detail"]

    assert Market.objects.count() == 59

    assert (
        Market.objects.filter(
            id__in=DIRECT_DELETE_IDS,
        ).count()
        == 14
    )

    assert (
        Market.objects.filter(
            id__in=CONFIG_ONLY_DELETE_IDS,
        ).count()
        == 5
    )

    assert (
        MarketLiquidityConfiguration.objects.filter(
            market_id__in=CONFIG_ONLY_DELETE_IDS,
        ).count()
        == 5
    )

    assert (
        Market.objects.filter(
            id__in=HIDE_IDS,
            is_catalog_visible=True,
        ).count()
        == 36
    )

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from markets.models import (
    Market,
    MarketCategory,
    MarketScope,
)
from markets.services.staging_catalogue_audit_service import (
    CANONICAL_QUESTIONS,
)
from sports.models import Sport

User = get_user_model()

URL = "/api/v1/system/review/markets/catalogue-audit/"


def make_user(email):
    return User.objects.create_user(
        username=email.split("@")[0],
        email=email,
        password="Catalogue-Test-Only-123!",
        is_active=True,
        is_verified=True,
    )


def authenticate(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_market(*, question):
    sport, _ = Sport.objects.get_or_create(
        code="FOOTBALL",
        defaults={
            "name": "Football",
        },
    )
    category, _ = MarketCategory.objects.get_or_create(
        name="Match Result",
    )

    return Market.objects.create(
        sport=sport,
        category=category,
        scope_type=MarketScope.CUSTOM,
        custom_subject="Staging catalogue audit",
        question=question,
        status=Market.Status.DRAFT,
    )


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=False)
def test_catalogue_audit_is_hidden_when_review_tools_disabled():
    user = make_user(
        "market.ops.local@leagueos.test",
    )

    response = authenticate(user).get(URL)

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
def test_catalogue_audit_is_hidden_from_ordinary_accounts():
    user = make_user(
        "market.ops@example.com",
    )

    response = authenticate(user).get(URL)

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
def test_catalogue_audit_classifies_without_mutating_markets():
    canonical = create_market(
        question=CANONICAL_QUESTIONS[0],
    )
    extra = create_market(
        question="Will an old staging market remain visible?",
    )

    user = make_user(
        "market.ops.local@leagueos.test",
    )

    response = authenticate(user).get(URL)

    assert response.status_code == 200

    body = response.json()

    assert body["total_markets"] == 2

    rows = {row["id"]: row for row in body["rows"]}

    assert rows[str(canonical.id)]["classification"] == "KEEP_CANONICAL"
    assert rows[str(extra.id)]["classification"] == "HIDE_NONCANONICAL"

    canonical.refresh_from_db()
    extra.refresh_from_db()

    assert canonical.is_catalog_visible is True
    assert extra.is_catalog_visible is True

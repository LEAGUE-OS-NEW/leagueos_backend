"""Tests for discovery fixture, result, and news endpoints."""

import uuid

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from discovery.models import AuditLog, News
from discovery.tests.factories import (
    NewsCategoryFactory,
    NewsFactory,
    SportingEventFactory,
)
from sports.models import SportingEvent

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client():
    return APIClient()


class TestFixtureEndpoints:
    def test_fixture_list_returns_verified(self, client):
        SportingEventFactory(name="Match One", is_verified=True)
        resp = client.get("/api/v1/fixtures/")
        assert resp.status_code == 200
        names = {item["name"] for item in resp.data["results"]}
        assert "Match One" in names

    def test_fixture_list_excludes_unverified(self, client):
        SportingEventFactory(name="Verified Match", is_verified=True)
        SportingEventFactory(name="Hidden Match", is_verified=False)
        resp = client.get("/api/v1/fixtures/")
        assert resp.status_code == 200
        names = {item["name"] for item in resp.data["results"]}
        assert "Verified Match" in names
        assert "Hidden Match" not in names

    def test_fixture_detail(self, client):
        fixture = SportingEventFactory(name="Match One", is_verified=True)
        resp = client.get(f"/api/v1/fixtures/{fixture.id}/")
        assert resp.status_code == 200
        assert resp.data["id"] == str(fixture.id)

    def test_fixture_detail_404(self, client):
        resp = client.get(f"/api/v1/fixtures/{uuid.uuid4()}/")
        assert resp.status_code == 404

    def test_fixture_detail_records_audit(self, client):
        fixture = SportingEventFactory(name="Audited Match", is_verified=True)
        client.get(f"/api/v1/fixtures/{fixture.id}/")
        assert AuditLog.objects.filter(action="FIXTURE_VIEWED", entity_id=fixture.id).exists()


class TestResultEndpoints:
    def test_results_only_completed(self, client):
        SportingEventFactory(
            name="Finished Match",
            status=SportingEvent.Status.COMPLETED,
            is_verified=True,
        )
        SportingEventFactory(
            name="Scheduled Match",
            status=SportingEvent.Status.SCHEDULED,
            is_verified=True,
        )
        resp = client.get("/api/v1/results/")
        assert resp.status_code == 200
        names = {item["name"] for item in resp.data["results"]}
        assert "Finished Match" in names
        assert "Scheduled Match" not in names


class TestNewsEndpoints:
    def test_news_list_only_published(self, client):
        NewsFactory(
            title="Published Story",
            status=News.Status.PUBLISHED,
            is_verified=True,
        )
        NewsFactory(title="Draft Story", status=News.Status.DRAFT, is_verified=True)
        resp = client.get("/api/v1/news/")
        assert resp.status_code == 200
        names = {item["title"] for item in resp.data["results"]}
        assert "Published Story" in names
        assert "Draft Story" not in names

    def test_news_list_only_verified(self, client):
        NewsFactory(title="Verified Story", is_verified=True)
        NewsFactory(title="Unverified Story", is_verified=False)
        resp = client.get("/api/v1/news/")
        assert resp.status_code == 200
        names = {item["title"] for item in resp.data["results"]}
        assert "Verified Story" in names
        assert "Unverified Story" not in names

    def test_news_filters_by_category(self, client):
        category_a = NewsCategoryFactory(name="Transfers")
        category_b = NewsCategoryFactory(name="Injuries")
        NewsFactory(
            title="Transfer Story",
            category=category_a,
            status=News.Status.PUBLISHED,
            is_verified=True,
        )
        NewsFactory(
            title="Injury Story",
            category=category_b,
            status=News.Status.PUBLISHED,
            is_verified=True,
        )
        resp = client.get("/api/v1/news/", {"category": str(category_a.id)})
        assert resp.status_code == 200
        names = {item["title"] for item in resp.data["results"]}
        assert "Transfer Story" in names
        assert "Injury Story" not in names

    def test_news_featured_filter(self, client):
        NewsFactory(
            title="Featured Story",
            is_featured=True,
            status=News.Status.PUBLISHED,
            is_verified=True,
        )
        NewsFactory(
            title="Regular Story",
            is_featured=False,
            status=News.Status.PUBLISHED,
            is_verified=True,
        )
        resp = client.get("/api/v1/news/", {"featured": "true"})
        assert resp.status_code == 200
        names = {item["title"] for item in resp.data["results"]}
        assert "Featured Story" in names
        assert "Regular Story" not in names

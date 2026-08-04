"""Tests for discovery search endpoints."""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from discovery.models import SearchAnalytics
from discovery.tests.factories import (
    ClubFactory,
    SearchSuggestionFactory,
    SportFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client():
    return APIClient()


class TestSearchEndpoint:
    def test_returns_club_results(self, client):
        ClubFactory(name="Arsenal FC", slug="arsenal-fc")
        resp = client.get("/api/v1/search/", {"q": "Arsenal"})
        assert resp.status_code == 200
        assert resp.data["count"] >= 1
        assert resp.data["results"][0]["entity_type"] == "club"

    def test_empty_query(self, client):
        ClubFactory(name="Arsenal FC", slug="arsenal-fc")
        resp = client.get("/api/v1/search/", {"q": ""})
        assert resp.status_code == 200
        assert resp.data["count"] == 0

    def test_pagination(self, client):
        for i in range(5):
            ClubFactory(name=f"Query Club {i}", slug=f"query-club-{i}")
        resp = client.get("/api/v1/search/", {"q": "Query", "page": 1, "page_size": 2})
        assert resp.status_code == 200
        assert resp.data["count"] == 5
        assert len(resp.data["results"]) == 2

    def test_sort_by_name(self, client):
        ClubFactory(name="Zulu FC", slug="zulu-fc")
        ClubFactory(name="Alpha FC", slug="alpha-fc")
        resp = client.get("/api/v1/search/", {"q": "FC", "ordering": "name"})
        assert resp.status_code == 200
        names = [r["display_name"] for r in resp.data["results"]]
        assert names == sorted(names)

    def test_filter_by_sport(self, client):
        football = SportFactory(name="Football", code="FOOTBALL")
        rugby = SportFactory(name="Rugby", code="RUGBY")
        ClubFactory(name="Football Club", slug="football-club", sport=football)
        ClubFactory(name="Rugby Club", slug="rugby-club", sport=rugby)
        resp = client.get("/api/v1/search/", {"q": "Club", "sport": str(football.id)})
        assert resp.status_code == 200
        assert all(r["sport"] == str(football.id) for r in resp.data["results"])

    def test_long_query_rejected(self, client):
        resp = client.get("/api/v1/search/", {"q": "T" * 250})
        assert resp.status_code == 400

    def test_records_analytics(self, client):
        ClubFactory(name="Analytics Club", slug="analytics-club")
        client.get("/api/v1/search/", {"q": "Analytics"})
        assert SearchAnalytics.objects.filter(query="Analytics").exists()


class TestSearchAutocomplete:
    def test_returns_results(self, client):
        ClubFactory(name="Autocomplete Club", slug="autocomplete-club")
        resp = client.get("/api/v1/search/autocomplete/", {"q": "Auto"})
        assert resp.status_code == 200
        assert len(resp.data) >= 1
        assert resp.data[0]["entity_type"] == "club"

    def test_empty_query(self, client):
        resp = client.get("/api/v1/search/autocomplete/", {"q": ""})
        assert resp.status_code == 200
        assert resp.data == []


class TestSearchSuggestions:
    def test_database_driven(self, client):
        SearchSuggestionFactory(suggestion_type="POPULAR", display_name="Top Club", score=100)
        resp = client.get("/api/v1/search/suggestions/")
        assert resp.status_code == 200
        assert resp.data[0]["display_name"] == "Top Club"

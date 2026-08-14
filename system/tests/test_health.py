from unittest.mock import patch

import pytest


@pytest.mark.django_db
def test_health_check(client):
    response = client.get("/api/v1/system/health/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "leagueos-backend",
        "dependencies": {
            "database": True,
            "cache": True,
        },
    }


def test_health_check_reports_degraded_when_database_is_down(client):
    with patch("system.views._check_database", return_value=False):
        response = client.get("/api/v1/system/health/")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["database"] is False


@pytest.mark.django_db
def test_health_check_reports_degraded_when_cache_is_down(client):
    with patch("system.views._check_cache", return_value=False):
        response = client.get("/api/v1/system/health/")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["cache"] is False

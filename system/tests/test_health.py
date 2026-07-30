def test_health_check(client):
    response = client.get("/api/v1/system/health/")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "leagueos-backend",
    }

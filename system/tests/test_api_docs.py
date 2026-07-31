from django.urls import reverse


def test_openapi_schema_is_publicly_available(client):
    response = client.get(
        reverse("api-schema"),
        {"format": "json"},
    )

    assert response.status_code == 200

    schema = response.json()

    assert schema["openapi"].startswith("3.")
    assert schema["info"]["title"] == "League OS API"
    assert schema["info"]["version"] == "1.0.0"


def test_swagger_documentation_is_publicly_available(client):
    response = client.get(
        reverse("api-docs"),
    )

    assert response.status_code == 200
    assert b"swagger" in response.content.lower()


def test_redoc_documentation_is_publicly_available(client):
    response = client.get(
        reverse("api-redoc"),
    )

    assert response.status_code == 200
    assert b"redoc" in response.content.lower()

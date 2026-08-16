from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

User = get_user_model()

URL = "/api/v1/system/integrations/pesapal/diagnostic/"


def make_user(email):
    return User.objects.create_user(
        username=email.split("@")[0],
        email=email,
        password="Diagnostic-Test-Only-123!",
        is_active=True,
        is_verified=True,
    )


def authenticate(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def sandbox_config():
    return SimpleNamespace(
        environment="SANDBOX",
        base_url="https://cybqa.pesapal.com/pesapalv3",
        consumer_key="configured-key",
        consumer_secret="configured-secret",
        ipn_id="configured-ipn",
        callback_url="https://example.test/callback/",
        ipn_url="https://example.test/ipn/",
        frontend_return_url="https://example.test/wallet",
        is_sandbox=True,
    )


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
def test_diagnostic_requires_authentication():
    response = APIClient().get(URL)

    assert response.status_code in (401, 403)


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=False)
def test_diagnostic_is_hidden_when_review_tools_are_disabled():
    user = make_user("fan.local@leagueos.test")

    response = authenticate(user).get(URL)

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
def test_diagnostic_is_hidden_from_ordinary_accounts():
    user = make_user("fan@example.com")

    response = authenticate(user).get(URL)

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
@patch(
    "system.views.PesapalClient.authenticate",
    return_value="secret-token-that-must-not-be-returned",
)
@patch("system.views.get_pesapal_config")
def test_synthetic_review_user_can_probe_pesapal_authentication(
    config_mock,
    authenticate_mock,
):
    config_mock.return_value = sandbox_config()

    user = make_user("fan.local@leagueos.test")

    response = authenticate(user).get(URL)

    assert response.status_code == 200

    body = response.json()

    assert body == {
        "environment": "SANDBOX",
        "sandbox": True,
        "base_url": "https://cybqa.pesapal.com/pesapalv3",
        "credentials_present": True,
        "ipn_configured": True,
        "callback_configured": True,
        "authentication": {
            "ok": True,
            "error_type": "",
        },
    }

    assert "secret-token-that-must-not-be-returned" not in response.content.decode()

    authenticate_mock.assert_called_once()


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
@patch(
    "system.views.PesapalClient.authenticate",
    side_effect=TimeoutError("simulated transport timeout"),
)
@patch("system.views.get_pesapal_config")
def test_transport_exception_is_reported_safely(
    config_mock,
    _authenticate_mock,
):
    config_mock.return_value = sandbox_config()

    user = make_user("fan.local@leagueos.test")

    response = authenticate(user).get(URL)

    assert response.status_code == 503

    body = response.json()

    assert body["authentication"] == {
        "ok": False,
        "error_type": "TimeoutError",
    }

    assert "simulated transport timeout" not in response.content.decode()

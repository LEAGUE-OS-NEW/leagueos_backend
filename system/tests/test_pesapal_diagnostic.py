import socket
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

from system.views import _pesapal_transport_diagnostic

User = get_user_model()

URL = "/api/v1/system/integrations/pesapal/diagnostic/"
SANDBOX_URL = "https://cybqa.pesapal.com/pesapalv3"


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
        base_url=SANDBOX_URL,
        consumer_key="configured-key",
        consumer_secret="configured-secret",
        ipn_id="configured-ipn",
        callback_url="https://example.test/callback/",
        ipn_url="https://example.test/ipn/",
        frontend_return_url="https://example.test/wallet",
        is_sandbox=True,
    )


def successful_transport():
    return {
        "host": "cybqa.pesapal.com",
        "port": 443,
        "dns": {
            "ok": True,
            "elapsed_ms": 1.5,
            "addresses": [
                {
                    "family": "IPv4",
                    "address": "203.0.113.10",
                }
            ],
            "error_type": "",
        },
        "probes": [
            {
                "family": "IPv4",
                "address": "203.0.113.10",
                "tcp": {
                    "ok": True,
                    "elapsed_ms": 3.0,
                    "error_type": "",
                },
                "tls": {
                    "ok": True,
                    "elapsed_ms": 5.0,
                    "protocol": "TLSv1.3",
                    "error_type": "",
                },
            }
        ],
    }


def unavailable_transport():
    return {
        "host": "cybqa.pesapal.com",
        "port": 443,
        "dns": {
            "ok": True,
            "elapsed_ms": 1.5,
            "addresses": [
                {
                    "family": "IPv4",
                    "address": "203.0.113.10",
                }
            ],
            "error_type": "",
        },
        "probes": [
            {
                "family": "IPv4",
                "address": "203.0.113.10",
                "tcp": {
                    "ok": False,
                    "elapsed_ms": 3000.0,
                    "error_type": "TimeoutError",
                },
                "tls": {
                    "ok": False,
                    "elapsed_ms": None,
                    "protocol": "",
                    "error_type": "",
                },
            }
        ],
    }


def test_transport_diagnostic_reports_dns_failure_without_exception_details():
    with patch(
        "system.views.socket.getaddrinfo",
        side_effect=socket.gaierror("simulated private resolver details"),
    ):
        result = _pesapal_transport_diagnostic(
            SANDBOX_URL,
        )

    assert result["host"] == "cybqa.pesapal.com"
    assert result["port"] == 443

    assert result["dns"]["ok"] is False
    assert result["dns"]["addresses"] == []
    assert result["dns"]["error_type"] == "gaierror"
    assert result["probes"] == []

    assert "simulated private resolver details" not in str(
        result,
    )


def test_transport_diagnostic_reports_tcp_timeout():
    raw_socket = MagicMock()
    raw_socket.connect.side_effect = TimeoutError(
        "simulated TCP timeout details",
    )

    dns_records = [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("203.0.113.10", 443),
        )
    ]

    with (
        patch(
            "system.views.socket.getaddrinfo",
            return_value=dns_records,
        ),
        patch(
            "system.views.socket.socket",
            return_value=raw_socket,
        ),
        patch(
            "system.views.ssl.create_default_context",
            return_value=MagicMock(),
        ),
    ):
        result = _pesapal_transport_diagnostic(
            SANDBOX_URL,
        )

    assert result["dns"]["ok"] is True
    assert result["dns"]["addresses"] == [
        {
            "family": "IPv4",
            "address": "203.0.113.10",
        }
    ]

    assert len(result["probes"]) == 1

    probe = result["probes"][0]

    assert probe["family"] == "IPv4"
    assert probe["tcp"]["ok"] is False
    assert probe["tcp"]["error_type"] == "TimeoutError"
    assert probe["tls"]["ok"] is False

    raw_socket.settimeout.assert_called_once_with(3)
    raw_socket.close.assert_called_once()

    assert "simulated TCP timeout details" not in str(
        result,
    )


def test_transport_diagnostic_reports_successful_tls_handshake():
    raw_socket = MagicMock()

    tls_socket = MagicMock()
    tls_socket.version.return_value = "TLSv1.3"

    ssl_context = MagicMock()
    ssl_context.wrap_socket.return_value.__enter__.return_value = tls_socket

    dns_records = [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("203.0.113.10", 443),
        )
    ]

    with (
        patch(
            "system.views.socket.getaddrinfo",
            return_value=dns_records,
        ),
        patch(
            "system.views.socket.socket",
            return_value=raw_socket,
        ),
        patch(
            "system.views.ssl.create_default_context",
            return_value=ssl_context,
        ),
    ):
        result = _pesapal_transport_diagnostic(
            SANDBOX_URL,
        )

    assert result["dns"]["ok"] is True
    assert len(result["probes"]) == 1

    probe = result["probes"][0]

    assert probe["family"] == "IPv4"

    assert probe["tcp"]["ok"] is True
    assert probe["tcp"]["error_type"] == ""

    assert probe["tls"] == {
        "ok": True,
        "elapsed_ms": probe["tls"]["elapsed_ms"],
        "protocol": "TLSv1.3",
        "error_type": "",
    }

    raw_socket.settimeout.assert_called_once_with(3)
    raw_socket.connect.assert_called_once_with(
        ("203.0.113.10", 443),
    )
    ssl_context.wrap_socket.assert_called_once_with(
        raw_socket,
        server_hostname="cybqa.pesapal.com",
    )


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
def test_diagnostic_requires_authentication():
    response = APIClient().get(URL)

    assert response.status_code in (401, 403)


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=False)
def test_diagnostic_is_hidden_when_review_tools_are_disabled():
    user = make_user(
        "fan.local@leagueos.test",
    )

    response = authenticate(user).get(URL)

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
def test_diagnostic_is_hidden_from_ordinary_accounts():
    user = make_user(
        "fan@example.com",
    )

    response = authenticate(user).get(URL)

    assert response.status_code == 404


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
@patch(
    "system.views._pesapal_transport_diagnostic",
    return_value=successful_transport(),
)
@patch(
    "system.views.PesapalClient.authenticate",
    return_value="secret-token-that-must-not-be-returned",
)
@patch(
    "system.views.get_pesapal_config",
)
def test_synthetic_review_user_can_probe_pesapal_authentication(
    config_mock,
    authenticate_mock,
    transport_mock,
):
    config_mock.return_value = sandbox_config()

    user = make_user(
        "fan.local@leagueos.test",
    )

    response = authenticate(user).get(URL)

    assert response.status_code == 200

    body = response.json()

    assert body == {
        "environment": "SANDBOX",
        "sandbox": True,
        "base_url": SANDBOX_URL,
        "credentials_present": True,
        "ipn_configured": True,
        "callback_configured": True,
        "transport": successful_transport(),
        "authentication": {
            "ok": True,
            "error_type": "",
        },
    }

    assert "secret-token-that-must-not-be-returned" not in response.content.decode()

    transport_mock.assert_called_once_with(
        SANDBOX_URL,
    )
    authenticate_mock.assert_called_once()


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
@patch(
    "system.views.PesapalClient.authenticate",
)
@patch(
    "system.views._pesapal_transport_diagnostic",
    return_value=unavailable_transport(),
)
@patch(
    "system.views.get_pesapal_config",
)
def test_authentication_is_skipped_when_transport_is_unavailable(
    config_mock,
    transport_mock,
    authenticate_mock,
):
    config_mock.return_value = sandbox_config()

    user = make_user(
        "fan.local@leagueos.test",
    )

    response = authenticate(user).get(URL)

    assert response.status_code == 503

    body = response.json()

    assert body["transport"] == unavailable_transport()
    assert body["authentication"] == {
        "ok": False,
        "error_type": "TransportUnavailable",
    }

    transport_mock.assert_called_once_with(
        SANDBOX_URL,
    )
    authenticate_mock.assert_not_called()


@pytest.mark.django_db
@override_settings(REVIEW_WORKFLOW_TOOLS_ENABLED=True)
@patch(
    "system.views._pesapal_transport_diagnostic",
    return_value=successful_transport(),
)
@patch(
    "system.views.PesapalClient.authenticate",
    side_effect=TimeoutError(
        "simulated transport timeout",
    ),
)
@patch(
    "system.views.get_pesapal_config",
)
def test_authentication_timeout_after_tls_is_reported_safely(
    config_mock,
    authenticate_mock,
    transport_mock,
):
    config_mock.return_value = sandbox_config()

    user = make_user(
        "fan.local@leagueos.test",
    )

    response = authenticate(user).get(URL)

    assert response.status_code == 503

    body = response.json()

    assert body["transport"] == successful_transport()

    assert body["authentication"] == {
        "ok": False,
        "error_type": "TimeoutError",
    }

    assert "simulated transport timeout" not in response.content.decode()

    transport_mock.assert_called_once_with(
        SANDBOX_URL,
    )
    authenticate_mock.assert_called_once()

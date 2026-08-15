from unittest.mock import Mock

from django.test import SimpleTestCase

from wallets.services.pesapal_client import (
    PesapalClient,
)
from wallets.services.pesapal_config import (
    PesapalConfig,
    SANDBOX_BASE_URL,
)


def sandbox_config():
    return PesapalConfig(
        environment="SANDBOX",
        base_url=SANDBOX_BASE_URL,
        consumer_key="sandbox-key",
        consumer_secret="sandbox-secret",
        ipn_id="sandbox-ipn-id",
        callback_url=(
            "https://staging.example.test/" "api/v1/wallets/deposits/" "pesapal/callback/"
        ),
        ipn_url=("https://staging.example.test/" "api/v1/wallets/deposits/" "pesapal/ipn/"),
        frontend_return_url=("https://frontend.example.test/" "fan/wallet"),
        is_sandbox=True,
    )


class PesapalClientTests(SimpleTestCase):
    def test_authentication_uses_credentials(self):
        client = PesapalClient(sandbox_config())

        client._request_json = Mock(
            return_value={
                "token": "sandbox-token",
                "status": "200",
            },
        )

        token = client.authenticate()

        self.assertEqual(
            token,
            "sandbox-token",
        )

        client._request_json.assert_called_once_with(
            "POST",
            "/api/Auth/RequestToken",
            payload={
                "consumer_key": "sandbox-key",
                "consumer_secret": "sandbox-secret",
            },
        )

    def test_submit_order_uses_bearer_token(self):
        client = PesapalClient(sandbox_config())

        client.authenticate = Mock(return_value="sandbox-token")

        client._request_json = Mock(
            return_value={
                "order_tracking_id": "tracking-123",
                "merchant_reference": "DEP-123",
                "redirect_url": "https://cybqa.pesapal.com/" "pesapaliframe/test",
                "status": "200",
            },
        )

        payload = {
            "id": "DEP-123",
            "currency": "UGX",
            "amount": 10000,
        }

        result = client.submit_order(payload)

        self.assertEqual(
            result["order_tracking_id"],
            "tracking-123",
        )

        client._request_json.assert_called_once_with(
            "POST",
            "/api/Transactions/SubmitOrderRequest",
            token="sandbox-token",
            payload=payload,
        )

    def test_transaction_status_uses_tracking_id(self):
        client = PesapalClient(sandbox_config())

        client.authenticate = Mock(return_value="sandbox-token")

        client._request_json = Mock(
            return_value={
                "payment_status_description": "Completed",
                "merchant_reference": "DEP-123",
                "amount": 10000,
                "currency": "UGX",
            },
        )

        result = client.get_transaction_status(
            order_tracking_id="tracking-123",
        )

        self.assertEqual(
            result["payment_status_description"],
            "Completed",
        )

        client._request_json.assert_called_once_with(
            "GET",
            "/api/Transactions/GetTransactionStatus",
            token="sandbox-token",
            query={
                "orderTrackingId": "tracking-123",
            },
        )

    def test_ipn_registration_defaults_to_post(self):
        client = PesapalClient(sandbox_config())

        client.authenticate = Mock(return_value="sandbox-token")

        client._request_json = Mock(
            return_value={
                "ipn_id": "sandbox-ipn-id",
                "status": "200",
            },
        )

        result = client.register_ipn(
            url=client.config.ipn_url,
        )

        self.assertEqual(
            result["ipn_id"],
            "sandbox-ipn-id",
        )

        client._request_json.assert_called_once_with(
            "POST",
            "/api/URLSetup/RegisterIPN",
            token="sandbox-token",
            payload={
                "url": client.config.ipn_url,
                "ipn_notification_type": "POST",
            },
        )

    def test_ipn_rejects_unknown_method(self):
        client = PesapalClient(sandbox_config())

        with self.assertRaises(ValueError):
            client.register_ipn(
                url=client.config.ipn_url,
                notification_type="DELETE",
            )

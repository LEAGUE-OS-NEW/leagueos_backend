from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from wallets.services.pesapal_config import (
    SANDBOX_BASE_URL,
    get_pesapal_config,
)


class PesapalConfigTests(SimpleTestCase):
    @patch.dict(
        "os.environ",
        {},
        clear=True,
    )
    def test_defaults_to_sandbox(self):
        config = get_pesapal_config(
            require_credentials=False,
        )

        self.assertEqual(
            config.environment,
            "SANDBOX",
        )
        self.assertEqual(
            config.base_url,
            SANDBOX_BASE_URL,
        )
        self.assertTrue(
            config.is_sandbox,
        )

    @patch.dict(
        "os.environ",
        {
            "PESAPAL_ENVIRONMENT": "SANDBOX",
            "PESAPAL_LIVE_ENABLED": "False",
        },
        clear=True,
    )
    def test_sandbox_is_allowed(self):
        config = get_pesapal_config(
            require_credentials=False,
        )

        self.assertTrue(
            config.is_sandbox,
        )

    @patch.dict(
        "os.environ",
        {
            "PESAPAL_ENVIRONMENT": "LIVE",
            "PESAPAL_LIVE_ENABLED": "False",
        },
        clear=True,
    )
    def test_live_is_blocked_by_default(self):
        with self.assertRaises(ImproperlyConfigured):
            get_pesapal_config(
                require_credentials=False,
            )

    @patch.dict(
        "os.environ",
        {
            "PESAPAL_ENVIRONMENT": "SANDBOX",
            "PESAPAL_LIVE_ENABLED": "True",
        },
        clear=True,
    )
    def test_sandbox_rejects_live_switch(self):
        with self.assertRaises(ImproperlyConfigured):
            get_pesapal_config(
                require_credentials=False,
            )

    @patch.dict(
        "os.environ",
        {
            "PESAPAL_ENVIRONMENT": "SANDBOX",
            "PESAPAL_SANDBOX_BASE_URL": "https://pay.pesapal.com/v3",
            "PESAPAL_LIVE_ENABLED": "False",
        },
        clear=True,
    )
    def test_sandbox_cannot_point_to_live_url(self):
        with self.assertRaises(ImproperlyConfigured):
            get_pesapal_config(
                require_credentials=False,
            )

    @patch.dict(
        "os.environ",
        {
            "PESAPAL_ENVIRONMENT": "SANDBOX",
            "PESAPAL_LIVE_ENABLED": "False",
            "PESAPAL_CONSUMER_KEY": "",
            "PESAPAL_CONSUMER_SECRET": "",
        },
        clear=True,
    )
    def test_credentials_are_required_for_api_use(self):
        with self.assertRaises(ImproperlyConfigured):
            get_pesapal_config()

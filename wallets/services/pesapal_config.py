"""Pesapal API 3.0 environment configuration.

Sandbox is intentionally the default. Live payments require two explicit
settings:

    PESAPAL_ENVIRONMENT=LIVE
    PESAPAL_LIVE_ENABLED=True

This prevents development/staging environments from accidentally using
production Pesapal credentials or endpoints.
"""

from dataclasses import dataclass
import os

from django.core.exceptions import ImproperlyConfigured

SANDBOX_BASE_URL = "https://cybqa.pesapal.com/pesapalv3"
LIVE_BASE_URL = "https://pay.pesapal.com/v3"


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True)
class PesapalConfig:
    environment: str
    base_url: str
    consumer_key: str
    consumer_secret: str
    ipn_id: str
    callback_url: str
    ipn_url: str
    frontend_return_url: str
    is_sandbox: bool


def get_pesapal_config(
    *,
    require_credentials: bool = True,
) -> PesapalConfig:
    environment = (
        os.getenv(
            "PESAPAL_ENVIRONMENT",
            "SANDBOX",
        )
        .strip()
        .upper()
    )

    if environment not in {
        "SANDBOX",
        "LIVE",
    }:
        raise ImproperlyConfigured("PESAPAL_ENVIRONMENT must be " "'SANDBOX' or 'LIVE'.")

    live_enabled = _bool_env(
        "PESAPAL_LIVE_ENABLED",
        False,
    )

    if environment == "LIVE":
        if not live_enabled:
            raise ImproperlyConfigured(
                "Pesapal LIVE access is disabled. "
                "Set PESAPAL_LIVE_ENABLED=True "
                "explicitly before using live payments."
            )

        base_url = (
            os.getenv(
                "PESAPAL_LIVE_BASE_URL",
                LIVE_BASE_URL,
            )
            .strip()
            .rstrip("/")
        )

        if "cybqa.pesapal.com" in base_url:
            raise ImproperlyConfigured(
                "LIVE Pesapal environment cannot use " "the sandbox hostname."
            )

        is_sandbox = False

    else:
        if live_enabled:
            raise ImproperlyConfigured(
                "PESAPAL_LIVE_ENABLED must remain " "False while using SANDBOX."
            )

        base_url = (
            os.getenv(
                "PESAPAL_SANDBOX_BASE_URL",
                SANDBOX_BASE_URL,
            )
            .strip()
            .rstrip("/")
        )

        if base_url != SANDBOX_BASE_URL:
            raise ImproperlyConfigured("Sandbox Pesapal base URL must be " f"{SANDBOX_BASE_URL}.")

        is_sandbox = True

    consumer_key = os.getenv(
        "PESAPAL_CONSUMER_KEY",
        "",
    ).strip()

    consumer_secret = os.getenv(
        "PESAPAL_CONSUMER_SECRET",
        "",
    ).strip()

    ipn_id = os.getenv(
        "PESAPAL_IPN_ID",
        "",
    ).strip()

    callback_url = os.getenv(
        "PESAPAL_CALLBACK_URL",
        "",
    ).strip()

    ipn_url = os.getenv(
        "PESAPAL_IPN_URL",
        "",
    ).strip()

    frontend_return_url = os.getenv(
        "PESAPAL_FRONTEND_RETURN_URL",
        "",
    ).strip()

    if require_credentials:
        missing = []

        if not consumer_key:
            missing.append("PESAPAL_CONSUMER_KEY")

        if not consumer_secret:
            missing.append("PESAPAL_CONSUMER_SECRET")

        if missing:
            raise ImproperlyConfigured("Missing Pesapal configuration: " + ", ".join(missing))

    return PesapalConfig(
        environment=environment,
        base_url=base_url,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        ipn_id=ipn_id,
        callback_url=callback_url,
        ipn_url=ipn_url,
        frontend_return_url=frontend_return_url,
        is_sandbox=is_sandbox,
    )

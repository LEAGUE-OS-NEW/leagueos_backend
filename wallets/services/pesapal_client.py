"""Minimal Pesapal API 3.0 client.

The environment/base URL is supplied exclusively by pesapal_config.
Development and staging therefore remain sandbox-only unless the
separate LIVE safety switch is explicitly enabled.
"""

from __future__ import annotations

import http.client
import json
import logging
from urllib import error, parse, request

from wallets.services.pesapal_config import (
    PesapalConfig,
    get_pesapal_config,
)

logger = logging.getLogger(__name__)


def _provider_error_summary(provider_error) -> str:
    if isinstance(provider_error, dict):
        parts = []

        for key in (
            "error_type",
            "type",
            "code",
            "message",
        ):
            value = str(provider_error.get(key) or "").strip()

            if value:
                parts.append(f"{key}={value}")

        return " | ".join(parts)[:500]

    return str(provider_error or "").strip()[:500]


def _safe_provider_error_summary(details: str) -> str:
    if not details:
        return ""

    try:
        data = json.loads(details)
    except json.JSONDecodeError:
        return ""

    if not isinstance(data, dict):
        return ""

    provider_summary = _provider_error_summary(data.get("error"))

    if provider_summary:
        return provider_summary

    return str(data.get("message") or "").strip()[:500]


class PesapalApiError(RuntimeError):
    """Raised when Pesapal rejects or cannot process an API request."""


class PesapalClient:
    TIMEOUT_SECONDS = 20

    def __init__(
        self,
        config: PesapalConfig | None = None,
    ):
        self.config = config if config is not None else get_pesapal_config()

    def authenticate(self) -> str:
        response = self._request_json(
            "POST",
            "/api/Auth/RequestToken",
            payload={
                "consumer_key": self.config.consumer_key,
                "consumer_secret": self.config.consumer_secret,
            },
        )

        token = str(response.get("token") or "").strip()

        if not token:
            raise PesapalApiError("Pesapal did not return an access token.")

        return token

    def register_ipn(
        self,
        *,
        url: str,
        notification_type: str = "POST",
    ) -> dict:
        notification_type = notification_type.strip().upper()

        if notification_type not in {
            "GET",
            "POST",
        }:
            raise ValueError("Pesapal IPN notification type " "must be GET or POST.")

        token = self.authenticate()

        return self._request_json(
            "POST",
            "/api/URLSetup/RegisterIPN",
            token=token,
            payload={
                "url": url,
                "ipn_notification_type": notification_type,
            },
        )

    def submit_order(
        self,
        payload: dict,
    ) -> dict:
        token = self.authenticate()

        return self._request_json(
            "POST",
            "/api/Transactions/SubmitOrderRequest",
            token=token,
            payload=payload,
        )

    def get_transaction_status(
        self,
        *,
        order_tracking_id: str,
    ) -> dict:
        tracking_id = str(order_tracking_id or "").strip()

        if not tracking_id:
            raise ValueError("order_tracking_id is required.")

        token = self.authenticate()

        return self._request_json(
            "GET",
            "/api/Transactions/GetTransactionStatus",
            token=token,
            query={
                "orderTrackingId": tracking_id,
            },
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict | None = None,
        token: str | None = None,
        query: dict | None = None,
    ) -> dict:
        url = self.config.base_url.rstrip("/") + "/" + path.lstrip("/")

        if query:
            url += "?" + parse.urlencode(query)

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        if token:
            headers["Authorization"] = f"Bearer {token}"

        body = None if payload is None else json.dumps(payload).encode("utf-8")

        http_request = request.Request(
            url=url,
            data=body,
            headers=headers,
            method=method.upper(),
        )

        try:
            with request.urlopen(
                http_request,
                timeout=self.TIMEOUT_SECONDS,
            ) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            try:
                details = exc.read().decode("utf-8")
            except Exception:
                details = ""

            provider_summary = _safe_provider_error_summary(details)

            logger.error(
                "Pesapal API HTTP error " "method=%s path=%s status=%s " "provider_error=%s",
                method.upper(),
                path,
                exc.code,
                provider_summary or "unavailable",
            )

            raise PesapalApiError(f"Pesapal HTTP error {exc.code}.") from exc

        except error.URLError as exc:
            reason = getattr(
                exc,
                "reason",
                None,
            )

            logger.error(
                "Pesapal API transport error " "method=%s path=%s " "reason_type=%s reason=%s",
                method.upper(),
                path,
                type(reason).__name__,
                str(reason or "")[:300],
            )

            raise PesapalApiError("Could not reach Pesapal " f"during {path}.") from exc

        except (OSError, http.client.HTTPException) as exc:
            logger.error(
                "Pesapal API low-level transport error " "method=%s path=%s error_type=%s",
                method.upper(),
                path,
                type(exc).__name__,
            )

            raise PesapalApiError("Could not reach Pesapal " f"during {path}.") from exc

        if not raw:
            return {}

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error(
                "Pesapal invalid JSON response " "method=%s path=%s",
                method.upper(),
                path,
            )

            raise PesapalApiError("Pesapal returned invalid JSON.") from exc

        provider_error = data.get("error")

        provider_error_summary = _provider_error_summary(provider_error)

        if provider_error_summary:
            message = (
                provider_error.get("message")
                if isinstance(
                    provider_error,
                    dict,
                )
                else str(provider_error)
            )

            safe_message = str(message or "Pesapal rejected the request.")[:300]

            logger.error(
                "Pesapal provider error " "method=%s path=%s error=%s",
                method.upper(),
                path,
                provider_error_summary,
            )

            raise PesapalApiError(safe_message)

        return data

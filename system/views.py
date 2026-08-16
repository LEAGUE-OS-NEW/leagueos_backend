from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.db.utils import OperationalError
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    permission_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from system.serializers import (
    HealthCheckSerializer,
    PesapalDiagnosticSerializer,
)
from wallets.services.pesapal_client import PesapalClient
from wallets.services.pesapal_config import get_pesapal_config


def _check_database() -> bool:
    try:
        connections["default"].ensure_connection()
        return True
    except OperationalError:
        return False


def _check_cache() -> bool:
    probe_key = "system:health-check:probe"
    try:
        cache.set(probe_key, "ok", timeout=5)
        return cache.get(probe_key) == "ok"
    except Exception:  # noqa: BLE001 - cache backend errors vary by provider
        return False


@extend_schema(
    request=None,
    responses=HealthCheckSerializer,
    summary="Backend health check",
    tags=["System"],
)
@api_view(["GET"])
@permission_classes([AllowAny])
def health_check(request):
    dependencies = {
        "database": _check_database(),
        "cache": _check_cache(),
    }
    healthy = all(dependencies.values())

    return Response(
        {
            "status": "ok" if healthy else "degraded",
            "service": "leagueos-backend",
            "dependencies": dependencies,
        },
        status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@extend_schema(
    request=None,
    responses={
        200: PesapalDiagnosticSerializer,
        503: PesapalDiagnosticSerializer,
    },
    summary="Pesapal Sandbox staging connectivity diagnostic",
    tags=["System"],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pesapal_diagnostic(request):
    """
    Staging-review-only Pesapal authentication probe.

    It never returns credentials or tokens and never submits a payment order.
    """
    review_enabled = getattr(
        settings,
        "REVIEW_WORKFLOW_TOOLS_ENABLED",
        False,
    )
    synthetic_actor = str(request.user.email or "").lower().endswith("@leagueos.test")

    if not (review_enabled and synthetic_actor):
        return Response(
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        config = get_pesapal_config(
            require_credentials=False,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic reports type only
        return Response(
            {
                "environment": "UNKNOWN",
                "sandbox": False,
                "base_url": "",
                "credentials_present": False,
                "ipn_configured": False,
                "callback_configured": False,
                "authentication": {
                    "ok": False,
                    "error_type": type(exc).__name__,
                },
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    credentials_present = bool(config.consumer_key and config.consumer_secret)

    payload = {
        "environment": config.environment,
        "sandbox": config.is_sandbox,
        "base_url": config.base_url,
        "credentials_present": credentials_present,
        "ipn_configured": bool(config.ipn_id),
        "callback_configured": bool(config.callback_url),
        "authentication": {
            "ok": False,
            "error_type": "",
        },
    }

    if not credentials_present:
        payload["authentication"] = {
            "ok": False,
            "error_type": "MissingCredentials",
        }
        return Response(
            payload,
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        token = PesapalClient(
            config=config,
        ).authenticate()
    except Exception as exc:  # noqa: BLE001 - diagnostic reports type only
        payload["authentication"] = {
            "ok": False,
            "error_type": type(exc).__name__,
        }
        return Response(
            payload,
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    authenticated = bool(token)

    payload["authentication"] = {
        "ok": authenticated,
        "error_type": ("" if authenticated else "MissingToken"),
    }

    return Response(
        payload,
        status=(status.HTTP_200_OK if authenticated else status.HTTP_503_SERVICE_UNAVAILABLE),
    )

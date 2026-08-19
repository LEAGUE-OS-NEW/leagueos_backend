import http.client
import json
import socket
import ssl
import time
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
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

from markets.services.staging_catalogue_audit_service import (
    build_staging_market_catalogue_audit,
)
from markets.services.staging_market_purge_service import (
    build_purge_preflight,
)
from system.serializers import (
    HealthCheckSerializer,
    MarketCatalogueAuditSerializer,
    MarketPurgePreflightSerializer,
    PesapalDiagnosticSerializer,
)
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


def _pesapal_direct_http_auth_diagnostic(config) -> dict:
    """
    Probe Pesapal RequestToken using http.client directly.

    This bypasses urllib handlers and proxy discovery.
    Credentials and tokens are never returned.
    """
    parsed = urlparse(config.base_url)

    host = parsed.hostname or ""
    port = parsed.port or 443
    path = parsed.path.rstrip("/") + "/api/Auth/RequestToken"

    body = json.dumps(
        {
            "consumer_key": config.consumer_key,
            "consumer_secret": config.consumer_secret,
        }
    ).encode("utf-8")

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
        "User-Agent": "LeagueOS-Pesapal/1.0",
        "Connection": "close",
    }

    result = {
        "ok": False,
        "elapsed_ms": None,
        "http_status": None,
        "token_present": False,
        "error_type": "",
    }

    started = time.monotonic()
    connection = None

    try:
        connection = http.client.HTTPSConnection(
            host,
            port,
            timeout=6,
            context=ssl.create_default_context(),
        )

        connection.request(
            "POST",
            path,
            body=body,
            headers=headers,
        )

        response = connection.getresponse()
        raw = response.read()

        result["elapsed_ms"] = round(
            (time.monotonic() - started) * 1000,
            1,
        )
        result["http_status"] = response.status

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ):
            payload = {}

        token_present = bool(isinstance(payload, dict) and str(payload.get("token") or "").strip())

        result["token_present"] = token_present

        if response.status == 200 and token_present:
            result["ok"] = True
            return result

        result["error_type"] = "HttpError" if response.status != 200 else "MissingToken"

        return result

    except Exception as exc:  # noqa: BLE001
        result["elapsed_ms"] = round(
            (time.monotonic() - started) * 1000,
            1,
        )
        result["error_type"] = type(exc).__name__
        return result

    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def _pesapal_transport_diagnostic(base_url: str) -> dict:
    """
    Safe staging diagnostic for the network layers below HTTPS.

    No credentials, tokens, request bodies, or private application data
    are returned.
    """
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    port = parsed.port or 443

    result = {
        "host": host,
        "port": port,
        "dns": {
            "ok": False,
            "elapsed_ms": None,
            "addresses": [],
            "error_type": "",
        },
        "probes": [],
    }

    started = time.monotonic()

    try:
        records = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic reports type only
        result["dns"] = {
            "ok": False,
            "elapsed_ms": round(
                (time.monotonic() - started) * 1000,
                1,
            ),
            "addresses": [],
            "error_type": type(exc).__name__,
        }
        return result

    addresses = []
    seen = set()

    for family, socktype, proto, _, sockaddr in records:
        address = sockaddr[0]

        key = (
            family,
            address,
        )

        if key in seen:
            continue

        seen.add(key)

        family_name = (
            "IPv6"
            if family == socket.AF_INET6
            else "IPv4" if family == socket.AF_INET else str(family)
        )

        addresses.append(
            {
                "family": family_name,
                "address": address,
                "_family": family,
                "_socktype": socktype,
                "_proto": proto,
                "_sockaddr": sockaddr,
            }
        )

    result["dns"] = {
        "ok": bool(addresses),
        "elapsed_ms": round(
            (time.monotonic() - started) * 1000,
            1,
        ),
        "addresses": [
            {
                "family": item["family"],
                "address": item["address"],
            }
            for item in addresses
        ],
        "error_type": "",
    }

    # Probe at most one address per family so the staging diagnostic remains
    # bounded even if the provider publishes a large DNS answer set.
    selected = []
    family_counts = {
        "IPv4": 0,
        "IPv6": 0,
    }

    for item in addresses:
        family = item["family"]

        if family not in family_counts:
            continue

        if family_counts[family] >= 1:
            continue

        family_counts[family] += 1
        selected.append(item)

    context = ssl.create_default_context()

    for item in selected:
        probe = {
            "family": item["family"],
            "address": item["address"],
            "tcp": {
                "ok": False,
                "elapsed_ms": None,
                "error_type": "",
            },
            "tls": {
                "ok": False,
                "elapsed_ms": None,
                "protocol": "",
                "error_type": "",
            },
        }

        tcp_started = time.monotonic()
        raw_socket = None

        try:
            raw_socket = socket.socket(
                item["_family"],
                item["_socktype"],
                item["_proto"],
            )
            raw_socket.settimeout(3)
            raw_socket.connect(
                item["_sockaddr"],
            )

            probe["tcp"] = {
                "ok": True,
                "elapsed_ms": round(
                    (time.monotonic() - tcp_started) * 1000,
                    1,
                ),
                "error_type": "",
            }
        except Exception as exc:  # noqa: BLE001
            probe["tcp"] = {
                "ok": False,
                "elapsed_ms": round(
                    (time.monotonic() - tcp_started) * 1000,
                    1,
                ),
                "error_type": type(exc).__name__,
            }

            if raw_socket is not None:
                raw_socket.close()

            result["probes"].append(probe)
            continue

        tls_started = time.monotonic()

        try:
            with context.wrap_socket(
                raw_socket,
                server_hostname=host,
            ) as tls_socket:
                probe["tls"] = {
                    "ok": True,
                    "elapsed_ms": round(
                        (time.monotonic() - tls_started) * 1000,
                        1,
                    ),
                    "protocol": tls_socket.version() or "",
                    "error_type": "",
                }
        except Exception as exc:  # noqa: BLE001
            probe["tls"] = {
                "ok": False,
                "elapsed_ms": round(
                    (time.monotonic() - tls_started) * 1000,
                    1,
                ),
                "protocol": "",
                "error_type": type(exc).__name__,
            }

            try:
                raw_socket.close()
            except Exception:
                pass

        result["probes"].append(probe)

    return result


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
        "transport": _pesapal_transport_diagnostic(
            config.base_url,
        ),
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

    tls_available = any(
        probe.get("tls", {}).get("ok")
        for probe in payload["transport"].get(
            "probes",
            [],
        )
    )

    if not tls_available:
        payload["authentication"] = {
            "ok": False,
            "error_type": "TransportUnavailable",
        }
        return Response(
            payload,
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    direct_http_auth = _pesapal_direct_http_auth_diagnostic(
        config,
    )
    payload["direct_http_auth"] = direct_http_auth

    if direct_http_auth.get("ok"):
        payload["authentication"] = {
            "ok": True,
            "error_type": "",
        }
        return Response(
            payload,
            status=status.HTTP_200_OK,
        )

    payload["authentication"] = {
        "ok": False,
        "error_type": ("DirectHttp" + str(direct_http_auth.get("error_type") or "UnknownError")),
    }

    return Response(
        payload,
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@extend_schema(
    request=None,
    responses=MarketCatalogueAuditSerializer,
    summary="Staging market catalogue audit",
    tags=["System"],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def market_catalogue_audit(request):
    """
    Read-only staging catalogue audit.

    The endpoint never changes market state or catalogue visibility.
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

    return Response(
        build_staging_market_catalogue_audit(),
        status=status.HTTP_200_OK,
    )


@extend_schema(
    request=None,
    responses=MarketPurgePreflightSerializer,
    summary="Final staging market purge preflight",
    tags=["System"],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def market_purge_preflight(request):
    """
    Read-only preflight for the exact audited
    46-to-4 staging market purge.

    This endpoint never changes market, wallet,
    payment, or ledger data.
    """
    review_enabled = getattr(
        settings,
        "REVIEW_WORKFLOW_TOOLS_ENABLED",
        False,
    )

    actor_email = str(request.user.email or "").lower()

    permitted_actor = actor_email in {
        "superadmin.local@leagueos.test",
        "results.local@leagueos.test",
    }

    if not (review_enabled and permitted_actor):
        return Response(
            status=status.HTTP_404_NOT_FOUND,
        )

    user_model = get_user_model()

    resolution_actor = user_model.objects.filter(
        email__iexact=("results.local@leagueos.test"),
    ).first()

    refund_actor = user_model.objects.filter(
        email__iexact=("superadmin.local@leagueos.test"),
    ).first()

    return Response(
        build_purge_preflight(
            resolution_actor=resolution_actor,
            refund_actor=refund_actor,
        ),
        status=status.HTTP_200_OK,
    )
